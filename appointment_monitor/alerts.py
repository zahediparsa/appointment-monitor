"""Cross-platform visible/audible alert."""
from __future__ import annotations

import platform
import subprocess
import time


def notify(message: str) -> None:
    system = platform.system()
    try:
        if system == "Windows":
            import winsound

            for _ in range(5):
                winsound.Beep(1000, 500)
                time.sleep(0.25)
        elif system == "Darwin":
            safe = message.replace("\\", "\\\\").replace('"', '\\"')
            script = f'display notification "{safe}" with title "Appointment monitor" sound name "Glass"'
            subprocess.run(["osascript", "-e", script], check=False)
        else:
            subprocess.run(["notify-send", "--urgency=critical", "Appointment monitor", message], check=False)
    except OSError:  # notifier missing: fall back to the terminal bell
        print("\a" + message, flush=True)
