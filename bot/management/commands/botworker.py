import time
from datetime import timedelta
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connections, transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from bot import ai, logic, max_api, messages
from bot.models import BotJob, BotMessage


MAX_ATTEMPTS = 3
LEASE_SECONDS = 90
SEND_INTERVAL = 0.55


def finish_job(job, status="done"):
    job.status = status
    job.finished_at = timezone.now()
    job.locked_at = None
    job.save(update_fields=["status", "finished_at", "locked_at", "result"])
    if job.kind == "send":
        messages.finish_merged(job, status)
    if job.kind == "download":
        job_id = job.pk

        def cleanup_download():
            cleanup_staged_file(job_id)

        transaction.on_commit(cleanup_download)


def recover_jobs():
    expired = timezone.now() - timedelta(seconds=LEASE_SECONDS)
    with transaction.atomic():
        for job in BotJob.objects.filter(status="running", locked_at__lt=expired).exclude(result__has_key="merged_into"):
            checkpoint = job.result
            if job.kind in ("send", "page"):
                checkpoint = job.result.get("sent")
            if job.attempts < MAX_ATTEMPTS or checkpoint:
                job.status = "pending"
                job.run_at = timezone.now()
                job.locked_at = None
                job.save(update_fields=["status", "run_at", "locked_at"])
            else:
                job.error_text = "worker_lease_expired"
                job.save(update_fields=["error_text"])
                record_failure(job, "worker_lease_expired", False)
    terminal_downloads = BotJob.objects.filter(kind="download", status__in=["done", "error", "cancelled"], result__has_key="staged_path").exclude(result__has_key="staged_cleaned")
    for job_id in terminal_downloads.values_list("pk", flat=True):
        cleanup_staged_file(job_id)


def claim_job():
    with transaction.atomic():
        logic.check_timers()
        priority = Case(
            When(kind="send", deduplication_key__startswith="defense:", then=Value(-1)),
            When(kind="event", then=Value(0)),
            When(kind__in=["send", "page", "delete_card"], then=Value(1)),
            When(kind="callback", then=Value(2)),
            default=Value(3), output_field=IntegerField(),
        )
        jobs = BotJob.objects.filter(status="pending", run_at__lte=timezone.now()).filter(
            Q(project__isnull=True) | ~Q(project__status="deferred") | Q(kind__in=["event", "callback"]),
        ).order_by(priority, "run_at", "pk")
        for job in jobs:
            if job.kind == "delete_card" and SEND_INTERVAL > 0:
                last_deleted = BotJob.objects.filter(kind="delete_card", status="done", result__deleted=True, payload__chat_id=job.payload.get("chat_id")).order_by("-finished_at").values_list("finished_at", flat=True).first()
                if last_deleted:
                    earliest = last_deleted + timedelta(seconds=max(0.5, SEND_INTERVAL))
                    if earliest > timezone.now():
                        job.run_at = earliest
                        job.save(update_fields=["run_at"])
                        continue
            if job.kind in ("send", "page") and not (job.deduplication_key or "").startswith("defense:"):
                if BotJob.objects.filter(
                    kind__in=["send", "page"], status__in=["pending", "running"],
                    payload__chat_id=job.payload.get("chat_id"), pk__lt=job.pk,
                ).exclude(project__status="deferred").exists():
                    continue
            if job.kind in ("send", "page") and not job.result.get("sent") and SEND_INTERVAL > 0:
                last_sent = BotJob.objects.filter(kind__in=["send", "page"], status="done", result__sent=True, payload__chat_id=job.payload.get("chat_id")).order_by("-finished_at").values_list("finished_at", flat=True).first()
                if last_sent:
                    earliest = last_sent + timedelta(seconds=SEND_INTERVAL)
                    if earliest > timezone.now():
                        job.run_at = earliest
                        job.save(update_fields=["run_at"])
                        continue
            job.status = "running"
            job.locked_at = timezone.now()
            job.attempts += 1
            job.save(update_fields=["status", "locked_at", "attempts"])
            return job.pk
        return None


def job_is_current(job):
    if job.project_id is None:
        return True
    if job.project.status in ("archived", "deferred"):
        return False
    return job.project_revision is None or job.project.revision == job.project_revision


def reserve_ai_request(job):
    with transaction.atomic():
        used = BotJob.objects.filter(
            kind="ai_usage", project__student=job.project.student, created_at__date=timezone.localdate(),
        ).count()
        if used >= logic.DAILY_LIMIT:
            raise ai.AIError().setup("ai_daily_limit")
        BotJob.objects.create(
            project=job.project, kind="ai_usage", status="done", finished_at=timezone.now(),
            project_revision=job.project_revision, prompt_version=job.prompt_version,
            result={"request_job_id": job.pk, "attempt": job.attempts},
        )


def cleanup_staged_file(job_id):
    job = BotJob.objects.filter(pk=job_id).first()
    if job and job.status in ("done", "error", "cancelled"):
        staged_path = job.result.get("staged_path")
        if staged_path and str(staged_path).startswith(".incoming/"):
            try:
                default_storage.delete(staged_path)
            except Exception as error:
                if isinstance(error, OSError):
                    return
                raise
            result = dict(job.result, staged_cleaned=True)
            BotJob.objects.filter(pk=job.pk).update(result=result)


