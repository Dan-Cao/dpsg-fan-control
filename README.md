# DPS G Fan

A tray monitor for the Thermaltake Toughpower DPS G power supply, plus a small command-line tool. Both can set the PSU's fan mode, one command at a time. It also documents the PSU's USB protocol.

## The short version

In **Zero Fan** mode the PSU firmware starts the fan at 40 °C and stops it at 39 °C. At a typical desktop load the PSU sits right at that line, so the fan keeps cycling ([forum thread](https://community.thermaltake.com/index.php?/topic/65374-toughpower-dps-g-1050w-fan-curve/)). Thermaltake's position is that the DPS series can't have a custom fan curve ([forum thread](https://community.thermaltake.com/index.php?/topic/240133-fan-control-curve/)).

**The fix is to put the PSU in Silent mode once and leave it.** The fan then runs steadily at about 930 RPM instead of starting and stopping, and the PSU runs at about 30–32 °C instead of 40 °C. The PSU remembers the mode through power-offs, so no software needs to keep running. You can set it from the Thermaltake app or with this project's command-line tool.

## Setup

Requires Windows and Python 3 on `PATH`.

1. Double-click **`Start DPSG Fan.cmd`**. The first run creates a `.venv` here and installs [requirements.txt](requirements.txt), then starts the tray monitor with no console window. Only one copy runs at a time.
2. If the PSU isn't already in Silent (the tray shows the current mode), right-click the tray icon and choose **Set fan mode → Silent**. You only need to do this once.

## The tray monitor

It reads from the PSU every 2 seconds. It only sends a command when you choose a fan mode from its menu: one command per click, never automatically.

The icon shows the PSU temperature. Its colour shows the fan:

| Colour  | Meaning       |
|---------|---------------|
| Grey    | Fan off       |
| Blue    | Fan on        |
| Red `!` | PSU not found |

Hover for temperature, fan speed, output power, efficiency and fan mode. Right-click for:

- Live readings: temperature, fan RPM, fan mode, input/output watts, efficiency, per-rail current, how long the fan has been on or off, and how many times it has stopped outside Zero Fan
- **Set fan mode → Zero Fan / Silent / Performance**: sends exactly one command. The current mode is ticked. Choosing the current mode sends the command again, which is how to restart the fan if the log shows it stopped in Silent.
- **Open log**: `%LOCALAPPDATA%\DPSG-Fan\dpsg_fan.log` records each command sent from the menu, fan-mode changes (from any app), and every fan start and stop outside Zero Fan. In Silent the fan should run steadily, so a stop there is worth knowing about. Zero Fan's own cycling isn't logged.
- **Start with Windows**: adds a `DPSG Fan` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` that starts the `.venv` copy at sign-in. Turn it on again if you move this folder.
- **Quit**

The Thermaltake DPS G app can run alongside it.

## Command line

```
.venv\Scripts\python dpsg_fan.py status        # model, serial, firmware, fan mode and one reading
.venv\Scripts\python dpsg_fan.py silent        # set the fan mode: silent | zero | performance
```

Setting a mode sends exactly one command each time, even if the PSU is already in that mode.

## What we found, and what not to do

All of this was worked out by reverse-engineering one 1200W unit. Thermaltake doesn't document any of it.

- **There's no fan curve or fan-speed command for this PSU.** The firmware only has three fan modes, each with its own built-in curve. The firmware dates from December 2015, and no update has ever been published.
- **Silent only runs steadily after a fan-mode command or a power-on.** Otherwise it cycles at 40/39 °C just like Zero Fan. In testing, one command kept the fan running steadily for 15+ minutes, and so did a power-on in Silent. Once, after a switch from Zero Fan to Silent, the fan cycled instead, until the command was sent again. The tray monitor's log will show if this happens to you.
- **The PSU stores its fan mode in non-volatile memory.** It's unknown whether every command writes that memory, or how many writes it survives (this kind of memory is typically rated for 10,000 to 1,000,000). So **don't send fan-mode commands repeatedly.**
- **Automatic switching between modes works, but isn't worth it.** An earlier version of this app switched between Zero Fan and Silent with hysteresis (fan on at 40 °C, off at 36 °C), giving about a minute of steady fan every few minutes. It worked, but sent about 40 commands an hour, and depended on the undocumented behaviour above. It's in the git history (commit `e277f8a`) if you want to experiment.
- **Rapid mode switching ("software PWM") doesn't work.** The fan takes about 8 s to start after a command and 3–9 s to coast to a stop, so fast toggling doesn't give an in-between speed. You'd hear every spin-up, and it would send a command every few seconds.
- **Don't send the unknown output reports** (`0x15`–`0x1A`); see [Protocol notes](#protocol-notes).
- **The firmware always keeps control of the fan speed and protections.** No mode stops the fan from cooling a hot PSU: Zero Fan still starts it at 40 °C.

## Supported hardware

Tested on a **Toughpower DPS G 1200W Platinum**, which reports itself over USB as:

- **USB ID:** `264A:232A`
- **Product:** "Thermaltake Platinum Digital Power Supply", model `TPG-1200D-P`
- **Manufacturer:** "ODM from Enhance Co., Ltd."

Other DPS G models with USB ID `264A:232A` should work. Models with USB ID `264A:2329` use a different protocol (see below) and aren't supported.

## Protocol notes

These were found by disassembling the Thermaltake DPS G PC App 3.3.1 (`Thermaltake DPS POWER.exe`) and checked against the PSU.

The app supports two PSU families:

| USB ID      | API in the app                                  | Fan control                                          |
|-------------|-------------------------------------------------|------------------------------------------------------|
| `264A:232A` | Windows HID (`HidD_GetInputReport` / `HidD_SetOutputReport`) | Three firmware modes only                 |
| `264A:2329` | hidapi, 64-byte reports                         | Three modes, plus a fixed duty cycle (`30 41 04 <percent>`) |

The app's **Custom** fan setting sends the duty-cycle command only to the `2329` family. For `232A` there is no duty-cycle or curve command, so a true fan curve isn't possible on this PSU.

### `264A:232A` reports

**Input report `0x10`, 31 bytes: telemetry.** After the report ID come 15 little-endian PMBus LINEAR11 words, in this order:

| # | Field        | # | Field        | # | Field              |
|---|--------------|---|--------------|---|--------------------|
| 0 | AC input V   | 5 | 12 V current | 10| Output W           |
| 1 | AC input A   | 6 | 5 V rail     | 11| Efficiency (0–1)   |
| 2 | Input W      | 7 | 5 V current  | 12| Secondary temp °C  |
| 3 | Power factor | 8 | 3.3 V rail   | 13| PSU temp °C (the one the fan follows) |
| 4 | 12 V rail    | 9 | 3.3 V current| 14| Fan RPM            |

LINEAR11: the top 5 bits are a signed exponent and the low 11 bits are a signed mantissa. The value is `mantissa × 2^exponent`.

**Input report `0x11`, 33 bytes:** model name (ASCII), e.g. `TPG-1200D-P`.

**Input report `0x12`, 33 bytes:** serial number (ASCII).

**Input report `0x14`, 2 bytes: current fan mode.** The second byte is the same value as the fan-mode command below (`FE`, `FD` or `FB`). It updates within 0.3 s of a mode change.

**Input report `0x1D`, 33 bytes:** firmware build date (ASCII), e.g. `Dec 10 2015 14:26:14`.

**Output report `0x13`, 2 bytes: fan mode.**

| Bytes   | Mode        |
|---------|-------------|
| `13 FE` | Performance |
| `13 FD` | Silent      |
| `13 FB` | Zero Fan    |

Other values of the second byte have not been tried.

The PSU **stores the fan mode in non-volatile memory**: after a full power-off (rear switch), it came back in Silent with no command sent. It's unknown whether the firmware writes that memory on every command or only when the mode changes, so avoid sending fan-mode commands more often than needed. Right after power-on in Silent, the fan ran continuously, as it does after a command.

The PSU's HID report descriptor also declares output reports `0x15`–`0x18` (24 bytes), `0x19` (3 bytes) and `0x1A` (32 bytes). The Thermaltake app never sends them and their purpose is unknown. They could be calibration or firmware-update commands, so don't send them blind.

**Output report `0x1E`, 16 bytes:** LED control (`1E 00 R G B` sets a colour, `1E 01 <0|1>` turns the LEDs on or off). Not used here.

### Measured behaviour (1200W, ~100 W load)

- **Zero Fan:** fan off below 40 °C. At 40 °C it spins at roughly 570–740 RPM, then stops at 39 °C, repeating every few seconds.
- **Silent, after a fan-mode command:** the fan spins up within about 8 s and holds a steady ~928 RPM. This happens even if the command repeats the current mode. One command kept it running for 15+ minutes at 30–32 °C. Temperature fell from 40 °C to 36 °C in under a minute.
- **Silent, when a switch doesn't take:** about one switch in six during one evening of automatic switching. The PSU reports Silent, but the fan cycles at 40/39 °C like Zero Fan: about 10 s on, 10–20 s off. Re-sending the command fixed it. The cause is unknown; it isn't a timeout, and it isn't caused by reading report `0x14`.

## Files

| File                  | Purpose                                                  |
|-----------------------|----------------------------------------------------------|
| `Start DPSG Fan.cmd`  | Double-click launcher; sets up `.venv` on first run       |
| `dpsg_tray.pyw`       | Tray monitor, with one-click fan-mode commands            |
| `dpsg_fan.py`         | PSU access and command-line tool                          |
| `requirements.txt`    | `hidapi`, `pystray`, `pillow`                            |

## Credits

The LINEAR11 decoding follows [erpalma's DPS script](https://gist.github.com/erpalma/4f4d73cb0f6ee54fe758b67446b9d044), which covers the `2329` family.

This project isn't affiliated with Thermaltake. Use it at your own risk.
