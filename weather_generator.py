import time, random, json, subprocess, uuid

STATIONS = [
    {"id": "ST001", "lat": 34.05, "lon": -118.24, "name": "Los Angeles"},
    {"id": "ST002", "lat": 37.77, "lon": -122.42, "name": "San Francisco"},
    {"id": "ST003", "lat": 36.16, "lon": -115.15, "name": "Las Vegas"},
]

SENSOR_KEYS = ("temperature", "wind_speed", "humidity")


def pick_available_sensors():
    """Simulate real-world sensor dropouts: which values arrive in this reading."""
    r = random.random()
    if r < 0.50:
        return {"temperature", "wind_speed", "humidity"}   # full reading
    elif r < 0.68:
        return {"temperature"}                              # only temperature
    elif r < 0.86:
        return {"wind_speed"}                               # only wind
    else:
        return set()                                        # nothing (station heartbeat only)


def generate_reading(station, spike=False):
    full = {
        "temperature": round(random.uniform(28, 42), 1) if spike else round(random.uniform(10, 27), 1),
        "wind_speed": round(random.uniform(6, 15), 1) if spike else round(random.uniform(0, 5), 1),
        "humidity": round(random.uniform(5, 20), 1) if spike else round(random.uniform(30, 70), 1),
    }
    reading = {
        "station_id": station["id"],
        "lat": station["lat"],
        "lon": station["lon"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    for key in pick_available_sensors():
        reading[key] = full[key]          # missing sensors are simply absent from the JSON
    return reading


print("=== Weather generator started (with random sensor dropouts). A reading every 5 seconds. Ctrl+C to stop. ===")

while True:
    station = random.choice(STATIONS)
    spike = random.random() < 0.5  # 35% chance of a fire-risk spike, tuned for demo visibility
    reading = generate_reading(station, spike)

    payload = json.dumps(reading)
    fname = f"w_{uuid.uuid4().hex}.json"

    subprocess.run(
        ["docker", "exec", "-i", "bda-namenode", "bash", "-c",
         f"cat > /tmp/{fname} && hdfs dfs -put -f /tmp/{fname} /bda_project/incoming/weather/{fname}"],
        input=payload.encode(),
    )

    tag = "🔥 SPIKE" if spike else "normal"
    shown = "  ".join(f"{k}={reading[k]}" for k in SENSOR_KEYS if k in reading) or "NO SENSOR DATA"
    print(f"[{tag}] {reading['station_id']}  {shown}")
    time.sleep(5)