def record_failure(job, code, retryable, retry_after=None):
    job.error_text = str(code)[:100]
    if retryable and job.attempts < MAX_ATTEMPTS:
        delay = [5, 15, 30][min(job.attempts - 1, 2)]
        if retry_after is not None:
            try:
                delay = max(delay, float(retry_after))
            except Exception as error:
                if not isinstance(error, (TypeError, ValueError)):
                    raise
        job.status = "pending"
        job.run_at = timezone.now() + timedelta(seconds=delay)
        job.locked_at = None
        job.save(update_fields=["status", "run_at", "locked_at", "error_text"])
        return
    job.save(update_fields=["error_text"])
    finish_job(job, "error")
    if job.kind == "ai" and job_is_current(job):
        logic.fail_ai_job(job)
    elif job.kind == "download" and job_is_current(job):
        BotJob.objects.get_or_create(
            deduplication_key=f"download-error:{job.pk}",
            defaults={
                "project": job.project, "project_revision": job.project_revision, "kind": "send",
                "payload": {"chat_id": job.project.student.max_chat_id, "text": "Не получилось принять файл. Проверь формат и размер: PDF, DOCX, PPTX, PNG или JPG, до 20 МБ. Отправь файл ещё раз."},
            },
        )
    if job.kind == "event" and job.event_id:
        job.event.status = "error"
        job.event.processed_at = timezone.now()
        job.event.save(update_fields=["status", "processed_at"])


def execute_job(job_id):
    job = BotJob.objects.select_related("project__student", "event").get(pk=job_id)
    if job.kind != "event" and not job_is_current(job):
        with transaction.atomic():
            finish_job(job, "cancelled")
        cleanup_staged_file(job.pk)
        return
    try:
        if job.kind == "event":
            with transaction.atomic():
                event = job.event
                if event.status == "done":
                    finish_job(job)
                    return
                logic.handle_event(event)
                event.status = "done"
                event.processed_at = timezone.now()
                event.save(update_fields=["status", "processed_at", "project"])
                job.result = {"processed": True}
                finish_job(job)
            return
        if job.kind in ("send", "page"):
            if job.kind == "send":
                result = messages.send_job(job)
            else:
                result = messages.page_job(job)
            BotJob.objects.filter(pk=job.pk, status="running").update(result=result)
            job.result = result
        elif not job.result:
            if job.kind == "ai":
                payload = job.payload
                if payload.get("code") == "topics":
                    logic.validate_topic_job(job)
                reserve_ai_request(job)
                result = ai.generate(payload["code"], payload["data"], payload["instruction"])
            elif job.kind == "callback":
                max_api.answer_callback(job.payload["callback_id"])
                result = {"answered": True}
            elif job.kind == "delete_card":
                message_id = job.payload["message_id"]
                if BotMessage.objects.filter(message_id=message_id).exists():
                    result = {"skipped": True}
                else:
                    max_api.delete_message(message_id)
                    result = {"deleted": True}
            elif job.kind == "download":
                attachment = max_api.download_attachment(job.payload["attachment"])
                name = default_storage.save(f".incoming/{uuid4().hex}", ContentFile(attachment["content"]))
                result = {
                    "staged_path": name, "original_name": attachment["original_name"],
                    "max_attachment_id": attachment.get("max_attachment_id", ""),
                }
            else:
                raise ValueError("unknown_job_kind")
            BotJob.objects.filter(pk=job.pk, status="running").update(result=result)
            job.result = result
        staged_path = None
        download_result = None
        if job.kind == "download":
            staged_path = job.result["staged_path"]
            source_file = None
            try:
                source_file = default_storage.open(staged_path, "rb")
                download_result = dict(job.result, content=source_file.read(20971521))
            finally:
                if source_file is not None:
                    source_file.close()
        with transaction.atomic():
            job.refresh_from_db()
            if job.project_id:
                job.project.refresh_from_db()
            if job.status != "running":
                return
            if not job_is_current(job):
                finish_job(job, "cancelled")
            else:
                if job.kind == "ai":
                    if job.payload.get("code") == "topics":
                        logic.validate_topic_job(job)
                    result = ai.validate_result(job.payload["code"], job.result)
                    logic.apply_ai_result(job, result)
                elif job.kind == "download":
                    logic.apply_download(job, download_result)
                status = "done"
                if job.result.get("skipped"):
                    status = "cancelled"
                finish_job(job, status)
        if staged_path:
            default_storage.delete(staged_path)
    except Exception as error:
        with transaction.atomic():
            job.refresh_from_db()
            if job.status == "running":
                if isinstance(error, (ai.AIError, max_api.ExternalServiceError)):
                    record_failure(job, error.code, error.retryable, error.retry_after)
                else:
                    record_failure(job, "internal_error", False)
    finally:
        cleanup_staged_file(job.pk)


def run_one_job():
    recover_jobs()
    job_id = claim_job()
    if job_id is None:
        return False
    execute_job(job_id)
    return True


class Command(BaseCommand):
    help = "Обрабатывает события MAX, отправки, запросы ИИ и таймеры защиты"

    def handle(self, *args, **options):
        self.stdout.write("Нави: worker запущен.")
        try:
            while True:
                close_old_connections()
                if not run_one_job():
                    time.sleep(1)
        except Exception:
            raise CommandError("Не получилось обработать очередь. Перезапустите worker.") from None
        finally:
            connections.close_all()
