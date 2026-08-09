"""
HTTP client for the Seedance video, Seedream image, Seed Audio, Whisper,
Suno, and Midjourney APIs.

Endpoints:
  POST {base_url}/v1/videos              submit task
  GET  {base_url}/v1/videos/{task_id}    poll task
  POST {base_url}/v1/image/generations   submit image task
  GET  {base_url}/v1/image/generations/{task_id}
                                             poll image task
  POST {base_url}/v1/audio/generations   submit audio task
  GET  {base_url}/v1/audio/generations/{task_id}
                                             poll audio task
  POST {base_url}/v1/audio/transcriptions
                                             synchronous speech transcription
  POST {base_url}/v1/files/upload        upload reference media (multipart)
  POST {base_url}/v1/music/generations/{action}
                                             submit Suno action
  GET  {base_url}/v1/music/tasks/{task_id}
                                             poll Suno task
  POST {base_url}/v1/midjourney/generations/{action}
                                             submit Midjourney action

Reliability rules:
  - Paid/synchronous submit requests are sent once unless the provider adds a
    documented idempotency contract.  An ambiguous timeout must never create a
    duplicate task or charge.
  - Idempotent upload/query/download requests use four isolated routes in the
    fixed direct/proxy/direct/proxy order, waiting 1/5/10 seconds between them.
  - Poll: consecutive-failure counter with exponential backoff; transient
    network / HTTP / JSON errors never kill a running task, but a terminal
    ``failed`` status raises immediately.
  - Upload: retry on transport failures and HTTP 429/502/503/504 only, using
    the same four-route order and 1/5/10-second delays.
"""

import json
import mimetypes
import os
import shutil
import ssl
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import requests

from .runtime import check_cancelled, cooperative_sleep


class SeedanceAPIError(RuntimeError):
    """Business (non-retryable) API error."""


# ---------------------------------------------------------------------------
# HTTP session
#
# Keep runtime dependencies minimal. Requests uses its bundled/default CA
# handling on most systems; on Windows we additionally load the OS certificate
# store into a standard-library SSLContext, avoiding the truststore dependency.
# SEEDANCE_CA_BUNDLE can point to a custom CA file. TLS verification is always
# enabled; there is deliberately no environment-variable bypass.
# ---------------------------------------------------------------------------

class _SSLContextAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, ssl_context: ssl.SSLContext):
        self._ssl_context = ssl_context
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ssl_context
        return super().proxy_manager_for(*args, **kwargs)

    def cert_verify(self, conn, url, verify, cert):
        if verify is True:
            conn.cert_reqs = "CERT_REQUIRED"
            if cert:
                if isinstance(cert, tuple):
                    conn.cert_file, conn.key_file = cert
                else:
                    conn.cert_file = cert
            return
        return super().cert_verify(conn, url, verify, cert)


_session_local = threading.local()

NETWORK_ROUTE_ATTEMPTS = (
    ("direct", False),
    ("proxy", True),
    ("direct", False),
    ("proxy", True),
)
NETWORK_RETRY_DELAYS = (1, 5, 10)
NETWORK_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})

IMAGE_RESULT_MAX_BYTES = 64 * 1024 * 1024
AUDIO_RESULT_MAX_BYTES = 512 * 1024 * 1024
FILE_RESULT_MAX_BYTES = 512 * 1024 * 1024
VIDEO_RESULT_MAX_BYTES = 2 * 1024 * 1024 * 1024


def _windows_cert_store_context() -> Tuple[Optional[ssl.SSLContext], int]:
    """Build an SSLContext with Windows ROOT/CA stores, no third-party deps."""
    if os.name != "nt" or not hasattr(ssl, "enum_certificates"):
        return None, 0

    context = ssl.create_default_context()
    pem_certs: List[str] = []

    for store_name in ("ROOT", "CA"):
        try:
            certificates = ssl.enum_certificates(store_name)
        except Exception:
            continue
        for cert_bytes, encoding, _trust in certificates:
            if encoding == "x509_asn":
                try:
                    pem_certs.append(ssl.DER_cert_to_PEM_cert(cert_bytes))
                except Exception:
                    pass

    if not pem_certs:
        return None, 0

    context.load_verify_locations(cadata="\n".join(pem_certs))
    return context, len(pem_certs)


def _build_session(trust_env: bool = True) -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_env
    ca_bundle = os.environ.get("SEEDANCE_CA_BUNDLE", "").strip()

    if ca_bundle:
        session.verify = ca_bundle
        print(f"[Seedance] Using custom CA bundle: {ca_bundle}")
    else:
        ssl_context, cert_count = _windows_cert_store_context()
        if ssl_context is not None:
            session.mount("https://", _SSLContextAdapter(ssl_context))
            print(f"[Seedance] Using Windows certificate store ({cert_count} certificates)")
    return session


def _session(route_attempt: Optional[int] = None) -> requests.Session:
    """Return the normal worker session or a route-isolated retry session.

    Retry callers pass their zero-based attempt number.  Those requests use
    fresh sessions in the fixed direct/proxy/direct/proxy order without
    changing process-wide proxy environment variables.
    """
    if route_attempt is not None:
        _mode, trust_env = NETWORK_ROUTE_ATTEMPTS[
            route_attempt % len(NETWORK_ROUTE_ATTEMPTS)
        ]
        return _build_session(trust_env=trust_env)

    existing = getattr(_session_local, "session", None)
    if existing is not None:
        return existing

    session = _build_session()
    _session_local.session = session
    return session


def _log(prefix: str, msg: str):
    print(f"[{prefix}] {msg}")


def _safe_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return parsed._replace(query="", fragment="").geturl()


def _sleep_before_route_attempt(attempt: int, logger_prefix: str, operation: str):
    if attempt <= 0:
        return
    wait = NETWORK_RETRY_DELAYS[attempt - 1]
    mode = NETWORK_ROUTE_ATTEMPTS[attempt][0]
    _log(
        logger_prefix,
        f"{operation} retry {attempt + 1}/{len(NETWORK_ROUTE_ATTEMPTS)} "
        f"via {mode} in {wait}s...",
    )
    cooperative_sleep(wait)


def _retryable_http_status(status_code: int) -> bool:
    return int(status_code) in NETWORK_RETRYABLE_STATUS_CODES


def _content_length(response: Any) -> Optional[int]:
    raw = (getattr(response, "headers", {}) or {}).get("Content-Length")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _check_download_size(response: Any, max_bytes: int, label: str):
    declared = _content_length(response)
    if declared is not None and declared > max_bytes:
        raise SeedanceAPIError(
            f"{label} is too large: {declared} bytes exceeds {max_bytes} bytes"
        )


def _write_response_limited(response: Any, output, max_bytes: int, label: str) -> int:
    _check_download_size(response, max_bytes, label)
    total = 0
    if hasattr(response, "iter_content"):
        chunks = response.iter_content(chunk_size=1 << 16)
    else:
        chunks = (bytes(response.content),)
    for chunk in chunks:
        check_cancelled()
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise SeedanceAPIError(
                f"{label} exceeded the {max_bytes}-byte download limit"
            )
        output.write(chunk)
    if total <= 0:
        raise RuntimeError(f"{label} download returned an empty body")
    return total


def _request_with_retry(
    method: str,
    url: str,
    *,
    logger_prefix: str,
    operation: str,
    max_attempts: int = len(NETWORK_ROUTE_ATTEMPTS),
    **kwargs,
):
    """Send one idempotent logical request over the fixed four-route policy."""
    attempts = max(1, min(int(max_attempts), len(NETWORK_ROUTE_ATTEMPTS)))
    last_error: Optional[requests.exceptions.RequestException] = None
    for attempt in range(attempts):
        _sleep_before_route_attempt(attempt, logger_prefix, operation)
        try:
            caller = getattr(_session(attempt), method.lower())
            response = caller(url, **kwargs)
        except requests.exceptions.RequestException as error:
            last_error = error
            _log(
                logger_prefix,
                f"{operation} transport error for {_safe_url(url)} "
                f"(attempt {attempt + 1}/{attempts}, "
                f"mode={NETWORK_ROUTE_ATTEMPTS[attempt][0]}): "
                f"{type(error).__name__}",
            )
            if attempt + 1 >= attempts:
                raise
            continue

        if _retryable_http_status(response.status_code) and attempt + 1 < attempts:
            _log(
                logger_prefix,
                f"{operation} HTTP {response.status_code} for {_safe_url(url)} "
                f"(attempt {attempt + 1}/{attempts}, "
                f"mode={NETWORK_ROUTE_ATTEMPTS[attempt][0]})",
            )
            close = getattr(response, "close", None)
            if callable(close):
                close()
            continue
        return response

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{operation} failed without a response")


