from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import max_api
from .models import BotJob, BotMessage


def queue_message(project, text, buttons=None, chat_id=None, file_path=None, deduplication_key=None, notify=False, relocate=False):
    payload = {"chat_id": chat_id or project.student.max_chat_id, "text": str(text)}
    if notify:
        payload["notify"] = True
    if relocate:
        payload["relocate"] = True
    if payload["chat_id"] != project.student.max_chat_id and not buttons:
        base_url = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
        if base_url:
            buttons = [[{"text": "Открыть проект", "url": f"{base_url}/admin/bot/project/{project.pk}/change/"}]]
    if buttons is not None:
        payload["buttons"] = buttons
    if file_path:
        payload["file_path"] = str(file_path)
    values = {"project": project, "kind": "send", "payload": payload, "project_revision": project.revision}
    if deduplication_key:
        return BotJob.objects.get_or_create(deduplication_key=deduplication_key, defaults=values)[0]
    return BotJob.objects.create(**values)


def split_text(text, limit=3900):
    chunks = []
    remaining = text
    while len(remaining) > limit:
        boundary = remaining.rfind("\n", 0, limit) + 1
        if boundary <= 1:
            boundary = remaining.rfind(" ", 0, limit) + 1
        if boundary <= 1:
            boundary = limit
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
    chunks.append(remaining)
    return chunks


def button_rows(buttons):
    rows = []
    for row in buttons:
        size = 7
        for item in row:
            if "url" in item:
                size = 3
                break
        for index in range(0, len(row), size):
            rows.append(row[index:index + size])
    return rows


def combine_payloads(jobs):
    texts = []
    links = []
    callbacks = []
    files = []
    seen_links = set()
    for job in jobs:
        payload = job.payload
        if payload.get("text"):
            if payload["text"] in texts:
                texts.remove(payload["text"])
            texts.append(payload["text"])
        new_callbacks = []
        for row in payload.get("buttons", []):
            callback_row = []
            link_row = []
            for item in row:
                if "url" in item:
                    key = (item["text"], item["url"])
                    if key not in seen_links:
                        link_row.append(item)
                        seen_links.add(key)
                else:
                    callback_row.append(item)
            if link_row:
                links.append(link_row)
            if callback_row:
                new_callbacks.append(callback_row)
        if "buttons" in payload:
            callbacks = new_callbacks
        if payload.get("file_path"):
            files.append({"file_path": payload["file_path"], "text": payload.get("text") or Path(payload["file_path"]).name})
    latest = jobs[-1]
    notify = False
    relocate = False
    for item in jobs:
        if item.payload.get("notify"):
            notify = True
        if (item.deduplication_key or "").startswith("defense:"):
            notify = True
        if item.payload.get("relocate"):
            relocate = True
    student_chat = False
    if latest.project_id is not None:
        student_chat = latest.payload["chat_id"] == latest.project.student.max_chat_id
        if not student_chat:
            notify = True
    return {
        "text": "\n\n".join(texts[-1:] + texts[:-1]), "buttons": button_rows(callbacks + links), "files": files,
        "project_id": latest.project_id, "project_revision": latest.project_revision, "last_job_id": latest.pk,
        "student_chat": student_chat,
        "notify": notify,
        "relocate": relocate,
    }


def page_button(payload, version, index, text):
    return {"text": text, "payload": f"p:{payload['project_id']}:{payload['project_revision']}:*:page:{version}:{index}"}


def card_pages(payload):
    buttons = payload.get("buttons") or []
    groups = []
    for index in range(0, len(buttons), 26):
        groups.append(buttons[index:index + 26])
    if not groups:
        groups.append([])
    chunks = split_text(payload.get("text") or "Выбери действие кнопкой.")
    pages = []
    for chunk in chunks:
        pages.append({"text": chunk, "buttons": groups[0]})
    for group in groups[1:]:
        pages.append({"text": "Действия и материалы", "buttons": group})
    for item in payload.get("files", []):
        file_chunks = split_text(item["text"])
        for chunk in file_chunks:
            pages.append({"text": chunk, "buttons": groups[0], "file_path": item["file_path"]})
    if len(pages) == 2 and len(payload.get("files", [])) == 1 and payload.get("text") == payload["files"][0]["text"]:
        pages = pages[1:]
    return pages


def render_card(payload, version, page=0):
    pages = card_pages(payload)
    page = min(max(0, page), len(pages) - 1)
    rendered = deepcopy(pages[page])
    buttons = rendered["buttons"]
    if len(pages) > 1:
        rendered["text"] += f"\n\nСтраница {page + 1} из {len(pages)}"
        navigation = []
        if page:
            navigation.append(page_button(payload, version, page - 1, "←"))
        navigation.append(page_button(payload, version, page, f"{page + 1}/{len(pages)}"))
        if page + 1 < len(pages):
            navigation.append(page_button(payload, version, page + 1, "→"))
        buttons.append(navigation)
        if page:
            buttons.append([page_button(payload, version, 0, "К началу")])
    return rendered


