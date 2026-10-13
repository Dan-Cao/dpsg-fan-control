"""Read and configure a Thermaltake Toughpower DPS G PSU (Enhance-made, USB 264A:232A).

The firmware has three fan modes (Performance / Silent / Zero Fan) and no duty-cycle
command. The PSU remembers its mode across power-offs, so set it once:

  pip install hidapi
  python dpsg_fan.py status                     # one reading
  python dpsg_fan.py silent|zero|performance    # set the fan mode
"""
import argparse
import ctypes
import ctypes.wintypes as W
import sys

import hid

VID, PID = 0x264A, 0x232A
MODES = {"performance": 0xFE, "silent": 0xFD, "zero": 0xFB}  # output 0x13, read back via input 0x14
MODE_NAMES = {v: k for k, v in MODES.items()}
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

    def text(self, report_id):
        """ASCII info reports: 0x11 model, 0x12 serial, 0x1D firmware build date."""
        r = self.dev.get_input_report(report_id, 33)
        return bytes(r[1:]).split(b"\0")[0].decode("ascii", "replace")

    def get_mode(self):
        """Current fan mode from input report 0x14; unknown bytes come back as e.g. '0xF7'."""
        b = self.dev.get_input_report(0x14, 2)[1]
        return MODE_NAMES.get(b, f"0x{b:02X}")

    def set_mode(self, mode):
        # Same call the official app makes: HidD_SetOutputReport([0x13, mode]).
        # The PSU stores the mode in non-volatile memory, so don't call this often.
        h = k32.CreateFileW(self.path.decode(), 0x40000000, 3, None, 3, 0, None)
        try:
            buf = (ctypes.c_ubyte * 2)(0x13, MODES[mode])
            if not hidd.HidD_SetOutputReport(h, buf, 2):
                raise IOError("HidD_SetOutputReport failed")
        finally:
            k32.CloseHandle(h)

    def close(self):
        self.dev.close()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("cmd", choices=["status", *MODES])
    args = p.parse_args()
    psu = PSU()
    if args.cmd == "status":
        d = psu.read()
        print(f"{psu.text(0x11)}  serial {psu.text(0x12)}  firmware {psu.text(0x1D)}\n"
              f"fan mode {psu.get_mode()}  fan {d['rpm']:.0f} RPM  "
              f"temp {d['temp']:.0f}C (secondary {d['temp2']:.0f}C)\n"
              f"in {d['pin']:.0f}W @ {d['vin']:.0f}V  out {d['pout']:.0f}W  eff {d['eff'] * 100:.1f}%\n"
              f"12V {d['v12']:.2f}V {d['i12']:.2f}A  5V {d['v5']:.2f}V {d['i5']:.2f}A  "
              f"3.3V {d['v33']:.2f}V {d['i33']:.2f}A")
    else:  # exactly one command, even if already in this mode (re-sending Silent restarts a stopped fan)
        psu.set_mode(args.cmd)
        print("fan mode set:", psu.get_mode())
    psu.close()


if __name__ == "__main__":
    sys.exit(main())
