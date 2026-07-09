"""
Config resolution for Seedance API nodes.

Priority:
  1. Settings node output (``api_config`` input, SEEDANCE_CONFIG)
  2. Environment variables (SEEDANCE_API_KEY / SEEDANCE_BASE_URL / ...)
  3. ``config/.env`` file inside the plugin directory

Timeouts and polling knobs always fall back to env / .env / defaults, so the
Settings node only needs to carry base_url + api_key.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_BASE_URL = "https://api.seedance.nz"
DEFAULT_TIMEOUT = 60
DEFAULT_POLL_INTERVAL = 4.0
DEFAULT_MAX_POLL_TIME = 1800
DEFAULT_UPLOAD_TIMEOUT = 180


def _plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_env_file() -> Dict[str, str]:
    """Parse ``config/.env`` (key=value lines) if present."""
    env_path = _plugin_root() / "config" / ".env"
    result: Dict[str, str] = {}
    if not env_path.exists():
        return result
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and value:
                        result[key] = value
    except Exception:
        pass
    return result


def _extract_settings(api_config: Any) -> Optional[Dict]:
    """Unwrap the Settings node output (list-wrapped dict or plain dict)."""
    if api_config is None:
        return None
    if isinstance(api_config, list) and api_config:
        api_config = api_config[0]
    if isinstance(api_config, dict):
        return api_config
    return None


def _get_setting(env_data: Dict[str, str], key: str, default) -> str:
    return os.environ.get(key) or env_data.get(key) or str(default)


def get_config(api_config: Any = None) -> Dict[str, Any]:
    """Resolve the effective config for one node execution.

    Returns dict with keys: base_url, api_key, timeout, poll_interval,
    max_poll_time, upload_timeout.
    """
    env_data = _load_env_file()

    base_url = ""
    api_key = ""
    source = ""

    settings = _extract_settings(api_config)
    if settings:
        base_url = str(settings.get("base_url") or "").strip()
        api_key = str(settings.get("api_key") or settings.get("apiKey") or "").strip()
        if not api_key:
            raise RuntimeError(
                "Seedance API Config node is connected but api_key is empty. | "
                "已连接 Seedance API Config 节点，但 api_key 为空。"
            )
        source = "settings_node"

    if not api_key:
        base_url = (os.environ.get("SEEDANCE_BASE_URL") or env_data.get("SEEDANCE_BASE_URL") or "").strip()
        api_key = (os.environ.get("SEEDANCE_API_KEY") or env_data.get("SEEDANCE_API_KEY") or "").strip()
        source = "environment"

    if not api_key:
        raise RuntimeError(
            "Seedance API key is required. Connect a 'Seedance API Config' node, "
            "or set SEEDANCE_API_KEY env var / config/.env. Get your key at "
            f"{DEFAULT_BASE_URL}/console -> API tokens. | "
            "缺少 Seedance API key。请连接 'Seedance API Config' 节点，或设置 "
            "SEEDANCE_API_KEY 环境变量 / config/.env。"
        )

    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    config = {
        "base_url": base_url,
        "api_key": api_key,
        "timeout": int(_get_setting(env_data, "SEEDANCE_TIMEOUT", DEFAULT_TIMEOUT)),
        "poll_interval": float(_get_setting(env_data, "SEEDANCE_POLL_INTERVAL", DEFAULT_POLL_INTERVAL)),
        "max_poll_time": int(_get_setting(env_data, "SEEDANCE_MAX_POLL_TIME", DEFAULT_MAX_POLL_TIME)),
        "upload_timeout": int(_get_setting(env_data, "SEEDANCE_UPLOAD_TIMEOUT", DEFAULT_UPLOAD_TIMEOUT)),
    }
    print(f"[Seedance] Config source={source}, base_url={config['base_url']}")
    return config
