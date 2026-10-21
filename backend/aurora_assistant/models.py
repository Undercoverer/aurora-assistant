"""Explicit online provisioning; runtime checks never download anything."""
import argparse
import fcntl
import hashlib
import json
import os
import re
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
    if type(manifest) is not dict:
        raise ValueError('Model manifest must be an object')
    if manifest.get('spec_hash') != spec_hash(spec):
        raise ValueError('Installed models do not match the Nix configuration; check aurora-models.service')
    entries = manifest.get('files')
    if type(entries) is not dict or not entries:
        raise ValueError('Model manifest must list installed files')
    for name, digest in entries.items():
        if (type(name) is not str or not name or Path(name).is_absolute()
                or '..' in Path(name).parts or type(digest) is not str
                or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise ValueError('Invalid model manifest entry')
        path = current / name
        if not path.resolve().is_relative_to(current.resolve()):
            raise ValueError('Model manifest file escapes its generation')
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


def install_gguf(name, revision, destination):
    from huggingface_hub import HfApi, hf_hub_download
    match = re.fullmatch(r'hf\.co/([^/:]+/[^/:]+):([A-Za-z0-9_]+)', name)
    if not match:
        raise ValueError('GGUF model must use hf.co/owner/repository:QUANT format')
    repo, quant = match.groups()
    info = HfApi().model_info(repo, revision=revision or 'main')
    files = HfApi().list_repo_files(repo, revision=info.sha)
    matches = [f for f in files if f.lower().endswith('.gguf') and re.search(r'(?:^|[._-])' + re.escape(quant) + r'(?:[._-]|$)', Path(f).name, re.IGNORECASE)]
    if len(matches) != 1:
        raise ValueError('Quantization must resolve to exactly one GGUF file; split or ambiguous models are not supported')
    source = hf_hub_download(repo, filename=matches[0], revision=info.sha)
    with open(source, 'rb') as stream:
        if stream.read(4) != b'GGUF':
            raise ValueError('Downloaded model does not have a GGUF header')
    shutil.copyfile(source, destination)
    return {'repo': repo, 'revision': info.sha, 'file': matches[0]}


def install_retrieval(spec, stage):
    """Download only explicitly named graph/tokenizer files at one commit."""
    from huggingface_hub import HfApi, hf_hub_download
    repo = spec.get('repo')
    if type(repo) is not str or not repo or '/' not in repo:
        raise ValueError('A named retrieval model repository is required')
    files = {'model.onnx': spec['onnxFile'], 'tokenizer.json': spec['tokenizerFile']}
    for filename in files.values():
        if not filename or Path(filename).is_absolute() or '..' in Path(filename).parts:
            raise ValueError('Retrieval asset paths must be relative repository files')
    info = HfApi().model_info(repo, revision=spec['revision'])
    destination = stage / 'retrieval'
    destination.mkdir()
    for target, filename in files.items():
        source = hf_hub_download(repo, filename=filename, revision=info.sha)
        shutil.copyfile(source, destination / target)
    from .recall import OnnxEncoder
    OnnxEncoder({**spec, 'directory': str(destination.resolve())}).encode(['Aurora capability'])
    return {'repo': repo, 'revision': info.sha, 'files': files}


def install_assets(spec, stage):
    from openwakeword import MODELS, FEATURE_MODELS
    from supertonic.config import get_model_config
    from importlib.resources import files
    resolved = {}
    if spec.get('retrieval'):
        resolved['retrieval'] = install_retrieval(spec['retrieval'], stage)
    if spec.get('kevDecisionModel'):
        resolved['kev'] = install_gguf(spec['kevDecisionModel'], spec.get('revisions', {}).get('kev'), stage / 'kev.gguf')
    if spec.get('plannerModel'):
        resolved['planner'] = install_gguf(spec['plannerModel'], spec.get('revisions', {}).get('planner'), stage / 'planner.gguf')
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


def provision(spec, root, refresh=False, installer=install_assets):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.provision.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            cached = check(spec, root, full=True)
        except (OSError, ValueError, KeyError):
            cached = None
        if cached and not refresh:
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
                        'resolved': resolved, 'files': content}
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
