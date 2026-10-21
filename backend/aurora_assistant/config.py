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
    _validate_stt(data["stt"])
    _validate_policy(data)
    _validate_apps(data["apps"])
    from .dbus_actions import validate_registry
    validate_registry(data.setdefault("dbus_actions", {}))
    return data


def _validate_number(section, key, low, high, integer=False):
    if key not in section:
        return
    value = section[key]
    kinds = (int,) if integer else (int, float)
    if type(value) not in kinds or not low <= value <= high:
        raise ValueError(f'{key} must be between {low} and {high}')


def _validate_stt(stt):
    silence = stt["silence_seconds"]
    if type(silence) not in (int, float) or not 0.2 <= silence <= 5:
        raise ValueError("silence_seconds must be between 0.2 and 5")
    _validate_number(stt, 'wake_threshold', 0.01, 1)
    _validate_number(stt, 'wake_timeout', 1, 60)
    _validate_number(stt, 'max_utterance_seconds', 5, 300)

def _validate_policy(data):
    execution = data.get('execution', {})
    if type(execution) is not dict or execution.get('backend', 'direct') not in ('direct', 'mcp'):
        raise ValueError('execution.backend must be direct or mcp')
    if execution.get('backend') == 'mcp':
        executable = execution.get('executable')
        if type(executable) is not str or not os.path.isabs(executable):
            raise ValueError('MCP requires an absolute installed executable')

    for section_name in ('settings', 'kev', 'safety', 'webSearch', 'catalog'):
        section = data.get(section_name, {})
        if type(section) is not dict:
            raise ValueError(f'{section_name} must be an object')
        for key in ('enable', 'announceEscalation', 'enrich', 'persist'):
            if key in section and type(section[key]) is not bool:
                raise ValueError(f'{section_name}.{key} must be boolean')
    if 'wordSync' in data['tts'] and type(data['tts']['wordSync']) is not bool:
        raise ValueError('tts.wordSync must be boolean')
    for key, low, high in (('idleSeconds', 15, 3600), ('intervalSeconds', 30, 86400), ('timeoutSeconds', 1, 60)):
        _validate_number(data.get('catalog', {}), key, low, high, integer=True)
    if data.get('settings', {}).get('discoveryMode', 'startup') not in ('startup', 'periodic'):
        raise ValueError('settings.discoveryMode must be startup or periodic')
    _validate_number(data.get('settings', {}), 'scanMaxObjects', 1, 128, integer=True)
    _validate_number(data.get('settings', {}), 'scanTimeoutSeconds', 1, 30)
    _validate_number(data.get('settings', {}), 'maxRounds', 1, 8, integer=True)
    _validate_number(data.get('kev', {}), 'maxRounds', 1, 4, integer=True)
    _validate_number(data.get('webSearch', {}), 'maxResults', 1, 8, integer=True)
    if 'url' in data.get('webSearch', {}):
        data['webSearch']['url'] = local_url(data['webSearch']['url'])
    for key in ('sessionPrefixes', 'systemPrefixes'):
        prefixes = data.get('settings', {}).get(key, [])
        if type(prefixes) is not list or any(type(p) is not str for p in prefixes):
            raise ValueError(f'{key} must be a list of strings')

    for section_name in ('presentation', 'conversation', 'diagnostics', 'inference'):
        if type(data.get(section_name, {})) is not dict:
            raise ValueError(f'{section_name} must be an object')
    inference = data.get('inference', {})
    if 'url' in inference:
        inference['url'] = local_url(inference['url'])
    models = inference.get('models', [])
    if type(models) is not list or len(models) > 2 or any(type(m) is not str or not m for m in models):
        raise ValueError('inference.models must contain at most two model names')
    if models and 'url' not in inference:
        raise ValueError('Managed models require an inference.url')
    _validate_number(inference, 'startupTimeoutSeconds', 30, 600, integer=True)
    if type(data.get('diagnostics', {}).get('logContent', False)) is not bool:
        raise ValueError('diagnostics.logContent must be boolean')
    for key, low, high in [('resultSeconds', 2, 60), ('errorSeconds', 3, 120), ('agentTimeoutSeconds', 10, 300)]:
        _validate_number(data.get('presentation', {}), key, low, high)
    _validate_number(data.get('conversation', {}), 'followUpSeconds', 0, 60)
    _validate_number(data.get('conversation', {}), 'maxFollowUps', 0, 4, integer=True)
    _validate_number(data.get('kev', {}), 'threshold', .5, 1)
    _validate_number(data.get('kev', {}), 'timeoutSeconds', 1, 60)
    _validate_number(data.get('kev', {}), 'contextSize', 4096, 65536, integer=True)
    if 'url' in data.get('kev', {}):
        data['kev']['url'] = local_url(data['kev']['url'])
    if data.get('safety', {}).get('backend', 'planner') not in ('kev', 'planner'):
        raise ValueError('safety.backend must be kev or planner')


def _validate_apps(apps):
    for alias, desktop in apps.items():
        if not alias or not isinstance(desktop, str) or not desktop.endswith(".desktop") or "/" in desktop or desktop.startswith("-"):
            raise ValueError("Applications must map to desktop entry filenames")


def offline_environment():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1", TORIO_USE_FFMPEG="0")


def require_assets(stt):
    for key in ("model", "realtime_model", "wake_model", "silero_model"):
        p = Path(stt[key]).expanduser()
        if not p.is_absolute() or not p.exists():
            raise ValueError(f"Missing local asset: {key}")
        stt[key] = str(p)
