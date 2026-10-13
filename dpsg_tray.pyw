"""System tray monitor for the Thermaltake DPS G PSU (see dpsg_fan.py).

The icon shows the PSU temperature; its colour shows the fan:
  grey = fan off, blue = fan on, red = PSU not found.
Hover for a summary, right-click for details. It only sends a command to the PSU when
you pick a fan mode from the menu: one command per click, never automatically.

  pip install hidapi pystray pillow
  pythonw dpsg_tray.pyw
"""
import ctypes
import os
import sys
import threading
import time
import winreg

import pystray
from PIL import Image, ImageDraw, ImageFont

from dpsg_fan import PSU

APP = "DPSG Fan"
LOG_DIR = os.path.join(os.environ["LOCALAPPDATA"], "DPSG-Fan")
LOG_FILE = os.path.join(LOG_DIR, "dpsg_fan.log")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
INTERVAL_S = 2
COLORS = {"off": (70, 70, 70), "on": (40, 120, 215), "error": (200, 40, 40)}
MODE_NAMES = {"zero": "Zero Fan", "silent": "Silent", "performance": "Performance"}


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
    def __init__(self):
        self.psu = None
        self.data = self.mode = self.error = None
        self.fan_on = None
        self.fan_since = time.monotonic()  # when the fan last started or stopped
        self.fan_stops = 0  # stops seen outside Zero Fan, where the fan should run steadily
        self.stop = threading.Event()
        self.icon = pystray.Icon(APP, make_icon("..", COLORS["off"]), APP, self.build_menu())

    # ---- PSU loop -------------------------------------------------------
    def poll(self):
        while not self.stop.is_set():
            try:
                if self.psu is None:
                    self.psu = PSU()
                d, mode = self.psu.read(), self.psu.get_mode()
                self.data, self.error = d, None
                self.track(d, mode)
            except Exception as e:  # PSU unplugged, asleep, etc.
                if self.error is None:
                    log(f"error: {e}")
                self.error, self.psu = str(e), None
            self.refresh()
            self.stop.wait(INTERVAL_S)

    def track(self, d, mode):
        """Log mode changes, and fan stops/starts outside Zero Fan (where it cycles by design)."""
        if mode != self.mode:
            log(f"fan mode {self.name(mode)}" if self.mode is None
                else f"fan mode changed: {self.name(self.mode)} -> {self.name(mode)}")
            self.mode = mode
        fan_on = d["rpm"] > 0
        if fan_on == self.fan_on:
            return
        if self.fan_on is not None and mode != "zero":
            if not fan_on:
                self.fan_stops += 1
            log(f"fan {'started' if fan_on else 'stopped'} in {self.name(mode)} after "
                f"{ago(self.fan_since)} (temp={d['temp']:.0f}C out={d['pout']:.0f}W)")
        self.fan_on, self.fan_since = fan_on, time.monotonic()

    @staticmethod
    def name(mode):
        return MODE_NAMES.get(mode, mode)

    def refresh(self):
        d = self.data
        if self.error or not d:
            self.icon.icon = make_icon("!", COLORS["error"])
            self.icon.title = f"{APP}: PSU not found"
        else:
            self.icon.icon = make_icon(f"{d['temp']:.0f}", COLORS["on" if d["rpm"] > 0 else "off"])
            fan = f"fan {d['rpm']:.0f} RPM" if d["rpm"] > 0 else "fan off"
            self.icon.title = (f"PSU {d['temp']:.0f}°C, {fan}\n"
                               f"{d['pout']:.0f} W out, {d['eff'] * 100:.1f}% eff\n"
                               f"Fan mode: {self.name(self.mode)}")
        self.icon.update_menu()

    # ---- menu -----------------------------------------------------------
    def info(self, i):
        d = self.data
        if self.error or not d:
            return ["PSU not found", self.error or "connecting...", "", ""][i]
        fan = "on" if d["rpm"] > 0 else "off"
        return [
            f"Temperature {d['temp']:.0f}°C  ·  Fan {d['rpm']:.0f} RPM  ·  {self.name(self.mode)}",
            f"Output {d['pout']:.0f} W  ·  Input {d['pin']:.0f} W  ·  {d['eff'] * 100:.1f}%",
            f"12V {d['v12']:.2f}V {d['i12']:.1f}A  ·  5V {d['i5']:.1f}A  ·  3.3V {d['i33']:.1f}A",
            f"Fan {fan} for {ago(self.fan_since)}  ·  stops outside Zero Fan: {self.fan_stops}",
        ][i]

    def set_mode(self, mode):
        def handler(icon, item):
            # Exactly one command per click, even if the PSU is already in this mode:
            # re-sending Silent restarts a fan that has stopped.
            try:
                (self.psu or PSU()).set_mode(mode)
                log(f"sent one command: set fan mode {self.name(mode)}")
            except Exception as e:
                log(f"setting fan mode {self.name(mode)} failed: {e}")
        return handler

    def build_menu(self):
        def info_item(i):
            return pystray.MenuItem(lambda _: self.info(i), None, enabled=False)

        def mode_item(mode):
            return pystray.MenuItem(MODE_NAMES[mode], self.set_mode(mode), radio=True,
                                    checked=lambda _: self.mode == mode)

        return pystray.Menu(
            info_item(0), info_item(1), info_item(2), info_item(3),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Set fan mode", pystray.Menu(
                mode_item("zero"), mode_item("silent"), mode_item("performance"))),
            pystray.MenuItem("Open log", lambda: os.startfile(LOG_FILE) if os.path.exists(LOG_FILE) else None),
            pystray.MenuItem("Start with Windows", self.toggle_startup,
                             checked=lambda _: self.startup_enabled()),
            pystray.MenuItem("Quit", self.quit),
        )

    # ---- startup registration --------------------------------------------
    def startup_cmd(self):
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        return f'"{pyw}" "{os.path.abspath(__file__)}"'

    def startup_enabled(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                return winreg.QueryValueEx(k, APP)[0] == self.startup_cmd()
        except OSError:
            return False

    def toggle_startup(self, icon, item):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if self.startup_enabled():
                winreg.DeleteValue(k, APP)
            else:
                winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, self.startup_cmd())

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
        log("stopped")


def main():
    # single instance
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\DPSG-Fan-Tray")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return
    TrayApp().run()


if __name__ == "__main__":
    main()
