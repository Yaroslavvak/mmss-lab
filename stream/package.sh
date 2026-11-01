# Драбина якостей і сегменти для адаптивного потокового передавання.
set -e

FORMAT=${1:-hls}
SRC=data/source.mp4
SEG=2
GOP=$((SEG*30))

# Три рівні якості: висота кадру та бітрейт (кбіт/с) — за результатами заняття 1
LADDER=(
    -map "[v1]" -b:v:0 2000k -maxrate:v:0 2200k -bufsize:v:0 4000k
    -map "[v2]" -b:v:1 900k  -maxrate:v:1 990k  -bufsize:v:1 1800k
    -map "[v3]" -b:v:2 500k  -maxrate:v:2 550k  -bufsize:v:2 1000k
)

SCALE="[0:v]split=3[a][b][c]; [a]scale=-2:720[v1];"
SCALE+="[b]scale=-2:480[v2]; [c]scale=-2:360[v3]"

CODEC=(-c:v libx264 -preset veryfast -pix_fmt yuv420p
       -g $GOP -keyint_min $GOP -sc_threshold 0 -an)

cd "$(dirname "$0")/.."
rm -rf "stream/$FORMAT" && mkdir -p "stream/$FORMAT"

if [ "$FORMAT" = hls ]; then
    ffmpeg -y -hide_banner -loglevel error -i $SRC -filter_complex "$SCALE" \
        "${LADDER[@]}" "${CODEC[@]}" \
        -f hls -hls_time $SEG -hls_playlist_type vod \
        -hls_segment_filename "stream/hls/v%v/seg_%03d.ts" \
        -master_pl_name master.m3u8 -var_stream_map "v:0 v:1 v:2" \
        "stream/hls/v%v/index.m3u8"
else
    ffmpeg -y -hide_banner -loglevel error -i $SRC -filter_complex "$SCALE" \
        "${LADDER[@]}" "${CODEC[@]}" \
        -f dash -seg_duration $SEG -use_template 1 -use_timeline 0 \
        -adaptation_sets "id=0,streams=v" "stream/dash/manifest.mpd"
fi

echo "Готово: stream/$FORMAT"