"""System tray monitor/controller for the Thermaltake DPS G PSU (see dpsg_fan.py).

The icon shows the PSU temperature; its colour shows the fan state:
  grey = fan off, blue = fan on (Silent), orange = Performance, red = PSU not found.
Hover for a summary, right-click for details, fan mode and options.

  pip install hidapi pystray pillow
  pythonw dpsg_tray.pyw [--on 40] [--off 36] [--min-on 60]
"""
import argparse
import ctypes
import os
import sys
import threading
import time
import winreg

import pystray
from PIL import Image, ImageDraw, ImageFont

from dpsg_fan import KEEPALIVE_S, PSU, STALL_S, Hysteresis

APP = "DPSG Fan"
LOG_DIR = os.path.join(os.environ["LOCALAPPDATA"], "DPSG-Fan")
LOG_FILE = os.path.join(LOG_DIR, "dpsg_fan.log")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
COLORS = {"off": (70, 70, 70), "silent": (40, 120, 215), "performance": (225, 120, 30),
          "error": (200, 40, 40)}
MODE_NAMES = {"auto": "Auto", "zero": "Zero Fan", "silent": "Silent", "performance": "Performance"}


def log(msg):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def ago(t):
    s = int(time.monotonic() - t)
    return f"{s}s" if s < 60 else f"{s // 60} min" if s < 3600 else f"{s / 3600:.1f} h"


def make_icon(text, color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, 63, 63), radius=12, fill=color + (255,))
    size = 44 if len(text) <= 2 else 32
    font = ImageFont.truetype("segoeuib.ttf", size)
    draw.text((32, 31), text, font=font, fill="white", anchor="mm")
    return img


