"""Bounded discovery, review, and execution loop for a single user request."""
import json
import asyncio
import time
from .actions import validate, PlanValidationError
from .settings import READ_ACTIONS
from .telemetry import event, phase, failure


class SettingsAgent:
    def __init__(self, config, inference, desktop, approval, overlay, live_refresh=None):
        self.config, self.inference, self.desktop = config, inference, desktop
        self.approval, self.overlay = approval, overlay
        self.live_refresh = live_refresh

    async def run(self, text):
        self.failed = False
        self.awaiting_reply = False
        if len(text) > 8192:
            self.failed = True
            return 'The request is too long to process safely. Please shorten it. No actions were run.'
        evidence = []
        if self.live_refresh is not None:
            evidence.extend(await self.live_refresh() or [])
        initial_evidence_count = len(evidence)
        kev = self.config.get('kev', {})
        kev_active = kev.get('enable', False)
        kev_rounds = 0
        announced = False
        invalid_plans = 0
        for _ in range(self.config.get('settings', {}).get('maxRounds', 5)):
            plan = None
            if kev_active and kev_rounds < kev.get('maxRounds', 2):
                kev_rounds += 1
                try:
                    plan = await self.inference.quick_plan(text, evidence=evidence)
                except Exception as exc:
                    failure('kev.route_failed', exc)
            try:
                if plan is None:
                    kev_active = False
                    if kev.get('enable', False) and kev.get('announceEscalation', True) and not announced:
                        announced = True
                        plan = await self.with_notice(self.inference.plan(text, evidence=evidence),
                                                      kev.get('escalationMessage', 'Checking that in more detail.'))
                    else:
                        plan = await self.inference.plan(text, evidence=evidence)
                actions, reply = validate(
                    plan, self.config['apps'], self.config.get('dbus_actions', {}),
                    settings=self.config.get('settings', {}).get('enable', True),
                    web_search=self.config.get('webSearch', {}).get('enable', False),
                )
            except PlanValidationError as exc:
                event('plan.invalid', reason=str(exc))
                invalid_plans += 1
                if invalid_plans > 1:
                    self.failed = True
                    return 'The model returned an invalid action plan twice. No actions were run. Run aurora-report for details.'
                evidence.append({'validation_error': str(exc),
                                 'instruction': 'Return a corrected plan matching the supplied action schema exactly.'})
                kev_active = False
                continue
            if any(a.name == 'web_search' for a in actions):
                if len(actions) != 1 or len(evidence) > initial_evidence_count:
                    return 'Please ask the web question separately from desktop actions.'
                return await self._search(text, actions[0].argument)
            if not actions:
                self.awaiting_reply = reply.rstrip().endswith("?")
                return reply
            reads = [a for a in actions if a.name in READ_ACTIONS]
            if reads:
                # Proposed writes in a discovery round are discarded and replanned.
                observations = await self._observe(reads)
                evidence.extend(observations)
                if len(actions) == 1 and actions[0].name == 'desktop_read' and actions[0].argument == 'clock':
                    try:
                        return json.loads(observations[0]['result'])['reply']
                    except (ValueError, KeyError, TypeError):
                        self.failed = True
                        return 'The system clock could not be read. Run aurora-report for details.'
                kev_active = kev.get('enable', False)
                continue
            # Mute the microphone last so earlier operations do not lose input.
            actions = sorted(actions, key=lambda a: a.name == 'microphone_mute' and a.argument is True)
            try:
                prepared = [await self.desktop.prepare(action) for action in actions]
            except Exception as exc:
                failure('desktop.prepare.failed', exc)
                kev_active = False
                evidence.append({'preparation_error': str(exc)[:1000], 'actions': plan['actions']})
                continue  # No mutations have occurred; let the larger model resolve it.
            return await self._execute_plan(text, prepared)
        return 'No suitable D-Bus operation was found within the search limit. No changes were made. This does not establish whether the application is installed.'

    async def _observe(self, actions):
        observations = []
        for action in actions:
            try:
                with phase("desktop.read", action=action.name):
                    value = await self.desktop.read(action)
                catalog = getattr(self.inference, 'catalog', None)
                if catalog is not None:
                    catalog.observe(action, value)
                data = json.dumps(value, ensure_ascii=False)
                result = data[:12000]
            except Exception as exc:
                result = f'Read failed: {type(exc).__name__}: {exc}'[:1000]
            observations.append({'action': action.name, 'argument': action.argument, 'result': result})
        return observations

    async def _search(self, text, query):
        from .web_search import WebSearch
        self.approval.latest_search = None
        try:
            result = await WebSearch(self.config.get('webSearch', {})).search(query)
            if not result['results']:
                return 'The web search returned no usable snippets. No summary was generated.'
            answer = await self.inference.summarize_search(text, result)
            self.approval.latest_search = {**answer, 'retrievedAt': result['retrievedAt'], 'basis': result['basis']}
            return answer['summary'] + ' This answer uses search snippets. Source links are available through aurora-control sources.'
        except Exception:
            self.failed = True
            return 'Web search or its local summary failed. No web answer was generated. Check the local search service and internet connection.'

    async def _review(self, text, prepared):
        review = {'decision': 'allow', 'reason': 'Local policy permits the supported desktop actions.'}
        # Policy is based on validated capabilities, not the wording used to
        # request them. Generic D-Bus never inherits routine adapter privileges.
        routine = {'volume', 'mute', 'microphone_mute', 'media', 'open_url'}
        actual = [p.get('action') for p in prepared]
        if (actual and all(a and a.get('name') in routine for a in actual)
                and not any(p.get('requires_approval', True) for p in prepared)):
            validate({'actions': actual, 'reply': ''}, self.config['apps'], settings=True)
            event('review.local', policy='routine_capabilities')
            return review
        if self.config.get('safety', {}).get('enable', True):
            try:
                review = await self.inference.review(text, prepared)
            except Exception as exc:
                failure('review.failed', exc)
                review = {'decision': 'ask', 'reason': 'The local reviewer is unavailable or returned an invalid result.'}
        return review

    async def _execute_plan(self, text, prepared):
        review = await self._review(text, prepared)
        event("review.result", decision=review["decision"])
        if review['decision'] == 'block':
            event('apply.failure.reason', reason='policy', completed_actions=0)
            return 'No changes were made. ' + review['reason']
        # Desktop tokens use this host's monotonic clock. Leave a short
        # transport margin and never ask for approval beyond plan validity.
        deadlines = [p['expires_at'] for p in prepared if 'expires_at' in p]
        deadline = min(deadlines) - 2 if deadlines else float('inf')
        if time.monotonic() >= deadline:
            event('apply.failure.reason', reason='expired', completed_actions=0)
            self.failed = True
            return 'The prepared plan expired during review. No actions were run. Please ask again.'
        approved = False
        if review['decision'] == 'ask' or any(p['requires_approval'] for p in prepared):
            approved = await self.approval.request(
                {'request': text, 'plan': prepared, 'review': review}, self.overlay.message,
                timeout=min(120, deadline - time.monotonic()))
            if not approved:
                event('apply.failure.reason', reason='not_approved', completed_actions=0)
                return 'The change was not approved. No actions were run.'
        if time.monotonic() >= deadline:
            event('apply.failure.reason', reason='expired', completed_actions=0)
            self.failed = True
            return 'The prepared plan expired. No actions were run. Please ask again.'
        mcp_plan = any('mcp_token' in step for step in prepared)
        if mcp_plan:
            if approved is not True:
                self.failed = True
                return 'The MCP plan requires explicit approval. No actions were run.'
            self.desktop.authorize_plan(prepared)
        try:
            await self.overlay.state('executing')
            results = []
            for step in prepared:
                try:
                    with phase("desktop.execute", action=step.get("action", {}).get("name", "unknown")):
                        results.append(await self.desktop.execute(step))
                except asyncio.CancelledError:
                    event('apply.failure.reason', reason='cancelled', completed_actions=len(results))
                    raise
                except Exception as exc:
                    failure('apply.failure.reason', exc, reason='execution_error', completed_actions=len(results))
                    self.failed = True
                    results.append('The next action failed or could not be verified. It may have changed state. Remaining actions were not run.')
                    break
            return ' '.join(results)
        finally:
            if mcp_plan:
                self.desktop.revoke_plan(prepared)

    async def with_notice(self, work, message):
        task = asyncio.create_task(work)
        started = False

        async def notice():
            nonlocal started
            # Avoid interrupting a result that is already ready.
            await asyncio.sleep(0.35)
            if task.done():
                return
            started = True
            try:
                async with asyncio.timeout(8):
                    await self.overlay.message(message)
                    await self.overlay.state('speaking')
                    await self.inference.speak(message, self.overlay.level, self.overlay.message)
            except Exception:
                pass  # Feedback failure must not fail the actual request.
            finally:
                try:
                    await self.overlay.level(0)
                    await self.overlay.state('thinking')
                except Exception:
                    pass

        speech = asyncio.create_task(notice())
        try:
            result = await task
            if not started and not speech.done():
                speech.cancel()
                await asyncio.gather(speech, return_exceptions=True)
            else:
                await speech  # Do not overlap speech with the final answer or actions.
            return result
        finally:
            for pending in (task, speech):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, speech, return_exceptions=True)
