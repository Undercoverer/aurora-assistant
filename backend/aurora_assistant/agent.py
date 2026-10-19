"""Bounded discovery, review, and execution loop for a single user request."""
import json
from .actions import validate
from .settings import READ_ACTIONS


class SettingsAgent:
    def __init__(self, config, inference, desktop, approval, overlay):
        self.config, self.inference, self.desktop = config, inference, desktop
        self.approval, self.overlay = approval, overlay

    async def run(self, text):
        self.failed = False
        evidence = []
        quick = None
        if self.config.get('kev', {}).get('enable', False):
            try:
                quick = await self.inference.quick_plan(text)
            except Exception:
                pass  # Routing failure escalates, never executes a partial answer.
        for _ in range(self.config.get('settings', {}).get('maxRounds', 5)):
            plan = quick if quick is not None else await self.inference.plan(text, evidence=evidence)
            quick = None
            actions, reply = validate(plan, self.config['apps'], self.config.get('dbus_actions', {}), settings=True)
            if not actions:
                return reply
            reads = [a for a in actions if a.name in READ_ACTIONS]
            if reads:
                # Proposed writes in a discovery round are discarded and replanned.
                for action in reads:
                    try:
                        value = await self.desktop.read(action)
                        data = json.dumps(value, ensure_ascii=False)
                        result = data[:12000]
                    except Exception as exc:
                        result = f'Read failed: {type(exc).__name__}: {exc}'[:1000]
                    evidence.append({'action': action.name, 'argument': action.argument, 'result': result})
                continue
            # Mute the microphone last so earlier operations do not lose input.
            actions = sorted(actions, key=lambda a: a.name == 'microphone_mute' and a.argument is True)
            try:
                prepared = [await self.desktop.prepare(action) for action in actions]
            except Exception as exc:
                evidence.append({'preparation_error': str(exc)[:1000], 'actions': plan['actions']})
                continue  # No mutations have occurred; let the larger model resolve it.
            review = {'decision': 'allow', 'reason': 'Local policy permits the supported desktop actions.'}
            if self.config.get('safety', {}).get('enable', True):
                try:
                    review = await self.inference.review(text, prepared)
                except Exception:
                    review = {'decision': 'ask', 'reason': 'The local reviewer is unavailable or returned an invalid result.'}
            if review['decision'] == 'block':
                return 'No changes were made. ' + review['reason']
            if review['decision'] == 'ask' or any(p['requires_approval'] for p in prepared):
                approved = await self.approval.request(
                    {'request': text, 'plan': prepared, 'review': review}, self.overlay.message)
                if not approved:
                    return 'The change was not approved. No actions were run.'
            await self.overlay.state('executing')
            results = []
            for step in prepared:
                try:
                    results.append(await self.desktop.execute(step))
                except Exception:
                    self.failed = True
                    results.append('The next action failed or could not be verified. It may have changed state. Remaining actions were not run.')
                    break
            return ' '.join(results)
        return 'The discovery limit was reached. No changes were made. Please narrow the request.'