def handle_page(project, action):
    if not action.startswith("page:"):
        return False
    pieces = action.split(":")
    message = BotMessage.objects.filter(max_chat_id=project.student.max_chat_id, project=project).first()
    if not message or message.payload.get("project_revision") != project.revision:
        from .logic import show_step

        show_step(project)
        return True
    page = message.page
    if len(pieces) == 3 and pieces[1].isdigit() and pieces[2].isdigit() and int(pieces[1]) == message.version:
        page = min(int(pieces[2]), len(card_pages(message.payload)) - 1)
    BotJob.objects.create(
        project=project, project_revision=project.revision, kind="page",
        payload={"chat_id": message.max_chat_id, "version": message.version, "page": page},
    )
    return True


def prepare_send(job):
    with transaction.atomic():
        job.refresh_from_db()
        if job.result:
            return job.result
        message, created = BotMessage.objects.get_or_create(max_chat_id=job.payload["chat_id"])
        if created:
            previous = BotJob.objects.filter(
                kind="send", status="done", result__sent=True, payload__chat_id=job.payload["chat_id"],
                result__response__message_id__isnull=False,
            ).exclude(result__response__message_id="").order_by("-finished_at", "-pk").first()
            if previous:
                response = previous.result.get("response") or {}
                message.message_id = str(response.get("message_id") or "")
                message.save(update_fields=["message_id", "updated_at"])
        if message.payload.get("last_job_id", 0) > job.pk:
            return {"skipped": True}
        jobs = [job]
        for following in BotJob.objects.filter(
            kind="send", status="pending", pk__gt=job.pk, payload__chat_id=job.payload["chat_id"],
        ).order_by("pk"):
            if following.project_id != job.project_id or following.project_revision != job.project_revision or following.result:
                break
            jobs.append(following)
        prepared = {
            "prepared": combine_payloads(jobs), "version": message.version + 1,
            "page": 0, "message_id": message.message_id,
        }
        if prepared["prepared"]["relocate"] and message.message_id:
            prepared["previous_message_id"] = message.message_id
            prepared["message_id"] = ""
        BotJob.objects.filter(pk=job.pk).update(result=prepared)
        following_ids = []
        for item in jobs[1:]:
            following_ids.append(item.pk)
        BotJob.objects.filter(pk__in=following_ids).update(
            status="running", locked_at=timezone.now(), result={"merged_into": job.pk},
        )
        job.result = prepared
        return prepared


def deliver_card(chat_id, message_id, rendered, notify=False):
    if message_id:
        try:
            return max_api.edit_message(message_id=message_id, notify=notify, **rendered)
        except Exception as error:
            if not isinstance(error, max_api.ExternalServiceError):
                raise
            if error.code != "max_message_gone":
                raise
    response = max_api.send_message(chat_id=chat_id, **rendered)
    if not response.get("message_id"):
        raise max_api.ExternalServiceError().setup("max_message_id_missing", True)
    return response


def send_job(job):
    prepared = prepare_send(job)
    if prepared.get("sent") or prepared.get("skipped"):
        return prepared
    message = BotMessage.objects.get(max_chat_id=job.payload["chat_id"])
    if message.version >= prepared["version"]:
        return {"skipped": True}
    rendered = render_card(prepared["prepared"], prepared["version"], prepared["page"])
    response = deliver_card(job.payload["chat_id"], prepared["message_id"], rendered, prepared["prepared"].get("notify", False))
    result = dict(prepared, sent=True, response=response)
    with transaction.atomic():
        BotMessage.objects.filter(max_chat_id=job.payload["chat_id"]).update(
            message_id=response["message_id"], project_id=job.project_id,
            payload=prepared["prepared"], version=prepared["version"], page=prepared["page"], updated_at=timezone.now(),
        )
        BotJob.objects.filter(pk=job.pk, status="running").update(result=result)
        previous_id = prepared.get("previous_message_id")
        if previous_id and previous_id != response["message_id"]:
            BotJob.objects.get_or_create(
                deduplication_key="delete-card:" + sha256(previous_id.encode()).hexdigest(),
                defaults={"kind": "delete_card", "payload": {"message_id": previous_id, "chat_id": job.payload["chat_id"]}},
            )
    return result


def finish_merged(job, status):
    BotJob.objects.filter(result__merged_into=job.pk).update(
        status=status, finished_at=timezone.now(), locked_at=None, error_text=job.error_text,
    )


def page_job(job):
    if job.result.get("sent"):
        return job.result
    message = BotMessage.objects.filter(max_chat_id=job.payload["chat_id"], project_id=job.project_id).first()
    if not message or message.version != job.payload["version"] or message.payload.get("project_revision") != job.project_revision:
        return {"skipped": True}
    page = min(max(0, job.payload["page"]), len(card_pages(message.payload)) - 1)
    response = deliver_card(message.max_chat_id, message.message_id, render_card(message.payload, message.version, page))
    result = {"sent": True, "response": response, "page": page}
    with transaction.atomic():
        BotMessage.objects.filter(pk=message.pk, version=message.version).update(
            page=page, message_id=response["message_id"], updated_at=timezone.now(),
        )
        BotJob.objects.filter(pk=job.pk, status="running").update(result=result)
    return result
