"""Bounded discovery, review, and execution loop for a single user request."""
import json
import asyncio
import time
import copy
import re
from .actions import validate, PlanValidationError
from .settings import READ_ACTIONS
from .telemetry import event, phase, failure


class SettingsAgent:
    def __init__(self, config, inference, desktop, approval, overlay, live_refresh=None, device_policy=False):
        self.config, self.inference, self.desktop = config, inference, desktop
        self.approval, self.overlay = approval, overlay
        self.live_refresh = live_refresh
        self.device_policy = device_policy
        self.voice_confirmation = False
        self.pending_confirmation = None

    async def run(self, text):
        self.failed = False
        self.awaiting_reply = False
        if len(text) > 8192:
            self.cancel_confirmation()
            self.failed = True
            return 'The request is too long to process safely. Please shorten it. No actions were run.'
        if self.confirmation_pending:
            return await self._answer_confirmation(text)
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

    @property
    def confirmation_pending(self):
        return self.pending_confirmation is not None

    def cancel_confirmation(self):
        pending, self.pending_confirmation = self.pending_confirmation, None
        if pending is not None:
            self.desktop.revoke_plan(pending['prepared'])
            self.approval.clear()

    def _stage_confirmation(self, text, prepared, review, deadline, system=False):
        # Display and speak an exact description, not a second model's paraphrase.
        descriptions = []
        for plan in prepared:
            if 'adapter_plan' in plan:
                description = plan['adapter_plan']['action']
            else:
                description = plan['action']
            descriptions.append(json.dumps(description, ensure_ascii=False, sort_keys=True))
        prompt = ('Confirm these destructive system-bus operations: ' if system else
                  'This plan includes a destructive operation: ') + '; '.join(descriptions)
        prompt += '. Say yes to approve this exact plan, or no to cancel. Proceed?'
        if len(prompt) > 2400:
            return None  # Oversized exact plans use the existing local control.
        identity, future = self.approval.stage(
            {'request': text, 'plan': prepared, 'review': review, 'system_confirmation': system},
            timeout=min(120, max(0, deadline - time.monotonic())))
        self.pending_confirmation = {'prepared': copy.deepcopy(prepared), 'deadline': deadline,
            'id': identity, 'future': future, 'text': text, 'review': review, 'system': system}
        self.awaiting_reply = True
        return prompt

    async def _answer_confirmation(self, text):
        pending, self.pending_confirmation = self.pending_confirmation, None
        prepared = pending['prepared']
        try:
            answer = re.sub(r'[.!?]+$', '', text.strip().casefold()).strip()
            if time.monotonic() >= pending['deadline']:
                return 'The approval expired. No actions were run.'
            if answer not in {'yes', 'yes please', 'confirm', 'proceed', 'do it'}:
                return 'The plan was cancelled. No actions were run.'
            future = pending['future']
            if not future.done():
                self.approval.dispatch({'command': 'approve', 'id': pending['id']})
            if future.cancelled() or future.result() is not True:
                return 'The plan was not approved. No actions were run.'
            self.approval.clear()
            # Keep the explicit second consent for destructive system-bus calls.
            system_calls = any(p.get('policy_effect') == 'destructive'
                and isinstance(p.get('action', {}).get('argument'), dict)
                and p['action']['argument'].get('bus') == 'system' for p in prepared)
            if system_calls and not pending['system']:
                prompt = self._stage_confirmation(pending['text'], prepared, pending['review'],
                                                  pending['deadline'], system=True)
                if prompt is not None:
                    return prompt
                return 'This system plan is too large for spoken approval. No actions were run.'
            return await self._apply_prepared(prepared, approved=True, system_confirmed=pending['system'])
        finally:
            if not self.confirmation_pending:
                self.desktop.revoke_plan(prepared)
                self.approval.clear()

    async def _execute_plan(self, text, prepared):
        try:
            return await self._prepare_execution(text, prepared)
        finally:
            if not self.confirmation_pending and any('mcp_token' in p for p in prepared):
                self.desktop.revoke_plan(prepared)

    async def _prepare_execution(self, text, prepared):
        if self.device_policy:
            from .action_policy import assess
            try:
                effects = await assess(self.inference, text, prepared, self.config['apps'])
                if 'unknown' in effects or 'unrequested' in effects:
                    self.desktop.revoke_plan(prepared)
                    return 'The available interface does not establish a suitable, understood operation for this request. No changes were made.'
                prepared = self.desktop.apply_policy(prepared, effects)
                review = {'decision': 'allow', 'reason': 'Requested effects assessed under device policy.'}
            except asyncio.CancelledError:
                self.desktop.revoke_plan(prepared)
                raise
            except Exception as exc:
                self.desktop.revoke_plan(prepared)
                failure('policy.effect_failed', exc)
                self.failed = True
                return 'The effects of this operation could not be checked. No actions were run.'
        else:
            review = await self._review(text, prepared)
        try:
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
                if self.voice_confirmation:
                    prompt = self._stage_confirmation(text, prepared, review, deadline)
                    if prompt is not None:
                        return prompt
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
            return await self._apply_prepared(prepared, approved)
        finally:
            if not self.confirmation_pending and any('mcp_token' in p for p in prepared):
                self.desktop.revoke_plan(prepared)

    async def _apply_prepared(self, prepared, approved, system_confirmed=False):
        if any(time.monotonic() >= p.get('expires_at', float('inf')) - 2 for p in prepared):
            self.desktop.revoke_plan(prepared)
            self.failed = True
            return 'The prepared plan expired. No actions were run.'
        mcp_plan = any('mcp_token' in step for step in prepared)
        try:
            if mcp_plan:
                if approved is True:
                    if system_confirmed:
                        self.desktop.authorize_plan(prepared, system_confirmed=True)
                    else:
                        self.desktop.authorize_plan(prepared)
                elif self.device_policy and all(p.get('policy_effect') == 'ordinary' and not p['requires_approval'] for p in prepared):
                    self.desktop.authorize_routine(prepared)
                else:
                    self.failed = True
                    return 'The MCP plan requires explicit approval. No actions were run.'
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
