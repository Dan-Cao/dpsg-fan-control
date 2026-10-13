# DPS G Fan

A tray app that stops a Thermaltake Toughpower DPS G power supply from switching its fan on and off every few seconds.

In **Zero Fan** mode the PSU firmware starts the fan at 40 °C and stops it at 39 °C. At a typical desktop load the PSU sits right at that line, so the fan keeps cycling ([forum thread](https://community.thermaltake.com/index.php?/topic/65374-toughpower-dps-g-1050w-fan-curve/)). Thermaltake's position is that the DPS series can't have a custom fan curve ([forum thread](https://community.thermaltake.com/index.php?/topic/240133-fan-control-curve/)).

This app adds hysteresis by switching between the PSU's own fan modes:

```
Zero Fan  --(temp >= 40 °C, or the fan starts)-->  Silent
Silent    --(temp <= 36 °C and on for >= 1 min)-->  Zero Fan
```

The firmware still sets the fan speed within each mode, so the worst case is the stock behaviour.

## Setup

Requires Windows and Python 3 on `PATH`.

Double-click **`Start DPSG Fan.cmd`**. The first run creates a `.venv` here and installs [requirements.txt](requirements.txt). After that it starts the tray app with no console window. Only one copy runs at a time.

To change the thresholds, pass options to the launcher or the script:

```
"Start DPSG Fan.cmd" --on 40 --off 37 --min-on 45
```

| Option       | Default | Meaning                                      |
|--------------|---------|----------------------------------------------|
| `--on`       | 40      | Switch the fan on at this temperature (°C)    |
| `--off`      | 36      | Allow it off again at this temperature (°C)   |
| `--min-on`   | 60      | Minimum seconds the fan stays on              |
| `--interval` | 2       | Seconds between readings                      |

## Using the tray icon

The icon shows the PSU temperature. Its colour shows the fan:

| Colour | Meaning                      |
|--------|------------------------------|
| Grey   | Fan off                      |
| Blue   | Fan on                       |
| Orange | Performance mode             |
| Red `!`| PSU not found                |

Hover for temperature, fan speed, output power, efficiency, and in Auto mode whether the fan should be on or off.

Right-click for:

- Live readings: temperature, fan RPM, input/output watts, efficiency, per-rail current, and the last Auto switch
- Fan mode: **Auto** (the hysteresis above), **Zero Fan** (stock), **Silent** or **Performance**
- **Open log**: fan switches are logged to `%LOCALAPPDATA%\DPSG-Fan\dpsg_fan.log`
- **Start with Windows**: adds a `DPSG Fan` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` that starts the `.venv` copy at sign-in. Turn it on again if you move this folder or change options.
- **Quit**: puts the PSU back in Zero Fan mode

The Thermaltake DPS G app can stay open for its stats. If it changes the fan mode, this app sets its own mode again within a minute. Avoid changing the fan mode in both apps.

## Command line

[dpsg_fan.py](dpsg_fan.py) works without the tray:

```
.venv\Scripts\python dpsg_fan.py status        # one reading
.venv\Scripts\python dpsg_fan.py silent        # set a mode: silent | zero | performance
.venv\Scripts\python dpsg_fan.py               # run the Auto controller in the console
```

## Supported hardware

Tested on a **Toughpower DPS G 1200W Platinum**, which reports itself over USB as:

- **USB ID:** `264A:232A`
- **Product:** "Thermaltake Platinum Digital Power Supply", model `TPG-1200D-P`
- **Manufacturer:** "ODM from Enhance Co., Ltd."

Other DPS G models with USB ID `264A:232A` should work. Models with USB ID `264A:2329` use a different protocol (see below) and are not supported by this app.

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

**Output report `0x13`, 2 bytes: fan mode.**

| Bytes   | Mode        |
|---------|-------------|
| `13 FE` | Performance |
| `13 FD` | Silent      |
| `13 FB` | Zero Fan    |

Other values of the second byte have not been tried.

**Output report `0x1E`, 16 bytes:** LED control (`1E 00 R G B` sets a colour, `1E 01 <0|1>` turns the LEDs on or off). Not used here.

### Measured behaviour (1200W, ~100 W load)

- **Zero Fan:** fan off below 40 °C. At 40 °C it spins at roughly 570–740 RPM, then stops at 39 °C, repeating every few seconds.
- **Silent:** a constant ~928 RPM at this load. Temperature fell from 39 °C to 35 °C in about 90 seconds.

## Files

| File                  | Purpose                                                  |
|-----------------------|----------------------------------------------------------|
| `Start DPSG Fan.cmd`  | Double-click launcher; sets up `.venv` on first run       |
| `dpsg_tray.pyw`       | Tray app                                                 |
| `dpsg_fan.py`         | PSU access, hysteresis controller and command-line tool   |
| `requirements.txt`    | `hidapi`, `pystray`, `pillow`                            |

## Credits

The LINEAR11 decoding follows [erpalma's DPS script](https://gist.github.com/erpalma/4f4d73cb0f6ee54fe758b67446b9d044), which covers the `2329` family.

This project isn't affiliated with Thermaltake. Use it at your own risk.
