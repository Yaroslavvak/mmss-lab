"""Графік залежності затримки й втрат від навантаження.

Запуск з кореня репозиторію: python smart/plot.py
Вхід: results/load.csv; вихід: results/latency.png
"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, NullLocator  # noqa: E402

plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = ["DejaVu Serif", "Times New Roman", "serif"]

with open("results/load.csv", encoding="utf-8") as f:
    rows = sorted(csv.DictReader(f), key=lambda r: float(r["rate"]))

rate = [float(r["rate"]) for r in rows]
lat_mean = [float(r["lat_mean_ms"]) for r in rows]
lat_p95 = [float(r["lat_p95_ms"]) for r in rows]
losses = [float(r["loss"]) for r in rows]

navy = "#143d75"
crimson = "#8b1a1a"

fig, ax = plt.subplots(figsize=(8.5, 4.2))

ax.plot(
    rate, lat_mean,
    color=navy, linestyle="-", linewidth=1.4,
    marker="o", markersize=5, markerfacecolor=navy,
    label="середня",
)
ax.plot(
    rate, lat_p95,
    color=navy, linestyle="--", linewidth=1.4,
    marker="s", markersize=5, markerfacecolor="white",
    markeredgecolor=navy, markeredgewidth=1.2,
    label="95-й процентиль",
)

ax.axvline(950, color=crimson, linestyle="--", linewidth=1.0)
ax.text(935, 22000, "Θ ≈ 950", color=crimson, fontsize=9.5, ha="right", va="center")

for x, y, loss in zip(rate, lat_mean, losses):
    if loss > 0:
        label = f"ε = {loss * 100:.1f} %".replace(".", ",")
        ax.annotate(
            label,
            xy=(x, y),
            xytext=(0, -14),
            textcoords="offset points",
            ha="center",
            va="top",
            color=crimson,
            fontsize=9,
        )

ax.set_yscale("log")
ax.set_xlim(0, 1600)
ax.set_ylim(1, 35000)

fmt_thousands = FuncFormatter(lambda val, _: f"{int(val):,}".replace(",", " "))
ax.set_xticks([0, 200, 400, 600, 800, 1000, 1200, 1400, 1600])
ax.xaxis.set_major_formatter(fmt_thousands)
ax.set_yticks([1, 10, 100, 1000, 10000])
ax.yaxis.set_major_formatter(fmt_thousands)
ax.yaxis.set_minor_locator(NullLocator())

ax.tick_params(axis="both", labelsize=9, colors="#333333")
ax.set_xlabel("Навантаження λ, повідомлень/с", fontsize=10, labelpad=6)
ax.set_ylabel("Затримка доставки, мс", fontsize=10, labelpad=6)

ax.grid(axis="y", which="major", color="#d3dce6", linewidth=0.8)
ax.set_axisbelow(True)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.spines["left"].set_color("#333333")
ax.spines["bottom"].set_color("#333333")

ax.legend(loc="upper left", frameon=False, fontsize=9.5, handlelength=2.8)

fig.tight_layout()
fig.savefig("results/latency.png", dpi=150)
print("Графік: results/latency.png")