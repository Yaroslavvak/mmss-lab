"""Периферійний шлюз: буферизація на периферії (store-and-forward).
Отримує телеметрію від брокера периферії, спершу записує її в локальний
буфер SQLite і лише потім пересилає серверному брокеру з QoS 1. Запис
видаляється з буфера тільки після підтвердження PUBACK.
"""
import os
import queue
import sqlite3
import time

import paho.mqtt.client as mqtt

EDGE = os.environ.get("EDGE_BROKER", "edge-broker")
CLOUD = os.environ.get("CLOUD_BROKER", "cloud-broker")
DB = os.environ.get("DB", "data/outbox.db")
MAX_ROWS = int(os.environ.get("MAX_ROWS", "50000"))  # місткість буфера
# Смуга ланки периферія-сервер, кбіт/с (тема й тіло); 0 — без обмеження
UPLINK = 1000 * float(os.environ.get("UPLINK_KBPS", "0"))
BATCH = 100  # записів за один прохід надсилання
TOPIC = "k1/+/+/tele"

inbox = queue.Queue()  # отримане, але ще не записане в буфер


def main():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("CREATE TABLE IF NOT EXISTS outbox ("
               "id INTEGER PRIMARY KEY, topic TEXT, payload BLOB)")

    edge = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                       client_id="perim1-gw-edge")
    edge.on_connect = lambda c, *_: c.subscribe(TOPIC, qos=0)
    edge.on_message = lambda c, u, msg: inbox.put((msg.topic, msg.payload))

    cloud = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id="perim1-gw-cloud")
    cloud.max_queued_messages_set(BATCH)  # не накопичувати в пам'яті

    for client, host in ((edge, EDGE), (cloud, CLOUD)):
        client.reconnect_delay_set(1, 5)  # пробувати не рідше ніж за 5 с
        client.connect_async(host, 1883, keepalive=10)
        client.loop_start()

    dropped, idle, report = 0, False, time.monotonic()
    while True:
        # 1. Усе отримане — спершу в буфер на диску
        rows = []
        if idle:
            try:
                rows.append(inbox.get(timeout=0.5))  # чекати нового повідомлення, не опитувати
            except queue.Empty:
                pass
        while not inbox.empty():
            rows.append(inbox.get())
        if rows:
            with db:
                db.executemany("INSERT INTO outbox (topic, payload) "
                               "VALUES (?, ?)", rows)

        # 2. Буфер переповнено: найстаріші покази поступаються новим
        first, last = db.execute(
            "SELECT MIN(id), MAX(id) FROM outbox").fetchone()
        backlog = last - first + 1 if first is not None else 0
        if backlog > MAX_ROWS:
            with db:
                db.execute("DELETE FROM outbox WHERE id <= ?",
                           (last - MAX_ROWS,))
            dropped += backlog - MAX_ROWS
            backlog = MAX_ROWS

        # 3. Надіслати найстаріші записи; видалити лише підтверджені
        done, start = [], time.monotonic()
        if cloud.is_connected():
            batch = db.execute("SELECT id, topic, payload FROM outbox "
                               "ORDER BY id LIMIT ?", (BATCH,)).fetchall()
            sent = [(rid, cloud.publish(topic, payload, qos=1))
                    for rid, topic, payload in batch]
            for rid, info in sent:
                try:
                    info.wait_for_publish(timeout=2)
                except (ValueError, RuntimeError):  # немає зв'язку
                    break
                if not info.is_published():
                    break
                done.append(rid)
            if done:
                with db:
                    db.execute("DELETE FROM outbox WHERE id <= ?",
                               (done[-1],))
            if done and UPLINK:  # не швидше, ніж дозволяє смуга ланки
                size = sum(len(t) + len(p) for _, t, p in batch[:len(done)])
                time.sleep(max(0.0, start + 8 * size / UPLINK - time.monotonic()))

        idle = not done  # надсилати нічого або немає зв'язку
        if time.monotonic() - report >= 2:
            link = "так" if cloud.is_connected() else "ні"
            print(f"буфер={backlog} відкинуто={dropped} зв'язок={link}",
                  flush=True)
            report = time.monotonic()


if __name__ == "__main__":
    main()