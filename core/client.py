"""
HTTP client for the Seedance video, Seedream image, Seed Audio, Whisper,
Suno, and Midjourney APIs.

Endpoints:
  POST {base_url}/v1/videos              submit task
  GET  {base_url}/v1/videos/{task_id}    poll task
  POST {base_url}/v1/video/generations   submit Context IR prompt task
  GET  {base_url}/v1/video/generations/{task_id}
                                             poll Context IR prompt task
  POST {base_url}/v1/image/generations   submit image task
  GET  {base_url}/v1/image/generations/{task_id}
                                             poll image task
  POST {base_url}/v1/3d/generations       submit Hunyuan 3D task
  GET  {base_url}/v1/3d/generations/{task_id}
                                             poll Hunyuan 3D task
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
  - Submit: retry only failures that prove the request was not sent and HTTP
    429 responses. Ambiguous transport failures and HTTP 5xx responses are not
    replayed because the upstream may already have created a task.
  - Poll: consecutive-failure counter with exponential backoff; transient
    network / HTTP / JSON errors never kill a running task, but a terminal
    ``failed`` status raises immediately.
  - Upload: retry on network / 5xx; 429 (rate limit: 10/min per token) waits
    long enough for the sliding window to move before retrying.
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
import warnings
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
# SEEDANCE_CA_BUNDLE can point to a custom CA file. SEEDANCE_SSL_VERIFY=0 is a
# deprecated last-resort escape hatch retained for workflow compatibility.
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
_insecure_tls_warning_lock = threading.Lock()
_insecure_tls_warning_emitted = False


def _warn_insecure_tls_once() -> None:
    global _insecure_tls_warning_emitted
    with _insecure_tls_warning_lock:
        if _insecure_tls_warning_emitted:
            return
        _insecure_tls_warning_emitted = True

    message = (
        "SEEDANCE_SSL_VERIFY=0 disables server identity verification and is "
        "deprecated. Configure SEEDANCE_CA_BUNDLE or the Windows certificate "
        "store instead; this compatibility escape hatch will be removed in a "
        "future release."
    )
    warnings.warn(message, FutureWarning, stacklevel=3)
    print(f"[Seedance] SECURITY WARNING: {message}")


def _create_session(
    *, trust_env: bool = True, announce: bool = True
) -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_env
    ca_bundle = os.environ.get("SEEDANCE_CA_BUNDLE", "").strip()

    if ca_bundle:
        session.verify = ca_bundle
        if announce:
            print(f"[Seedance] Using custom CA bundle: {ca_bundle}")
    elif os.environ.get("SEEDANCE_SSL_VERIFY", "").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        session.verify = False
        if announce:
            _warn_insecure_tls_once()
    else:
        ssl_context, cert_count = _windows_cert_store_context()
        if ssl_context is not None:
            session.mount("https://", _SSLContextAdapter(ssl_context))
            if announce:
                print(
                    "[Seedance] Using Windows certificate store "
                    f"({cert_count} certificates)"
                )

    return session


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


def _session() -> requests.Session:
    existing = getattr(_session_local, "session", None)
    if existing is not None:
        return existing

    session = _create_session()
    _session_local.session = session
    return session


def _direct_session() -> requests.Session:
    """Return a result-download session that ignores broken proxy env vars."""
    existing = getattr(_session_local, "direct_session", None)
    if existing is not None:
        return existing

    session = _create_session(trust_env=False, announce=False)
    _session_local.direct_session = session
    return session


def _reset_thread_session() -> None:
    """Discard only this worker's connection pool after a transport failure."""
    existing = getattr(_session_local, "session", None)
    if existing is None:
        return

    close = getattr(existing, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    try:
        delattr(_session_local, "session")
    except AttributeError:
        pass


def _reset_direct_thread_session() -> None:
    existing = getattr(_session_local, "direct_session", None)
    if existing is None:
        return

    close = getattr(existing, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    try:
        delattr(_session_local, "direct_session")
    except AttributeError:
        pass


def _log(prefix: str, msg: str):
    print(f"[{prefix}] {msg}")


def _network_error_text(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}"
    if isinstance(e, requests.exceptions.SSLError):
        text += (
            " | SSL certificate verification failed. Fix: update certifi/requests "
            "in ComfyUI's Python, set SEEDANCE_CA_BUNDLE to a CA bundle file, or set "
            "SEEDANCE_SSL_VERIFY=0 only as a deprecated temporary diagnostic. | "
            "SSL 证书校验失败：请更新 ComfyUI Python 环境中的 certifi/requests，"
            "或设置 SEEDANCE_CA_BUNDLE 指向证书包；SEEDANCE_SSL_VERIFY=0 "
            "仅保留为即将移除的临时排障方式。"
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


def _sanitize_payload_for_log(value: Any, key: str = "") -> Any:
    """Return a log-safe payload copy without URLs or runtime identifiers."""
    normalized_key = str(key).strip().lower()
    if isinstance(value, dict):
        return {
            child_key: _sanitize_payload_for_log(child_value, child_key)
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_payload_for_log(item, normalized_key) for item in value]
    if value in (None, ""):
        return value
    if (
        normalized_key in {"authorization", "api_key", "token"}
        or normalized_key.endswith("_id")
        or normalized_key.endswith("_token")
    ):
        return "<redacted-id>"
    if isinstance(value, str):
        text = value.strip()
        if normalized_key == "url" or normalized_key.endswith(("_url", "_urls")):
            return "<redacted-url>"
        if text.startswith(("http://", "https://")):
            return "<redacted-url>"
        if text.startswith(("task_", "sk-")):
            return "<redacted-id>"
    return value


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

_UPLOAD_MAX_ATTEMPTS = 5
_UPLOAD_RATE_LIMIT_WAIT = 30  # seconds; per-token limit is 10 uploads/minute


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

    last_error: Optional[Exception] = None
    for attempt in range(_UPLOAD_MAX_ATTEMPTS):
        if attempt > 0:
            wait = min(2 ** attempt, 15)
            _log(logger_prefix, f"Upload retry {attempt + 1}/{_UPLOAD_MAX_ATTEMPTS} in {wait}s...")
            cooperative_sleep(wait)

        try:
            response = _session().post(
                url,
                headers=_headers(config["api_key"], with_json=False),
                files={"file": (filename, file_bytes, mime_type)},
                timeout=config.get("upload_timeout", 180),
            )
        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Network error: {_network_error_text(e)}")
            _log(logger_prefix, f"Upload network error (attempt {attempt + 1}): {type(e).__name__}")
            continue

        try:
            data = response.json() if response.text else {}
        except ValueError:
            data = {}

        if response.status_code == 429:
            # Per-token sliding window (10/min). Waiting ~30s moves the window
            # enough for large multi-material workflows to finish uploading.
            last_error = RuntimeError(
                f"Upload rate limited: {_extract_error_message(data, response.text[:200])}"
            )
            _log(logger_prefix, f"Upload 429 rate limited, waiting {_UPLOAD_RATE_LIMIT_WAIT}s...")
            cooperative_sleep(_UPLOAD_RATE_LIMIT_WAIT)
            continue

        if response.status_code >= 500:
            last_error = RuntimeError(
                f"HTTP {response.status_code}: {_extract_error_message(data, response.text[:200])}"
            )
            _log(logger_prefix, f"Upload HTTP {response.status_code} (attempt {attempt + 1}), retrying...")
            continue

        if response.status_code != 200:
            # 4xx: bad file type / too large / auth problem - not retryable
            raise SeedanceAPIError(
                f"Upload rejected (HTTP {response.status_code}): "
                f"{_extract_error_message(data, response.text[:200])}"
            )

        file_url = data.get("url") if isinstance(data, dict) else None
        if not file_url:
            last_error = RuntimeError(f"No url in upload response: {_truncate(response.text, 200)}")
            continue

        _log(logger_prefix, "  Upload success")
        return file_url

    raise RuntimeError(f"Upload failed after {_UPLOAD_MAX_ATTEMPTS} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

_SUBMIT_MAX_ATTEMPTS = 3


def _is_safe_submit_retry_error(error: Exception) -> bool:
    """Return True only when the task-creation request was not transmitted."""
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return True

    pending: List[Any] = [error]
    visited: Set[int] = set()
    safe_connect_error_names = {
        "ConnectTimeoutError",
        "NameResolutionError",
        "NewConnectionError",
    }
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if type(current).__name__ in safe_connect_error_names:
            return True
        for nested in (
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
            getattr(current, "reason", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
        for argument in getattr(current, "args", ()):
            if isinstance(argument, BaseException):
                pending.append(argument)
    return False


def _submit_retry_wait(attempt: int, response: Any = None) -> float:
    retry_after = ""
    headers = getattr(response, "headers", None)
    if headers:
        retry_after = str(headers.get("Retry-After", "") or "").strip()
    if retry_after:
        try:
            return max(1.0, min(float(retry_after), 60.0))
        except (TypeError, ValueError):
            pass
    return float(min(2 ** (attempt + 1) + 1, 15))


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _post_task_creation(
    request: Callable[[], Any],
    logger_prefix: str,
    operation: str,
) -> Any:
    """Run a non-idempotent POST without duplicating ambiguous submissions."""
    last_error: Optional[Exception] = None
    for attempt in range(_SUBMIT_MAX_ATTEMPTS):
        try:
            response = request()
        except requests.exceptions.RequestException as error:
            if not _is_safe_submit_retry_error(error):
                raise RuntimeError(
                    f"{operation} response was not received "
                    f"({type(error).__name__}). The request was not retried "
                    "because the upstream may already have created the task."
                ) from None

            last_error = RuntimeError(
                f"{operation} connection failed before send: "
                f"{_network_error_text(error)}"
            )
            if attempt + 1 >= _SUBMIT_MAX_ATTEMPTS:
                break
            _reset_thread_session()
            wait = _submit_retry_wait(attempt)
            _log(
                logger_prefix,
                f"{operation} connection failed before send; retry "
                f"{attempt + 2}/{_SUBMIT_MAX_ATTEMPTS} in {wait:g}s...",
            )
            cooperative_sleep(wait)
            continue

        if response.status_code == 429:
            try:
                data = response.json() if response.text else {}
            except ValueError:
                data = {}
            last_error = RuntimeError(
                "HTTP 429: "
                f"{_extract_error_message(data, response.text[:200])}"
            )
            if attempt + 1 >= _SUBMIT_MAX_ATTEMPTS:
                _close_response(response)
                break
            wait = _submit_retry_wait(attempt, response)
            _close_response(response)
            _log(
                logger_prefix,
                f"{operation} HTTP 429; retry "
                f"{attempt + 2}/{_SUBMIT_MAX_ATTEMPTS} in {wait:g}s...",
            )
            cooperative_sleep(wait)
            continue

        if response.status_code >= 500:
            try:
                data = response.json() if response.text else {}
            except ValueError:
                data = {}
            detail = _extract_error_message(data, response.text[:200])
            status_code = response.status_code
            _close_response(response)
            raise RuntimeError(
                f"{operation} returned HTTP {status_code}: {detail}. "
                "The request was not retried because the upstream may already "
                "have created the task."
            )

        return response

    raise RuntimeError(
        f"{operation} failed after {_SUBMIT_MAX_ATTEMPTS} safe attempts: "
        f"{last_error}"
    )


def submit_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Seedance_Task",
) -> str:
    """POST /v1/videos, return task id."""
    url = f"{config['base_url']}/v1/videos"

    safe_payload = json.dumps(
        _sanitize_payload_for_log(payload),
        ensure_ascii=False,
    )
    _log(logger_prefix, f"Submit -> POST /v1/videos model={payload.get('model')}")
    _log(logger_prefix, f"  Payload: {_truncate(safe_payload, 500)}")

    response = _post_task_creation(
        lambda: _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
        ),
        logger_prefix,
        "Video submit",
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

    task_id = None
    if isinstance(data, dict):
        task_id = data.get("id") or data.get("task_id")
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
            response = _session().get(
                url,
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
# MiniMax H3 Context IR prompt enhancement (legacy compatibility endpoint)
# ---------------------------------------------------------------------------

_CONTEXT_IR_RUNNING_STATUSES = {
    "NOT_START", "SUBMITTED", "QUEUED", "IN_PROGRESS", "PENDING", "PROCESSING",
}


def submit_context_ir_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Minimax_H3_Context_IR",
    task_label: str = "Context IR",
) -> str:
    """POST /v1/video/generations and return a compatibility task id."""
    url = f"{config['base_url']}/v1/video/generations"
    _log(
        logger_prefix,
        f"Submit -> POST /v1/video/generations model={payload.get('model')}",
    )

    response = _post_task_creation(
        lambda: _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
        ),
        logger_prefix,
        f"{task_label} submit",
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}

    if response.status_code != 200:
        raise SeedanceAPIError(
            f"{task_label} submit rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:200])}"
        )

    task_id = None
    if isinstance(data, dict):
        task_id = data.get("task_id") or data.get("id")
        nested = data.get("data")
        if not task_id and isinstance(nested, dict):
            task_id = nested.get("task_id") or nested.get("id")
    if not task_id:
        raise SeedanceAPIError(
            f"No {task_label} task id in submit response: "
            f"{_truncate(response.text, 300)}"
        )

    _log(logger_prefix, "  Submit accepted")
    return str(task_id)


def poll_context_ir_task(
    task_id: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
    logger_prefix: str = "Minimax_H3_Context_IR",
    task_label: str = "Context IR",
) -> Dict[str, Any]:
    """Poll a compatibility task until ``data.status`` is terminal."""
    url = f"{config['base_url']}/v1/video/generations/{task_id}"
    poll_interval = config.get("poll_interval", 4.0)
    max_poll_time = config.get("max_poll_time", 1800)

    _log(logger_prefix, f"Poll {task_label} -> interval={poll_interval}s, max={max_poll_time}s")
    start_time = time.time()
    consecutive_failures = 0
    last_status = ""

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_poll_time:
            raise RuntimeError(
                f"{task_label} task exceeded {max_poll_time}s, polling stopped | "
                f"兼容任务超过 {max_poll_time}s，已停止轮询"
            )

        cooperative_sleep(poll_interval)

        try:
            response = _session().get(
                url,
                headers=_headers(config["api_key"], with_json=False),
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            consecutive_failures += 1
            _log(
                logger_prefix,
                f"{task_label} poll network error "
                f"({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES}): "
                f"{type(e).__name__}",
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"{task_label} polling failed after repeated network errors"
                )
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200:
            consecutive_failures += 1
            _log(
                logger_prefix,
                f"{task_label} poll HTTP {response.status_code} "
                f"({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})",
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"{task_label} polling failed: HTTP {response.status_code} repeatedly"
                )
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        try:
            response_data = response.json()
        except ValueError:
            consecutive_failures += 1
            _log(
                logger_prefix,
                f"{task_label} poll JSON parse error "
                f"({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})",
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"{task_label} polling failed: invalid JSON repeatedly"
                )
            continue

        task_data = response_data.get("data") if isinstance(response_data, dict) else None
        if not isinstance(task_data, dict):
            task_data = response_data if isinstance(response_data, dict) else None
        if not isinstance(task_data, dict):
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"{task_label} polling response has no task object"
                )
            continue

        consecutive_failures = 0
        status = str(task_data.get("status") or "").strip().upper()
        progress = _coerce_progress(task_data.get("progress"))

        if status != last_status:
            _log(
                logger_prefix,
                f"  {task_label} poll: status={status}, progress={progress}, "
                f"elapsed={int(elapsed)}s",
            )
            last_status = status

        if on_progress and progress is not None:
            try:
                on_progress(progress)
            except Exception:
                pass

        if status in {"SUCCESS", "SUCCEEDED", "COMPLETED"}:
            _log(logger_prefix, f"  {task_label} task completed in {int(elapsed)}s")
            return response_data

        if status in {"FAILURE", "FAILED", "CANCELED", "CANCELLED"}:
            reason = task_data.get("fail_reason") or _extract_error_message(
                task_data, f"{task_label} task failed"
            )
            raise SeedanceAPIError(
                f"{task_label} task failed: {reason}"
            )

        if status and status not in _CONTEXT_IR_RUNNING_STATUSES:
            _log(logger_prefix, f"  Unknown {task_label} status '{status}', continue polling...")


def submit_legacy_video_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Legacy_Video",
) -> str:
    """Submit a video task through the documented compatibility endpoint."""
    return submit_context_ir_task(
        payload,
        config,
        logger_prefix=logger_prefix,
        task_label="Legacy video",
    )


def poll_legacy_video_task(
    task_id: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
    logger_prefix: str = "Legacy_Video",
) -> Dict[str, Any]:
    """Poll a video task submitted through the compatibility endpoint."""
    return poll_context_ir_task(
        task_id,
        config,
        on_progress=on_progress,
        logger_prefix=logger_prefix,
        task_label="Legacy video",
    )


def extract_legacy_video_url(final_response: Dict[str, Any]) -> str:
    """Extract a video URL from the compatibility endpoint response."""
    containers: List[Any] = [final_response]
    visited = set()
    index = 0
    while index < len(containers) and index < 32:
        container = containers[index]
        index += 1
        if not isinstance(container, dict):
            continue
        identity = id(container)
        if identity in visited:
            continue
        visited.add(identity)
        containers.extend([
            container.get("data"),
            container.get("result"),
            container.get("output"),
            container.get("content"),
            container.get("metadata"),
        ])
        for key in ("result_url", "video_url", "url"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        return item.strip()

    raise SeedanceAPIError(
        "Legacy video task completed but no video URL in response: "
        f"{_truncate(json.dumps(final_response, ensure_ascii=False), 300)}"
    )


def extract_context_ir_text(final_response: Dict[str, Any]) -> str:
    """Extract the documented ``result_text`` from a completed Context IR task."""
    containers: List[Any] = [final_response]
    if isinstance(final_response, dict):
        containers.append(final_response.get("data"))
    for container in containers:
        if isinstance(container, dict):
            result_text = container.get("result_text")
            if isinstance(result_text, str) and result_text.strip():
                return result_text.strip()
    raise SeedanceAPIError(
        "Context IR task completed but no result_text in response: "
        f"{_truncate(json.dumps(final_response, ensure_ascii=False), 300)}"
    )


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

_IMAGE_RUNNING_STATUSES = {"NOT_START", "SUBMITTED", "QUEUED", "IN_PROGRESS"}
_IMAGE_DOWNLOAD_TIMEOUT = 60
_IMAGE_DOWNLOAD_CONNECT_TIMEOUT = 8
_IMAGE_DOWNLOAD_READ_TIMEOUT = 60


def _download_limit_bytes(environment_name: str, default_mib: int) -> int:
    raw_value = os.environ.get(environment_name, "").strip()
    if not raw_value:
        return int(default_mib) * 1024 * 1024
    try:
        value_mib = int(raw_value)
        if value_mib <= 0:
            raise ValueError
    except (TypeError, ValueError):
        print(
            f"[Seedance] WARNING: ignoring invalid {environment_name}; "
            f"using {default_mib} MiB"
        )
        value_mib = int(default_mib)
    return value_mib * 1024 * 1024


_IMAGE_DOWNLOAD_MAX_BYTES = _download_limit_bytes(
    "SEEDANCE_IMAGE_MAX_MIB", 64
)
_RESULT_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36 ComfyUI-Seedance"
)
_IMAGE_DOWNLOAD_HEADERS = {
    "User-Agent": _RESULT_DOWNLOAD_USER_AGENT,
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
    "Connection": "close",
}
_AUDIO_DOWNLOAD_HEADERS = {
    "User-Agent": _RESULT_DOWNLOAD_USER_AGENT,
    "Accept": "audio/mpeg,audio/wav,audio/ogg,audio/*,*/*;q=0.8",
    "Connection": "close",
}
_VIDEO_DOWNLOAD_HEADERS = {
    "User-Agent": _RESULT_DOWNLOAD_USER_AGENT,
    "Accept": "video/mp4,video/webm,video/*,*/*;q=0.8",
    "Connection": "close",
}
_FILE_DOWNLOAD_HEADERS = {
    "User-Agent": _RESULT_DOWNLOAD_USER_AGENT,
    "Accept": "*/*",
    "Connection": "close",
}


class _ResultDownloadTransportError(RuntimeError):
    """Sanitized failure from a generated-media result transport."""


class _ResultDownloadLimitError(_ResultDownloadTransportError):
    """Generated media exceeded its configured safety limit."""


_ImageDownloadTransportError = _ResultDownloadTransportError


def _declared_content_length(response: Any) -> int:
    headers = getattr(response, "headers", {}) or {}
    raw_value = headers.get("Content-Length", None)
    if raw_value is None:
        for name, value in getattr(headers, "items", lambda: ())():
            if str(name).lower() == "content-length":
                raw_value = value
                break
    try:
        return max(0, int(raw_value or 0))
    except (TypeError, ValueError):
        return 0


def _raise_if_download_too_large(size: int, max_bytes: int, item_name: str) -> None:
    if int(size) > int(max_bytes):
        raise _ResultDownloadLimitError(
            f"{item_name} exceeded the configured download size limit"
        )


def submit_image_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Seedream_Image",
) -> str:
    """POST /v1/image/generations and return the image task id."""
    url = f"{config['base_url']}/v1/image/generations"
    _log(logger_prefix, f"Submit -> POST /v1/image/generations model={payload.get('model')}")

    response = _post_task_creation(
        lambda: _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
        ),
        logger_prefix,
        "Image submit",
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
            response = _session().get(
                url,
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
    """Extract every documented image URL while preserving API result order."""
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


def extract_image_operation_result(final_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the documented result object from GK v2 utility operations."""
    task_data = final_response.get("data") if isinstance(final_response, dict) else None
    containers: List[Any] = [task_data]
    if isinstance(task_data, dict):
        containers.extend((task_data.get("data"), task_data.get("content")))
        upstream_data = task_data.get("data")
        if isinstance(upstream_data, dict):
            containers.append(upstream_data.get("content"))

    for container in containers:
        if isinstance(container, dict):
            result = container.get("result")
            if isinstance(result, dict):
                return result
    raise SeedanceAPIError(
        "Image utility task completed but no result object was returned"
    )


def extract_region_edit_url(final_response: Dict[str, Any]) -> str:
    """Extract a region-edit image URL from standard or nested result shapes."""
    try:
        return extract_image_url(final_response)
    except SeedanceAPIError:
        result = extract_image_operation_result(final_response)
        for key in ("image_url", "result_url", "url"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise SeedanceAPIError(
        "Region edit completed but no image URL was returned"
    )


# ---------------------------------------------------------------------------
# Hunyuan 3D generation
# ---------------------------------------------------------------------------

_3D_RUNNING_STATUSES = {
    "NOT_START", "SUBMITTED", "QUEUED", "IN_PROGRESS", "PENDING", "PROCESSING",
}
_3D_SUCCESS_STATUSES = {"SUCCESS", "SUCCEEDED", "COMPLETED"}
_3D_FAILURE_STATUSES = {"FAILURE", "FAILED", "CANCELLED", "CANCELED"}


def submit_3d_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Hunyuan3D",
) -> str:
    """POST /v1/3d/generations and return the asynchronous task id."""
    url = f"{config['base_url']}/v1/3d/generations"
    _log(logger_prefix, f"Submit -> POST /v1/3d/generations model={payload.get('model')}")
    response = _post_task_creation(
        lambda: _session().post(
            url,
            headers=_headers(config["api_key"]),
            json=payload,
            timeout=config.get("timeout", 60),
        ),
        logger_prefix,
        "3D submit",
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}
    if response.status_code != 200:
        raise SeedanceAPIError(
            f"3D submit rejected (HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:200])}"
        )
    task_id = None
    if isinstance(data, dict):
        task_id = data.get("task_id") or data.get("id")
    if not task_id:
        raise SeedanceAPIError("3D submit response did not contain a task id")
    _log(logger_prefix, "  Submit accepted")
    return str(task_id)


def poll_3d_task(
    task_id: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
    logger_prefix: str = "Hunyuan3D",
) -> Dict[str, Any]:
    """Poll a Hunyuan 3D task until its documented terminal state."""
    url = f"{config['base_url']}/v1/3d/generations/{task_id}"
    poll_interval = config.get("poll_interval", 4.0)
    max_poll_time = config.get("max_poll_time", 1800)
    _log(logger_prefix, f"Poll 3D -> interval={poll_interval}s, max={max_poll_time}s")
    start_time = time.time()
    consecutive_failures = 0
    last_status = ""

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_poll_time:
            raise RuntimeError(
                f"3D task exceeded {max_poll_time}s and polling stopped [task_id: {task_id}]"
            )
        cooperative_sleep(poll_interval)
        try:
            response = _session().get(
                url,
                headers=_headers(config["api_key"], with_json=False),
                timeout=30,
            )
        except requests.exceptions.RequestException as error:
            consecutive_failures += 1
            _log(
                logger_prefix,
                f"3D poll network error ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES}): "
                f"{type(error).__name__}",
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError("3D polling failed after repeated network errors")
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200:
            consecutive_failures += 1
            _log(
                logger_prefix,
                f"3D poll HTTP {response.status_code} "
                f"({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})",
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"3D polling failed after repeated HTTP {response.status_code} responses"
                )
            cooperative_sleep(min(consecutive_failures * 2, 10))
            continue

        try:
            response_data = response.json()
        except ValueError:
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError("3D polling repeatedly returned invalid JSON")
            continue

        consecutive_failures = 0
        task_data = response_data.get("data") if isinstance(response_data, dict) else None
        status_source = task_data if isinstance(task_data, dict) else response_data
        status = str(status_source.get("status") or "").strip().upper()
        progress = _coerce_progress(status_source.get("progress"))
        if status != last_status:
            _log(
                logger_prefix,
                f"  3D poll: status={status}, progress={progress}, elapsed={int(elapsed)}s",
            )
            last_status = status
        if on_progress and progress is not None:
            try:
                on_progress(progress)
            except Exception:
                pass
        if status in _3D_SUCCESS_STATUSES:
            _log(logger_prefix, f"  3D task completed in {int(elapsed)}s")
            return response_data
        if status in _3D_FAILURE_STATUSES:
            reason = _extract_error_message(status_source, "3D generation failed")
            raise SeedanceAPIError(f"3D task failed: {reason} [task_id: {task_id}]")
        if status and status not in _3D_RUNNING_STATUSES:
            _log(logger_prefix, f"  Unknown 3D status '{status}', continue polling...")


def extract_3d_url(final_response: Dict[str, Any]) -> str:
    """Extract the actual GLB URL from documented and observed result shapes."""
    candidates: List[Tuple[int, int, str]] = []

    def visit(value: Any, path: str = "root") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(value, str):
            return
        url = value.strip()
        if not url.startswith(("http://", "https://")):
            return
        lower_path = urlparse(url).path.lower()
        score = 0
        if lower_path.endswith(".glb"):
            score += 100
        if ".file_urls[" in path:
            score += 20
        if path.endswith(".file_url"):
            score += 10
        if path.endswith(".result_url"):
            score += 5
        candidates.append((score, len(candidates), url))

    visit(final_response)
    if candidates:
        return max(candidates, key=lambda item: (item[0], -item[1]))[2]
    raise SeedanceAPIError("3D task completed but no GLB URL was returned")


def _download_image_bytes(
    url: str,
    timeout: int,
    session: Optional[requests.Session] = None,
) -> bytes:
    total_timeout = _result_download_seconds(timeout)
    deadline = time.monotonic() + total_timeout
    request_timeout = (
        min(float(_IMAGE_DOWNLOAD_CONNECT_TIMEOUT), total_timeout),
        min(float(_IMAGE_DOWNLOAD_READ_TIMEOUT), total_timeout),
    )
    response = None
    try:
        response = (session or _session()).get(
            url,
            headers=_IMAGE_DOWNLOAD_HEADERS,
            stream=True,
            timeout=request_timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        _raise_if_download_too_large(
            _declared_content_length(response),
            _IMAGE_DOWNLOAD_MAX_BYTES,
            "Image result",
        )
        if not hasattr(response, "iter_content"):
            content = bytes(response.content)
            if not content:
                raise _ImageDownloadTransportError(
                    "Image result download returned an empty body"
                )
            _raise_if_download_too_large(
                len(content), _IMAGE_DOWNLOAD_MAX_BYTES, "Image result"
            )
            return content

        content = bytearray()
        for chunk in response.iter_content(chunk_size=1 << 16):
            check_cancelled()
            if time.monotonic() > deadline:
                raise requests.exceptions.Timeout(
                    f"Image result download exceeded {total_timeout:g}s"
                )
            if chunk:
                _raise_if_download_too_large(
                    len(content) + len(chunk),
                    _IMAGE_DOWNLOAD_MAX_BYTES,
                    "Image result",
                )
                content.extend(chunk)
        if not content:
            raise _ImageDownloadTransportError(
                "Image result download returned an empty body"
            )
        return bytes(content)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def download_image(
    url: str,
    timeout: int = _IMAGE_DOWNLOAD_TIMEOUT,
    max_retries: int = 3,
    logger_prefix: str = "Seedream_Image",
) -> Any:
    """Download a result image and return a ComfyUI IMAGE tensor [1,H,W,3]."""
    from io import BytesIO

    import numpy as np
    import torch
    from PIL import Image

    _log(logger_prefix, "Download image -> remote result")

    def decode(content: bytes) -> Any:
        with Image.open(BytesIO(content)) as image:
            rgb = image.convert("RGB")
            array = np.asarray(rgb, dtype=np.float32).copy() / 255.0
        return torch.from_numpy(array).unsqueeze(0)

    tensor = _download_and_decode_image(
        url, decode, timeout, max_retries, logger_prefix, "Image"
    )
    _log(logger_prefix, f"  Downloaded image {tensor.shape[2]}x{tensor.shape[1]}")
    return tensor


def download_image_with_mask(
    url: str,
    timeout: int = _IMAGE_DOWNLOAD_TIMEOUT,
    max_retries: int = 3,
    logger_prefix: str = "Seedream_Layer_Decomposition",
) -> Tuple[Any, Any]:
    """Download one image as standard ComfyUI IMAGE and transparency MASK tensors."""
    from io import BytesIO

    import numpy as np
    import torch
    from PIL import Image

    _log(logger_prefix, "Download layer image -> remote result")

    def decode(content: bytes) -> Tuple[Any, Any]:
        with Image.open(BytesIO(content)) as source:
            rgba = source.convert("RGBA")
            rgb_array = np.asarray(rgba.convert("RGB"), dtype=np.float32).copy()
            alpha_array = np.asarray(rgba.getchannel("A"), dtype=np.float32).copy()
        image = torch.from_numpy(rgb_array / 255.0).unsqueeze(0)
        mask = torch.from_numpy(1.0 - alpha_array / 255.0).unsqueeze(0)
        return image, mask

    image, mask = _download_and_decode_image(
        url, decode, timeout, max_retries, logger_prefix, "Layer image"
    )
    _log(
        logger_prefix,
        f"  Downloaded layer image {image.shape[2]}x{image.shape[1]}",
    )
    return image, mask


def download_image_with_path(
    url: str,
    timeout: int = _IMAGE_DOWNLOAD_TIMEOUT,
    max_retries: int = 3,
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

    def decode(content: bytes) -> Tuple[Any, str]:
        with Image.open(BytesIO(content)) as image:
            rgb = image.convert("RGB")
            array = np.asarray(rgb, dtype=np.float32).copy() / 255.0
            path = os.path.join(
                output_dir,
                f"midjourney_image_{uuid.uuid4().hex[:12]}.png",
            )
            rgb.save(path, format="PNG")
        return torch.from_numpy(array).unsqueeze(0), path

    tensor, path = _download_and_decode_image(
        url, decode, timeout, max_retries, logger_prefix, "Image"
    )
    _log(
        logger_prefix,
        f"  Downloaded image {tensor.shape[2]}x{tensor.shape[1]} -> {path}",
    )
    return tensor, path


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

    response = _post_task_creation(
        lambda: _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
        ),
        logger_prefix,
        "Audio submit",
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
            response = _session().get(
                url,
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


def extract_audio_urls(final_response: Dict[str, Any]) -> List[str]:
    """Extract every documented audio URL while preserving upstream order."""
    task_data = final_response.get("data")
    if isinstance(task_data, dict):
        upstream_data = task_data.get("data")
        if isinstance(upstream_data, dict):
            content = upstream_data.get("content")
            if isinstance(content, dict):
                audio_urls = content.get("audio_urls")
                if isinstance(audio_urls, list):
                    urls = [str(value) for value in audio_urls if value]
                    if urls:
                        return urls
                for key in ("audio_url", "url"):
                    if content.get(key):
                        return [str(content[key])]

        result_url = task_data.get("result_url")
        if result_url:
            return [str(result_url)]

    raise SeedanceAPIError(
        f"Audio task completed but no audio URL in response: "
        f"{_truncate(json.dumps(final_response, ensure_ascii=False), 300)}"
    )


def extract_audio_url(final_response: Dict[str, Any]) -> str:
    """Extract the primary audio URL from a successful task response."""
    return extract_audio_urls(final_response)[0]


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

    response = _post_task_creation(
        lambda: _session().post(
                url,
                headers=_headers(config["api_key"], with_json=False),
                data=data,
                files=files,
                timeout=config.get("timeout", 60),
        ),
        logger_prefix,
        "Transcription submit",
    )
    parsed: Any = None
    try:
        parsed = response.json() if response.text else None
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


_AUDIO_DOWNLOAD_TIMEOUT = 300
_AUDIO_DOWNLOAD_CONNECT_TIMEOUT = 8
_AUDIO_DOWNLOAD_READ_TIMEOUT = 60
_AUDIO_DOWNLOAD_MAX_BYTES = _download_limit_bytes(
    "SEEDANCE_AUDIO_MAX_MIB", 512
)


def download_audio(
    url: str,
    output_format: str = "wav",
    sample_rate: int = 24000,
    timeout: int = _AUDIO_DOWNLOAD_TIMEOUT,
    max_retries: int = 3,
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
    extension = _guess_audio_extension(url, "", output_format)
    audio_path = os.path.join(
        output_dir,
        f"seed_audio_{uuid.uuid4().hex[:12]}.{extension}",
    )

    def decode_download(path: str) -> Any:
        try:
            return _decode_audio_file(path, int(sample_rate), logger_prefix)
        except Exception as error:
            raise _ResultDownloadTransportError(
                f"Downloaded audio validation failed: {type(error).__name__}"
            ) from None

    _content_type, audio = _download_to_path_with_recovery(
        url=url,
        path=audio_path,
        timeout=timeout,
        max_retries=max_retries,
        logger_prefix=logger_prefix,
        item_name="Audio",
        headers=_AUDIO_DOWNLOAD_HEADERS,
        connect_timeout=_AUDIO_DOWNLOAD_CONNECT_TIMEOUT,
        read_timeout=_AUDIO_DOWNLOAD_READ_TIMEOUT,
        max_bytes=_AUDIO_DOWNLOAD_MAX_BYTES,
        validator=decode_download,
    )
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    _log(logger_prefix, f"  Downloaded {size_mb:.2f} MB -> {audio_path}")
    return audio, audio_path


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

    response = _post_task_creation(
        lambda: _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
        ),
        logger_prefix,
        "Music submit",
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
    _log(
        logger_prefix,
        f"  Music submit accepted with {response_mode} response",
    )
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
            response = _session().get(
                url,
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
        for item in value:
            text = _extract_music_text(item)
            if text:
                return text
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


def _collect_music_string_values(value: Any, key_name: str) -> List[str]:
    values: List[str] = []
    seen: Set[str] = set()

    def visit(item: Any):
        if isinstance(item, dict):
            for key, child in item.items():
                if key == key_name and isinstance(child, str) and child.strip():
                    normalized = child.strip()
                    if normalized not in seen:
                        seen.add(normalized)
                        values.append(normalized)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return values


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
        "clip_ids": _collect_music_string_values(result_data, "clip_id"),
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

    response = _post_task_creation(
        lambda: _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
        ),
        logger_prefix,
        "Midjourney submit",
    )
    try:
        data = response.json() if response.text else {}
    except ValueError:
        data = {}

    if response.status_code < 200 or response.status_code >= 300:
        raise SeedanceAPIError(
            f"Midjourney {action_text} rejected "
            f"(HTTP {response.status_code}): "
            f"{_extract_error_message(data, response.text[:300])}"
        )
    if not isinstance(data, dict):
        raise SeedanceAPIError(
            "Midjourney submit returned an invalid JSON object"
        )

    task_id = _extract_midjourney_task_id(data)
    response_mode = "task" if task_id else "immediate"
    _log(
        logger_prefix,
        f"  Midjourney {action_text} accepted with {response_mode} response",
    )
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
                candidate = _session().get(
                    f"{config['base_url']}{route}",
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

        if response.status_code == 429 or response.status_code >= 500:
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


_FILE_DOWNLOAD_TIMEOUT = 300
_FILE_DOWNLOAD_CONNECT_TIMEOUT = 8
_FILE_DOWNLOAD_READ_TIMEOUT = 60
_FILE_DOWNLOAD_MAX_BYTES = _download_limit_bytes(
    "SEEDANCE_FILE_MAX_MIB", 1024
)


def download_file(
    url: str,
    filename_prefix: str = "suno_result",
    default_extension: str = "bin",
    timeout: int = _FILE_DOWNLOAD_TIMEOUT,
    max_retries: int = 3,
    logger_prefix: str = "Suno_Music",
) -> str:
    """Download an arbitrary result file into the ComfyUI output directory."""
    try:
        import folder_paths
        output_dir = folder_paths.get_output_directory()
    except ImportError:
        output_dir = os.environ.get("SEEDANCE_OUTPUT_DIR") or os.getcwd()

    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.join(
        output_dir,
        f"{filename_prefix}_{uuid.uuid4().hex[:12]}",
    )
    download_path = f"{stem}.download"
    content_type, _validation = _download_to_path_with_recovery(
        url=url,
        path=download_path,
        timeout=timeout,
        max_retries=max_retries,
        logger_prefix=logger_prefix,
        item_name="File",
        headers=_FILE_DOWNLOAD_HEADERS,
        connect_timeout=_FILE_DOWNLOAD_CONNECT_TIMEOUT,
        read_timeout=_FILE_DOWNLOAD_READ_TIMEOUT,
        max_bytes=_FILE_DOWNLOAD_MAX_BYTES,
    )
    extension = _guess_file_extension(url, content_type, default_extension)
    path = f"{stem}{extension}"
    os.replace(download_path, path)
    _log(logger_prefix, f"  Downloaded result -> {path}")
    return path


def download_glb(
    url: str,
    filename_prefix: str = "hunyuan3d",
    logger_prefix: str = "Hunyuan3D",
) -> str:
    """Download and validate a GLB result for ComfyUI Preview3D/SaveGLB."""
    path = download_file(
        url,
        filename_prefix=filename_prefix,
        default_extension="glb",
        logger_prefix=logger_prefix,
    )
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            header = handle.read(12)
        if len(header) != 12 or header[:4] != b"glTF":
            raise SeedanceAPIError("Downloaded 3D result is not a GLB file")
        version = int.from_bytes(header[4:8], "little")
        declared_length = int.from_bytes(header[8:12], "little")
        if version != 2 or declared_length != size:
            raise SeedanceAPIError("Downloaded GLB header is invalid or incomplete")
        if not path.lower().endswith(".glb"):
            glb_path = f"{os.path.splitext(path)[0]}.glb"
            os.replace(path, glb_path)
            path = glb_path
        return path
    except Exception:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Result download
# ---------------------------------------------------------------------------

_VIDEO_DOWNLOAD_TIMEOUT = 180
_VIDEO_DOWNLOAD_CONNECT_TIMEOUT = 8
_VIDEO_DOWNLOAD_READ_TIMEOUT = 60
_VIDEO_DOWNLOAD_MAX_BYTES = _download_limit_bytes(
    "SEEDANCE_VIDEO_MAX_MIB", 8192
)


def _result_download_seconds(timeout: int) -> float:
    try:
        requested = float(timeout)
    except (TypeError, ValueError):
        requested = 1.0
    return max(1.0, requested)


def _download_result_to_path_requests(
    url: str,
    path: str,
    timeout: int,
    connect_timeout: int,
    read_timeout: int,
    headers: Dict[str, str],
    max_bytes: int = _VIDEO_DOWNLOAD_MAX_BYTES,
    session: Optional[requests.Session] = None,
) -> str:
    total_timeout = _result_download_seconds(timeout)
    deadline = time.monotonic() + total_timeout
    request_timeout = (
        min(float(connect_timeout), total_timeout),
        min(float(read_timeout), total_timeout),
    )
    part_path = f"{path}.part"
    response = None
    try:
        response = (session or _session()).get(
            url,
            headers=headers,
            stream=True,
            timeout=request_timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        _raise_if_download_too_large(
            _declared_content_length(response), max_bytes, "Generated media"
        )
        response_headers = getattr(response, "headers", {}) or {}
        content_type = str(response_headers.get("Content-Type", ""))
        content_encoding = str(response_headers.get("Content-Encoding", "")).lower()
        expected_size = 0
        if not content_encoding or content_encoding == "identity":
            try:
                expected_size = int(response_headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                expected_size = 0

        bytes_written = 0
        with open(part_path, "wb") as file_handle:
            if hasattr(response, "iter_content"):
                chunks = response.iter_content(chunk_size=1 << 16)
            else:
                chunks = (bytes(response.content),)
            for chunk in chunks:
                check_cancelled()
                if time.monotonic() > deadline:
                    raise requests.exceptions.Timeout(
                        f"Generated media download exceeded {total_timeout:g}s"
                    )
                if chunk:
                    _raise_if_download_too_large(
                        bytes_written + len(chunk), max_bytes, "Generated media"
                    )
                    file_handle.write(chunk)
                    bytes_written += len(chunk)
        if bytes_written <= 0:
            raise _ResultDownloadTransportError(
                "Generated media download returned an empty body"
            )
        if expected_size > 0 and bytes_written != expected_size:
            raise _ResultDownloadTransportError(
                "Generated media download length did not match the response"
            )
        os.replace(part_path, path)
        return content_type
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass


def _download_video_to_path(url: str, path: str, timeout: int) -> None:
    _download_result_to_path_requests(
        url=url,
        path=path,
        timeout=timeout,
        connect_timeout=_VIDEO_DOWNLOAD_CONNECT_TIMEOUT,
        read_timeout=_VIDEO_DOWNLOAD_READ_TIMEOUT,
        headers=_VIDEO_DOWNLOAD_HEADERS,
        max_bytes=_VIDEO_DOWNLOAD_MAX_BYTES,
    )


def _find_curl_binary() -> Optional[str]:
    for variable in ("SEEDANCE_CURL", "CURL_BINARY"):
        configured = os.environ.get(variable, "").strip()
        if not configured:
            continue
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        if os.path.isfile(configured):
            return configured

    return shutil.which("curl.exe") or shutil.which("curl")


def _curl_config_value(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise _ResultDownloadTransportError("Invalid generated media URL")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run_curl_download(
    url: str,
    timeout: int,
    connect_timeout: int,
    headers: Dict[str, str],
    output_path: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> bytes:
    """Download through the system TLS stack without exposing result URLs in argv."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise _ResultDownloadTransportError("Invalid generated media URL")

    curl_binary = _find_curl_binary()
    if not curl_binary:
        raise _ResultDownloadTransportError("System media downloader is unavailable")

    total_timeout = _result_download_seconds(timeout)
    limited_connect_timeout = min(float(connect_timeout), total_timeout)
    config_lines = [
        "silent",
        "show-error",
        "fail",
        "location",
        "compressed",
        f"connect-timeout = {limited_connect_timeout:g}",
        f"max-time = {total_timeout:g}",
    ]
    if max_bytes is not None:
        config_lines.append(f"max-filesize = {int(max_bytes)}")
    user_agent = str(headers.get("User-Agent", _RESULT_DOWNLOAD_USER_AGENT))
    config_lines.append(f'user-agent = "{_curl_config_value(user_agent)}"')
    for name, value in headers.items():
        if name.lower() == "user-agent":
            continue
        header = _curl_config_value(f"{name}: {value}")
        config_lines.append(f'header = "{header}"')
    config_lines.extend((f'url = "{_curl_config_value(url)}"', ""))
    config = "\n".join(config_lines).encode("utf-8")
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    )
    part_path = f"{output_path}.part" if output_path else None
    command = [curl_binary, "--disable", "--config", "-"]
    if part_path:
        try:
            os.remove(part_path)
        except FileNotFoundError:
            pass
        command.extend(("--output", part_path))

    try:
        check_cancelled()
        completed = subprocess.run(
            command,
            input=config,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=total_timeout + 5.0,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError) as error:
        if part_path and os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        raise _ResultDownloadTransportError(
            f"System media downloader failed: {type(error).__name__}"
        ) from None
    try:
        check_cancelled()
        if completed.returncode != 0:
            if completed.returncode == 63:
                raise _ResultDownloadLimitError(
                    "Generated media exceeded the configured download size limit"
                )
            raise _ResultDownloadTransportError(
                f"System media downloader failed with exit code {completed.returncode}"
            )
        if part_path:
            if not os.path.isfile(part_path) or os.path.getsize(part_path) <= 0:
                raise _ResultDownloadTransportError(
                    "System media downloader returned an empty body"
                )
            if max_bytes is not None:
                _raise_if_download_too_large(
                    os.path.getsize(part_path), max_bytes, "Generated media"
                )
            os.replace(part_path, output_path)
            return b""
        if not completed.stdout:
            raise _ResultDownloadTransportError(
                "System media downloader returned an empty body"
            )
        if max_bytes is not None:
            _raise_if_download_too_large(
                len(completed.stdout), max_bytes, "Generated media"
            )
        return bytes(completed.stdout)
    finally:
        if part_path and os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass


def _download_image_bytes_with_curl(url: str, timeout: int) -> bytes:
    return _run_curl_download(
        url=url,
        timeout=timeout,
        connect_timeout=_IMAGE_DOWNLOAD_CONNECT_TIMEOUT,
        headers=_IMAGE_DOWNLOAD_HEADERS,
        max_bytes=_IMAGE_DOWNLOAD_MAX_BYTES,
    )


def _download_result_to_path_with_curl(
    url: str,
    path: str,
    timeout: int,
    connect_timeout: int,
    headers: Dict[str, str],
    max_bytes: Optional[int] = None,
) -> None:
    _run_curl_download(
        url=url,
        timeout=timeout,
        connect_timeout=connect_timeout,
        headers=headers,
        output_path=path,
        max_bytes=max_bytes,
    )


def _is_result_transport_error(error: Exception) -> bool:
    return isinstance(
        error,
        (
            requests.exceptions.RequestException,
            _ResultDownloadTransportError,
            ConnectionError,
            TimeoutError,
            ssl.SSLError,
        ),
    )


def _should_retry_without_proxy(error: Exception) -> bool:
    return isinstance(
        error,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.ProxyError,
            ConnectionError,
        ),
    )


_is_image_transport_error = _is_result_transport_error


def _remove_result_path(path: str) -> None:
    for candidate in (path, f"{path}.part"):
        try:
            os.remove(candidate)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _download_to_path_with_recovery(
    url: str,
    path: str,
    timeout: int,
    max_retries: int,
    logger_prefix: str,
    item_name: str,
    headers: Dict[str, str],
    connect_timeout: int,
    read_timeout: int,
    max_bytes: int,
    validator: Optional[Callable[[str], Any]] = None,
) -> Tuple[str, Any]:
    attempts = max(1, int(max_retries))
    last_error: Optional[Exception] = None
    curl_attempted = False

    for attempt in range(attempts):
        if attempt > 0:
            cooperative_sleep(min(attempt, 2))
        try:
            content_type = _download_result_to_path_requests(
                url=url,
                path=path,
                timeout=timeout,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                headers=headers,
                max_bytes=max_bytes,
            )
            validation = validator(path) if validator is not None else None
            return content_type, validation
        except Exception as error:
            last_error = error
            _remove_result_path(path)
            _log(
                logger_prefix,
                f"{item_name} download attempt {attempt + 1} failed: "
                f"{type(error).__name__}",
            )

            if isinstance(error, _ResultDownloadLimitError):
                break

            if not _is_result_transport_error(error):
                continue

            _reset_thread_session()
            if _should_retry_without_proxy(error):
                _log(
                    logger_prefix,
                    f"Retrying {item_name.lower()} download without environment proxy...",
                )
                try:
                    content_type = _download_result_to_path_requests(
                        url=url,
                        path=path,
                        timeout=timeout,
                        connect_timeout=connect_timeout,
                        read_timeout=read_timeout,
                        headers=headers,
                        max_bytes=max_bytes,
                        session=_direct_session(),
                    )
                    validation = validator(path) if validator is not None else None
                    _log(logger_prefix, "  Direct no-proxy download succeeded")
                    return content_type, validation
                except Exception as direct_error:
                    last_error = direct_error
                    _remove_result_path(path)
                    _reset_direct_thread_session()
                    _log(
                        logger_prefix,
                        "Direct no-proxy download failed: "
                        f"{type(direct_error).__name__}",
                    )
                    if isinstance(direct_error, _ResultDownloadLimitError):
                        break

            if curl_attempted:
                continue

            curl_attempted = True
            _log(
                logger_prefix,
                f"Direct {item_name.lower()} connection failed; "
                "switching to system downloader...",
            )
            try:
                _download_result_to_path_with_curl(
                    url=url,
                    path=path,
                    timeout=timeout,
                    connect_timeout=connect_timeout,
                    headers=headers,
                    max_bytes=max_bytes,
                )
                validation = validator(path) if validator is not None else None
                _log(logger_prefix, "  System media downloader succeeded")
                return "", validation
            except Exception as fallback_error:
                last_error = fallback_error
                _remove_result_path(path)
                _log(
                    logger_prefix,
                    "System media downloader failed: "
                    f"{type(fallback_error).__name__}",
                )
                if isinstance(fallback_error, _ResultDownloadLimitError):
                    break

    error_name = (
        type(last_error).__name__ if last_error is not None else "UnknownError"
    )
    raise RuntimeError(
        f"Failed to download {item_name.lower()} after {attempts} attempts: "
        f"{error_name}"
    )


def _download_and_decode_image(
    url: str,
    decoder: Callable[[bytes], Any],
    timeout: int,
    max_retries: int,
    logger_prefix: str,
    item_name: str,
) -> Any:
    attempts = max(1, int(max_retries))
    last_error: Optional[Exception] = None
    curl_attempted = False

    for attempt in range(attempts):
        if attempt > 0:
            cooperative_sleep(min(attempt, 2))
        try:
            return decoder(_download_image_bytes(url, timeout))
        except Exception as error:
            last_error = error
            _log(
                logger_prefix,
                f"{item_name} download attempt {attempt + 1} failed: "
                f"{type(error).__name__}",
            )

            if isinstance(error, _ResultDownloadLimitError):
                break

            if not _is_image_transport_error(error):
                continue

            _reset_thread_session()
            if _should_retry_without_proxy(error):
                _log(
                    logger_prefix,
                    "Retrying image download without environment proxy...",
                )
                try:
                    result = decoder(
                        _download_image_bytes(
                            url,
                            timeout,
                            session=_direct_session(),
                        )
                    )
                    _log(logger_prefix, "  Direct no-proxy image download succeeded")
                    return result
                except Exception as direct_error:
                    last_error = direct_error
                    _reset_direct_thread_session()
                    _log(
                        logger_prefix,
                        "Direct no-proxy image download failed: "
                        f"{type(direct_error).__name__}",
                    )
                    if isinstance(direct_error, _ResultDownloadLimitError):
                        break

            if curl_attempted:
                continue

            curl_attempted = True
            _log(
                logger_prefix,
                "Direct image connection failed; switching to system downloader...",
            )
            try:
                result = decoder(_download_image_bytes_with_curl(url, timeout))
                _log(logger_prefix, "  System image downloader succeeded")
                return result
            except Exception as fallback_error:
                last_error = fallback_error
                _log(
                    logger_prefix,
                    "System image downloader failed: "
                    f"{type(fallback_error).__name__}",
                )
                if isinstance(fallback_error, _ResultDownloadLimitError):
                    break

    error_name = (
        type(last_error).__name__ if last_error is not None else "UnknownError"
    )
    raise RuntimeError(
        f"Failed to download {item_name.lower()} after {attempts} attempts: {error_name}"
    )


def _validate_mp4_result(path: str) -> None:
    try:
        with open(path, "rb") as file_handle:
            header = file_handle.read(64)
    except OSError as error:
        raise _ResultDownloadTransportError(
            f"Downloaded video could not be opened: {type(error).__name__}"
        ) from None
    if len(header) < 12 or b"ftyp" not in header:
        raise _ResultDownloadTransportError(
            "Downloaded video did not contain a valid MP4 header"
        )


def download_video_with_path(
    url: str,
    timeout: int = _VIDEO_DOWNLOAD_TIMEOUT,
    max_retries: int = 5,
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
    _download_to_path_with_recovery(
        url=url,
        path=video_path,
        timeout=timeout,
        max_retries=max_retries,
        logger_prefix=logger_prefix,
        item_name="Video",
        headers=_VIDEO_DOWNLOAD_HEADERS,
        connect_timeout=_VIDEO_DOWNLOAD_CONNECT_TIMEOUT,
        read_timeout=_VIDEO_DOWNLOAD_READ_TIMEOUT,
        max_bytes=_VIDEO_DOWNLOAD_MAX_BYTES,
        validator=_validate_mp4_result,
    )
    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    _log(logger_prefix, f"  Downloaded {size_mb:.1f} MB -> {video_path}")
    if VideoFromFile is not None:
        return VideoFromFile(video_path), video_path
    return video_path, video_path


def download_video(
    url: str,
    timeout: int = _VIDEO_DOWNLOAD_TIMEOUT,
    max_retries: int = 5,
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
