"""
HTTP client for the Seedance video, Seedream image, Seed Audio, and Whisper
transcription APIs.

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

Reliability rules:
  - Submit: retry on network errors / HTTP 5xx / 429; never retry 4xx
    business errors (invalid params, auth, moderation).
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
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import requests


class SeedanceAPIError(RuntimeError):
    """Business (non-retryable) API error."""


# ---------------------------------------------------------------------------
# HTTP session
#
# Keep runtime dependencies minimal. Requests uses its bundled/default CA
# handling on most systems; on Windows we additionally load the OS certificate
# store into a standard-library SSLContext, avoiding the truststore dependency.
# SEEDANCE_CA_BUNDLE can point to a custom CA file, and SEEDANCE_SSL_VERIFY=0
# disables verification as a last-resort escape hatch.
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


_session_singleton: Optional[requests.Session] = None


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
    global _session_singleton
    if _session_singleton is not None:
        return _session_singleton

    session = requests.Session()
    ca_bundle = os.environ.get("SEEDANCE_CA_BUNDLE", "").strip()

    if os.environ.get("SEEDANCE_SSL_VERIFY", "").strip().lower() in ("0", "false", "no"):
        session.verify = False
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        print("[Seedance] WARNING: SSL verification disabled via SEEDANCE_SSL_VERIFY=0")
    elif ca_bundle:
        session.verify = ca_bundle
        print(f"[Seedance] Using custom CA bundle: {ca_bundle}")
    else:
        ssl_context, cert_count = _windows_cert_store_context()
        if ssl_context is not None:
            session.mount("https://", _SSLContextAdapter(ssl_context))
            print(f"[Seedance] Using Windows certificate store ({cert_count} certificates)")

    _session_singleton = session
    return session


def _log(prefix: str, msg: str):
    print(f"[{prefix}] {msg}")


def _network_error_text(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}"
    if isinstance(e, requests.exceptions.SSLError):
        text += (
            " | SSL certificate verification failed. Fix: update certifi/requests "
            "in ComfyUI's Python, set SEEDANCE_CA_BUNDLE to a CA bundle file, or set "
            "SEEDANCE_SSL_VERIFY=0 to skip verification temporarily. | "
            "SSL 证书校验失败：请更新 ComfyUI Python 环境中的 certifi/requests，"
            "或设置 SEEDANCE_CA_BUNDLE 指向证书包；临时排障可设置 "
            "SEEDANCE_SSL_VERIFY=0 跳过校验。"
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
            time.sleep(wait)

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
            time.sleep(_UPLOAD_RATE_LIMIT_WAIT)
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

    last_error: Optional[Exception] = None
    for attempt in range(_SUBMIT_MAX_ATTEMPTS):
        if attempt > 0:
            wait = min(2 ** attempt + 1, 15)
            _log(logger_prefix, f"Submit retry {attempt + 1}/{_SUBMIT_MAX_ATTEMPTS} in {wait}s...")
            time.sleep(wait)

        try:
            response = _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
            )
        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Submit network error: {_network_error_text(e)}")
            _log(logger_prefix, f"Submit network error (attempt {attempt + 1}): {type(e).__name__}")
            continue

        try:
            data = response.json() if response.text else {}
        except ValueError:
            data = {}

        if response.status_code == 429 or response.status_code >= 500:
            last_error = RuntimeError(
                f"HTTP {response.status_code}: {_extract_error_message(data, response.text[:200])}"
            )
            _log(logger_prefix, f"Submit HTTP {response.status_code} (attempt {attempt + 1}), retrying...")
            continue

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

    raise RuntimeError(f"Submit failed after {_SUBMIT_MAX_ATTEMPTS} attempts: {last_error}")


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

        time.sleep(poll_interval)

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
            time.sleep(min(consecutive_failures * 2, 10))
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
            time.sleep(min(consecutive_failures * 2, 10))
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

_IMAGE_RUNNING_STATUSES = {"NOT_START", "SUBMITTED", "IN_PROGRESS"}


def submit_image_task(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    logger_prefix: str = "Seedream_Image",
) -> str:
    """POST /v1/image/generations and return the image task id."""
    url = f"{config['base_url']}/v1/image/generations"
    _log(logger_prefix, f"Submit -> POST /v1/image/generations model={payload.get('model')}")

    last_error: Optional[Exception] = None
    for attempt in range(_SUBMIT_MAX_ATTEMPTS):
        if attempt > 0:
            wait = min(2 ** attempt + 1, 15)
            _log(logger_prefix, f"Submit retry {attempt + 1}/{_SUBMIT_MAX_ATTEMPTS} in {wait}s...")
            time.sleep(wait)

        try:
            response = _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
            )
        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Submit network error: {_network_error_text(e)}")
            _log(logger_prefix, f"Submit network error (attempt {attempt + 1}): {type(e).__name__}")
            continue

        try:
            data = response.json() if response.text else {}
        except ValueError:
            data = {}

        if response.status_code == 429 or response.status_code >= 500:
            last_error = RuntimeError(
                f"HTTP {response.status_code}: {_extract_error_message(data, response.text[:200])}"
            )
            _log(logger_prefix, f"Submit HTTP {response.status_code} (attempt {attempt + 1}), retrying...")
            continue

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

    raise RuntimeError(f"Image submit failed after {_SUBMIT_MAX_ATTEMPTS} attempts: {last_error}")


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

        time.sleep(poll_interval)

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
            time.sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200:
            consecutive_failures += 1
            _log(logger_prefix, f"Image poll HTTP {response.status_code} ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"Image polling failed: HTTP {response.status_code} repeatedly [task_id: {task_id}]"
                )
            time.sleep(min(consecutive_failures * 2, 10))
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


def download_image(
    url: str,
    timeout: int = 300,
    max_retries: int = 3,
    logger_prefix: str = "Seedream_Image",
) -> Any:
    """Download a result image and return a ComfyUI IMAGE tensor [1,H,W,3]."""
    from io import BytesIO

    import numpy as np
    import torch
    from PIL import Image

    _log(logger_prefix, "Download image -> remote result")
    last_error: Optional[str] = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(2 ** attempt)
            response = _session().get(url, timeout=timeout)
            response.raise_for_status()
            with Image.open(BytesIO(response.content)) as image:
                rgb = image.convert("RGB")
                array = np.asarray(rgb, dtype=np.float32).copy() / 255.0
            tensor = torch.from_numpy(array).unsqueeze(0)
            _log(logger_prefix, f"  Downloaded image {tensor.shape[2]}x{tensor.shape[1]}")
            return tensor
        except Exception as e:
            last_error = type(e).__name__
            _log(logger_prefix, f"Image download attempt {attempt + 1} failed: {last_error}")

    raise RuntimeError(f"Failed to download image after {max_retries} attempts: {last_error}")


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

    last_error: Optional[Exception] = None
    for attempt in range(_SUBMIT_MAX_ATTEMPTS):
        if attempt > 0:
            wait = min(2 ** attempt + 1, 15)
            _log(logger_prefix, f"Submit retry {attempt + 1}/{_SUBMIT_MAX_ATTEMPTS} in {wait}s...")
            time.sleep(wait)

        try:
            response = _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
            )
        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Submit network error: {_network_error_text(e)}")
            _log(logger_prefix, f"Submit network error (attempt {attempt + 1}): {type(e).__name__}")
            continue

        try:
            data = response.json() if response.text else {}
        except ValueError:
            data = {}

        if response.status_code == 429 or response.status_code >= 500:
            last_error = RuntimeError(
                f"HTTP {response.status_code}: {_extract_error_message(data, response.text[:200])}"
            )
            _log(logger_prefix, f"Submit HTTP {response.status_code} (attempt {attempt + 1}), retrying...")
            continue

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

    raise RuntimeError(f"Audio submit failed after {_SUBMIT_MAX_ATTEMPTS} attempts: {last_error}")


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

        time.sleep(poll_interval)

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
            time.sleep(min(consecutive_failures * 2, 10))
            continue

        if response.status_code != 200:
            consecutive_failures += 1
            _log(logger_prefix, f"Audio poll HTTP {response.status_code} ({consecutive_failures}/{_MAX_CONSECUTIVE_POLL_FAILURES})")
            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"Audio polling failed: HTTP {response.status_code} repeatedly [task_id: {task_id}]"
                )
            time.sleep(min(consecutive_failures * 2, 10))
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

    last_error: Optional[Exception] = None
    for attempt in range(_SUBMIT_MAX_ATTEMPTS):
        if attempt > 0:
            wait = min(2 ** attempt + 1, 15)
            _log(logger_prefix, f"Transcription retry {attempt + 1}/{_SUBMIT_MAX_ATTEMPTS} in {wait}s...")
            time.sleep(wait)

        try:
            response = _session().post(
                url,
                headers=_headers(config["api_key"], with_json=False),
                data=data,
                files=files,
                timeout=config.get("timeout", 60),
            )
        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Transcription network error: {_network_error_text(e)}")
            _log(logger_prefix, f"Transcription network error (attempt {attempt + 1}): {type(e).__name__}")
            continue

        parsed: Any = None
        try:
            parsed = response.json() if response.text else None
        except ValueError:
            parsed = None

        if response.status_code == 429 or response.status_code >= 500:
            last_error = RuntimeError(
                f"HTTP {response.status_code}: {_extract_error_message(parsed, response.text[:200])}"
            )
            _log(logger_prefix, f"Transcription HTTP {response.status_code} (attempt {attempt + 1}), retrying...")
            continue

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

    raise RuntimeError(f"Transcription failed after {_SUBMIT_MAX_ATTEMPTS} attempts: {last_error}")


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
    last_error: Optional[str] = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(2 ** attempt)
            response = _session().get(url, stream=True, timeout=timeout)
            response.raise_for_status()
            content_type = (getattr(response, "headers", {}) or {}).get("Content-Type", "")
            ext = _guess_audio_extension(url, content_type, output_format)
            audio_path = os.path.join(output_dir, f"seed_audio_{uuid.uuid4().hex[:12]}.{ext}")

            with open(audio_path, "wb") as f:
                if hasattr(response, "iter_content"):
                    for chunk in response.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
                else:
                    f.write(response.content)

            size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            _log(logger_prefix, f"  Downloaded {size_mb:.2f} MB -> {audio_path}")
            audio = _decode_audio_file(audio_path, int(sample_rate), logger_prefix)
            return audio, audio_path
        except Exception as e:
            last_error = type(e).__name__
            _log(logger_prefix, f"Audio download attempt {attempt + 1} failed: {last_error}")

    raise RuntimeError(f"Failed to download audio after {max_retries} attempts: {last_error}")


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

    last_error: Optional[Exception] = None
    for attempt in range(_SUBMIT_MAX_ATTEMPTS):
        if attempt > 0:
            wait = min(2 ** attempt + 1, 15)
            _log(
                logger_prefix,
                f"Music submit retry {attempt + 1}/{_SUBMIT_MAX_ATTEMPTS} in {wait}s...",
            )
            time.sleep(wait)

        try:
            response = _session().post(
                url,
                headers=_headers(config["api_key"]),
                json=payload,
                timeout=config.get("timeout", 60),
            )
        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Music submit network error: {_network_error_text(e)}")
            _log(
                logger_prefix,
                f"Music submit network error (attempt {attempt + 1}): {type(e).__name__}",
            )
            continue

        try:
            data = response.json() if response.text else {}
        except ValueError:
            data = {}

        if response.status_code == 429 or response.status_code >= 500:
            last_error = RuntimeError(
                f"HTTP {response.status_code}: "
                f"{_extract_error_message(data, response.text[:200])}"
            )
            _log(
                logger_prefix,
                f"Music submit HTTP {response.status_code} "
                f"(attempt {attempt + 1}), retrying...",
            )
            continue

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

    raise RuntimeError(
        f"Music submit failed after {_SUBMIT_MAX_ATTEMPTS} attempts: {last_error}"
    )


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

        time.sleep(poll_interval)
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
    last_error: Optional[str] = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(2 ** attempt)
            response = _session().get(url, stream=True, timeout=timeout)
            response.raise_for_status()
            content_type = (getattr(response, "headers", {}) or {}).get(
                "Content-Type", ""
            )
            extension = _guess_file_extension(url, content_type, default_extension)
            path = os.path.join(
                output_dir,
                f"{filename_prefix}_{uuid.uuid4().hex[:12]}{extension}",
            )
            with open(path, "wb") as f:
                if hasattr(response, "iter_content"):
                    for chunk in response.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
                else:
                    f.write(response.content)
            _log(logger_prefix, f"  Downloaded result -> {path}")
            return path
        except Exception as e:
            last_error = type(e).__name__
            _log(
                logger_prefix,
                f"File download attempt {attempt + 1} failed: {last_error}",
            )
    raise RuntimeError(
        f"Failed to download result file after {max_retries} attempts: {last_error}"
    )


# ---------------------------------------------------------------------------
# Result download
# ---------------------------------------------------------------------------

def download_video_with_path(
    url: str,
    timeout: int = 300,
    max_retries: int = 3,
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
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(2 ** attempt)
            response = _session().get(url, stream=True, timeout=timeout)
            response.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            size_mb = os.path.getsize(video_path) / (1024 * 1024)
            _log(logger_prefix, f"  Downloaded {size_mb:.1f} MB -> {video_path}")
            if VideoFromFile is not None:
                return VideoFromFile(video_path), video_path
            return video_path, video_path
        except Exception as e:
            last_error = type(e).__name__
            _log(logger_prefix, f"Download attempt {attempt + 1} failed: {last_error}")
            continue

    raise RuntimeError(f"Failed to download video after {max_retries} attempts: {last_error}")


def download_video(
    url: str,
    timeout: int = 300,
    max_retries: int = 3,
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
