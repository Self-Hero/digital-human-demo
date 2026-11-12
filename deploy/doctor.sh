#!/usr/bin/env bash

set -u

AVATAR_ID="${1:-ma_renda_dynamic}"
AVATAR_UNIT="livetalking@${AVATAR_ID}.service"
if [[ "${EUID}" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo)
fi

section() {
  printf '\n== %s ==\n' "$1"
}

service_state() {
  local unit="$1"
  printf '%-36s %s\n' "${unit}" "$(systemctl is-active "${unit}" 2>/dev/null || true)"
}

http_check() {
  curl --silent --show-error --max-time 3 "$1" || true
  printf '\n'
}

wait_for_backend() {
  local attempt
  for attempt in {1..10}; do
    if curl --silent --max-time 1 \
      http://127.0.0.1:8001/api/v1/health >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
}

section "Services"
service_state nginx.service
service_state digital-human-backend.service
service_state "${AVATAR_UNIT}"

section "HTTP checks"
wait_for_backend
http_check http://127.0.0.1:8001/api/v1/health
http_check http://127.0.0.1:8001/api/v1/ready

section "GPU"
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu \
  --format=csv,noheader 2>/dev/null || echo "nvidia-smi unavailable"

section "Listening ports"
ss -lntup 2>/dev/null | grep -E ':(8001|8010|9000)\b' || \
  echo "No expected ports found"

section "Recent avatar metrics and errors"
"${SUDO[@]}" journalctl -u "${AVATAR_UNIT}" --since "10 minutes ago" -a -o cat --no-pager \
  2>/dev/null | grep -aE \
  'Creating session|Removing session|reclaiming session|actual avg final fps|Realtime GFPGAN batch|timed out|queue full|Traceback|ERROR' | tail -n 40 || true

section "Recent backend errors"
"${SUDO[@]}" journalctl -u digital-human-backend.service --since "10 minutes ago" \
  -a -o cat --no-pager 2>/dev/null | \
  grep -aE 'Traceback|ERROR|failed|exception' | tail -n 20 || true
