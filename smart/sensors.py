"""Емулятор сенсорів периметра: публікує телеметрію MQTT за схемою повідомлення."""
import json
import math
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

BROKER = os.environ.get("BROKER", "localhost")
HZ = float(os.environ.get("HZ", "2"))              # частота одного сенсора, 1/с (1-5 Гц)
DURATION = float(os.environ.get("DURATION", "0"))  # с; 0 — без обмеження

# Частки внесених збоїв для перевірки підписника
DROP = float(os.environ.get("DROP", "0"))          # пропущений показ
DUP = float(os.environ.get("DUP", "0"))            # дублікат
LATE = float(os.environ.get("LATE", "0"))          # позачерговий показ
BAD = float(os.environ.get("BAD", "0"))            # зіпсоване повідомлення

BOOT_FILE = Path(os.environ.get("BOOT_FILE", "data/boot.txt"))

# Об'єкт і вузол периметра — рівні теми
SITE, ROOM = "k1", "perim1"
# Сенсори предметної області: назва, величина, одиниця, шум (sigma), модель значення
SENSORS = [
    ("motion-1", "motion", "state", 0, lambda t: 1 if math.sin(t / 15) > 0.6 else 0),
    ("light-1",  "light",  "lx",    5, lambda t: 350 + 250 * math.sin(t / 120)),
    ("gate-1",   "gate",   "state", 0, lambda t: 1 if math.sin(t / 45) > 0.85 else 0),
]


def next_boot():
    """Номер запуску: зростає після кожного перезапуску емулятора."""
    boot = int(BOOT_FILE.read_text()) + 1 if BOOT_FILE.exists() else 1
    BOOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOOT_FILE.write_text(str(boot))
    return boot


def connect(name):
    """Окремий клієнт MQTT для кожного сенсора зі своїм заповітом (keepalive=3 с для FR-08)."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"{ROOM}-{name}")
    state = f"{SITE}/{ROOM}/{name}/state"
    client.will_set(state, "offline", qos=1, retain=True)
    client.connect_async(BROKER, 1883, keepalive=3)
    client.loop_start()
    while not client.is_connected():
        time.sleep(0.1)
    client.publish(state, "online", qos=1, retain=True)
    return client


def main():
    boot = next_boot()
    print(f"Підключення до {BROKER}...", flush=True)
    clients = [connect(s[0]) for s in SENSORS]
    seq = [0] * len(SENSORS)
    stats = dict(published=0, drop=0, dup=0, late=0, bad=0)
    held = None
    period = 1 / (HZ * len(SENSORS))
    start = next_t = time.monotonic()
    print(f"boot={boot}, HZ={HZ}, сенсорів: {len(SENSORS)}", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    i = 0
    try:
        while not DURATION or time.monotonic() - start < DURATION:
            k = i % len(SENSORS)
            name, qty, unit, noise, model = SENSORS[k]
            raw_val = model(time.time()) + (random.gauss(0, noise) if noise else 0)
            val = int(round(raw_val)) if noise == 0 else round(raw_val, 1)
            msg = {
                "dev": f"{ROOM}-{name}",
                "boot": boot,
                "seq": seq[k],
                "ts": datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds").replace("+00:00", "Z"),
                "qty": qty,
                "val": val,
                "unit": unit,
            }
            seq[k] += 1
            topic = f"{SITE}/{ROOM}/{name}/tele"
            body = json.dumps(msg, separators=(",", ":"))
            faults = i >= len(SENSORS)
            r = random.random()
            if faults and r < DROP:
                stats["drop"] += 1
            elif faults and r < DROP + LATE and held is None:
                held = (k, topic, body)
                stats["late"] += 1
            else:
                clients[k].publish(topic, body)
                stats["published"] += 1
            if faults and random.random() < DUP:
                clients[k].publish(topic, body)
                stats["dup"] += 1
            if held and held[0] == k:
                clients[k].publish(held[1], held[2])
                held = None
                stats["published"] += 1
            if faults and random.random() < BAD:
                clients[k].publish(topic, body[:len(body) // 2])
                stats["bad"] += 1
            i += 1
            next_t += period
            time.sleep(max(0.0, next_t - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        if held:
            clients[held[0]].publish(held[1], held[2])
            stats["published"] += 1
        for (name, *_), client in zip(SENSORS, clients):
            client.publish(f"{SITE}/{ROOM}/{name}/state", "offline",
                           qos=1, retain=True).wait_for_publish(2)
            client.disconnect()
        print(f"Підсумок: {stats}", flush=True)


if __name__ == "__main__":
    main()
