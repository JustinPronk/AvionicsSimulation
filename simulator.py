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
from rocketpy import Environment, Rocket, SolidMotor, Flight



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


env = Environment(latitude=51.5, longitude=-3.18, elevation=100)

motor = SolidMotor(
    thrust_source=[[0, 0], [0.1, 800], [0.5, 820], [1.0, 810], [1.5, 800],
                   [2.0, 790], [2.5, 750], [3.0, 600], [3.5, 200], [3.6, 0]],
    dry_mass=0.5, dry_inertia=(0.02, 0.02, 0.001), nozzle_radius=0.025,
    grain_number=4, grain_density=1700, grain_outer_radius=0.025,
    grain_initial_inner_radius=0.015, grain_initial_height=0.1,
    grain_separation=0.005, grains_center_of_mass_position=0.3,
    center_of_dry_mass_position=0.3, nozzle_position=0,
    burn_time=3.5, throat_radius=0.01,
)

rocket = Rocket(
    radius=0.05, mass=2.0, inertia=(0.5, 0.5, 0.01),
    power_off_drag=0.5, power_on_drag=0.5,
    center_of_mass_without_motor=0.6,
    coordinate_system_orientation="tail_to_nose",
)

rocket.add_motor(motor, position=0)
rocket.add_nose(length=0.3, kind="ogive", position=1.2)
rocket.add_fins(n=4, root_chord=0.12, tip_chord=0.06, span=0.08, position=0.1)
rocket.add_parachute(name="main", cd_s=10.0, trigger=300)

flight = Flight(rocket=rocket, environment=env, rail_length=3,
                 inclination=90, heading=0, terminate_on_apogee=False)

print(f"[SIM] Apogee: {flight.apogee - env.elevation:.1f}m AGL at T+{flight.apogee_time:.2f}s\n")


server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('localhost', 9000))
server.listen(1)

print("[SIM] Waiting for firmware to connect on port 9000...")
conn, _ = server.accept()
conn.setblocking(False)
print("[SIM] Firmware connected! Sending flight data...\n")

detected_apogee_time = None
detected_apogee_alt = None
detected_pyro1_time = None
detected_pyro1_alt = None

t = 0
dt = 0.01

PRESSURE_NOISE_STD = 2.4
BARO_NOISE_STD = 0.3
ACCEL_NOISE_STD = 0.05 * 9.81 * math.sqrt(100)
GYRO_NOISE_STD = math.radians(0.0038) * math.sqrt(100)
GPS_NOISE_STD_METERS = 1.5 
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

        lat, lon = 51.5, -3.18
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
                    detected_apogee_time = t
                    detected_apogee_alt = float(parts[2])
                    print(f"[SIM] Firmware reported APOGEE at T+{t:.2f}s, alt={detected_apogee_alt:.2f}m")
                elif parts[0] == "EVENT" and parts[1] == "PYRO1":
                    detected_pyro1_time = t
                    detected_pyro1_alt = float(parts[2])
                    print(f"[SIM] Firmware reported PYRO1 FIRE at T+{t:.2f}s, alt={detected_pyro1_alt:.2f}m")

        time.sleep(dt)
        t += dt

    except BrokenPipeError:
        print("[SIM] Firmware disconnected")
        break

print("\n[SIM] Flight complete")


firmware_proc.terminate()
firmware_proc.wait()


true_apogee_time = flight.apogee_time
true_apogee_alt = flight.apogee - env.elevation

print("\n=== TEST REPORT ===")
if detected_apogee_time is None:
    print("Apogee detection:   FAIL (never detected)")
else:
    time_error = abs(detected_apogee_time - true_apogee_time)
    status = "PASS" if time_error < 1 else "FAIL"
    print(f"Apogee detection:   {status}")
    print(f"  True apogee:      {true_apogee_alt:.1f}m at T+{true_apogee_time:.2f}s")
    print(f"  Detected apogee:  {detected_apogee_alt:.1f}m at T+{detected_apogee_time:.2f}s")
    print(f"  Time error:       {time_error:.2f}s")

print(f"\nPyro channel 1:")
if detected_pyro1_time is None:
    print("  FAIL (never fired)")
else:
    expected_time = true_apogee_time
    time_error = abs(detected_pyro1_time - expected_time)
    status = "PASS" if time_error < 1.0 else "FAIL"
    print(f"  {status}")
    print(f"  Fired at:       T+{detected_pyro1_time:.2f}s, alt={detected_pyro1_alt:.1f}m")
    print(f"  Expected at:    T+{expected_time:.2f}s")
    print(f"  Time error:     {time_error:.2f}s")

server.close()
