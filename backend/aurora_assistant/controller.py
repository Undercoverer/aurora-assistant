import asyncio
import logging
from .actions import validate


class Controller:
    def __init__(self, overlay, inference, executor, apps, dbus_actions=None):
        self.overlay, self.inference, self.executor, self.apps = overlay, inference, executor, apps
        self.dbus_actions = dbus_actions or {}
        self.accept_events = False
        # Partial hypotheses and levels are latest-value slots, not an unbounded queue.
        self.pending = {}
        self.visual_lock = asyncio.Lock()

    def event(self, kind, value):
        if self.accept_events:
            self.pending[kind] = value

    async def visuals(self):
        while True:
            async with self.visual_lock:
                pending, self.pending = self.pending, {}
                if self.accept_events:
                    if "state" in pending:
                        await self.overlay.state(pending["state"])
                    if "partial" in pending:
                        await self.overlay.message(pending["partial"])
                    if "level" in pending:
                        await self.overlay.level(pending["level"])
            await asyncio.sleep(1 / 30)

    async def handle(self, text):
        self.accept_events = False
        self.pending.clear()
        async with self.visual_lock:
            await self._handle(text)

    async def _handle(self, text):
        if not text.strip():
            await self.overlay.reset()
            return
        self.accept_events = False
        self.pending.clear()
        await self.overlay.level(0)
        await self.overlay.message(text)
        try:
            await self.overlay.state("thinking")
            actions, reply = validate(await self.inference.plan(text), self.apps, self.dbus_actions)
            results = []
            failed = False
            if actions:
                await self.overlay.state("executing")
                for action in actions:
                    try:
                        results.append(await self.executor.execute(action))
                    except Exception:
                        failed = True
                        results.append("The next action failed. Remaining actions were not run.")
                        await self.overlay.state("error")
                        break
                # Only executor results can report action success.
                reply = " ".join(results)
            if reply:
                await self.overlay.message(reply)
                await self.overlay.state("speaking")
                await self.inference.speak(reply, self.overlay.level)
            await self.overlay.state("error" if failed else "success")
            await asyncio.sleep(0.6)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never log transcripts, generated content, or raw model responses.
            logging.warning("Turn failed (%s)", type(exc).__name__)
            await self.overlay.state("error")
            await self.overlay.message("The request could not be completed. Check the local services.")
            await asyncio.sleep(2)
        finally:
            await self.overlay.reset()
