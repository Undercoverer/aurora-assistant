"""Explicit online provisioning; runtime checks never download anything."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time


def spec_hash(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def hashes(root):
    result = {}
    for file in sorted(root.rglob('*')):
        if file.is_file() and file.name != 'manifest.json' and '.cache' not in file.parts:
            with file.open('rb') as stream:
                result[file.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def check(spec, root, full=False):
    current = Path(root) / 'current'
    manifest = json.loads((current / 'manifest.json').read_text())
    if manifest['spec_hash'] != spec_hash(spec):
        raise ValueError('Installed models do not match the Nix configuration; check aurora-models.service')
    for name, digest in manifest['files'].items():
        path = current / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Missing model file: {name}')
    if full and hashes(current) != manifest['files']:
        raise ValueError('Model content hash mismatch')
    return manifest


def snapshot(repo, revision, destination):
    from huggingface_hub import HfApi, snapshot_download
    info = HfApi().model_info(repo, revision=revision)
    # Resolve once, then fetch that exact commit rather than following a moving ref.
    snapshot_download(repo_id=repo, revision=info.sha, local_dir=str(destination))
    shutil.rmtree(destination / '.cache', ignore_errors=True)
    return {'repo': repo, 'revision': info.sha}


def download(url, destination):
    import httpx
    with httpx.Client(follow_redirects=True, timeout=120, trust_env=False) as client:
        with client.stream('GET', url) as response:
            response.raise_for_status()
            with destination.open('wb') as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
    if destination.stat().st_size == 0:
        raise ValueError(f'Empty model download: {destination.name}')


def install_assets(spec, stage):
    from openwakeword import MODELS, FEATURE_MODELS
    from supertonic.config import get_model_config
    from importlib.resources import files
    resolved = {}
    wake = spec['wakeWord']
    if wake not in MODELS and not spec.get('wakeSource'):
        raise ValueError(f'Unknown openWakeWord model {wake!r}; available: {", ".join(sorted(MODELS))}. A new phrase needs a trained model.')
    if spec['silero'] != 'silero-vad':
        raise ValueError(f'Unknown Silero model: {spec["silero"]}')
    tts = get_model_config(spec['tts'])  # Reject unknown names before downloading.
    for key, dirname in [('stt', 'whisper'), ('realtimeStt', 'whisper-realtime')]:
        repo = spec[key]
        if '/' not in repo:
            repo = 'Systran/faster-whisper-' + repo
        destination = stage / dirname
        resolved[key] = snapshot(repo, spec.get('revisions', {}).get(key) or 'main', destination)
        for required in ('model.bin', 'config.json', 'tokenizer.json'):
            if not (destination / required).is_file():
                raise ValueError(f'{repo} is not a complete CTranslate2 Whisper model: missing {required}')
    if spec.get('wakeSource'):
        source = spec['wakeSource']
        path = source['file']
        if Path(path).is_absolute() or '..' in Path(path).parts:
            raise ValueError('wakeSource.file must be a relative repository path')
        from huggingface_hub import HfApi, hf_hub_download
        info = HfApi().model_info(source['repo'], revision=source['revision'])
        local = hf_hub_download(source['repo'], filename=path, revision=info.sha)
        shutil.copyfile(local, stage / 'wake.onnx')
        resolved['wakeWord'] = {'repo': source['repo'], 'revision': info.sha, 'file': path}
    else:
        url = MODELS[wake]['download_url'].replace('.tflite', '.onnx')
        download(url, stage / 'wake.onnx')
        resolved['wakeWord'] = {'name': wake, 'url': url}
    for key, filename in [('embedding', 'embedding_model.onnx'), ('melspectrogram', 'melspectrogram.onnx')]:
        url = FEATURE_MODELS[key]['download_url'].replace('.tflite', '.onnx')
        download(url, stage / filename)
        resolved[key] = {'url': url}
    # Silero assets are bundled in the locked Python package; no torch.hub access.
    silero = files('silero_vad').joinpath('data/silero_vad.onnx')
    (stage / 'silero_vad.onnx').write_bytes(silero.read_bytes())
    resolved['silero'] = {'package': 'silero-vad', 'file': 'data/silero_vad.onnx'}
    resolved['tts'] = snapshot(tts['repo'], spec.get('revisions', {}).get('tts') or tts['revision'], stage / 'supertonic')
    # Parse model/config assets without allowing any further downloads.
    from faster_whisper import WhisperModel
    for dirname in ('whisper', 'whisper-realtime'):
        recognizer = WhisperModel(str(stage / dirname), device='cpu', compute_type='int8', local_files_only=True)
        del recognizer
    from supertonic import TTS
    engine = TTS(model=spec['tts'], model_dir=stage / 'supertonic', auto_download=False)
    engine.get_voice_style(voice_name=spec.get('voice', 'F1'))
    del engine
    import onnxruntime as ort
    for filename in ('wake.onnx', 'embedding_model.onnx', 'melspectrogram.onnx', 'silero_vad.onnx'):
        session = ort.InferenceSession(str(stage / filename), providers=['CPUExecutionProvider'])
        del session
    return resolved


def ensure_ollama(spec, refresh=False):
    import httpx
    from .config import local_url
    url = local_url(spec['ollamaUrl'])
    names = {spec['llm']}
    if spec.get('kev'):
        names.add(spec['kev'])
    if spec.get('reviewer'):
        names.add(spec['reviewer'])
    if any('cloud' in name.lower() for name in names):
        raise ValueError('Cloud Ollama models are not permitted')
    with httpx.Client(trust_env=False, timeout=1800, follow_redirects=False) as client:
        for attempt in range(60):
            try:
                response = client.get(url + '/api/tags', timeout=2)
                response.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 59:
                    raise RuntimeError('Local Ollama service did not become ready') from None
                time.sleep(1)
        existing = {m['name']: m for m in response.json()['models']}
        resolved = {}
        for name in sorted(names):
            canonical = name if ':' in name.rsplit('/', 1)[-1] else name + ':latest'
            if canonical not in existing or refresh:
                print(f'Provisioning Ollama model: {name}', flush=True)
                result = client.post(url + '/api/pull', json={'model': name, 'stream': False})
                result.raise_for_status()
                if result.json().get('error') or result.json().get('status') != 'success':
                    raise ValueError(f'Ollama could not pull model {name}')
            result = client.post(url + '/api/show', json={'model': name})
            result.raise_for_status()
            if result.json().get('remote_host') or result.json().get('remote_model'):
                raise ValueError('Ollama model delegates inference to a remote host')
            response = client.get(url + '/api/tags')
            response.raise_for_status()
            installed = {m['name']: m for m in response.json()['models']}
            if canonical not in installed:
                raise ValueError(f'Ollama model is absent after provisioning: {name}')
            resolved[name] = installed[canonical]['digest']
    return resolved


def provision(spec, root, refresh=False, installer=install_assets, ollama=ensure_ollama):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.provision.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            cached = check(spec, root, full=True)
        except (OSError, ValueError, KeyError):
            cached = None
        # This checks the local service even when all speech files are already cached.
        ollama_models = ollama(spec, refresh=refresh)
        if cached and not refresh:
            if cached.get('ollama') != ollama_models:
                cached['ollama'] = ollama_models
                manifest_update = root / '.manifest-next'
                manifest_update.write_text(json.dumps(cached, indent=2) + '\n')
                os.replace(manifest_update, root / 'current' / 'manifest.json')
            print('Configured models are already installed.', flush=True)
            return cached
        generations = root / 'generations'
        generations.mkdir(exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='staging-', dir=generations))
        try:
            resolved = installer(spec, stage)
            content = hashes(stage)
            if not content:
                raise ValueError('No model files were installed')
            manifest = {'spec_hash': spec_hash(spec), 'requested': spec,
                        'resolved': resolved, 'ollama': ollama_models, 'files': content}
            (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            for path in stage.rglob('*'):
                path.chmod(0o755 if path.is_dir() else 0o644)
            stage.chmod(0o755)
            # Readers see a complete generation, never a half-downloaded snapshot.
            link = root / '.current-next'
            link.unlink(missing_ok=True)
            link.symlink_to(stage.relative_to(root), target_is_directory=True)
            os.replace(link, root / 'current')
            return manifest
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    spec = json.loads(Path(args.config).read_text())
    try:
        if args.check:
            check(spec, args.root)
        else:
            # Only this explicit setup command is online. The runtime remains offline.
            os.environ.update(HF_HUB_OFFLINE='0', TRANSFORMERS_OFFLINE='0', HF_HUB_DISABLE_TELEMETRY='1')
            provision(spec, args.root, args.refresh)
    except Exception as exc:
        raise SystemExit(f'Model provisioning/check failed: {exc}') from None


if __name__ == '__main__':
    main()
