"""Підписник: перевіряє формат, виявляє пропуски й позачергові показники,
зберігає дані в SQLite.
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER = os.environ.get("BROKER", "localhost")
DB = os.environ.get("DB", "data/telemetry.db")
TOPIC = "k1/+/+/tele"  # телеметрія всіх пристроїв об'єкта k1

# Схема повідомлення: поле -> очікуваний тип
FIELDS = {
    "dev": str, "boot": int, "seq": int, "ts": str,
    "qty": str, "val": (int, float), "unit": str,
}
# Величина -> (одиниця, мінімум, максимум) з даташитів сенсорів периметра
QTY = {
    "motion": ("state", 0, 1),
    "light":  ("lx", 0, 100000),
    "gate":   ("state", 0, 1),
}
FUTURE_MS = 5000  # допуск розбіжності годинників, мс

SQL = """
CREATE TABLE IF NOT EXISTS readings (
    dev TEXT, boot INTEGER, seq INTEGER, ts_ms INTEGER, qty TEXT,
    val REAL, unit TEXT, rx_ms INTEGER, PRIMARY KEY (dev, boot, seq));
CREATE TABLE IF NOT EXISTS anomalies (
    rx_ms INTEGER, dev TEXT, boot INTEGER, seq INTEGER, kind TEXT, n INTEGER);
CREATE TABLE IF NOT EXISTS rejected (
    rx_ms INTEGER, topic TEXT, payload BLOB, reason TEXT);
"""


def now_ms():
    return int(time.time() * 1000)


def validate(topic, payload):
    """Повертає показ (dict) або піднімає ValueError з причиною."""
    try:
        m = json.loads(payload)
    except ValueError:
        raise ValueError("не JSON")
    if not isinstance(m, dict):
        raise ValueError("не об'єкт JSON")
    for name, kind in FIELDS.items():
        if name not in m:
            raise ValueError(f"немає поля {name}")
        if not isinstance(m[name], kind) or isinstance(m[name], bool):
            raise ValueError(f"тип поля {name}")
    try:
        _, room, sensor, _ = topic.split("/")
    except ValueError:
        raise ValueError("формат теми")
    if m["dev"] != f"{room}-{sensor}":
        raise ValueError("dev не відповідає темі")
    if m["qty"] not in QTY:
        raise ValueError("невідома величина")
    unit, low, high = QTY[m["qty"]]
    if m["unit"] != unit:
        raise ValueError("одиниця")
    if not low <= m["val"] <= high:
        raise ValueError("поза діапазоном")
    if m["boot"] < 1 or m["seq"] < 0:
        raise ValueError("boot або seq")
    try:
        ts = datetime.strptime(m["ts"], "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise ValueError("формат ts")
    m["ts_ms"] = int(ts.replace(tzinfo=timezone.utc).timestamp() * 1000)
    if m["ts_ms"] > now_ms() + FUTURE_MS:
        raise ValueError("мітка часу з майбутнього")
    return m


def main():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(SQL)
    last = {(d, b): s for d, b, s in db.execute(
        "SELECT dev, boot, MAX(seq) FROM readings GROUP BY dev, boot")}

    def on_connect(client, userdata, flags, reason, props):
        client.subscribe(TOPIC, qos=1)
        print(f"Підписано на {TOPIC}: {reason}", flush=True)

    def on_message(client, userdata, msg):
        rx = now_ms()
        try:
            m = validate(msg.topic, msg.payload)
        except ValueError as e:
            with db:
                db.execute("INSERT INTO rejected VALUES (?, ?, ?, ?)",
                           (rx, msg.topic, msg.payload, str(e)))
            print(f"Відхилено ({e}): {msg.payload[:60]!r}", flush=True)
            return
        key, seq = (m["dev"], m["boot"]), m["seq"]
        with db:
            cur = db.execute(
                "INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?,?,?)",
                (m["dev"], m["boot"], seq, m["ts_ms"], m["qty"], m["val"],
                 m["unit"], rx))
            if cur.rowcount == 0:
                kind, n = "dup", 1
            elif key not in last:
                kind, n = None, 0
            else:
                n = seq - last[key] - 1
                kind = "gap" if n > 0 else "late" if n < 0 else None
            if kind:
                db.execute("INSERT INTO anomalies VALUES (?, ?, ?, ?, ?, ?)",
                           (rx, m["dev"], m["boot"], seq, kind, n))
            if kind != "dup":
                last[key] = max(seq, last.get(key, seq))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="collector")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(BROKER, 1883, keepalive=30)
    print(f"Підключення до {BROKER}, база {DB}", flush=True)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()