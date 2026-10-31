"""Конвеєр «декодування — перетворення — кодування» і вимірювання якості."""
import csv
import os
import re
import subprocess
import time
from pathlib import Path
import cv2

SRC = Path("data/source.mp4")
REF = Path("data/reference.mkv")
OUT = Path("data/out")
CSV_FILE = Path("results/encoding.csv")

WIDTH, HEIGHT, FPS = 1280, 720, 15
SECONDS = 20 
DEPTH = 24   
os.environ.setdefault("SVT_LOG", "1")

X1, Y1, X2, Y2 = 670, 460, 850, 700

VARIANTS = [
    ("h264_1000k", "h264", "1000k"),
    ("h264_2000k", "h264", "2000k"),
    ("av1_1000k", "av1", "1000k"),
    ("av1_2000k", "av1", "2000k"),
]

def process(frame, t):
    """Перетворення одного кадру (Маскування приватних зон для відеоспостереження)."""
    roi = frame[Y1:Y2, X1:X2]
    frame[Y1:Y2, X1:X2] = cv2.GaussianBlur(roi, (51, 51), 30)

    cv2.putText(
        frame,
        f"{t:6.2f} s",
        (20, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame

def transform():
    """Декодування (OpenCV) — перетворення — еталон без втрат (FFmpeg)."""
    cap = cv2.VideoCapture(str(SRC))
    if not cap.isOpened():
        raise SystemExit(f"Не вдалося відкрити {SRC}")

    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if src_fps < FPS:
        raise SystemExit(f"FPS = {FPS} більша за частоту джерела ({src_fps})")

    step = src_fps / FPS
    writer = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(REF),
        ],
        stdin=subprocess.PIPE,
    )
    index, frames, next_index = 0, 0, 0.0
    while frames < SECONDS * FPS:
        ok, frame = cap.read()
        if not ok:
            break
        index += 1
        if index < next_index:
            continue
        next_index += step
        frame = cv2.resize(frame, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
        writer.stdin.write(process(frame, frames / FPS).tobytes())
        frames += 1

    cap.release()
    writer.stdin.close()
    writer.wait()
    return frames

def av1_encoder():
    """Обирає наявний кодер AV1: SVT-AV1, якщо немає — libaom."""
    names = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
    ).stdout

    if "libsvtav1" in names:
        return ["-c:v", "libsvtav1", "-preset", "8"]
    if "libaom-av1" in names:
        return ["-c:v", "libaom-av1", "-cpu-used", "6", "-row-mt", "1"]
    raise SystemExit("У збірці FFmpeg немає кодера AV1")

def encode(codec, bitrate, out):
    """Кодування еталона одним варіантом; повертає час кодування, с."""
    args = (
        ["-c:v", "libx264", "-preset", "medium"]
        if codec == "h264"
        else av1_encoder()
    )
    start = time.perf_counter()
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(REF), *args,
            "-b:v", bitrate, "-an", str(out),
        ],
        check=True,
    )
    return time.perf_counter() - start

def quality(out):
    """PSNR (дБ) і SSIM закодованого файлу відносно еталона засобами FFmpeg."""
    result = {}
    patterns = {
        "psnr": r"(?:average|PSNR\s*y):([0-9\.]+)",
        "ssim": r"(?:All|SSIM\s*Y):([0-9\.]+)"
    }
    
    for name, pattern in (("psnr", patterns["psnr"]), ("ssim", patterns["ssim"])):
        cmd = [
            "ffmpeg", "-hide_banner",
            "-i", str(out), "-i", str(REF),
            "-lavfi", name, "-f", "null", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        log = (proc.stderr or "") + "\n" + (proc.stdout or "")
        
        matches = re.findall(pattern, log, re.IGNORECASE)
        if not matches:
            print(f"\n[ПОМИЛКА FFmpeg при розрахунку {name.upper()}]:")
            print(log[-1000:])
            raise RuntimeError(f"Не вдалося витягти {name} для {out.name}")
            
        result[name] = float(matches[-1])   
    return result

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)

    frames = transform()
    duration = frames / FPS
    raw_kbps = WIDTH * HEIGHT * FPS * DEPTH / 1000

    print(
        f"Еталон: {frames} кадрів, {duration:.1f} с, {WIDTH}x{HEIGHT}, {FPS} кадр/с"
    )
    rows = []
    for name, codec, bitrate in VARIANTS:
        out = OUT / f"{name}.mp4"
        seconds = encode(codec, bitrate, out)
        size = out.stat().st_size
        kbps = size * 8 / duration / 1000
        q = quality(out)
        rows.append(
            {
                "variant": name,
                "codec": codec,
                "target_kbps": int(bitrate[:-1]),
                "size_kb": round(size / 1024),
                "actual_kbps": round(kbps),
                "compression": round(raw_kbps / kbps),
                "encode_s": round(seconds, 1),
                "psnr_db": round(q["psnr"], 2),
                "ssim": round(q["ssim"], 4),
            }
        )
        print(rows[-1])

    with CSV_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Результати: {CSV_FILE}")

if __name__ == "__main__":
    main()