def _network_error_text(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}"
    if isinstance(e, requests.exceptions.SSLError):
        text += (
            " | SSL certificate verification failed. Fix: update certifi/requests "
            "in ComfyUI's Python or set SEEDANCE_CA_BUNDLE to a trusted CA bundle. | "
            "SSL 证书校验失败：请更新 ComfyUI Python 环境中的 certifi/requests，"
            "或设置 SEEDANCE_CA_BUNDLE 指向可信证书包。"
        )
    return text


def _headers(api_key: str, with_json: bool = True) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if with_json:
        headers["Content-Type"] = "application/json"
    return headers


def _extract_error_message(data: Any, fallback: str = "") -> str:
    """Extract a human-readable message from new-api error response shapes.

    Known shapes:
      {"error": {"code": "...", "message": "...", "type": "..."}}
      {"code": "invalid_request", "message": "...", "data": null}
      {"code": "fail_to_fetch_task", "message": "{\"error\":{...}}", ...}
    """
    if not isinstance(data, dict):
        return fallback

    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("code")
        if msg:
            return str(msg)
    elif isinstance(err, str) and err.strip():
        return err

    for key in ("message", "msg", "detail"):
        value = data.get(key)
        if value:
            text = str(value)
            # message may itself be a JSON-encoded upstream error; unwrap once
            if text.startswith("{"):
                try:
                    inner = json.loads(text)
                    inner_msg = _extract_error_message(inner, "")
                    if inner_msg:
                        return inner_msg
                except (ValueError, TypeError):
                    pass
            return text
    return fallback


def _truncate(text: str, limit: int = 300) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"...({len(text)} chars)"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def upload_media(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    config: Dict[str, Any],
    logger_prefix: str = "Seedance_Upload",
) -> str:
    """Upload one media file to /v1/files/upload, return its public URL.

    The returned URL is valid for ~24h upstream, which comfortably covers the
    lifetime of one generation task.
    """
    url = f"{config['base_url']}/v1/files/upload"
    size_kb = len(file_bytes) / 1024
    _log(logger_prefix, f"Upload -> {filename} ({mime_type}, {size_kb:.1f} KB)")

    response = _request_with_retry(
        "post",
        url,
        logger_prefix=logger_prefix,
        operation="Upload",
        headers=_headers(config["api_key"], with_json=False),
        files={"file": (filename, file_bytes, mime_type)},
        timeout=config.get("upload_timeout", 180),
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}
    if response.status_code != 200:
        raise SeedanceAPIError(
            f"Upload rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:200])}"
        )
    file_url = data.get("url") if isinstance(data, dict) else None
    if not file_url:
        raise SeedanceAPIError(
            f"No url in upload response: {_truncate(response.text, 200)}"
        )
    _log(logger_prefix, "  Upload success")
    return str(file_url)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


def _post_once(
    url: str,
    *,
    logger_prefix: str,
    operation: str,
    **kwargs,
):
    """Send one potentially billable POST without ambiguous automatic replay."""
    try:
        return _session(0).post(url, **kwargs)
    except requests.exceptions.RequestException as error:
        _log(
            logger_prefix,
            f"{operation} transport error for {_safe_url(url)}: "
            f"{type(error).__name__}; request was not retried to avoid duplicate work",
        )
        raise RuntimeError(
            f"{operation} failed with an ambiguous network error and was not retried. "
            "Check the provider console before submitting again. | "
            f"{_network_error_text(error)}"
        ) from error


def submit_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Seedance_Task",
) -> str:
    """POST /v1/videos, return task id."""
    url = f"{config['base_url']}/v1/videos"

    safe_payload = json.dumps(payload, ensure_ascii=False)
    _log(logger_prefix, f"Submit -> POST /v1/videos model={payload.get('model')}")
    _log(logger_prefix, f"  Payload: {_truncate(safe_payload, 500)}")

    response = _post_once(
        url,
        logger_prefix=logger_prefix,
        operation="Submit",
        headers=_headers(config["api_key"]),
        json=payload,
        timeout=config.get("timeout", 60),
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}
    if response.status_code != 200:
        raise SeedanceAPIError(
            f"Submit rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:200])}"
        )
    task_id = data.get("id") or data.get("task_id") if isinstance(data, dict) else None
    if not task_id:
        raise SeedanceAPIError(f"No task id in submit response: {_truncate(response.text, 300)}")
    _log(logger_prefix, "  Submit accepted")
    return str(task_id)


# ---------------------------------------------------------------------------
# Poll
# ---------------------------------------------------------------------------

_MAX_CONSECUTIVE_POLL_FAILURES = 6

_TERMINAL_COMPLETED = "completed"
_TERMINAL_FAILED = "failed"
_RUNNING_STATUSES = {"queued", "in_progress", "pending", "processing"}


def _coerce_progress(value: Any) -> Optional[int]:
    """Normalize the API progress field (int 0-100, maybe '50' / '50%')."""
    if value is None:
        return None
    try:
        return max(0, min(100, int(str(value).strip().rstrip("%"))))
    except (ValueError, TypeError):
        return None


