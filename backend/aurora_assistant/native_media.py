"""Direct MPRIS control, using the same interfaces available through qdbus."""
from .settings import plain

PATH = '/org/mpris/MediaPlayer2'
INTERFACE = 'org.mpris.MediaPlayer2.Player'
METHODS = {'play': 'Play', 'pause': 'Pause', 'play-pause': 'PlayPause', 'next': 'Next', 'previous': 'Previous'}


class NativeMedia:
    def __init__(self, bus):
        self.bus = bus

    async def players(self):
        names = (await self.bus.call('session', 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames'))[0]
        result = []
        for name in sorted(n for n in names if n.startswith('org.mpris.MediaPlayer2.'))[:32]:
            try:
                owner = (await self.bus.call('session', 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner', 's', [name]))[0]
                props = plain((await self.bus.call('session', owner, PATH, 'org.freedesktop.DBus.Properties', 'GetAll', 's', [INTERFACE]))[0])
                result.append({'destination': name, 'owner': owner, **{key: props.get(key) for key in ('PlaybackStatus', 'CanControl', 'CanPlay', 'CanPause', 'CanGoNext', 'CanGoPrevious')}})
            except Exception:
                continue
        return result

    async def prepare(self, action):
        players = await self.players()
        playing = [p for p in players if p['PlaybackStatus'] == 'Playing']
        candidates = playing if len(playing) == 1 else players
        if len(candidates) != 1:
            raise ValueError('No unique media player. Ask which player and use its discovered MPRIS interface.')
        player = candidates[0]
        needed = {'play': 'CanPlay', 'pause': 'CanPause', 'next': 'CanGoNext', 'previous': 'CanGoPrevious',
                  'play-pause': 'CanPause' if player['PlaybackStatus'] == 'Playing' else 'CanPlay'}[action.argument]
        if player['CanControl'] is not True or player[needed] is not True:
            raise ValueError('Selected media player does not support this action')
        expected = {'play': 'Playing', 'pause': 'Paused', 'play-pause': 'Paused' if player['PlaybackStatus'] == 'Playing' else 'Playing'}.get(action.argument)
        return {'action': {'name': 'media', 'argument': action.argument}, 'requires_approval': False,
                'native_media': True, 'destination': player['destination'], 'owner': player['owner'],
                'path': PATH, 'interface': INTERFACE, 'member': METHODS[action.argument],
                'before': player['PlaybackStatus'], 'expected': expected}

    async def execute(self, prepared):
        owner = (await self.bus.call('session', 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner', 's', [prepared['destination']]))[0]
        if owner != prepared['owner']:
            raise RuntimeError('Media player restarted; prepare again')
        if prepared['action']['argument'] == 'play-pause':
            status = plain((await self.bus.call('session', owner, PATH, 'org.freedesktop.DBus.Properties', 'Get', 'ss', [INTERFACE, 'PlaybackStatus']))[0])
            if status != prepared['before']:
                raise RuntimeError('Playback changed since review; toggle was not sent')
        await self.bus.call('session', owner, PATH, INTERFACE, prepared['member'])
        if prepared['expected'] is not None:
            status = plain((await self.bus.call('session', owner, PATH, 'org.freedesktop.DBus.Properties', 'Get', 'ss', [INTERFACE, 'PlaybackStatus']))[0])
            if status != prepared['expected']:
                raise RuntimeError('Playback state did not match after the method returned')
            return f'Playback is {status.lower()}.'
        return f"{prepared['member']} returned successfully. Track change was not independently verified."
