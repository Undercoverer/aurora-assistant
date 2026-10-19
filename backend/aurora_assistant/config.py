import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def local_url(value):
    if type(value) is not str or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Inference URL must be a valid loopback HTTP URL")
    try:
        u = urlsplit(value)
        local = ipaddress.ip_address(u.hostname).is_loopback
        port = u.port  # Validate malformed and out-of-range ports at configuration load.
        valid = (u.scheme == "http" and local and u.username is None
                 and u.password is None and not u.query and not u.fragment
                 and port != 0 and not u.netloc.endswith(':'))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Inference URL must use http and a literal loopback IP with a valid port")
    return value.rstrip("/")


def load(path):
    data = json.loads(Path(path).read_text())
    data["llm"]["url"] = local_url(data["llm"]["url"])
    data["tts"]["url"] = local_url(data["tts"]["url"])
    silence = data["stt"]["silence_seconds"]
    if type(silence) not in (int, float) or not 0.2 <= silence <= 5:
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
