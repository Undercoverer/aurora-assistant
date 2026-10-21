"""Effect policy for requested actions, independent of model confidence."""
import re
from .actions import validate

EFFECTS = {'ordinary', 'destructive', 'unknown', 'unrequested'}
# These are mandatory approval floors, not a complete destructive-method detector.
DESTRUCTIVE = {'delete', 'remove', 'erase', 'wipe', 'purge', 'format', 'destroy',
               'overwrite', 'factory', 'reboot', 'shutdown', 'poweroff', 'terminate', 'kill'}
ROUTINE = {'volume', 'mute', 'microphone_mute', 'media', 'open_url', 'launch_app',
           'open_app', 'color_scheme'}


def approval_floor(plan):
    action = plan.get('action', {})
    arg = action.get('argument', {})
    if not isinstance(arg, dict):
        return False
    identifiers = ' '.join(str(arg.get(k, '')) for k in ('interface', 'method', 'property'))
    identifiers = re.sub(r'([a-z])([A-Z])', r'\1 \2', identifiers).lower()
    return bool(set(re.findall(r'[a-z]+', identifiers)) & DESTRUCTIVE)


def routine_adapter(plan, apps):
    action = plan.get('adapter_plan', {}).get('action')
    if not isinstance(action, dict) or action.get('name') not in ROUTINE:
        return False
    try:
        validate({'actions': [action], 'reply': ''}, apps, settings=True)
    except ValueError:
        return False
    return True


async def assess(inference, text, plans, apps):
    """Known adapter effects are local policy; generic effects require assessment.

    Unknown meaning refuses execution rather than asking for blind approval.
    No model answer can lower an independently required approval.
    """
    effects = ['ordinary' if routine_adapter(p, apps) else None for p in plans]
    pending = [i for i, effect in enumerate(effects) if effect is None]
    if pending:
        answers = await inference.assess_effects(text, [plans[i] for i in pending])
        if type(answers) is not list or len(answers) != len(pending) or any(type(a) is not str or a not in EFFECTS for a in answers):
            raise ValueError('Invalid effect assessment')
        for i, answer in zip(pending, answers):
            effects[i] = answer
    for i, plan in enumerate(plans):
        if effects[i] not in {'unknown', 'unrequested'} and approval_floor(plan):
            effects[i] = 'destructive'
    return effects
