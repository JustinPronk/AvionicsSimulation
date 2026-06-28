# Rocket Firmware Simulator

Test your rocket flight computer firmware against a realistic simulated flight.

## What this is

If you're building a flight computer for high-power rocketry, your only real way to test apogee detection, pyro channel firing, and other flight logic has traditionally been to launch a rocket and hope it works. That's expensive, weather-dependent, and you only get one shot per test.

This tool runs your firmware code, unmodified and compiled natively on your laptop, against a physically realistic simulated flight powered by [RocketPy](https://github.com/RocketPy-Team/RocketPy). Your firmware reads simulated sensor data: barometer, accelerometer, gyroscope, GPS — exactly as it would read real hardware, with realistic sensor noise based on actual datasheet specifications. At the end of the simulated flight, you get a pass/fail report comparing what your firmware decided against the ground truth physics.

```
=== TEST REPORT ===
Apogee detection:   PASS
  True apogee:      2937.0m at T+18.78s
  Detected apogee:  2935.4m at T+18.27s
  Time error:       0.51s

Pyro channel 1:
  PASS
  Fired at:       T+18.27s, alt=2935.4m
  Expected at:    T+18.78s
  Time error:     0.51s
```

## How it works

Your firmware is written against a small hardware abstraction layer (HAL) instead of talking to sensor chips directly. On a real flight computer, the HAL talks to actual hardware. For testing, a different implementation of the same HAL talks to this simulator instead — your firmware has no idea the flight isn't real.

```
Your firmware (compiled natively)
        ↕  HAL_ReadPressure(), HAL_ReadAccelX(), etc.
Simulator (Python + RocketPy)
        ↕
Realistic 6-DOF flight physics + sensor noise
```

The simulator streams sensor data to your firmware over a local socket at 100Hz, listens for events your firmware reports back (apogee detected, pyro fired), and compares them against RocketPy's known-correct physics at the end of the flight.

## Requirements

- [PlatformIO](https://platformio.org/) installed (CLI or VS Code extension)
- Python 3.9+
- A C++ compiler available natively on your machine:
  - **Windows**: [MSYS2](https://www.msys2.org/) with `mingw-w64-x86_64-gcc` installed, added to your PATH
  - **macOS**: Xcode Command Line Tools (`xcode-select --install`)
  - **Linux**: `gcc`/`g++` (usually already installed)

## Setup

1. Clone this repo and install Python dependencies:

```bash
pip install -r requirements.txt
```

2. Add the native build environment to your `platformio.ini`:

```ini
[env:native]
platform = native
build_src_filter = +<main.cpp> +<hal_sim.cpp> +<native_main.cpp>
build_flags = -lws2_32 -mconsole
```

> `-lws2_32` is required on Windows for socket support. Omit it on macOS/Linux.

3. Make sure your firmware reads sensors through the HAL functions defined in `Hal.h` (`HAL_ReadPressure()`, `HAL_ReadAccelX()`, etc.) rather than talking to hardware registers directly. See `main.cpp` for the expected structure.

## Usage

```bash
python simulation.py
```

This will:
1. Clean and rebuild your firmware for the native target
2. Run a simulated rocket flight through RocketPy
3. Stream live sensor data (with realistic noise) into your firmware
4. Print your firmware's debug output live, prefixed with `[FIRMWARE]`
5. Print a final pass/fail test report comparing your firmware's decisions to ground truth

## Configuring the simulated rocket

Rocket, motor, and flight parameters are defined directly in `simulation.py` — edit the `Rocket`, `SolidMotor`, and `Flight` setup near the top of the file to match your own vehicle. A YAML-based config (so you don't need to touch Python to change rocket parameters) is on the roadmap.

## Sensor noise model

Sensor noise is modeled using real datasheet specifications where possible, so a firmware bug that only shows up under realistic noise won't be hidden by an artificially clean simulation:

| Sensor | Noise spec source | 
|---|---|
| Barometer (MS5607) | 0.024 mbar RMS @ OSR4096 |
| Accelerometer (ADXL375) | 5 mg/√Hz noise density |
| Gyroscope (ICM-45686) | 3.8 mdps/√Hz noise density |
| GPS | ~2.5m CEP (typical consumer module) |

## What this is not

This is **not** a replacement for [OpenRocket](https://openrocket.info/) or RocketPy's own simulation tools — those answer "will this rocket fly well?" This tool answers a different question: "does my flight computer's *code* make the right decisions during a flight?" The two are complementary — you'd typically use OpenRocket/RocketPy to design your rocket, then this tool to test the firmware that flies it.

This also doesn't (yet) test actual hardware — it's software-in-the-loop (SITL), running your firmware as a native process on your laptop. Hardware-in-the-loop (HIL) support, where you plug in your actual flight computer board and feed it simulated sensor data over its real interfaces, is a planned future direction.

## Status

Early-stage / proof of concept. Built to validate a Kalman-filter-based apogee detection algorithm and dual-deploy pyro logic. Currently supports:

- ✅ Apogee detection testing
- ✅ Single pyro channel testing
- ✅ Realistic, datasheet-based sensor noise
- ⬜ Multiple pyro channels
- ⬜ Staging/multi-stage logic
- ⬜ HIL mode (real hardware over serial)
- ⬜ CI integration (GitHub Actions)

## Why this exists

Most amateur and university rocketry teams currently test flight computer firmware by launching a rocket and hoping it works, or with ad-hoc bench tests using real sensors. There's no equivalent of [ArduPilot's SITL](https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html) for high-power rocketry. This is an attempt to build that — starting small, with apogee detection and pyro firing, and growing from there.

## Contributing / trying this on your own firmware

If you're part of a university rocketry team or building your own flight computer and want to try this against your firmware, [open an issue](../../issues) or reach out — happy to help wire it up.


