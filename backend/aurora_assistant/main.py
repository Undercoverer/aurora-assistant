import argparse
import asyncio
import logging
import signal
import os
from contextlib import AsyncExitStack
from .actions import Executor
from .dbus_actions import DBusActions
from .config import load, offline_environment
from .controller import Controller
from .inference import Inference
from .overlay import Overlay
from .approval import Approval
from .settings import BusAccess
from .desktop_bus import RemoteDesktop
from .agent import SettingsAgent
from .telemetry import configure, event, phase


async def stop_visuals(controller, task):
    controller.accept_events = False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def show_service_failure(overlay, seconds, exc_type, exc, traceback):
    if exc is None or isinstance(exc, asyncio.CancelledError):
        return False
    event('controller.failed', error_type=type(exc).__name__)
    try:
        await overlay.state('error')
        await overlay.message('Assistant service failed. Run aurora-report to collect details.')
        await asyncio.sleep(seconds)
    except Exception:
        pass  # Preserve the original failure and continue resource cleanup.
    return False


async def run(config, text=None):
    # Each acquired resource is registered immediately. A failed cleanup must
    # not prevent closing the remaining resources, including on startup failure.
    async with AsyncExitStack() as cleanup:
        overlay = Overlay()
        cleanup.callback(overlay.close)
        await overlay.connect()
        inference = Inference(config)
        cleanup.push_async_callback(inference.close)
        registry = config.get("dbus_actions", {})
        executor = Executor(config["apps"], config["commands"], dbus_actions=DBusActions(registry))
        controller = Controller(overlay, inference, executor, config["apps"], registry, presentation=config.get("presentation", {}), conversation=config.get("conversation", {}))
        approval = Approval()
        approval.catalog = inference.catalog
        cleanup.push_async_callback(approval.close)
        controller.agent = SettingsAgent(config, inference,
            RemoteDesktop(BusAccess(config.get("settings", {})), executor), approval, overlay)
        voice = None
        await approval.start()
        cleanup.push_async_callback(overlay.reset)
        from functools import partial
        cleanup.push_async_exit(partial(show_service_failure, overlay, config.get("presentation", {}).get("errorSeconds", 10)))
        visuals = asyncio.create_task(controller.visuals())
        cleanup.push_async_callback(stop_visuals, controller, visuals)
        await overlay.state('thinking')
        await overlay.message('Starting local services and loading voice models…')
        with phase("services.ready"):
            await inference.wait_ready()
        if text is not None:
            await controller.handle(text)
            return
        from .voice import Voice
        loop = asyncio.get_running_loop()
        # A single scheduled flush bounds callback traffic even if the loop is busy.
        import threading
        lock = threading.Lock()
        mailbox = {}
        scheduled = False
        def flush():
            nonlocal scheduled
            with lock:
                values = dict(mailbox)
                mailbox.clear()
                scheduled = False
            for kind, value in values.items():
                controller.event(kind, value)
        def emit(kind, value):
            nonlocal scheduled
            with lock:
                mailbox[kind] = value
                if not scheduled:
                    scheduled = True
                    loop.call_soon_threadsafe(flush)
        event("voice.initialize.start")
        initializing = asyncio.create_task(asyncio.to_thread(Voice, config["stt"], emit))
        try:
            voice = await asyncio.shield(initializing)
        except asyncio.CancelledError:
            # Retain ownership of any recorder created during shutdown.
            voice = await initializing
            cleanup.push_async_callback(asyncio.to_thread, voice.close)
            raise
        cleanup.push_async_callback(asyncio.to_thread, voice.close)
        event("voice.initialize.done")
        await overlay.reset()
        while True:
            controller.accept_events = True
            if controller.follow_up:
                text = await asyncio.to_thread(voice.next, follow_up=True,
                    follow_up_seconds=config.get('conversation', {}).get('followUpSeconds', 12))
            else:
                text = await asyncio.to_thread(voice.next)
            controller.accept_events = False
            controller.pending.clear()
            await controller.handle(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--check-audio", action="store_true", help="Verify packaged audio libraries without opening a device")
    parser.add_argument("--text", help="Run one real request without opening the microphone")
    args = parser.parse_args()
    if args.check_audio:
        import json
        import sounddevice
        import soundfile
        print(json.dumps({'portaudio': sounddevice.get_portaudio_version(), 'libsndfile': soundfile.__libsndfile_version__}))
        return
    if not args.config:
        parser.error('--config is required unless --check-audio is used')
    config = load(args.config)
    configure(config)
    event('controller.start', config_path=args.config, revision=os.environ.get('AURORA_REVISION', 'unknown'))
    offline_environment()
    logging.basicConfig(level=logging.WARNING)
    # Upstream INFO logs can contain recognized text.
    logging.getLogger("realtimestt").disabled = True
    async def entry():
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, task.cancel)
        try:
            await run(config, args.text)
        except asyncio.CancelledError:
            pass
    asyncio.run(entry())


if __name__ == "__main__":
    main()
