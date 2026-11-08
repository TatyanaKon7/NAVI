import asyncio
import warnings
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree
from zipfile import ZipFile

import aiohttp
from asgiref.sync import async_to_sync
from django.conf import settings
from maxapi import Bot
from maxapi.client.default import DefaultConnectionProperties
from maxapi.exceptions.max import InvalidToken, MaxApiError, MaxConnection, MaxUploadFileFailed
from maxapi.types.attachments.attachment import ButtonsPayload
from maxapi.types.attachments.buttons import CallbackButton, LinkButton
from maxapi.types.input_media import InputMedia
from PIL import Image
from pypdf import PdfReader

from .ai import retry_after_seconds


class ExternalServiceError(Exception):
    def setup(self, code, retryable=False, retry_after=None):
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        self.args = (code,)
        return self


FILE_LIMIT = 20971520


def safe_filename(value):
    name = str(value or "").replace("\\", "/").split("/")[-1].replace("\x00", "").strip()
    if not name or name in {".", ".."}:
        raise ExternalServiceError().setup("file_name_required")
    if len(name) > 255:
        suffix = Path(name).suffix
        name = name[:255 - len(suffix)] + suffix
    return name


def validate_file(content, original_name):
    if not content:
        raise ExternalServiceError().setup("file_empty")
    if len(content) > FILE_LIMIT:
        raise ExternalServiceError().setup("file_too_large")
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg"}:
        raise ExternalServiceError().setup("file_type_unsupported")
    stream = BytesIO(content)
    reader = None
    archive = None
    picture = None
    try:
        if suffix == ".pdf":
            if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
                raise ValueError
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted or not len(reader.pages):
                raise ValueError
        elif suffix in {".docx", ".pptx"}:
            archive = ZipFile(stream)
            records = archive.infolist()
            size = 0
            for item in records:
                size += item.file_size
            if len(records) > 2000 or size > 100 * 1024 * 1024:
                raise ValueError
            names = set(archive.namelist())
            required = "ppt/presentation.xml"
            if suffix == ".docx":
                required = "word/document.xml"
            if "[Content_Types].xml" not in names or required not in names:
                raise ValueError
            for name in names:
                if "vbaproject" in name.lower() or name.startswith("/") or ".." in name.split("/"):
                    raise ValueError
            types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
            if "macroenabled" in ElementTree.tostring(types, encoding="unicode").lower():
                raise ValueError
            ElementTree.fromstring(archive.read(required))
            if archive.testzip() is not None:
                raise ValueError
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                picture = Image.open(stream)
                expected = "JPEG"
                if suffix == ".png":
                    expected = "PNG"
                if picture.format != expected or picture.width * picture.height > 60000000:
                    raise ValueError
                picture.verify()
    except Exception:
        raise ExternalServiceError().setup("file_content_invalid") from None
    finally:
        if picture is not None:
            picture.close()
        if archive is not None:
            archive.close()
        if reader is not None:
            reader.close()
        stream.close()


def attachment_url(value):
    if not isinstance(value, str):
        raise ExternalServiceError().setup("attachment_url_invalid")
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        allowed = False
        for domain in ("oneme.ru", "max.ru"):
            if host == domain or host.endswith("." + domain):
                allowed = True
        if parts.scheme != "https" or not allowed or parts.username or parts.password or parts.port not in (None, 443):
            raise ValueError
    except Exception:
        raise ExternalServiceError().setup("attachment_url_invalid") from None
    return value


def build_buttons(buttons):
    rows = []
    for row in buttons or []:
        converted = []
        for button in row:
            if "url" in button:
                parts = urlsplit(button["url"])
                if parts.scheme not in {"http", "https"} or not parts.hostname:
                    raise ExternalServiceError().setup("button_url_invalid")
                converted.append(LinkButton(text=button["text"], url=button["url"]))
            else:
                converted.append(CallbackButton(text=button["text"], payload=button["payload"]))
        rows.append(converted)
    return ButtonsPayload(buttons=rows).pack()


