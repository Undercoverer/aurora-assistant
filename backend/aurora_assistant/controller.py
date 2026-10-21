import asyncio
import logging
from .actions import validate
from .telemetry import phase, content, new_turn, turn_id, failure, duration


class Controller:
    def __init__(self, overlay, inference, executor, apps, dbus_actions=None, agent=None, presentation=None, conversation=None):
        self.overlay, self.inference, self.executor, self.apps = overlay, inference, executor, apps
        self.dbus_actions = dbus_actions or {}
        self.agent = agent
        self.presentation = presentation or {}
        self.conversation = conversation or {}
        self.catalog_learner = None
        self.follow_up = False
        self.follow_up_count = 0
        self.context = []
        self.accept_events = False
        # Partial hypotheses and levels are latest-value slots, not an unbounded queue.
        self.pending = {}
        self.visual_lock = asyncio.Lock()

    def event(self, kind, value):
        if self.accept_events:
            if self.catalog_learner is not None and kind in {"state", "partial"}:
                self.catalog_learner.activity()
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
        if self.catalog_learner is not None:
            self.catalog_learner.activity()
        self.accept_events = False
        self.pending.clear()
        async with self.visual_lock:
            token = new_turn()
            try:
                content("transcript.final", text)
                with phase("turn"), duration("turn.end_to_end_ms", boundary="controller_lifecycle"):
                    spoken_approval = self.agent is not None and getattr(self.agent, 'confirmation_pending', False) is True
                    if spoken_approval and not self.follow_up:
                        self.agent.cancel_confirmation()
                        spoken_approval = False
                    if self.follow_up and text.strip() and not spoken_approval:
                        self.context.append({'user': text})
                        import json
                        request = 'Continue this clarification conversation: ' + json.dumps(self.context)
                    else:
                        self.context = [{'user': text}]
                        if not spoken_approval:
                            self.follow_up_count = 0
                        request = text
                    self.follow_up = False
                    await self._handle(request if text.strip() else '')
            finally:
                turn_id.reset(token)
                if self.catalog_learner is not None:
                    self.catalog_learner.activity(busy=self.follow_up)

    async def _handle(self, text):
        if not text.strip():
            if self.agent is not None and getattr(self.agent, 'confirmation_pending', False) is True:
                self.agent.cancel_confirmation()
            self.context = []
            await self.overlay.reset()
            return
        self.accept_events = False
        self.pending.clear()
        await self.overlay.level(0)
        await self.overlay.message(text)
        try:
            await self.overlay.state("thinking")
            if self.agent:
                with phase("agent"), duration("turn.processing_ms", boundary="agent_run"):
                    async with asyncio.timeout(self.presentation.get("agentTimeoutSeconds", 60)):
                        reply = await self.agent.run(text)
                failed = self.agent.failed
            else:
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
                content("reply.final", reply)
                await self.overlay.message(reply)
                await self.overlay.state("speaking")
                try:
                    with phase("speech"):
                        async with asyncio.timeout(30):
                            await self.inference.speak(reply, self.overlay.level, self.overlay.message)
                except Exception as exc:
                    # A failed output device must not erase completed action results.
                    logging.warning("Speech output failed (%s)", type(exc).__name__)
                    await self.overlay.level(0)
                    await self.overlay.message(reply + " Speech output is unavailable.")
                    await asyncio.sleep(3)
            if (self.agent and getattr(self.agent, "awaiting_reply", False) is True and not failed
                    and self.conversation.get('followUpSeconds', 12) > 0
                    and self.follow_up_count < self.conversation.get('maxFollowUps', 2)):
                self.follow_up = True
                self.follow_up_count += 1
                self.context.append({'assistant': reply})
                await self.overlay.message(reply + ' Listening for your answer…')
                await self.overlay.state('listening')
                return
            await self.overlay.state("error" if failed else "success")
            await asyncio.sleep(self.presentation.get("errorSeconds", 10) if failed else self.presentation.get("resultSeconds", 6))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never log transcripts, generated content, or raw model responses.
            failure('request.failed', exc)
            logging.warning("Turn failed (%s)", type(exc).__name__)
            await self.overlay.state("error")
            await self.overlay.message(f"The request could not be completed ({type(exc).__name__}, request {turn_id.get()}). Run aurora-report for details.")
            await asyncio.sleep(self.presentation.get("errorSeconds", 10))
        finally:
            if not self.follow_up:
                if self.agent is not None and getattr(self.agent, 'confirmation_pending', False) is True:
                    self.agent.cancel_confirmation()
                self.context = []
                await self.overlay.reset()