def poll_task(
    task_id: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
    logger_prefix: str = "Seedance_Task",
) -> Dict[str, Any]:
    """Poll GET /v1/videos/{task_id} until terminal status.

    Returns the final response dict on success; raises SeedanceAPIError on
    task failure and RuntimeError on unrecoverable polling problems.
    """
    url = f"{config['base_url']}/v1/videos/{task_id}"
    poll_interval = config.get("poll_interval", 4.0)
    max_poll_time = config.get("max_poll_time", 1800)

    _log(logger_prefix, f"Poll -> interval={poll_interval}s, max={max_poll_time}s")

    start_time = time.time()
    consecutive_failures = 0
    last_status = ""

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_poll_time:
            raise RuntimeError(
                f"Task exceeded {max_poll_time}s, polling stopped. The task may still "
                f"complete server-side; query it later with task_id={task_id}. | "
                f"任务超过 {max_poll_time}s，已停止轮询。任务可能仍在服务端继续，"
                f"稍后可用 task_id={task_id} 查询结果。"
            )

        cooperative_sleep(poll_interval)

        try:
            response = _request_with_retry(
                "get",
                url,
                logger_prefix=logger_prefix,
                operation="Poll",
                headers=_headers(config["api_key"], with_json=False),
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            consecutive_failures += 1
            _log(logger_prefix, f"Poll network error ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES}): {type(e).__name__}")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(f"Polling failed after repeated network errors [task_id: {task_id}]")
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200 and not _retryable_http_status(response.status_code):
            raise SeedanceAPIError(
                f"Polling rejected (HTTP {response.status_code}) [task_id: {task_id}]"
            )
        if response.status_code != 200:
            consecutive_failures += 1
            _log(logger_prefix, f"Poll HTTP {response.status_code} ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                try:
                    body = response.text[:200]
                except Exception:
                    body = ""
                raise RuntimeError(
                    f"Polling failed: HTTP {response.status_code} repeatedly [task_id: {task_id}] {body}"
                )
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        try:
            data = response.json()
        except ValueError:
            consecutive_failures += 1
            _log(logger_prefix, f"Poll JSON parse error ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(f"Polling failed: invalid JSON repeatedly [task_id: {task_id}]")
            continue

        consecutive_failures = 0

        status = str(data.get("status") or "").strip().lower()
        progress = _coerce_progress(data.get("progress"))

        if status != last_status:
            _log(logger_prefix, f"  Poll: status={status}, progress={progress}, elapsed={int(elapsed)}s")
            last_status = status

        if on_progress and progress is not None:
            try:
                on_progress(progress)
            except Exception:
                pass

        if status == _TERMINAL_COMPLETED:
            _log(logger_prefix, f"  Task completed in {int(elapsed)}s")
            return data

        if status == _TERMINAL_FAILED:
            err_msg = _extract_error_message(data, "video generation failed")
            _log(logger_prefix, f"  Task FAILED: {_truncate(err_msg, 300)}")
            raise SeedanceAPIError(f"Task failed: {err_msg} [task_id: {task_id}]")

        if status and status not in _RUNNING_STATUSES:
            # Unknown non-terminal status: keep polling but make it visible.
            _log(logger_prefix, f"  Unknown status '{status}', continue polling...")


def extract_video_url(final_response: Dict[str, Any]) -> str:
    """Pull the result video URL out of the completed /v1/videos response."""
    metadata = final_response.get("metadata")
    if isinstance(metadata, dict):
        url = metadata.get("url")
        if url:
            return str(url)
    # defensive fallbacks for possible shape variations
    for key in ("url", "video_url"):
        value = final_response.get(key)
        if value:
            return str(value)
    content = final_response.get("content")
    if isinstance(content, dict) and content.get("video_url"):
        return str(content["video_url"])
    raise SeedanceAPIError(
        f"Task completed but no video URL in response: {_truncate(json.dumps(final_response, ensure_ascii=False), 300)}"
    )


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

_IMAGE_RUNNING_STATUSES = {"NOT_START", "SUBMITTED", "QUEUED", "IN_PROGRESS"}
_IMAGE_DOWNLOAD_TIMEOUT = 45
_IMAGE_DOWNLOAD_CONNECT_TIMEOUT = 15
_IMAGE_DOWNLOAD_READ_TIMEOUT = 15


def submit_image_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Seedream_Image",
) -> str:
    """POST /v1/image/generations and return the image task id."""
    url = f"{config['base_url']}/v1/image/generations"
    _log(logger_prefix, f"Submit -> POST /v1/image/generations model={payload.get('model')}")

    response = _post_once(
        url,
        logger_prefix=logger_prefix,
        operation="Image submit",
        headers=_headers(config["api_key"]),
        json=payload,
        timeout=config.get("timeout", 60),
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}
    if response.status_code != 200:
        raise SeedanceAPIError(
            f"Image submit rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:200])}"
        )
    task_id = data.get("task_id") or data.get("id") if isinstance(data, dict) else None
    if not task_id:
        raise SeedanceAPIError(f"No image task id in submit response: {_truncate(response.text, 300)}")
    _log(logger_prefix, "  Submit accepted")
    return str(task_id)


def poll_image_task(
    task_id: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
    logger_prefix: str = "Seedream_Image",
) -> Dict[str, Any]:
    """Poll an image task until ``data.status`` is SUCCESS or FAILURE."""
    url = f"{config['base_url']}/v1/image/generations/{task_id}"
    poll_interval = config.get("poll_interval", 4.0)
    max_poll_time = config.get("max_poll_time", 1800)

    _log(logger_prefix, f"Poll image -> interval={poll_interval}s, max={max_poll_time}s")
    start_time = time.time()
    consecutive_failures = 0
    last_status = ""

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_poll_time:
            raise RuntimeError(
                f"Image task exceeded {max_poll_time}s, polling stopped [task_id: {task_id}] | "
                f"图片任务超过 {max_poll_time}s，已停止轮询"
            )

        cooperative_sleep(poll_interval)

        try:
            response = _request_with_retry(
                "get",
                url,
                logger_prefix=logger_prefix,
                operation="Image poll",
                headers=_headers(config["api_key"], with_json=False),
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            consecutive_failures += 1
            _log(logger_prefix, f"Image poll network error ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES}): {type(e).__name__}")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(f"Image polling failed after repeated network errors [task_id: {task_id}]")
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200 and not _retryable_http_status(response.status_code):
            raise SeedanceAPIError(
                f"Image polling rejected (HTTP {response.status_code}) [task_id: {task_id}]"
            )
        if response.status_code != 200:
            consecutive_failures += 1
            _log(logger_prefix, f"Image poll HTTP {response.status_code} ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"Image polling failed: HTTP {response.status_code} repeatedly [task_id: {task_id}]"
                )
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        try:
            response_data = response.json()
        except ValueError:
            consecutive_failures += 1
            _log(logger_prefix, f"Image poll JSON parse error ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(f"Image polling failed: invalid JSON repeatedly [task_id: {task_id}]")
            continue

        task_data = response_data.get("data") if isinstance(response_data, dict) else None
        if not isinstance(task_data, dict):
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(f"Image polling response has no data object [task_id: {task_id}]")
            continue

        consecutive_failures = 0
        status = str(task_data.get("status") or "").strip().upper()
        progress = _coerce_progress(task_data.get("progress"))

        if status != last_status:
            _log(logger_prefix, f"  Image poll: status={status}, progress={progress}, elapsed={int(elapsed)}s")
            last_status = status

        if on_progress and progress is not None:
            try:
                on_progress(progress)
            except Exception:
                pass

        if status == "SUCCESS":
            _log(logger_prefix, f"  Image task completed in {int(elapsed)}s")
            return response_data

        if status == "FAILURE":
            reason = task_data.get("fail_reason") or _extract_error_message(task_data, "image generation failed")
            raise SeedanceAPIError(f"Image task failed: {reason} [task_id: {task_id}]")

        if status and status not in _IMAGE_RUNNING_STATUSES:
            _log(logger_prefix, f"  Unknown image status '{status}', continue polling...")


def extract_image_url(final_response: Dict[str, Any]) -> str:
    """Extract the documented image URL from a successful task response."""
    task_data = final_response.get("data")
    if isinstance(task_data, dict):
        result_url = task_data.get("result_url")
        if result_url:
            return str(result_url)

        upstream_data = task_data.get("data")
        if isinstance(upstream_data, dict):
            content = upstream_data.get("content")
            if isinstance(content, dict) and content.get("image_url"):
                return str(content["image_url"])

    raise SeedanceAPIError(
        f"Image task completed but no image URL in response: "
        f"{_truncate(json.dumps(final_response, ensure_ascii=False), 300)}"
    )


def extract_image_urls(final_response: Dict[str, Any]) -> List[str]:
    """Extract every documented image URL while preserving result order."""
    task_data = final_response.get("data")
    if isinstance(task_data, dict):
        upstream_data = task_data.get("data")
        if isinstance(upstream_data, dict):
            content = upstream_data.get("content")
            if isinstance(content, dict):
                raw_urls = content.get("image_urls")
                if isinstance(raw_urls, (list, tuple)):
                    urls = [
                        str(value or "").strip()
                        for value in raw_urls
                        if str(value or "").strip()
                    ]
                    if urls:
                        return urls
    return [extract_image_url(final_response)]


def _download_image_bytes(url: str, timeout: int, route_attempt: int = 0) -> bytes:
    total_timeout = max(1.0, float(timeout))
    deadline = time.monotonic() + total_timeout
    request_timeout = (
        min(float(_IMAGE_DOWNLOAD_CONNECT_TIMEOUT), total_timeout),
        min(float(_IMAGE_DOWNLOAD_READ_TIMEOUT), total_timeout),
    )
    response = None
    try:
        response = _session(route_attempt).get(
            url,
            stream=True,
            timeout=request_timeout,
        )
        status_code = int(getattr(response, "status_code", 200))
        if _retryable_http_status(status_code):
            raise requests.exceptions.HTTPError(
                f"retryable HTTP {status_code}", response=response
            )
        if status_code < 200 or status_code >= 300:
            raise SeedanceAPIError(
                f"Image download rejected (HTTP {status_code})"
            )
        _check_download_size(response, IMAGE_RESULT_MAX_BYTES, "Image result")
        if not hasattr(response, "iter_content"):
            content = bytes(response.content)
            if len(content) > IMAGE_RESULT_MAX_BYTES:
                raise SeedanceAPIError("Image result exceeded the download limit")
            return content

        content = bytearray()
        for chunk in response.iter_content(chunk_size=1 << 16):
            check_cancelled()
            if time.monotonic() > deadline:
                raise requests.exceptions.Timeout(
                    f"Image result download exceeded {total_timeout:g}s"
                )
            if chunk:
                content.extend(chunk)
                if len(content) > IMAGE_RESULT_MAX_BYTES:
                    raise SeedanceAPIError("Image result exceeded the download limit")
        if not content:
            raise RuntimeError("Image result download returned an empty body")
        return bytes(content)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def download_image(
    url: str,
    timeout: int = _IMAGE_DOWNLOAD_TIMEOUT,
    max_retries: int = len(NETWORK_ROUTE_ATTEMPTS),
    logger_prefix: str = "Seedream_Image",
) -> Any:
    """Download a result image and return a ComfyUI IMAGE tensor [1,H,W,3]."""
    from io import BytesIO

    import numpy as np
    import torch
    from PIL import Image

    _log(logger_prefix, "Download image -> remote result")
    last_error: Optional[str] = None
    attempts = max(1, min(int(max_retries), len(NETWORK_ROUTE_ATTEMPTS)))
    for attempt in range(attempts):
        try:
            _sleep_before_route_attempt(attempt, logger_prefix, "Image download")
            content = _download_image_bytes(url, timeout, attempt)
            with Image.open(BytesIO(content)) as image:
                rgb = image.convert("RGB")
                array = np.asarray(rgb, dtype=np.float32).copy() / 255.0
            tensor = torch.from_numpy(array).unsqueeze(0)
            _log(logger_prefix, f"  Downloaded image {tensor.shape[2]}x{tensor.shape[1]}")
            return tensor
        except SeedanceAPIError:
            raise
        except Exception as e:
            last_error = type(e).__name__
            _log(logger_prefix, f"Image download attempt {attempt + 1} failed: {last_error}")

    raise RuntimeError(f"Failed to download image after {attempts} attempts: {last_error}")


def download_image_with_mask(
    url: str,
    timeout: int = _IMAGE_DOWNLOAD_TIMEOUT,
    max_retries: int = len(NETWORK_ROUTE_ATTEMPTS),
    logger_prefix: str = "Seedream_Layer_Decomposition",
) -> Tuple[Any, Any]:
    """Download one image as standard ComfyUI IMAGE and transparency MASK tensors."""
    from io import BytesIO

    import numpy as np
    import torch
    from PIL import Image

    _log(logger_prefix, "Download layer image -> remote result")
    last_error: Optional[str] = None
    attempts = max(1, min(int(max_retries), len(NETWORK_ROUTE_ATTEMPTS)))
    for attempt in range(attempts):
        try:
            _sleep_before_route_attempt(attempt, logger_prefix, "Layer image download")
            content = _download_image_bytes(url, timeout, attempt)
            with Image.open(BytesIO(content)) as source:
                rgba = source.convert("RGBA")
                rgb_array = np.asarray(rgba.convert("RGB"), dtype=np.float32).copy()
                alpha_array = np.asarray(
                    rgba.getchannel("A"), dtype=np.float32
                ).copy()
            image = torch.from_numpy(rgb_array / 255.0).unsqueeze(0)
            mask = torch.from_numpy(1.0 - alpha_array / 255.0).unsqueeze(0)
            _log(
                logger_prefix,
                f"  Downloaded layer image {image.shape[2]}x{image.shape[1]}",
            )
            return image, mask
        except SeedanceAPIError:
            raise
        except Exception as error:
            last_error = type(error).__name__
            _log(
                logger_prefix,
                f"Layer image download attempt {attempt + 1} failed: {last_error}",
            )

    raise RuntimeError(
        f"Failed to download layer image after {attempts} attempts: {last_error}"
    )


def download_image_with_path(
    url: str,
    timeout: int = _IMAGE_DOWNLOAD_TIMEOUT,
    max_retries: int = len(NETWORK_ROUTE_ATTEMPTS),
    logger_prefix: str = "Midjourney_Multi_Action",
) -> Tuple[Any, str]:
    """Download an image once and return its ComfyUI tensor and local path."""
    from io import BytesIO

    import numpy as np
    import torch
    from PIL import Image

    try:
        import folder_paths
        output_dir = folder_paths.get_output_directory()
    except ImportError:
        output_dir = os.environ.get("SEEDANCE_OUTPUT_DIR") or os.getcwd()

    os.makedirs(output_dir, exist_ok=True)
    last_error: Optional[str] = None
    attempts = max(1, min(int(max_retries), len(NETWORK_ROUTE_ATTEMPTS)))
    for attempt in range(attempts):
        try:
            _sleep_before_route_attempt(attempt, logger_prefix, "Image download")
            content = _download_image_bytes(url, timeout, attempt)
            with Image.open(BytesIO(content)) as image:
                rgb = image.convert("RGB")
                array = np.asarray(rgb, dtype=np.float32).copy() / 255.0
                path = os.path.join(
                    output_dir,
                    f"midjourney_image_{uuid.uuid4().hex[:12]}.png",
                )
                rgb.save(path, format="PNG")
            tensor = torch.from_numpy(array).unsqueeze(0)
            _log(
                logger_prefix,
                f"  Downloaded image {tensor.shape[2]}x{tensor.shape[1]} -> {path}",
            )
            return tensor, path
        except SeedanceAPIError:
            raise
        except Exception as error:
            last_error = type(error).__name__
            _log(
                logger_prefix,
                f"Image download attempt {attempt + 1} failed: {last_error}",
            )

    raise RuntimeError(
        f"Failed to download image after {attempts} attempts: {last_error}"
    )


# ---------------------------------------------------------------------------
# Audio generation
# ---------------------------------------------------------------------------

_AUDIO_RUNNING_STATUSES = {"NOT_START", "SUBMITTED", "IN_PROGRESS"}


def submit_audio_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Doubao_Seed_Audio",
) -> str:
    """POST /v1/audio/generations and return the audio task id."""
    url = f"{config['base_url']}/v1/audio/generations"
    _log(logger_prefix, f"Submit -> POST /v1/audio/generations model={payload.get('model')}")

    response = _post_once(
        url,
        logger_prefix=logger_prefix,
        operation="Audio submit",
        headers=_headers(config["api_key"]),
        json=payload,
        timeout=config.get("timeout", 60),
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}
    if response.status_code != 200:
        raise SeedanceAPIError(
            f"Audio submit rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:200])}"
        )
    task_id = data.get("task_id") or data.get("id") if isinstance(data, dict) else None
    if not task_id:
        raise SeedanceAPIError(f"No audio task id in submit response: {_truncate(response.text, 300)}")
    _log(logger_prefix, "  Submit accepted")
    return str(task_id)


def poll_audio_task(
    task_id: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
    logger_prefix: str = "Doubao_Seed_Audio",
) -> Dict[str, Any]:
    """Poll an audio task until ``data.status`` is SUCCESS or FAILURE."""
    url = f"{config['base_url']}/v1/audio/generations/{task_id}"
    poll_interval = config.get("poll_interval", 4.0)
    max_poll_time = config.get("max_poll_time", 1800)

    _log(logger_prefix, f"Poll audio -> interval={poll_interval}s, max={max_poll_time}s")
    start_time = time.time()
    consecutive_failures = 0
    last_status = ""

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_poll_time:
            raise RuntimeError(
                f"Audio task exceeded {max_poll_time}s, polling stopped [task_id: {task_id}] | "
                f"音频任务超过 {max_poll_time}s，已停止轮询"
            )

        cooperative_sleep(poll_interval)

        try:
            response = _request_with_retry(
                "get",
                url,
                logger_prefix=logger_prefix,
                operation="Audio poll",
                headers=_headers(config["api_key"], with_json=False),
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            consecutive_failures += 1
            _log(logger_prefix, f"Audio poll network error ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES}): {type(e).__name__}")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(f"Audio polling failed after repeated network errors [task_id: {task_id}]")
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200 and not _retryable_http_status(response.status_code):
            raise SeedanceAPIError(
                f"Audio polling rejected (HTTP {response.status_code}) [task_id: {task_id}]"
            )
        if response.status_code != 200:
            consecutive_failures += 1
            _log(logger_prefix, f"Audio poll HTTP {response.status_code} ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"Audio polling failed: HTTP {response.status_code} repeatedly [task_id: {task_id}]"
                )
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        try:
            response_data = response.json()
        except ValueError:
            consecutive_failures += 1
            _log(logger_prefix, f"Audio poll JSON parse error ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(f"Audio polling failed: invalid JSON repeatedly [task_id: {task_id}]")
            continue

        task_data = response_data.get("data") if isinstance(response_data, dict) else None
        if not isinstance(task_data, dict):
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(f"Audio polling response has no data object [task_id: {task_id}]")
            continue

        consecutive_failures = 0
        status = str(task_data.get("status") or "").strip().upper()
        progress = _coerce_progress(task_data.get("progress"))

        if status != last_status:
            _log(logger_prefix, f"  Audio poll: status={status}, progress={progress}, elapsed={int(elapsed)}s")
            last_status = status

        if on_progress and progress is not None:
            try:
                on_progress(progress)
            except Exception:
                pass

        if status == "SUCCESS":
            _log(logger_prefix, f"  Audio task completed in {int(elapsed)}s")
            return response_data

        if status == "FAILURE":
            reason = task_data.get("fail_reason") or _extract_error_message(task_data, "audio generation failed")
            raise SeedanceAPIError(f"Audio task failed: {reason} [task_id: {task_id}]")

        if status and status not in _AUDIO_RUNNING_STATUSES:
            _log(logger_prefix, f"  Unknown audio status '{status}', continue polling...")


def extract_audio_url(final_response: Dict[str, Any]) -> str:
    """Extract the documented audio URL from a successful task response."""
    task_data = final_response.get("data")
    if isinstance(task_data, dict):
        result_url = task_data.get("result_url")
        if result_url:
            return str(result_url)

        upstream_data = task_data.get("data")
        if isinstance(upstream_data, dict):
            content = upstream_data.get("content")
            if isinstance(content, dict):
                for key in ("audio_url", "url"):
                    if content.get(key):
                        return str(content[key])

    raise SeedanceAPIError(
        f"Audio task completed but no audio URL in response: "
        f"{_truncate(json.dumps(final_response, ensure_ascii=False), 300)}"
    )


def _extract_transcription_text(data: Any) -> str:
    """Pull the human text field from common transcription response shapes."""
    if isinstance(data, dict):
        for key in ("text", "transcript", "transcription"):
            value = data.get(key)
            if value is not None:
                return str(value)
        nested = data.get("data")
        if isinstance(nested, dict):
            return _extract_transcription_text(nested)
    return ""


def transcribe_audio(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    model: str,
    response_format: str,
    config: Dict[str, Any],
    logger_prefix: str = "Whisper_Transcription",
) -> Tuple[str, str]:
    """POST /v1/audio/transcriptions and return (text, response_string).

    The endpoint is synchronous and multipart-based, so requests must not set a
    JSON Content-Type header; requests will generate the multipart boundary.
    """
    url = f"{config['base_url']}/v1/audio/transcriptions"
    _log(logger_prefix, f"Submit -> POST /v1/audio/transcriptions model={model}")

    data = {
        "model": model,
        "response_format": response_format,
    }
    files = {
        "file": (filename, file_bytes, mime_type),
    }

    response = _post_once(
        url,
        logger_prefix=logger_prefix,
        operation="Transcription",
        headers=_headers(config["api_key"], with_json=False),
        data=data,
        files=files,
        timeout=config.get("timeout", 60),
    )
    try:
        parsed: Any = response.json() if response.text else None
    except ValueError:
        parsed = None
    if response.status_code != 200:
        raise SeedanceAPIError(
            f"Transcription rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(parsed, response.text[:200])}"
        )
    if response_format in {"json", "verbose_json"}:
        if parsed is None:
            raise SeedanceAPIError(f"Transcription returned invalid JSON: {_truncate(response.text, 300)}")
        response_str = json.dumps(parsed, ensure_ascii=False, indent=2)
        text = _extract_transcription_text(parsed)
    else:
        response_str = response.text
        text = response.text
    _log(logger_prefix, f"  Transcription completed, text length={len(text)}")
    return text, response_str


def _guess_audio_extension(url: str, content_type: str, fallback_format: str) -> str:
    fallback = str(fallback_format or "").strip().lower()
    if fallback == "ogg_opus":
        return "ogg"
    if fallback in {"wav", "mp3", "pcm", "ogg"}:
        return fallback

    content_type = str(content_type or "").lower()
    if "mpeg" in content_type or "mp3" in content_type:
        return "mp3"
    if "wav" in content_type or "wave" in content_type:
        return "wav"
    if "ogg" in content_type or "opus" in content_type:
        return "ogg"
    if "pcm" in content_type:
        return "pcm"

    ext = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
    if ext in {"wav", "mp3", "pcm", "ogg"}:
        return ext
    return "wav"


def _load_wav_audio(audio_path: str) -> Dict[str, Any]:
    import wave

    import numpy as np
    import torch

    with wave.open(audio_path, "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())

    if sample_width == 1:
        data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        data = (data - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise RuntimeError(f"Unsupported WAV sample width: {sample_width} bytes")

    data = data.reshape(-1, channels).T
    waveform = torch.from_numpy(data.copy()).unsqueeze(0)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def _load_pcm_audio(audio_path: str, sample_rate: int) -> Dict[str, Any]:
    import numpy as np
    import torch

    with open(audio_path, "rb") as f:
        raw = f.read()
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    waveform = torch.from_numpy(data.copy()).unsqueeze(0).unsqueeze(0)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def _find_ffmpeg() -> Optional[str]:
    configured = (
        os.environ.get("SEEDANCE_FFMPEG")
        or os.environ.get("FFMPEG_BINARY")
        or ""
    ).strip()
    if configured and os.path.isfile(configured):
        return configured

    path_binary = shutil.which("ffmpeg")
    if path_binary:
        return path_binary

    bundle_candidate = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "..",
            "ffmpeg",
            "bin",
            "ffmpeg.exe",
        )
    )
    if os.path.isfile(bundle_candidate):
        return bundle_candidate
    return None


def _decode_audio_with_ffmpeg(audio_path: str) -> Dict[str, Any]:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg executable was not found")

    wav_path = f"{audio_path}.decoded.wav"
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.name == "nt"
        else 0
    )
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                audio_path,
                "-acodec",
                "pcm_s16le",
                wav_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            timeout=180,
            creationflags=creation_flags,
        )
        if completed.returncode != 0:
            error = completed.stderr.decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"FFmpeg decode failed: {error}")
        return _load_wav_audio(wav_path)
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


def _decode_audio_file(audio_path: str, sample_rate: int, logger_prefix: str) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    try:
        import torchaudio

        waveform, loaded_rate = torchaudio.load(audio_path)
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        return {"waveform": waveform.unsqueeze(0), "sample_rate": int(loaded_rate)}
    except Exception as e:
        last_error = e
        _log(logger_prefix, f"torchaudio decode unavailable/failed: {type(e).__name__}: {_truncate(str(e), 200)}")

    ext = os.path.splitext(audio_path)[1].lstrip(".").lower()
    try:
        if ext == "wav":
            return _load_wav_audio(audio_path)
        if ext == "pcm":
            return _load_pcm_audio(audio_path, sample_rate)
    except Exception as e:
        last_error = e

    try:
        return _decode_audio_with_ffmpeg(audio_path)
    except Exception as e:
        last_error = e
        _log(
            logger_prefix,
            f"FFmpeg decode unavailable/failed: {type(e).__name__}: {_truncate(str(e), 200)}",
        )

    raise RuntimeError(
        f"Audio downloaded to {audio_path}, but it could not be decoded into a ComfyUI AUDIO object. "
        f"Install torchaudio or provide FFmpeg via SEEDANCE_FFMPEG. "
        f"Last decoder error: {last_error}"
    )


def download_audio(
    url: str,
    output_format: str = "wav",
    sample_rate: int = 24000,
    timeout: int = 300,
    max_retries: int = len(NETWORK_ROUTE_ATTEMPTS),
    logger_prefix: str = "Doubao_Seed_Audio",
) -> Tuple[Any, str]:
    """Download result audio into ComfyUI's output dir and return (AUDIO, path)."""
    try:
        import folder_paths
        output_dir = folder_paths.get_output_directory()
    except ImportError:
        output_dir = os.environ.get("SEEDANCE_OUTPUT_DIR") or os.getcwd()

    os.makedirs(output_dir, exist_ok=True)

    _log(logger_prefix, "Download audio -> remote result")
    last_error: Optional[str] = None
    attempts = max(1, min(int(max_retries), len(NETWORK_ROUTE_ATTEMPTS)))
    for attempt in range(attempts):
        audio_path = None
        try:
            _sleep_before_route_attempt(attempt, logger_prefix, "Audio download")
            response = _session(attempt).get(url, stream=True, timeout=timeout)
            if _retryable_http_status(response.status_code):
                raise requests.exceptions.HTTPError(
                    f"retryable HTTP {response.status_code}", response=response
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise SeedanceAPIError(
                    f"Audio download rejected (HTTP {response.status_code})"
                )
            content_type = (getattr(response, "headers", {}) or {}).get("Content-Type", "")
            ext = _guess_audio_extension(url, content_type, output_format)
            audio_path = os.path.join(output_dir, f"seed_audio_{uuid.uuid4().hex[:12]}.{ext}")

            with open(audio_path, "wb") as f:
                _write_response_limited(
                    response, f, AUDIO_RESULT_MAX_BYTES, "Audio result"
                )

            size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            _log(logger_prefix, f"  Downloaded {size_mb:.2f} MB -> {audio_path}")
            audio = _decode_audio_file(audio_path, int(sample_rate), logger_prefix)
            return audio, audio_path
        except SeedanceAPIError:
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
            raise
        except Exception as e:
            last_error = type(e).__name__
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
            _log(logger_prefix, f"Audio download attempt {attempt + 1} failed: {last_error}")

    raise RuntimeError(f"Failed to download audio after {attempts} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Suno music
# ---------------------------------------------------------------------------

_MUSIC_RUNNING_STATUSES = {
    "created",
    "submitted",
    "queued",
    "pending",
    "processing",
    "in_progress",
    "running",
}
_MUSIC_COMPLETED_STATUSES = {"completed", "complete", "success", "succeeded"}
_MUSIC_FAILED_STATUSES = {"failed", "failure", "error", "cancelled", "canceled"}


def _extract_music_task_id(data: Any) -> Optional[str]:
    if isinstance(data, list):
        for item in data:
            task_id = _extract_music_task_id(item)
            if task_id:
                return task_id
        return None

    if not isinstance(data, dict):
        return None

    for key in ("task_id", "id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    nested = data.get("data")
    if isinstance(nested, (dict, list)):
        return _extract_music_task_id(nested)
    return None


def submit_music_action(
    action: str,
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Suno_Music",
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Submit one Suno action and return ``(task_id, response_json)``.

    ``action`` is empty for the base generation route and kebab-case for every
    other route. Some actions may return their result synchronously, so a
    missing task id is not rejected here.
    """
    action_text = str(action or "").strip().strip("/")
    suffix = f"/{action_text}" if action_text else ""
    url = f"{config['base_url']}/v1/music/generations{suffix}"
    route_label = f"/v1/music/generations{suffix}"
    _log(logger_prefix, f"Submit -> POST {route_label}")

    response = _post_once(
        url,
        logger_prefix=logger_prefix,
        operation="Music submit",
        headers=_headers(config["api_key"]),
        json=payload,
        timeout=config.get("timeout", 60),
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}
    if response.status_code < 200 or response.status_code >= 300:
        raise SeedanceAPIError(
            f"Music submit rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:300])}"
        )
    if not isinstance(data, dict):
        raise SeedanceAPIError(
            f"Music submit returned invalid JSON object: {_truncate(response.text, 300)}"
        )
    task_id = _extract_music_task_id(data)
    response_mode = "asynchronous" if task_id else "synchronous"
    _log(logger_prefix, f"  Music submit accepted with {response_mode} response")
    return task_id, data


def poll_music_task(
    task_id: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
    logger_prefix: str = "Suno_Music",
) -> Dict[str, Any]:
    """Poll one Suno task until a documented terminal state."""
    task_id_text = str(task_id or "").strip()
    if not task_id_text:
        raise SeedanceAPIError("Music task_id is required for polling")

    url = f"{config['base_url']}/v1/music/tasks/{task_id_text}"
    poll_interval = config.get("poll_interval", 4.0)
    max_poll_time = config.get("max_poll_time", 1800)
    _log(
        logger_prefix,
        f"Poll music -> interval={poll_interval}s, max={max_poll_time}s",
    )

    start_time = time.time()
    consecutive_failures = 0
    last_status = ""
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_poll_time:
            raise RuntimeError(
                f"Music task exceeded {max_poll_time}s, polling stopped | "
                f"音乐任务超过 {max_poll_time}s，已停止查询"
            )

        cooperative_sleep(poll_interval)
        try:
            response = _request_with_retry(
                "get",
                url,
                logger_prefix=logger_prefix,
                operation="Music poll",
                headers=_headers(config["api_key"], with_json=False),
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            consecutive_failures += 1
            _log(
                logger_prefix,
                f"Music poll network error "
                f"({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES}): "
                f"{type(e).__name__}",
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError("Music polling failed after repeated network errors")
            time.sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200 and not _retryable_http_status(response.status_code):
            raise SeedanceAPIError(
                f"Music polling rejected (HTTP {response.status_code})"
            )
        if response.status_code != 200:
            consecutive_failures += 1
            _log(
                logger_prefix,
                f"Music poll HTTP {response.status_code} "
                f"({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})",
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"Music polling failed: HTTP {response.status_code} repeatedly"
                )
            time.sleep(min(consecutive_failures * 2, 10))
            continue

        try:
            response_data = response.json()
        except ValueError:
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError("Music polling returned invalid JSON repeatedly")
            continue

        task_data = (
            response_data.get("data")
            if isinstance(response_data, dict)
            else None
        )
        if (
            isinstance(task_data, list)
            and task_data
            and isinstance(task_data[0], dict)
        ):
            task_data = task_data[0]
        elif not isinstance(task_data, dict) and isinstance(response_data, dict):
            if response_data.get("status"):
                task_data = response_data
        if not isinstance(task_data, dict):
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError("Music polling response has no data object")
            continue

        consecutive_failures = 0
        status = str(task_data.get("status") or "").strip().lower()
        progress = _coerce_progress(task_data.get("progress"))

        if status != last_status:
            _log(
                logger_prefix,
                f"  Music poll: status={status}, progress={progress}, "
                f"elapsed={int(elapsed)}s",
            )
            last_status = status

        if on_progress and progress is not None:
            try:
                on_progress(progress)
            except Exception:
                pass

        if status in _MUSIC_COMPLETED_STATUSES:
            _log(logger_prefix, f"  Music task completed in {int(elapsed)}s")
            return response_data

        if status in _MUSIC_FAILED_STATUSES:
            reason = (
                task_data.get("fail_reason")
                or task_data.get("error")
                or _extract_error_message(task_data, "music task failed")
            )
            raise SeedanceAPIError(f"Music task failed: {reason}")

        if status and status not in _MUSIC_RUNNING_STATUSES:
            _log(logger_prefix, f"  Unknown music status '{status}', continue polling...")


def _url_media_kind(key: str, url: str) -> str:
    key_text = str(key or "").lower()
    path = urlparse(url).path.lower()
    ext = os.path.splitext(path)[1]
    if "image" in key_text or ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return "image"
    if (
        "video" in key_text
        or "mp4" in key_text
        or ext in {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    ):
        return "video"
    if (
        "audio" in key_text
        or "wav" in key_text
        or ext in {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac"}
    ):
        return "audio"
    return "file"


def _collect_music_urls(
    value: Any,
    key: str,
    buckets: Dict[str, List[str]],
    seen: Set[str],
    artifacts: List[Dict[str, str]],
):
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _collect_music_urls(child_value, str(child_key), buckets, seen, artifacts)
        return
    if isinstance(value, list):
        for item in value:
            _collect_music_urls(item, key, buckets, seen, artifacts)
        return
    if not isinstance(value, str):
        return

    url = value.strip()
    if not url.startswith(("http://", "https://")):
        return
    if url in seen:
        return
    seen.add(url)
    kind = _url_media_kind(key, url)
    buckets[kind].append(url)
    buckets["all"].append(url)
    artifacts.append({"url": url, "kind": kind})


def _extract_music_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        simple = [item for item in value if isinstance(item, (str, int, float, bool))]
        if simple and len(simple) == len(value):
            return json.dumps(simple, ensure_ascii=False)
    if not isinstance(value, dict):
        return ""

    priority_keys = (
        "text",
        "lyrics",
        "tags",
        "aligned_lyrics",
        "bpm",
        "persona_id",
        "voice_id",
        "audio_id",
        "content",
        "message",
    )
    for key in priority_keys:
        if key in value:
            text = _extract_music_text(value.get(key))
            if text:
                return text

    music = value.get("music")
    if isinstance(music, list):
        for item in music:
            if isinstance(item, dict):
                for key in ("lyrics", "title", "audio_id"):
                    text = _extract_music_text(item.get(key))
                    if text:
                        return text

    for key, child in value.items():
        if key in {"id", "task_id", "status", "progress"}:
            continue
        text = _extract_music_text(child)
        if text:
            return text
    return ""


def extract_music_results(final_response: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize documented and observed Suno result shapes without losing raw data."""
    if not isinstance(final_response, dict):
        raise SeedanceAPIError("Music response must be a JSON object")

    data = final_response.get("data")
    task_data = data if isinstance(data, dict) else final_response
    result = task_data.get("result") if isinstance(task_data, dict) else None
    result_data = result if result is not None else task_data

    buckets: Dict[str, List[str]] = {
        "audio": [],
        "video": [],
        "image": [],
        "file": [],
        "all": [],
    }
    artifacts: List[Dict[str, str]] = []
    _collect_music_urls(result_data, "", buckets, set(), artifacts)

    task_id = _extract_music_task_id(final_response) or ""
    status = (
        str(task_data.get("status") or "").strip()
        if isinstance(task_data, dict)
        else ""
    )
    music = (
        result_data.get("music")
        if isinstance(result_data, dict) and isinstance(result_data.get("music"), list)
        else []
    )
    return {
        "task_id": task_id,
        "status": status,
        "result": result_data,
        "music": music,
        "audio_urls": buckets["audio"],
        "video_urls": buckets["video"],
        "image_urls": buckets["image"],
        "file_urls": buckets["file"],
        "all_urls": buckets["all"],
        "artifacts": artifacts,
        "text": _extract_music_text(result_data),
    }


# ---------------------------------------------------------------------------
# Midjourney image and video actions
# ---------------------------------------------------------------------------

_MIDJOURNEY_RUNNING_STATUSES = {
    "NOT_START",
    "CREATED",
    "SUBMITTED",
    "QUEUED",
    "PENDING",
    "PROCESSING",
    "IN_PROGRESS",
    "RUNNING",
}
_MIDJOURNEY_COMPLETED_STATUSES = {
    "SUCCESS",
    "SUCCEEDED",
    "COMPLETED",
    "COMPLETE",
}
_MIDJOURNEY_FAILED_STATUSES = {
    "CANCEL",
    "FAILURE",
    "FAILED",
    "ERROR",
    "CANCELLED",
    "CANCELED",
}


def _extract_midjourney_task_id(data: Any) -> Optional[str]:
    if isinstance(data, list):
        for item in data:
            task_id = _extract_midjourney_task_id(item)
            if task_id:
                return task_id
        return None
    if not isinstance(data, dict):
        return None

    for key in ("task_id", "id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("data", "result", "task", "output"):
        nested = data.get(key)
        if isinstance(nested, (dict, list)):
            task_id = _extract_midjourney_task_id(nested)
            if task_id:
                return task_id
    return None


def submit_midjourney_action(
    action: str,
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Midjourney_Multi_Action",
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Submit one explicit Midjourney action."""
    action_text = str(action or "").strip().strip("/")
    if not action_text:
        raise SeedanceAPIError("Midjourney action is required")

    route_label = f"/v1/midjourney/generations/{action_text}"
    url = f"{config['base_url']}{route_label}"
    _log(logger_prefix, f"Submit -> POST {route_label}")

    response = _post_once(
        url,
        logger_prefix=logger_prefix,
        operation="Midjourney submit",
        headers=_headers(config["api_key"]),
        json=payload,
        timeout=config.get("timeout", 60),
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}
    if response.status_code < 200 or response.status_code >= 300:
        raise SeedanceAPIError(
            f"Midjourney {action_text} rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:300])}"
        )
    if not isinstance(data, dict):
        raise SeedanceAPIError("Midjourney submit returned an invalid JSON object")
    task_id = _extract_midjourney_task_id(data)
    response_mode = "task" if task_id else "immediate"
    _log(logger_prefix, f"  Midjourney {action_text} accepted with {response_mode} response")
    return task_id, data


_MIDJOURNEY_ENVELOPE_KEYS = ("data", "result", "task", "output")
_MIDJOURNEY_TASK_KEYS = (
    "status", "task_id", "id", "image_urls", "images", "video_urls",
    "videos", "grid_image_url", "description", "prompt", "text", "buttons",
)


def _unwrap_midjourney_task_data(response_data: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(response_data, dict):
        return None

    # The submit/query compatibility wrappers put task state under ``data``.
    # Completed MJ responses instead become a top-level task object that may
    # also contain a nested ``result``. Preserve that top-level status before
    # descending into result content.
    data = response_data.get("data")
    data_candidates = data if isinstance(data, list) else [data]
    for candidate in data_candidates:
        if isinstance(candidate, dict):
            unwrapped = _unwrap_midjourney_task_data(candidate)
            if unwrapped is not None:
                return unwrapped

    direct_task_keys = tuple(
        key for key in _MIDJOURNEY_TASK_KEYS if key != "id"
    )
    if any(key in response_data for key in direct_task_keys):
        return response_data

    for key in ("result", "task", "output"):
        nested = response_data.get(key)
        candidates = nested if isinstance(nested, list) else [nested]
        for candidate in candidates:
            if isinstance(candidate, dict):
                unwrapped = _unwrap_midjourney_task_data(candidate)
                if unwrapped is not None:
                    return unwrapped

    if isinstance(response_data.get("id"), str):
        return response_data
    return None


def poll_midjourney_task(
    task_id: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
    logger_prefix: str = "Midjourney_Multi_Action",
    stop_on_modal: bool = False,
) -> Dict[str, Any]:
    """Poll a Midjourney task, retaining MJ-specific result and button fields."""
    task_id_text = str(task_id or "").strip()
    if not task_id_text:
        raise SeedanceAPIError("Midjourney task_id is required for polling")

    route_templates = (
        "/v1/midjourney/{task_id}",
        "/v1/midjourney/tasks/{task_id}",
        "/v1/tasks/{task_id}",
    )
    active_route: Optional[str] = None
    poll_interval = config.get("poll_interval", 4.0)
    max_poll_time = config.get("max_poll_time", 1800)
    _log(
        logger_prefix,
        f"Poll Midjourney -> interval={poll_interval}s, max={max_poll_time}s",
    )

    start_time = time.time()
    consecutive_failures = 0
    last_status = ""
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_poll_time:
            raise RuntimeError(
                f"Midjourney task exceeded {max_poll_time}s, polling stopped | "
                f"Midjourney 任务超过 {max_poll_time}s，已停止查询"
            )

        time.sleep(poll_interval)
        candidate_routes = (
            (active_route,) if active_route else route_templates
        )
        response = None
        last_not_found = None
        route_used = ""
        for route_template in candidate_routes:
            if not route_template:
                continue
            route = route_template.format(task_id=task_id_text)
            try:
                candidate = _request_with_retry(
                    "get",
                    f"{config['base_url']}{route}",
                    logger_prefix=logger_prefix,
                    operation="Midjourney poll",
                    headers=_headers(config["api_key"], with_json=False),
                    timeout=30,
                )
            except requests.exceptions.RequestException as error:
                consecutive_failures += 1
                _log(
                    logger_prefix,
                    "Midjourney poll network error "
                    f"({consecutive_failures}/"
                    f"{_MAX_CONSECUTIVE_POLL_FAILURES}): "
                    f"{type(error).__name__}",
                )
                if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                    raise RuntimeError(
                        "Midjourney polling failed after repeated network errors"
                    )
                response = None
                break

            if candidate.status_code == 404 and active_route is None:
                last_not_found = candidate
                continue
            response = candidate
            route_used = route_template
            break

        if response is None:
            if last_not_found is not None:
                raise SeedanceAPIError(
                    "Midjourney task was not found on any documented query route"
                )
            cooperative_sleep(min(max(1, consecutive_failures) * 2, 10))
            continue

        if _retryable_http_status(response.status_code):
            consecutive_failures += 1
            _log(
                logger_prefix,
                f"Midjourney poll HTTP {response.status_code} "
                f"({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})",
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"Midjourney polling failed: "
                    f"HTTP {response.status_code} repeatedly"
                )
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200:
            try:
                error_data = response.json()
            except ValueError:
                error_data = {}
            raise SeedanceAPIError(
                f"Midjourney polling rejected (HTTP {response.status_code}): "
                f"{_extract_error_message(error_data, response.text[:200])}"
            )

        try:
            response_data = response.json()
        except ValueError:
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    "Midjourney polling returned invalid JSON repeatedly"
                )
            continue

        task_data = _unwrap_midjourney_task_data(response_data)
        if not isinstance(task_data, dict):
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    "Midjourney polling response has no task data"
                )
            continue

        active_route = route_used
        consecutive_failures = 0
        status = str(task_data.get("status") or "").strip().upper()
        progress = _coerce_progress(task_data.get("progress"))
        if status != last_status:
            _log(
                logger_prefix,
                f"  Midjourney poll: status={status}, progress={progress}, "
                f"elapsed={int(elapsed)}s",
            )
            last_status = status

        if on_progress and progress is not None:
            try:
                on_progress(progress)
            except Exception:
                pass

        if status in _MIDJOURNEY_COMPLETED_STATUSES:
            _log(logger_prefix, f"  Midjourney task completed in {int(elapsed)}s")
            return response_data

        if status == "MODAL":
            if stop_on_modal:
                _log(logger_prefix, "  Midjourney task is waiting for modal input")
                return response_data
            raise SeedanceAPIError(
                "Midjourney task requires modal follow-up input"
            )

        if status in _MIDJOURNEY_FAILED_STATUSES:
            reason = (
                task_data.get("fail_reason")
                or task_data.get("error")
                or _extract_error_message(task_data, "Midjourney task failed")
            )
            raise SeedanceAPIError(f"Midjourney task failed: {reason}")

        if status and status not in _MIDJOURNEY_RUNNING_STATUSES:
            _log(
                logger_prefix,
                f"  Unknown Midjourney status '{status}', continue polling...",
            )


def _midjourney_containers(value: Any) -> List[Dict[str, Any]]:
    """Return only documented task/result envelopes, never arbitrary metadata."""
    containers: List[Dict[str, Any]] = []
    queue: List[Any] = [value]
    seen: Set[int] = set()
    while queue:
        item = queue.pop(0)
        if isinstance(item, dict):
            identity = id(item)
            if identity in seen:
                continue
            seen.add(identity)
            containers.append(item)
            for key in _MIDJOURNEY_ENVELOPE_KEYS:
                nested = item.get(key)
                if isinstance(nested, (dict, list)):
                    queue.append(nested)
        elif isinstance(item, list):
            queue.extend(child for child in item if isinstance(child, dict))
    return containers


def _append_unique_url(target: List[str], value: Any):
    if isinstance(value, str):
        url = value.strip()
        if url.startswith(("http://", "https://")) and url not in target:
            target.append(url)


def _collect_midjourney_url_values(
    target: List[str],
    value: Any,
):
    if isinstance(value, str):
        _append_unique_url(target, value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                for key in ("url", "image_url", "video_url"):
                    _append_unique_url(target, item.get(key))
            else:
                _append_unique_url(target, item)


def extract_midjourney_results(
    final_response: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize documented and observed Midjourney response shapes."""
    if not isinstance(final_response, dict):
        raise SeedanceAPIError("Midjourney response must be a JSON object")

    containers = _midjourney_containers(final_response)
    task_data = _unwrap_midjourney_task_data(final_response)
    if task_data is not None:
        containers = [task_data] + [
            item for item in containers if item is not task_data
        ]
    image_urls: List[str] = []
    video_urls: List[str] = []
    grid_image_url = ""
    buttons: List[Any] = []
    text = ""
    status = ""

    for container in containers:
        if not status and container.get("status") is not None:
            status = str(container.get("status") or "").strip()

        if not grid_image_url:
            candidate = container.get("grid_image_url")
            if isinstance(candidate, str) and candidate.startswith(
                ("http://", "https://")
            ):
                grid_image_url = candidate

        for key in ("image_urls", "images"):
            _collect_midjourney_url_values(image_urls, container.get(key))
        _append_unique_url(image_urls, container.get("image_url"))

        for key in ("video_urls", "videos"):
            _collect_midjourney_url_values(video_urls, container.get(key))
        _append_unique_url(video_urls, container.get("video_url"))

        if not buttons and isinstance(container.get("buttons"), list):
            buttons = container["buttons"]

    for key in ("description", "prompt", "text"):
        for container in containers:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if text:
            break

    if grid_image_url in image_urls:
        image_urls.remove(grid_image_url)

    return {
        "task_id": _extract_midjourney_task_id(final_response) or "",
        "status": status,
        "image_urls": image_urls,
        "grid_image_url": grid_image_url,
        "video_urls": video_urls,
        "text": text,
        "buttons": buttons,
    }


def _guess_file_extension(
    url: str,
    content_type: str,
    default_extension: str,
) -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if 1 < len(ext) <= 10 and ext[1:].replace("_", "").isalnum():
        return ext

    media_type = str(content_type or "").split(";", 1)[0].strip().lower()
    guessed = mimetypes.guess_extension(media_type) if media_type else None
    if guessed:
        return guessed

    fallback = str(default_extension or "bin").strip().lower().lstrip(".")
    return f".{fallback or 'bin'}"


def download_file(
    url: str,
    filename_prefix: str = "suno_result",
    default_extension: str = "bin",
    timeout: int = 300,
    max_retries: int = len(NETWORK_ROUTE_ATTEMPTS),
    logger_prefix: str = "Suno_Music",
) -> str:
    """Download an arbitrary result file into the ComfyUI output directory."""
    try:
        import folder_paths
        output_dir = folder_paths.get_output_directory()
    except ImportError:
        output_dir = os.environ.get("SEEDANCE_OUTPUT_DIR") or os.getcwd()

    os.makedirs(output_dir, exist_ok=True)
    last_error: Optional[str] = None
    attempts = max(1, min(int(max_retries), len(NETWORK_ROUTE_ATTEMPTS)))
    for attempt in range(attempts):
        path = None
        try:
            _sleep_before_route_attempt(attempt, logger_prefix, "File download")
            response = _session(attempt).get(url, stream=True, timeout=timeout)
            if _retryable_http_status(response.status_code):
                raise requests.exceptions.HTTPError(
                    f"retryable HTTP {response.status_code}", response=response
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise SeedanceAPIError(
                    f"File download rejected (HTTP {response.status_code})"
                )
            content_type = (getattr(response, "headers", {}) or {}).get(
                "Content-Type", ""
            )
            extension = _guess_file_extension(url, content_type, default_extension)
            path = os.path.join(
                output_dir,
                f"{filename_prefix}_{uuid.uuid4().hex[:12]}{extension}",
            )
            with open(path, "wb") as f:
                _write_response_limited(
                    response, f, FILE_RESULT_MAX_BYTES, "Result file"
                )
            _log(logger_prefix, f"  Downloaded result -> {path}")
            return path
        except SeedanceAPIError:
            if path and os.path.exists(path):
                os.remove(path)
            raise
        except Exception as e:
            last_error = type(e).__name__
            if path and os.path.exists(path):
                os.remove(path)
            _log(
                logger_prefix,
                f"File download attempt {attempt + 1} failed: {last_error}",
            )
    raise RuntimeError(
        f"Failed to download result file after {attempts} attempts: {last_error}"
    )


# ---------------------------------------------------------------------------
# Result download
# ---------------------------------------------------------------------------

_VIDEO_DOWNLOAD_TIMEOUT = 180
_VIDEO_DOWNLOAD_CONNECT_TIMEOUT = 15
_VIDEO_DOWNLOAD_READ_TIMEOUT = 45


def _download_video_to_path(
    url: str, path: str, timeout: int, route_attempt: int = 0
) -> None:
    total_timeout = max(1.0, float(timeout))
    deadline = time.monotonic() + total_timeout
    request_timeout = (
        min(float(_VIDEO_DOWNLOAD_CONNECT_TIMEOUT), total_timeout),
        min(float(_VIDEO_DOWNLOAD_READ_TIMEOUT), total_timeout),
    )
    part_path = f"{path}.part"
    response = None
    try:
        response = _session(route_attempt).get(
            url, stream=True, timeout=request_timeout
        )
        status_code = int(getattr(response, "status_code", 200))
        if _retryable_http_status(status_code):
            raise requests.exceptions.HTTPError(
                f"retryable HTTP {status_code}", response=response
            )
        if status_code < 200 or status_code >= 300:
            raise SeedanceAPIError(
                f"Video download rejected (HTTP {status_code})"
            )
        _check_download_size(response, VIDEO_RESULT_MAX_BYTES, "Video result")
        wrote_data = False
        with open(part_path, "wb") as file_handle:
            if hasattr(response, "iter_content"):
                chunks = response.iter_content(chunk_size=1 << 16)
            else:
                chunks = (bytes(response.content),)
            for chunk in chunks:
                check_cancelled()
                if time.monotonic() > deadline:
                    raise requests.exceptions.Timeout(
                        f"Video result download exceeded {total_timeout:g}s"
                    )
                if chunk:
                    file_handle.write(chunk)
                    wrote_data = True
                    if file_handle.tell() > VIDEO_RESULT_MAX_BYTES:
                        raise SeedanceAPIError(
                            "Video result exceeded the download limit"
                        )
        if not wrote_data:
            raise RuntimeError("Video result download returned an empty body")
        os.replace(part_path, path)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass

def download_video_with_path(
    url: str,
    timeout: int = 300,
    max_retries: int = len(NETWORK_ROUTE_ATTEMPTS),
    logger_prefix: str = "Seedance_Video",
) -> Tuple[Any, str]:
    """Download an MP4 and return ``(VIDEO object, local path)``.

    Returns comfy_api VideoFromFile when running inside ComfyUI, otherwise the
    local file path (useful for testing outside ComfyUI).
    """
    try:
        import folder_paths
        from comfy_api.input_impl import VideoFromFile
        output_dir = folder_paths.get_output_directory()
    except ImportError:
        VideoFromFile = None
        output_dir = os.environ.get("SEEDANCE_OUTPUT_DIR") or os.getcwd()

    os.makedirs(output_dir, exist_ok=True)
    video_path = os.path.join(output_dir, f"seedance_{uuid.uuid4().hex[:12]}.mp4")

    _log(logger_prefix, "Download video -> remote result")
    last_error: Optional[str] = None
    attempts = max(1, min(int(max_retries), len(NETWORK_ROUTE_ATTEMPTS)))
    for attempt in range(attempts):
        try:
            _sleep_before_route_attempt(attempt, logger_prefix, "Video download")
            _download_video_to_path(url, video_path, timeout, attempt)
            size_mb = os.path.getsize(video_path) / (1024 * 1024)
            _log(logger_prefix, f"  Downloaded {size_mb:.1f} MB -> {video_path}")
            if VideoFromFile is not None:
                return VideoFromFile(video_path), video_path
            return video_path, video_path
        except SeedanceAPIError:
            if os.path.exists(video_path):
                os.remove(video_path)
            raise
        except Exception as e:
            last_error = type(e).__name__
            if os.path.exists(video_path):
                os.remove(video_path)
            _log(logger_prefix, f"Download attempt {attempt + 1} failed: {last_error}")
            continue

    raise RuntimeError(f"Failed to download video after {attempts} attempts: {last_error}")


def download_video(
    url: str,
    timeout: int = 300,
    max_retries: int = len(NETWORK_ROUTE_ATTEMPTS),
    logger_prefix: str = "Seedance_Video",
) -> Any:
    """Download the result MP4 into the ComfyUI output directory."""
    video, _path = download_video_with_path(
        url,
        timeout=timeout,
        max_retries=max_retries,
        logger_prefix=logger_prefix,
    )
    return video