def response_dict(response):
    if response is None:
        raise ExternalServiceError().setup("max_empty_response", True)
    if hasattr(response, "model_dump"):
        result = response.model_dump(mode="json", exclude_none=True)
    elif isinstance(response, dict):
        result = response
    else:
        raise ExternalServiceError().setup("max_invalid_response", True)
    if result.get("success") is False:
        raise ExternalServiceError().setup("max_unsuccessful_response", True)
    message = result.get("message") or {}
    body = {}
    if isinstance(message, dict):
        body = message.get("body") or {}
    return {"success": True, "message_id": str(body.get("mid") or "")[:255]}


def message_attachments(buttons=None, file_path=None):
    attachments = []
    if buttons:
        attachments.append(build_buttons(buttons))
    if file_path:
        path = Path(file_path)
        if path.stat().st_size > FILE_LIMIT:
            raise ExternalServiceError().setup("file_too_large")
        validate_file(path.read_bytes(), path.name)
        attachments.append(InputMedia(str(path), type="file"))
    return attachments


def service_error(error, headers):
    if isinstance(error, ExternalServiceError):
        return error
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return ExternalServiceError().setup("max_timeout", True)
    if isinstance(error, InvalidToken):
        return ExternalServiceError().setup("max_authentication")
    if isinstance(error, MaxApiError):
        status = error.code
        raw = {}
        if isinstance(error.raw, dict):
            raw = error.raw
        pending_media = raw.get("code") in {"attachment.not.ready", "attachment.processing"}
        retryable = status == 429 or status >= 500 or pending_media
        return ExternalServiceError().setup("max_http_" + str(status), retryable, retry_after_seconds(headers))
    if isinstance(error, (MaxConnection, MaxUploadFileFailed, aiohttp.ClientError, ConnectionError)):
        return ExternalServiceError().setup("max_connection", True)
    if isinstance(error, RuntimeError):
        if str(error) in {"Не удалось отправить сообщение", "Не удалось отредактировать сообщение"}:
            return ExternalServiceError().setup("max_media_not_ready", True)
        return ExternalServiceError().setup("max_sdk_error")
    if isinstance(error, OSError):
        return ExternalServiceError().setup("max_file_unavailable")
    return ExternalServiceError().setup("max_sdk_error")


async def run_operation(operation):
    if not settings.MAX_BOT_TOKEN:
        raise ExternalServiceError().setup("max_not_configured")
    captured_headers = {}
    trace = aiohttp.TraceConfig()

    async def capture_headers(session, context, params):
        if params.response.status == 429:
            captured_headers.update(params.response.headers)

    trace.on_request_end.append(capture_headers)
    bot = None
    try:
        bot = Bot(
            token=settings.MAX_BOT_TOKEN,
            default_connection=DefaultConnectionProperties(timeout=15, sock_connect=5, max_retries=0, trace_configs=[trace]),
            after_upload_attempts=1, after_upload_give_up_timeout=25, auto_requests=False,
        )
        bot.set_api_url("https://platform-api2.max.ru")
        return await asyncio.wait_for(operation(bot), timeout=30)
    except Exception as error:
        raise service_error(error, captured_headers) from None
    finally:
        if bot is not None:
            await bot.close_session()


def send_message(chat_id, text, buttons=None, file_path=None):
    async def operation(bot):
        response = await bot.send_message(
            chat_id=int(chat_id), text=text, attachments=message_attachments(buttons, file_path) or None,
            disable_link_preview=True, sleep_after_input_media=False,
        )
        return response_dict(response)

    return async_to_sync(run_operation)(operation)


async def check_message(bot, message_id):
    try:
        await bot.get_message(message_id=str(message_id))
    except Exception as error:
        if isinstance(error, MaxApiError) and error.code == 404:
            raise ExternalServiceError().setup("max_message_gone") from None
        raise


def edit_message(message_id, text, buttons=None, file_path=None, notify=False):
    async def operation(bot):
        try:
            response = await bot.edit_message(
                message_id=str(message_id), text=text, attachments=message_attachments(buttons, file_path),
                notify=notify, sleep_after_input_media=False,
            )
            result = response_dict(response)
            result["message_id"] = str(message_id)
            return result
        except Exception as error:
            if isinstance(error, MaxApiError) and error.code == 404:
                raise ExternalServiceError().setup("max_message_gone") from None
            if isinstance(error, ExternalServiceError) and error.code == "max_unsuccessful_response":
                await check_message(bot, message_id)
            raise

    return async_to_sync(run_operation)(operation)


