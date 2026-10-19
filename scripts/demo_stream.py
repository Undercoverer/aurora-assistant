#!/usr/bin/env python3
"""Exercise the overlay using qdbus, no external Python packages."""
import math
import shutil
import subprocess
import time

SERVICE = "org.example.VoiceOverlay"
OBJECT = "/org/example/VoiceOverlay"
INTERFACE = "org.example.VoiceOverlay1"


def call(name, *args):
    subprocess.run(
        ["qdbus", SERVICE, OBJECT, f"{INTERFACE}.{name}", *map(str, args)],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def main():
    if not shutil.which("qdbus"):
        raise SystemExit("qdbus not found in PATH")
    call("Reset")
    call("SetState", "wake")
    time.sleep(0.65)
    call("SetState", "listening")
    for i in range(28):
        value = 0.15 + 0.75 * abs(math.sin(i * 0.43))
        call("SetLevel", f"{value:.3f}")
        time.sleep(0.055)
    call("SetLevel", 0)
    call("SetState", "transcribing")
    call("SetMessage", "Turn the volume down to thirty percent")
    time.sleep(1.2)
    call("ClearMessage")
    call("SetState", "thinking")
    time.sleep(0.9)
    call("SetState", "speaking")
    for word in "The volume has been set to thirty percent. The assistant is ready.".split():
        call("AppendMessage", word + " ")
        call("SetLevel", f"{0.18 + 0.55 * abs(math.sin(len(word) * 0.62)):.3f}")
        time.sleep(0.12)
    call("SetLevel", 0)
    call("SetState", "success")
    time.sleep(2)
    call("Reset")


if __name__ == "__main__":
    main()
