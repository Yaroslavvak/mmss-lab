"""Підсумок каналу даних за базою підписника: втрати, дублікати, затримка."""
import os
import sqlite3
import sys

DB = os.environ.get("DB", "data/telemetry.db")
COLS = ["boot", "rate", "sent", "received", "loss", "late", "dup",
        "lat_mean_ms", "lat_p95_ms", "lat_max_ms"]


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def summary(db, boot):
    """Показники одного запуску емулятора сумарно за всіма сенсорами."""
    sent = received = 0
    for n_sent, n_rx in db.execute(
            "SELECT MAX(seq) - MIN(seq) + 1, COUNT(*) FROM readings "
            "WHERE boot = ? GROUP BY dev", (boot,)):
        sent += n_sent
        received += n_rx
    t0, t1 = db.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM readings "
                        "WHERE boot = ?", (boot,)).fetchone()
    rate = sent / max((t1 - t0) / 1000, 0.001)
    late, dup = (one(db, "SELECT COUNT(*) FROM anomalies "
                     "WHERE boot = ? AND kind = ?", boot, kind)
                 for kind in ("late", "dup"))
    lat = sorted(r for (r,) in db.execute(
        "SELECT rx_ms - ts_ms FROM readings WHERE boot = ?", (boot,)))
    return [boot, round(rate, 1), sent, received,
            round(1 - received / sent, 4), late, dup,
            round(sum(lat) / len(lat), 1),
            lat[int(0.95 * (len(lat) - 1))], lat[-1]]


def main():
    db = sqlite3.connect(DB)
    rows = [summary(db, b) for (b,) in db.execute(
        "SELECT DISTINCT boot FROM readings ORDER BY boot").fetchall()]
    if "--csv" in sys.argv:
        print(",".join(COLS))
        for r in rows:
            print(",".join(map(str, r)))
        return
    table = [COLS] + [[str(v) for v in r] for r in rows]
    width = [max(len(r[i]) for r in table) for i in range(len(COLS))]
    for r in table:
        print("  ".join(v.rjust(w) for v, w in zip(r, width)))
    rejected = db.execute(
        "SELECT reason, COUNT(*) FROM rejected GROUP BY reason").fetchall()
    print("Відхилено:",
          ", ".join(f"{r} {n}" for r, n in rejected) or 0)


if __name__ == "__main__":
    main()