def delete_message(message_id):
    async def operation(bot):
        try:
            response = await bot.delete_message(message_id=str(message_id))
            result = response_dict(response)
            result["message_id"] = str(message_id)
            return result
        except Exception as error:
            if isinstance(error, MaxApiError) and error.code == 404:
                return {"success": True, "message_id": str(message_id)}
            raise

    return async_to_sync(run_operation)(operation)


def answer_callback(callback_id):
    async def operation(bot):
        return response_dict(await bot.send_callback(callback_id=callback_id, notification="Принято"))

    return async_to_sync(run_operation)(operation)


def get_me():
    async def operation(bot):
        response = await bot.get_me()
        if hasattr(response, "model_dump"):
            response = response.model_dump(mode="json", exclude_none=True)
        if not isinstance(response, dict):
            raise ExternalServiceError().setup("max_invalid_response")
        return response

    return async_to_sync(run_operation)(operation)


def get_updates(marker=None, timeout=20, limit=100):
    if (
        marker is not None and (type(marker) is not int or marker < 0)
        or type(timeout) is not int or not 0 <= timeout <= 20
        or type(limit) is not int or not 1 <= limit <= 1000
    ):
        raise ExternalServiceError().setup("max_polling_parameters_invalid")

    async def operation(bot):
        bot.default_connection.timeout = aiohttp.ClientTimeout(total=timeout + 5, sock_connect=5)
        response = await bot.get_updates(
            marker=marker, timeout=timeout, limit=limit,
            types=["bot_started", "message_created", "message_callback"],
        )
        if not isinstance(response, dict):
            raise ExternalServiceError().setup("max_invalid_response")
        return response

    return async_to_sync(run_operation)(operation)


async def read_attachment(bot, attachment):
    if hasattr(attachment, "model_dump"):
        attachment = attachment.model_dump(mode="json")
    if not isinstance(attachment, dict) or attachment.get("type") not in {"file", "image"}:
        raise ExternalServiceError().setup("file_type_unsupported")
    payload = attachment.get("payload") or {}
    size = attachment.get("size", payload.get("size"))
    if size is not None and (type(size) is not int or size < 0 or size > FILE_LIMIT):
        raise ExternalServiceError().setup("file_too_large")
    url = attachment_url(payload.get("url"))
    supplied_name = attachment.get("filename") or payload.get("filename")
    if attachment["type"] == "file":
        supplied_name = safe_filename(supplied_name)
        if Path(supplied_name).suffix.lower() not in {".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg"}:
            raise ExternalServiceError().setup("file_type_unsupported")
    session = await bot.ensure_session()
    for redirect in range(4):
        response = None
        try:
            response = await session.get(url, allow_redirects=False)
            if response.status in {301, 302, 303, 307, 308}:
                url = attachment_url(urljoin(url, response.headers.get("Location", "")))
                continue
            if response.status != 200:
                raise ExternalServiceError().setup(
                    "max_download_http_" + str(response.status), response.status == 429 or response.status >= 500,
                    retry_after_seconds(response.headers),
                )
            if response.content_length is not None and response.content_length > FILE_LIMIT:
                raise ExternalServiceError().setup("file_too_large")
            content = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                content.extend(chunk)
                if len(content) > FILE_LIMIT:
                    raise ExternalServiceError().setup("file_too_large")
            content = bytes(content)
            if not supplied_name:
                suffix = ".jpg"
                if content.startswith(b"\x89PNG\r\n\x1a\n"):
                    suffix = ".png"
                supplied_name = "image" + suffix
            original_name = safe_filename(unquote(supplied_name))
            validate_file(content, original_name)
            return {
                "content": content,
                "original_name": original_name,
                "max_attachment_id": str(payload.get("token") or payload.get("photo_id") or "")[:500],
            }
        finally:
            if response is not None:
                response.close()
    raise ExternalServiceError().setup("max_download_redirect_limit")


def download_attachment(attachment):
    async def operation(bot):
        return await read_attachment(bot, attachment)

    return async_to_sync(run_operation)(operation)
