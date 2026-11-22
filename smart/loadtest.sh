#!/usr/bin/env bash
# Навантажувальне випробування: частота сенсорів зростає ступенями.
# Запуск з кореня репозиторію: bash smart/loadtest.sh
set -e
export COMPOSE_FILE=smart/docker-compose.yml
STEP=30                 # тривалість ступеня, с
export MAX_ROWS=10000   # менший буфер: переповниться за ступінь

docker compose down -v  # почати з чистого стану
docker compose build
docker compose up -d edge-broker gateway cloud-broker collector

for HZ in 10 100 200 250 300 350 400 450 500; do
    echo "$(date +%T) HZ=$HZ: λ=$((3*HZ)) повідомлень/с"
    HZ=$HZ DURATION=$STEP docker compose up -d sensors
    sleep $((STEP + 5))
    until docker compose logs --tail 1 gateway | grep -q "буфер=0 "; do
        sleep 2
    done
done

docker compose exec -T collector python stats.py --csv > results/load.csv
cat results/load.csv