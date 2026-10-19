import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def local_url(value):
    u = urlsplit(value)
    try:
        local = ipaddress.ip_address(u.hostname).is_loopback
    except ValueError:
        local = False
    if u.scheme != "http" or not local or u.username or u.password or u.query or u.fragment:
        raise ValueError("Inference URL must use http and a literal loopback IP")
    return value.rstrip("/")


def load(path):
    data = json.loads(Path(path).read_text())
    data["llm"]["url"] = local_url(data["llm"]["url"])
    data["tts"]["url"] = local_url(data["tts"]["url"])
    if not 0.2 <= data["stt"]["silence_seconds"] <= 5:
        raise ValueError("silence_seconds must be between 0.2 and 5")
    for alias, desktop in data["apps"].items():
        if not alias or not isinstance(desktop, str) or not desktop.endswith(".desktop") or "/" in desktop or desktop.startswith("-"):
            raise ValueError("Applications must map to desktop entry filenames")
    from .dbus_actions import validate_registry
    validate_registry(data.setdefault("dbus_actions", {}))
    return data


def offline_environment():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1", TORIO_USE_FFMPEG="0")


def require_assets(stt):
    for key in ("model", "realtime_model", "wake_model", "silero_model"):
        p = Path(stt[key]).expanduser()
        if not p.is_absolute() or not p.exists():
            raise ValueError(f"Missing local asset: {key}")
        stt[key] = str(p)