class TrayApp:
    def __init__(self, args):
        self.interval = args.interval
        self.ctl = Hysteresis(args.on, args.off, args.min_on)
        self.choice = "auto"  # auto | zero | silent | performance
        self.applied = None  # PSU's fan mode as last read back (report 0x14)
        self.sent_at = 0.0  # last time a fan-mode command was sent
        self.data, self.error = None, None
        self.last_switch = None, None  # (message, monotonic time)
        self.psu = None
        self.stop = threading.Event()
        self.icon = pystray.Icon(APP, make_icon("..", COLORS["off"]), APP, self.build_menu())

    # ---- PSU loop -------------------------------------------------------
    def poll(self):
        while not self.stop.is_set():
            try:
                if self.psu is None:
                    self.psu, self.applied = PSU(), None
                d = self.psu.read()
                self.data, self.error = d, None
                if self.choice == "auto":
                    msg = self.ctl.step(d)
                    if msg:
                        log(msg)
                        self.last_switch = msg.split(" temp")[0].replace("  ", " "), time.monotonic()
                    want = self.ctl.mode
                else:
                    want = self.choice
                actual = self.psu.get_mode()
                if actual != want:
                    if self.applied == want:  # it was right last poll, so something else changed it
                        log(f"PSU mode changed to {actual} by something else, setting {want}")
                    self.psu.set_mode(want)
                    self.sent_at = time.monotonic()
                    actual = self.psu.get_mode()
                elif want != "zero":
                    since_sent = time.monotonic() - self.sent_at
                    # the fan normally spins up within ~8 s of a command
                    stalled = d["rpm"] == 0 and since_sent > STALL_S
                    if stalled:
                        log(f"fan still stopped {since_sent:.0f}s after setting {want}, re-sending")
                    if stalled or since_sent > KEEPALIVE_S:
                        self.psu.set_mode(want)  # keep-alive, see KEEPALIVE_S
                        self.sent_at = time.monotonic()
                self.applied = actual
            except Exception as e:  # PSU unplugged, asleep, etc.
                if self.error is None:
                    log(f"error: {e}")
                self.error, self.psu = str(e), None
            self.refresh()
            self.stop.wait(self.interval)

    def state(self):
        if self.error or not self.data:
            return "error"
        if self.applied == "performance":
            return "performance"
        return "silent" if self.data["rpm"] > 0 else "off"

    def refresh(self):
        d, st = self.data, self.state()
        if st == "error":
            self.icon.icon = make_icon("!", COLORS["error"])
            self.icon.title = f"{APP}: PSU not found"
        else:
            self.icon.icon = make_icon(f"{d['temp']:.0f}", COLORS[st])
            fan = f"fan {d['rpm']:.0f} RPM" if d["rpm"] > 0 else "fan off"
            self.icon.title = (f"PSU {d['temp']:.0f}°C, {fan}\n"
                               f"{d['pout']:.0f} W out, {d['eff'] * 100:.1f}% eff\n"
                               f"{self.mode_label()}")
        self.icon.update_menu()

    def auto_status(self):
        c = self.ctl
        if c.mode == "zero":
            return f"fan should be off, on at {c.on:.0f}°C"
        left = c.min_on - (time.monotonic() - c.since)
        if left > 0:
            return f"fan should be on, min run {int(left) // 60}:{int(left) % 60:02d} left"
        return f"fan should be on, off at {c.off:.0f}°C"

    def mode_label(self):
        if self.choice == "auto":
            return f"Auto: {self.auto_status()}"
        return f"Mode: {MODE_NAMES[self.choice]}"

    # ---- menu -----------------------------------------------------------
    def info(self, i):
        d = self.data
        if self.error or not d:
            return ["PSU not found", self.error or "connecting...", "", ""][i]
        msg, t = self.last_switch
        return [
            f"Temperature {d['temp']:.0f}°C  ·  Fan {d['rpm']:.0f} RPM  ·  "
            f"PSU in {MODE_NAMES.get(self.applied, self.applied)}",
            f"Output {d['pout']:.0f} W  ·  Input {d['pin']:.0f} W  ·  {d['eff'] * 100:.1f}%",
            f"12V {d['v12']:.2f}V {d['i12']:.1f}A  ·  5V {d['i5']:.1f}A  ·  3.3V {d['i33']:.1f}A",
            f"Last auto switch: {msg} ({ago(t)} ago)" if msg else "No auto switch yet",
        ][i]

    def set_choice(self, choice):
        def handler(icon, item):
            self.choice = choice
            log(f"mode -> {choice}")
            if choice == "auto":  # restart hysteresis from the current fan state
                self.ctl.mode, self.ctl.since = "zero", time.monotonic()
        return handler

    def build_menu(self):
        def info_item(i):
            return pystray.MenuItem(lambda _: self.info(i), None, enabled=False)

        def mode_item(key, label):
            return pystray.MenuItem(label, self.set_choice(key), radio=True,
                                    checked=lambda _: self.choice == key)

        c = self.ctl
        return pystray.Menu(
            info_item(0), info_item(1), info_item(2), info_item(3),
            pystray.Menu.SEPARATOR,
            mode_item("auto", lambda _: f"Auto: {self.auto_status()}" if self.choice == "auto"
                      else f"Auto (on at {c.on:.0f}°C, off at {c.off:.0f}°C)"),
            mode_item("zero", "Zero Fan (stock)"),
            mode_item("silent", "Silent"),
            mode_item("performance", "Performance"),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open log", lambda: os.startfile(LOG_FILE) if os.path.exists(LOG_FILE) else None),
            pystray.MenuItem("Start with Windows", self.toggle_startup,
                             checked=lambda _: self.startup_enabled()),
            pystray.MenuItem("Quit", self.quit),
        )

    # ---- startup registration --------------------------------------------
    def startup_cmd(self):
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        return f'"{pyw}" "{os.path.abspath(__file__)}" ' + " ".join(sys.argv[1:])

    def startup_enabled(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                return winreg.QueryValueEx(k, APP)[0] == self.startup_cmd().strip()
        except OSError:
            return False

    def toggle_startup(self, icon, item):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if self.startup_enabled():
                winreg.DeleteValue(k, APP)
            else:
                winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, self.startup_cmd().strip())

    # ---- lifecycle --------------------------------------------------------
    def quit(self, icon, item):
        self.stop.set()
        icon.stop()

    def run(self):
        log("started")
        worker = threading.Thread(target=self.poll, daemon=True)
        worker.start()
        self.icon.run()
        worker.join(timeout=5)
        try:  # leave the PSU in its stock mode
            (self.psu or PSU()).set_mode("zero")
        except Exception:
            pass
        log("stopped (Zero Fan restored)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--on", type=float, default=40)
    p.add_argument("--off", type=float, default=36)
    p.add_argument("--min-on", type=float, default=60)
    p.add_argument("--interval", type=float, default=2)
    args = p.parse_args()
    # single instance
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\DPSG-Fan-Tray")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return
    TrayApp(args).run()


if __name__ == "__main__":
    main()
