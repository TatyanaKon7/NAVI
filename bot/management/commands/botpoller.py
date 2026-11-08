import math
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections, connections, transaction
from django.utils import timezone

from bot import max_api
from bot.events import event_key
from bot.models import BotEvent, BotJob


UPDATE_TYPES = {"bot_started", "message_created", "message_callback"}
MAX_FAILURES = 5


def valid_marker(value):
    return value is None or type(value) is int and value >= 0


def cursor_marker(cursor, bot_user_id):
    result = cursor.result
    if cursor.kind != "poll_cursor" or cursor.status != "done" or not isinstance(result, dict):
        raise CommandError("poll_cursor_invalid")
    if result.get("bot_user_id") != bot_user_id or "marker" not in result or not valid_marker(result["marker"]):
        raise CommandError("poll_cursor_invalid")
    return result["marker"]


def read_marker(bot_user_id):
    cursor = BotJob.objects.filter(deduplication_key=f"poll_cursor:{bot_user_id}").first()
    if cursor:
        return cursor_marker(cursor, bot_user_id)
    return None


def ingest_batch(bot_user_id, previous_marker, batch):
    if not isinstance(batch, dict) or not isinstance(batch.get("updates"), list):
        raise CommandError("poll_batch_invalid")
    if "marker" not in batch or not valid_marker(batch["marker"]):
        raise CommandError("poll_batch_invalid")
    next_marker = previous_marker
    if batch["marker"] is not None:
        next_marker = batch["marker"]
    created_events = 0
    with transaction.atomic():
        cursor, created = BotJob.objects.get_or_create(
            deduplication_key=f"poll_cursor:{bot_user_id}",
            defaults={"kind": "poll_cursor", "status": "done", "finished_at": timezone.now(),
                      "result": {"marker": previous_marker, "bot_user_id": bot_user_id}},
        )
        if cursor_marker(cursor, bot_user_id) != previous_marker:
            raise CommandError("poll_cursor_changed")
        for payload in batch["updates"]:
            try:
                if not isinstance(payload, dict) or payload.get("update_type") not in UPDATE_TYPES:
                    raise ValueError("event")
                key = event_key(payload)
                if len(key) > 255:
                    raise ValueError("event")
            except Exception:
                raise CommandError("poll_batch_event_invalid") from None
            event, created = BotEvent.objects.get_or_create(
                deduplication_key=key,
                defaults={"event_type": payload["update_type"], "payload": payload},
            )
            if created:
                BotJob.objects.create(event=event, kind="event", payload={}, run_at=timezone.now(),
                                      deduplication_key=f"event:{event.pk}")
                created_events += 1
        cursor.result = {"marker": next_marker, "bot_user_id": bot_user_id}
        cursor.finished_at = timezone.now()
        cursor.save(update_fields=["result", "finished_at"])
    return created_events


def safe_word(value, maximum):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        return False
    for character in value:
        if not character.isascii() or not (character.isalnum() or character == "_"):
            return False
    return True


def retry_delay(value):
    try:
        number = float(value)
        if math.isfinite(number):
            return number
        return 0
    except Exception:
        return 0


class Command(BaseCommand):
    help = "Получает события MAX через polling и сохраняет их в очередь для botworker"

    def request(self, operation, **kwargs):
        for attempt in range(MAX_FAILURES):
            try:
                return operation(**kwargs)
            except Exception as error:
                if not isinstance(error, max_api.ExternalServiceError):
                    raise
                code = "max_error"
                if safe_word(str(error.code), 100):
                    code = str(error.code)
                permanent = code in {"max_authentication", "max_http_400", "max_http_401", "max_http_403"}
                if permanent or not error.retryable or attempt + 1 == MAX_FAILURES:
                    raise CommandError(code + "; polling остановлен.") from None
                delay = min(30.0, 5.0 * 2 ** attempt)
                delay = min(30.0, max(delay, retry_delay(error.retry_after)))
                self.stderr.write(f"{code}; повтор через {delay:g} с.")
                time.sleep(delay)

    def identify_bot(self):
        expected = "ideya_fiks_81_bot"
        response = self.request(max_api.get_me)
        if not isinstance(response, dict) or response.get("is_bot") is not True:
            raise CommandError("max_invalid_bot_identity")
        if type(response.get("user_id")) is not int or response["user_id"] <= 0:
            raise CommandError("max_invalid_bot_identity")
        if response.get("username") != expected:
            raise CommandError("max_bot_identity_mismatch; токен принадлежит другому боту.")
        return response["user_id"], expected

    def handle(self, *args, **options):
        try:
            bot_user_id, username = self.identify_bot()
            self.stdout.write(f"Нави: poller запущен, MAX bot ID {bot_user_id}, username {username}.")
            while True:
                close_old_connections()
                started_at = time.monotonic()
                marker = read_marker(bot_user_id)
                batch = self.request(max_api.get_updates, marker=marker, timeout=20, limit=100)
                ingest_batch(bot_user_id, marker, batch)
                delay = 0.35 - (time.monotonic() - started_at)
                if delay > 0:
                    time.sleep(delay)
        except Exception as error:
            if isinstance(error, CommandError):
                raise
            if isinstance(error, DatabaseError):
                raise CommandError("poll_database_error; курсор незавершённого батча не продвинут.") from None
            raise CommandError("poll_internal_error; проверьте состояние poll_cursor и очередь.") from None
        finally:
            connections.close_all()
