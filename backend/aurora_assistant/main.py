import argparse
import asyncio
import logging
import signal
from .actions import Executor
from .dbus_actions import DBusActions
from .config import load, offline_environment
from .controller import Controller
from .inference import Inference
from .overlay import Overlay


async def run(config, text=None):
    overlay = Overlay()
    await overlay.connect()
    inference = Inference(config)
    registry = config.get("dbus_actions", {})
    executor = Executor(config["apps"], config["commands"], dbus_actions=DBusActions(registry))
    controller = Controller(overlay, inference, executor, config["apps"], registry)
    voice = None
    visuals = asyncio.create_task(controller.visuals())
    try:
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
        initializing = asyncio.create_task(asyncio.to_thread(Voice, config["stt"], emit))
        try:
            voice = await asyncio.shield(initializing)
        except asyncio.CancelledError:
            # Retain ownership of any recorder created during shutdown.
            voice = await initializing
            raise
        await overlay.reset()
        while True:
            controller.accept_events = True
            text = await asyncio.to_thread(voice.next)
            controller.accept_events = False
            controller.pending.clear()
            await controller.handle(text)
    finally:
        controller.accept_events = False
        if voice:
            await asyncio.to_thread(voice.close)
        visuals.cancel()
        await asyncio.gather(visuals, return_exceptions=True)
        await overlay.reset()
        await inference.close()
        overlay.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--text", help="Run one real request without opening the microphone")
    args = parser.parse_args()
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
            await run(load(args.config), args.text)
        except asyncio.CancelledError:
            pass
    asyncio.run(entry())


if __name__ == "__main__":
    main()
