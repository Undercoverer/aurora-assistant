# D-Bus actions and qdbus

## What is direct, and what needs an adapter?

The controller uses dbus-next to send typed D-Bus messages. These are the same
service/object/interface/method calls that qdbus sends. It does not generate
qdbus shell strings. Live introspection supplies argument signatures; the model
supplies values that must pass validation before a call is sent.

| Capability | Current execution path | Manual command configuration needed? |
| --- | --- | --- |
| Service listing and introspection | Direct session/system D-Bus | No; discovery scope has defaults |
| Generic property read/write | Direct D-Bus Properties interface | No |
| Generic method call | Direct call to the discovered service | No |
| Playback play/pause/toggle/next/previous | Direct MPRIS player interface | No |
| Overlay state, text, level | Direct pinned VoiceOverlay1 interface | No |
| Speaker volume/mute and microphone mute | Aurora desktop D-Bus adapter → wpctl → PipeWire | No |
| Global theme and color scheme | Aurora desktop D-Bus adapter → Plasma tools | No |
| Application listing/launch | Aurora desktop D-Bus adapter → XDG entries/gtk-launch | No |
| Optional fixed shortcuts | Direct configured D-Bus call | Only if you choose to add a shortcut |

Before this change, the six direct D-Bus planner tools were dbus_list,
dbus_inspect, dbus_get, dbus_set, dbus_call, and the optional fixed dbus shortcut.
Playback used playerctl, which itself uses MPRIS. Other built-in controls used
command-line backends. The current Nix-managed controller sends every desktop
operation through D-Bus, but the adapter is not a native API for all Linux settings.
PipeWire's main protocol uses Unix sockets. KConfig-backed settings also do not
become writable D-Bus properties merely because KDE is installed.

The adapter is deliberately small. It does not make arbitrary shell execution,
file editing, or every System Settings page available. Desktop services remain
subject to their own access checks. Unsupported settings must return a limitation,
not a fabricated method or a false success report.

## Inspect the real interfaces

The examples use Qt 6 `qdbus`. If it is not on PATH, enter
`nix shell nixpkgs#kdePackages.qttools` first. Some distributions name the binary
`qdbus6`; use that name if needed. Run in your desktop session.

```sh
# List session services, then inspect the returned player name.
qdbus
qdbus org.mpris.MediaPlayer2.YOUR_PLAYER /org/mpris/MediaPlayer2
qdbus org.mpris.MediaPlayer2.YOUR_PLAYER /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.PlaybackStatus
# This command changes playback immediately; it is a manual example.
qdbus org.mpris.MediaPlayer2.YOUR_PLAYER /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Pause
```

Replace YOUR_PLAYER with an actual service from the listing. Do not assume that
all installed apps export MPRIS. Aurora's common media action selects the sole
playing player, or the sole available player. An ambiguous selection is escalated
for discovery. The generic planner can target a specific observed player.

The corresponding planner method object is:

```json
{
  "name": "dbus_call",
  "argument": {
    "bus": "session",
    "destination": "org.mpris.MediaPlayer2.YOUR_PLAYER",
    "path": "/org/mpris/MediaPlayer2",
    "interface": "org.mpris.MediaPlayer2.Player",
    "method": "Pause",
    "argumentsJson": "[]"
  }
}
```

This is an illustrative object, not a valid target until the real player has been
observed. Generic calls require approval; the narrow common media operation is
validated against the MPRIS contract and reviewed before execution.

## Aurora adapter interface

Service `org.aurora.Desktop`, path `/org/aurora/Desktop`, interface
`org.aurora.Desktop1` are started automatically by the NixOS module. Inspect and
read without changing anything:

```sh
qdbus org.aurora.Desktop /org/aurora/Desktop
qdbus org.aurora.Desktop /org/aurora/Desktop org.aurora.Desktop1.Read applications
qdbus org.aurora.Desktop /org/aurora/Desktop org.aurora.Desktop1.Read colors
```

`Read(s topic) -> s` returns JSON. Topics are audio, media, themes, colors, and
applications. Application names and desktop IDs come from the desktop service's
XDG paths. Hidden entries and entries for another desktop are excluded; higher
priority user entries override system entries, including Hidden tombstones.

`Prepare(s name, s argument_json) -> s` validates one built-in action and returns
an opaque token plus the exact plan. It makes no desktop change. `Apply(s token)
-> s` consumes that plan once, within 120 seconds. Restarting the service invalidates
pending plans. The controller binds each token to the service's unique owner.
The adapter stores plans; it never trusts a caller-supplied rewritten plan.

Manual example, which changes volume if Apply is invoked:

```sh
qdbus org.aurora.Desktop /org/aurora/Desktop org.aurora.Desktop1.Prepare volume '30'
# Inspect the JSON response. To perform this change manually, copy its token:
qdbus org.aurora.Desktop /org/aurora/Desktop org.aurora.Desktop1.Apply TOKEN_FROM_PREPARE
```

The adapter runs as the desktop user. It is a transport boundary, not an elevated
security service: same-session applications can call it, just as they can call
the underlying desktop tools. Review and human approval belong to the assistant
controller. Manual qdbus calls are not voice requests and do not run the reviewer.

## Typed values and scope

D-Bus method arguments are positional. `argumentsJson` is a JSON array. A boolean
is `true`, not `1`. Variant values use `{"signature":"b","value":true}`.
Property writes use `valueJson` containing one JSON value. File-descriptor values
are unsupported. Property changes require read/write access, check the previous
value before mutation, and compare the result after mutation. A restarted service
or changed prior value invalidates the plan. Generic methods can have arbitrary
side effects; a successful method return alone does not verify those effects.

Defaults cover KDE and MPRIS on the session bus and UPower on the system bus.
You can extend service scope in Nix, but do not need to define individual methods:

```nix
programs.aurora-assistant.settings = {
  sessionPrefixes = [ "org.kde." "org.mpris." "org.example.VoiceOverlay" "org.aurora.Desktop" ];
  systemPrefixes = [ "org.freedesktop.UPower" ];
  maxRounds = 5;
};
```

Wallet/secrets services and known scripting/command-execution interfaces remain
excluded. A model cannot infer permission from a method's existence.

Upstream references: [MPRIS Player](https://specifications.freedesktop.org/mpris/latest/Player_Interface.html),
[PipeWire native protocol](https://docs.pipewire.org/page_module_protocol_native.html).
