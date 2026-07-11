"""
HTTP client for the Seedance video and Seedream image generation APIs.

Endpoints:
  POST {base_url}/v1/videos              submit task
  GET  {base_url}/v1/videos/{task_id}    poll task
  POST {base_url}/v1/image/generations   submit image task
  GET  {base_url}/v1/image/generations/{task_id}
                                             poll image task
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
import os
import ssl
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests


class SeedanceAPIError(RuntimeError):
    """Business (non-retryable) API error."""


# ---------------------------------------------------------------------------
# HTTP session with OS trust store support
#
# Bundled certifi CA files in portable Python builds are often too old for
# newer Let's Encrypt intermediates, which makes cert verification fail even
# though browsers/curl (OS trust store) accept the site. When ``truststore``
# is available we verify against the OS trust store instead, matching
# browser behavior. SEEDANCE_SSL_VERIFY=0 disables verification entirely as
# a last-resort escape hatch.
# ---------------------------------------------------------------------------

class _TruststoreAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, ssl_context):
        self._ssl_context = ssl_context
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ssl_context
        return super().proxy_manager_for(*args, **kwargs)


_session_singleton: Optional[requests.Session] = None


def _session() -> requests.Session:
    global _session_singleton
    if _session_singleton is not None:
        return _session_singleton

    session = requests.Session()

    if os.environ.get("SEEDANCE_SSL_VERIFY", "").strip().lower() in ("0", "false", "no"):
        session.verify = False
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        print("[Seedance] WARNING: SSL verification disabled via SEEDANCE_SSL_VERIFY=0")
    else:
        try:
            import truststore
            ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            session.mount("https://", _TruststoreAdapter(ctx))
            print("[Seedance] Using OS trust store for SSL verification (truststore)")
        except ImportError:
            pass  # fall back to requests/certifi default
        except Exception as e:
            print(f"[Seedance] truststore setup failed, using certifi default: {e}")

    _session_singleton = session
    return session


def _log(prefix: str, msg: str):
    print(f"[{prefix}] {msg}")


def _network_error_text(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}"
    if isinstance(e, requests.exceptions.SSLError):
        text += (
            " | SSL certificate verification failed. Fix: install the 'truststore' "
            "package into ComfyUI's Python (pip install truststore) to use the OS "
            "trust store, or set env SEEDANCE_SSL_VERIFY=0 to skip verification. | "
            "SSL 证书校验失败：请在 ComfyUI 的 Python 环境安装 truststore 包"
            "（使用系统信任库），或设置环境变量 SEEDANCE_SSL_VERIFY=0 跳过校验。"
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

        _log(logger_prefix, f"  Upload success: {_truncate(file_url, 200)}")
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

        _log(logger_prefix, f"  Submit success: task_id={task_id}")
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

    _log(logger_prefix, f"Poll -> task_id={task_id}, interval={poll_interval}s, max={max_poll_time}s")

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

        _log(logger_prefix, f"  Submit success: task_id={task_id}")
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

    _log(logger_prefix, f"Poll image -> task_id={task_id}, interval={poll_interval}s, max={max_poll_time}s")
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

    _log(logger_prefix, f"Download image -> {_truncate(url, 200)}")
    last_error: Optional[Exception] = None
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
            last_error = e
            _log(logger_prefix, f"Image download attempt {attempt + 1} failed: {type(e).__name__}: {e}")

    raise RuntimeError(f"Failed to download image after {max_retries} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Result download
# ---------------------------------------------------------------------------

def download_video(
    url: str,
    timeout: int = 300,
    max_retries: int = 3,
    logger_prefix: str = "Seedance_Video",
) -> Any:
    """Download the result mp4 into ComfyUI's output dir, return VIDEO object.

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

    _log(logger_prefix, f"Download -> {_truncate(url, 200)}")
    last_error: Optional[Exception] = None
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
                return VideoFromFile(video_path)
            return video_path
        except Exception as e:
            last_error = e
            _log(logger_prefix, f"Download attempt {attempt + 1} failed: {type(e).__name__}: {e}")
            continue

    raise RuntimeError(f"Failed to download video after {max_retries} attempts: {last_error}")
