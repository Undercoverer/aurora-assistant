"""Bounded, typed choices for Kev; free-form arguments remain planner work."""
import re


def desktop_candidates(text):
    """Offer supported operations, never shell commands or guessed D-Bus methods."""
    choices = []
    def add(description, name, argument):
        choices.append({'description': description,
                        'candidate': {'name': name, 'argument': argument}})
    for muted, verb in ((True, 'Mute'), (False, 'Unmute')):
        add(verb + ' the default speakers/computer sound', 'mute', muted)
        add(verb + ' the default microphone', 'microphone_mute', muted)
    for command in ('play', 'pause', 'next', 'previous'):
        add(command + ' media playback', 'media', command)
    add('Read the current local time and date from the system clock', 'desktop_read', 'clock')
    add('Read current speaker volume and microphone mute state', 'desktop_read', 'audio')
    add('Open YouTube in the default browser', 'open_url', 'https://www.youtube.com/')
    # Values must come from the utterance. The decision must still distinguish
    # absolute volume from relative changes, other devices, and negation.
    numbers = re.findall(r'(?<![\w.\-])\d{1,3}(?![\w.])', text)
    for value in dict.fromkeys(numbers):
        if 0 <= int(value) <= 100:
            add(f'Set speaker volume to exactly {int(value)} percent (absolute, not relative)', 'volume', int(value))
        if len(choices) >= 15:
            break
    return choices
