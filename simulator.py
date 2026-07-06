import subprocess
import socket
import time
import select
import random
import sys
import threading
import shutil
import os
import math
import json
import argparse
from rocketpy import Environment, Rocket, SolidMotor, Flight

def preflight_checks():
    print("[CHECK] Running preflight checks...")
    all_ok = True

    # 1. Check Python version
    import sys
    if sys.version_info < (3, 9):
        print(f"[CHECK] FAIL: Python 3.9+ required, you have {sys.version}")
        all_ok = False
    else:
        print(f"[CHECK] PASS: Python {sys.version_info.major}.{sys.version_info.minor}")

    # 2. Check RocketPy installed
    try:
        import rocketpy
        print("[CHECK] PASS: RocketPy installed")
    except ImportError:
        print("[CHECK] FAIL: RocketPy not installed — run: pip install rocketpy")
        all_ok = False

    # 3. Check g++ available
    import shutil
    if shutil.which("g++"):
        print("[CHECK] PASS: g++ found")
    else:
        print("[CHECK] FAIL: g++ not found — install MSYS2 on Windows or Xcode tools on macOS")
        all_ok = False

    # 4. Check PlatformIO available
    try:
        pio = find_pio()
        print(f"[CHECK] PASS: PlatformIO found at {pio}")
    except FileNotFoundError as e:
        print(f"[CHECK] FAIL: {e}")
        all_ok = False

    # 5. Check port 9000 is free
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        result = s.connect_ex(('localhost', 9000))
        if result == 0:
            print("[CHECK] FAIL: Port 9000 is already in use — kill any previous simulator processes")
            all_ok = False
        else:
            print("[CHECK] PASS: Port 9000 is free")

    # 6. Check config file exists
    if os.path.isfile(args.config):
        print(f"[CHECK] PASS: Config file found ({args.config})")
    else:
        print(f"[CHECK] FAIL: Config file not found at '{args.config}' — copy config.json.example to config.json")
        all_ok = False

    if not all_ok:
        print("\n[CHECK] One or more preflight checks failed. Fix the issues above and try again.")
        sys.exit(1)

    print("[CHECK] All checks passed.\n")

def find_pio():
    pio = shutil.which("pio") or shutil.which("platformio")
    if pio:
        return pio

    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".platformio", "penv", "Scripts", "platformio.exe"),
        os.path.join(home, ".platformio", "penv", "bin", "platformio"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "Could not find PlatformIO. Make sure it's installed and either "
        "on your PATH, or installed in the default location."
    )


# --- Load config ---------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--config", default="config.json", help="Path to config file")
args = parser.parse_args()

with open(args.config) as f:
    cfg = json.load(f)

env_cfg = cfg["environment"]
motor_cfg = cfg["motor"]
rocket_cfg = cfg["rocket"]
flight_cfg = cfg["flight"]
noise_cfg = cfg["sensor_noise"]
sim_cfg = cfg["sim"]
val_cfg = cfg["validation"]
# --------------------------------------------------------------------------
CHECKS = preflight_checks()
PIO = find_pio()
print("[RUNNER] Cleaning native build...")
subprocess.run([PIO, "run", "-e", "native", "-t", "clean"], capture_output=True, text=True)

print("[RUNNER] Building firmware (native)...")
build = subprocess.run([PIO, "run", "-e", "native"], capture_output=True, text=True)
if build.returncode != 0:
    print("[RUNNER] Build failed!")
    print(build.stdout)
    print(build.stderr)
    sys.exit(1)
print("[RUNNER] Build succeeded.\n")

