import time, random, json, subprocess, uuid

STATIONS = [
    {"id": "ST001", "lat": 34.05, "lon": -118.24, "name": "Los Angeles"},
    {"id": "ST002", "lat": 37.77, "lon": -122.42, "name": "San Francisco"},
    {"id": "ST003", "lat": 36.16, "lon": -115.15, "name": "Las Vegas"},
]

FIRE_PHRASES = ["smoke everywhere near", "fire spreading fast near", "evacuation warning near", "flames visible near"]
NOISE_PHRASES = ["nice sunset near", "traffic jam near", "great food near", "concert tonight near"]

GEOTAG_PROBABILITY = 0.70   # 30% of posts arrive without coordinates, like real social media


def generate_post(genuine):
    station = random.choice(STATIONS)
    phrase = random.choice(FIRE_PHRASES) if genuine else random.choice(NOISE_PHRASES)
    post = {
        "post_id": uuid.uuid4().hex,
        "text": f"{phrase} {station['name']}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "is_fire_related": genuine,
    }
    if random.random() < GEOTAG_PROBABILITY:
        post["lat"] = round(station["lat"] + random.uniform(-0.05, 0.05), 4)
        post["lon"] = round(station["lon"] + random.uniform(-0.05, 0.05), 4)
    return post


print("=== Social media generator started (some posts have no geotag). A post every 3 seconds. Ctrl+C to stop. ===")

while True:
    genuine = random.random() < 0.5  # most posts are noise, some mention fire
    post = generate_post(genuine)

    payload = json.dumps(post)
    fname = f"s_{uuid.uuid4().hex}.json"

    subprocess.run(
        ["docker", "exec", "-i", "bda-namenode", "bash", "-c",
         f"cat > /tmp/{fname} && hdfs dfs -put -f /tmp/{fname} /bda_project/incoming/social/{fname}"],
        input=payload.encode(),
    )

    tag = "🔥 FIRE POST" if genuine else "noise"
    geo = "geotagged" if "lat" in post else "NO GEOTAG"
    print(f"[{tag}] {post['text']}  ({geo})")
    time.sleep(3)