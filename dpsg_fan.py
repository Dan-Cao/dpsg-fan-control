"""Hysteresis fan control for Thermaltake Toughpower DPS G (Enhance-made, USB 264A:232A).

The PSU firmware only exposes three fan modes over USB (Performance / Silent / Zero Fan);
there is no duty-cycle command for this model. Zero Fan mode starts the fan at 40C and stops
it at 39C, so it cycles constantly. This script adds hysteresis by switching modes:

  Zero Fan  --(temp >= ON_C or fan starts)-->  Silent
  Silent    --(temp <= OFF_C and on for MIN_ON_S)-->  Zero Fan

The firmware still owns the fan speed inside each mode, so the worst case is stock behaviour.
On exit the PSU is put back in Zero Fan mode.

  pip install hidapi
  python dpsg_fan.py            # run the controller
  python dpsg_fan.py status     # print one telemetry reading
  python dpsg_fan.py silent|zero|performance   # set a mode once
"""
import argparse
import ctypes
import ctypes.wintypes as W
import sys
import time

import hid

VID, PID = 0x264A, 0x232A
MODES = {"performance": 0xFE, "silent": 0xFD, "zero": 0xFB}  # output report 0x13
FIELDS = ["vin", "iin", "pin", "pf", "v12", "i12", "v5", "i5", "v33", "i33",
          "pout", "eff", "temp2", "temp", "rpm"]  # input report 0x10, PMBus LINEAR11 words

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = W.HANDLE
hidd = ctypes.WinDLL("hid")


def linear11(v):
    e = v >> 11
    e = e - 32 if e > 15 else e
    m = v & 0x7FF
    m = m - 2048 if m > 1023 else m
    return m * 2.0 ** e


class PSU:
    def __init__(self):
        devs = hid.enumerate(VID, PID)
        if not devs:
            raise IOError("PSU not found (264A:232A)")
        self.path = devs[0]["path"]
        self.dev = hid.device()
        self.dev.open_path(self.path)

    def read(self):
        r = self.dev.get_input_report(0x10, 31)
        return {n: linear11(r[1 + 2 * i] | r[2 + 2 * i] << 8) for i, n in enumerate(FIELDS)}

    def set_mode(self, mode):
        # Same call the official app makes: HidD_SetOutputReport([0x13, mode])
        h = k32.CreateFileW(self.path.decode(), 0x40000000, 3, None, 3, 0, None)
        try:
            buf = (ctypes.c_ubyte * 2)(0x13, MODES[mode])
            if not hidd.HidD_SetOutputReport(h, buf, 2):
                raise IOError("HidD_SetOutputReport failed")
        finally:
            k32.CloseHandle(h)

    def close(self):
        self.dev.close()


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Hysteresis:
    """Decides between Zero Fan and Silent; step() returns a log message when it switches."""

    SPIN_DOWN_S = 30  # after switching to Zero Fan, the fan is still coasting for a while

    def __init__(self, on=40, off=36, min_on=60):
        self.on, self.off, self.min_on = on, off, min_on
        self.mode, self.since = "zero", time.monotonic()

    def step(self, d):
        t, on_for = d["temp"], time.monotonic() - self.since
        # rpm > 0 in Zero Fan means the firmware started the fan, unless it is still spinning down
        fw_started = d["rpm"] > 0 and on_for >= self.SPIN_DOWN_S
        if self.mode == "zero" and (t >= self.on or fw_started):
            self.mode, self.since = "silent", time.monotonic()
            return f"fan ON  temp={t:.0f}C pout={d['pout']:.0f}W"
        if self.mode == "silent" and t <= self.off and on_for >= self.min_on:
            self.mode, self.since = "zero", time.monotonic()
            return f"fan OFF temp={t:.0f}C after {on_for / 60:.1f} min"


def run(args):
    psu = PSU()
    ctl = Hysteresis(args.on, args.off, args.min_on)
    psu.set_mode(ctl.mode)
    log(f"started: on>={args.on}C off<={args.off}C min_on={args.min_on}s")
    try:
        while True:
            try:
                d = psu.read()
            except (IOError, OSError, ValueError):
                log("read failed, reconnecting")
                time.sleep(5)
                psu = PSU()
                psu.set_mode(ctl.mode)
                continue
            msg = ctl.step(d)
            if msg:
                psu.set_mode(ctl.mode)
                log(msg)
            time.sleep(args.interval)
    finally:
        try:
            psu.set_mode("zero")
        finally:
            psu.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", nargs="?", default="run", choices=["run", "status", *MODES])
    p.add_argument("--on", type=float, default=40)
    p.add_argument("--off", type=float, default=36)
    p.add_argument("--min-on", type=float, default=60)
    p.add_argument("--interval", type=float, default=2)
    args = p.parse_args()
    if args.cmd == "run":
        run(args)
        return
    psu = PSU()
    if args.cmd == "status":
        d = psu.read()
        print(f"temp {d['temp']:.0f}C (secondary {d['temp2']:.0f}C)  fan {d['rpm']:.0f} RPM  "
              f"in {d['pin']:.0f}W @ {d['vin']:.0f}V  out {d['pout']:.0f}W  eff {d['eff'] * 100:.1f}%\n"
              f"12V {d['v12']:.2f}V {d['i12']:.2f}A  5V {d['v5']:.2f}V {d['i5']:.2f}A  "
              f"3.3V {d['v33']:.2f}V {d['i33']:.2f}A")
    else:
        psu.set_mode(args.cmd)
        print("mode set:", args.cmd)
    psu.close()


if __name__ == "__main__":
    sys.exit(main())