print("[RUNNER] Launching firmware...\n")
firmware_proc = subprocess.Popen(
    [".pio/build/native/program.exe"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)


def stream_firmware_output(proc):
    for line in proc.stdout:
        print(f"[FIRMWARE] {line.rstrip()}")

output_thread = threading.Thread(target=stream_firmware_output, args=(firmware_proc,), daemon=True)
output_thread.start()

time.sleep(0.5)

# --- Rocket / motor / flight setup, all from config ----------------------
env = Environment(
    latitude=env_cfg["latitude"],
    longitude=env_cfg["longitude"],
    elevation=env_cfg["elevation"],
)

motor = SolidMotor(
    thrust_source=motor_cfg["thrust_source"],
    dry_mass=motor_cfg["dry_mass"],
    dry_inertia=tuple(motor_cfg["dry_inertia"]),
    nozzle_radius=motor_cfg["nozzle_radius"],
    grain_number=motor_cfg["grain_number"],
    grain_density=motor_cfg["grain_density"],
    grain_outer_radius=motor_cfg["grain_outer_radius"],
    grain_initial_inner_radius=motor_cfg["grain_initial_inner_radius"],
    grain_initial_height=motor_cfg["grain_initial_height"],
    grain_separation=motor_cfg["grain_separation"],
    grains_center_of_mass_position=motor_cfg["grains_center_of_mass_position"],
    center_of_dry_mass_position=motor_cfg["center_of_dry_mass_position"],
    nozzle_position=motor_cfg["nozzle_position"],
    burn_time=motor_cfg["burn_time"],
    throat_radius=motor_cfg["throat_radius"],
)

rocket = Rocket(
    radius=rocket_cfg["radius"],
    mass=rocket_cfg["mass"],
    inertia=tuple(rocket_cfg["inertia"]),
    power_off_drag=rocket_cfg["power_off_drag"],
    power_on_drag=rocket_cfg["power_on_drag"],
    center_of_mass_without_motor=rocket_cfg["center_of_mass_without_motor"],
    coordinate_system_orientation="tail_to_nose",
)

rocket.add_motor(motor, position=0)
rocket.add_nose(**rocket_cfg["nose"])
rocket.add_fins(**rocket_cfg["fins"])
rocket.add_parachute(**rocket_cfg["parachute"])

flight = Flight(
    rocket=rocket, environment=env,
    rail_length=flight_cfg["rail_length"],
    inclination=flight_cfg["inclination"],
    heading=flight_cfg["heading"],
    terminate_on_apogee=False,
)

print(f"[SIM] Apogee: {flight.apogee - env.elevation:.1f}m AGL at T+{flight.apogee_time:.2f}s\n")

# --- Socket server --------------------------------------------------------
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((sim_cfg["socket_host"], sim_cfg["socket_port"]))
server.listen(1)

print(f"[SIM] Waiting for firmware to connect on port {sim_cfg['socket_port']}...")
conn, _ = server.accept()
conn.setblocking(False)
print("[SIM] Firmware connected! Sending flight data...\n")

MIN_PYRO_SEPARATION_S = val_cfg["min_pyro_separation_s"]

apogee_events = []
pyro1_events = []
pyro2_events = []

t = 0
dt = sim_cfg["dt"]

PRESSURE_NOISE_STD = noise_cfg["pressure_std"]
BARO_NOISE_STD = noise_cfg["baro_std"]
ACCEL_NOISE_STD = noise_cfg["accel_std_g"] * 9.81 * math.sqrt(100)
GYRO_NOISE_STD = math.radians(noise_cfg["gyro_std_deg"]) * math.sqrt(100)
GPS_NOISE_STD_METERS = noise_cfg["gps_std_meters"]
GPS_NOISE_STD_DEG = GPS_NOISE_STD_METERS / 111320

while t <= flight.t_final:
    try:
        alt = flight.z(t) - env.elevation
        alt_noisy = alt + random.gauss(0, BARO_NOISE_STD)

        if alt < 0:
            break

        pressure = flight.pressure(t)
        pressure_noisy = pressure + random.gauss(0, PRESSURE_NOISE_STD)

        ax, ay, az = flight.ax(t), flight.ay(t), flight.az(t)
        ax_noisy = ax + random.gauss(0, ACCEL_NOISE_STD)
        ay_noisy = ay + random.gauss(0, ACCEL_NOISE_STD)
        az_noisy = az + random.gauss(0, ACCEL_NOISE_STD)

        wx, wy, wz = flight.w1(t), flight.w2(t), flight.w3(t)
        wx_noisy = wx + random.gauss(0, GYRO_NOISE_STD)
        wy_noisy = wy + random.gauss(0, GYRO_NOISE_STD)
        wz_noisy = wz + random.gauss(0, GYRO_NOISE_STD)

        lat, lon = env_cfg["latitude"], env_cfg["longitude"]
        lat_noisy = lat + random.gauss(0, GPS_NOISE_STD_DEG)
        lon_noisy = lon + random.gauss(0, GPS_NOISE_STD_DEG)

        packet = f"{pressure_noisy:.2f},{ax_noisy:.4f},{ay_noisy:.4f},{az_noisy:.4f},{wx_noisy:.4f},{wy_noisy:.4f},{wz_noisy:.4f},{lat_noisy:.6f},{lon_noisy:.6f},{alt_noisy:.2f}\n"
        conn.send(packet.encode())

        ready, _, _ = select.select([conn], [], [], 0)
        if ready:
            data = conn.recv(1024).decode()
            for line in data.strip().split("\n"):
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if parts[0] == "EVENT" and parts[1] == "APOGEE":
                    apogee_events.append((t, float(parts[2])))
                    print(f"[SIM] Firmware reported APOGEE at T+{t:.2f}s, alt={float(parts[2]):.2f}m")
                elif parts[0] == "EVENT" and parts[1] == "PYRO1":
                    pyro1_events.append((t, float(parts[2])))
                    print(f"[SIM] Firmware reported PYRO1 FIRE at T+{t:.2f}s, alt={float(parts[2]):.2f}m")
                elif parts[0] == "EVENT" and parts[1] == "PYRO2":
                    pyro2_events.append((t, float(parts[2])))
                    print(f"[SIM] Firmware reported PYRO2 FIRE at T+{t:.2f}s, alt={float(parts[2]):.2f}m")

        time.sleep(dt)
        t += dt

    except BrokenPipeError:
        print("[SIM] Firmware disconnected")
        break

print("\n[SIM] Flight complete")

firmware_proc.terminate()
firmware_proc.wait()

# --- Test report -----------------------------------------------------------
true_apogee_time = flight.apogee_time
true_apogee_alt = flight.apogee - env.elevation
pyro2_state = val_cfg["pyro2"]
true_pyro2_alt = rocket_cfg["parachute"]["trigger"]

detected_apogee_time = apogee_events[0][0] if apogee_events else None
detected_apogee_alt = apogee_events[0][1] if apogee_events else None
detected_pyro1_time = pyro1_events[0][0] if pyro1_events else None
detected_pyro1_alt = pyro1_events[0][1] if pyro1_events else None
detected_pyro2_time = pyro2_events[0][0] if pyro2_events else None
detected_pyro2_alt = pyro2_events[0][1] if pyro2_events else None

print("\n=== TEST REPORT ===")
if detected_apogee_time is None:
    print("Apogee detection:   FAIL (never detected)")
else:
    time_error = abs(detected_apogee_time - true_apogee_time)
    status = "PASS" if time_error < val_cfg["apogee_time_tolerance_s"] else "FAIL"
    print(f"Apogee detection:   {status}")
    print(f"  True apogee:      {true_apogee_alt:.1f}m at T+{true_apogee_time:.2f}s")
    print(f"  Detected apogee:  {detected_apogee_alt:.1f}m at T+{detected_apogee_time:.2f}s")
    print(f"  Time error:       {time_error:.2f}s")

print(f"\nPyro channel 1:")
if detected_pyro1_time is None:
    print("  FAIL (never fired)")
else:
    time_error = abs(detected_pyro1_time - true_apogee_time)
    status = "PASS" if time_error < val_cfg["pyro1_time_tolerance_s"] else "FAIL"
    print(f"  {status}")
    print(f"  Fired at:       T+{detected_pyro1_time:.2f}s, alt={detected_pyro1_alt:.1f}m")
    print(f"  Expected at:    T+{true_apogee_time:.2f}s")
    print(f"  Time error:     {time_error:.2f}s")


if pyro2_state:
    print(f"\nPyro channel 2:")
    if detected_pyro2_time is None:
        print("  FAIL (never fired)")
    else:
        alt_error = abs(detected_pyro2_alt - true_pyro2_alt)
        status = "PASS" if alt_error < val_cfg["pyro2_alt_tolerance_m"] else "FAIL"
        print(f"  {status}")
        print(f"  Fired at:       T+{detected_pyro2_time:.2f}s, alt={detected_pyro2_alt:.1f}m")
        print(f"  Expected at:    alt={true_pyro2_alt:.2f}m")
        print(f"  Distance error: {alt_error:.2f}m")

    # --- Deployment sequence validation -----------------------------------------
    print(f"\n=== SEQUENCE VALIDATION ===")

    for name, events in [("PYRO1", pyro1_events), ("PYRO2", pyro2_events)]:
        if len(events) > 1:
            times = ", ".join(f"T+{e[0]:.2f}s" for e in events)
            print(f"{name} single-fire check: FAIL — fired {len(events)} times at: {times}")
        elif len(events) == 1:
            print(f"{name} single-fire check: PASS — fired once")

    if detected_pyro1_time is not None and detected_pyro2_time is not None:
        order_ok = detected_pyro2_time > detected_pyro1_time
        print(f"PYRO1 -> PYRO2 order:  {'PASS' if order_ok else 'FAIL'} "
            f"(PYRO1 at T+{detected_pyro1_time:.2f}s, PYRO2 at T+{detected_pyro2_time:.2f}s)")

        gap = detected_pyro2_time - detected_pyro1_time
        sep_ok = gap >= MIN_PYRO_SEPARATION_S
        print(f"PYRO1/PYRO2 separation: {'PASS' if sep_ok else 'FAIL'} "
            f"(gap={gap:.2f}s, min required={MIN_PYRO_SEPARATION_S}s)")
    else:
        print(f"PYRO1 -> PYRO2 order:  SKIPPED (one or both channels never fired)")
        print(f"PYRO1/PYRO2 separation: SKIPPED (one or both channels never fired)")

server.close()
