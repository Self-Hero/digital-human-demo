#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

DATA_ROOT="${DATA_ROOT:-/data}"
CONDA_ROOT="${CONDA_ROOT:-${DATA_ROOT}/miniconda3}"
LIVETALKING_DIR="${LIVETALKING_DIR:-${DATA_ROOT}/LiveTalking}"
TORCH_HOME="${TORCH_HOME:-${DATA_ROOT}/cache/torch}"
LIVETALKING_ENV="livetalking"
APP_ENV="digitalhuman"
AVATAR_ID="ma_renda_dynamic"
AVATAR_SOURCE=""

usage() {
  cat <<'EOF'
Usage: bash deploy/start_avatar.sh [options]

Preprocesses an avatar when a source is supplied, configures the frontend,
and starts the matching LiveTalking systemd instance. It does not install or
download dependencies and models.

Options:
  --avatar-source PATH       Source video/image to preprocess (optional when prepared)
  --avatar-id ID             Avatar id (default: ma_renda_dynamic)
  -h, --help                 Show this help

Environment overrides:
  DATA_ROOT, CONDA_ROOT, LIVETALKING_DIR, TORCH_HOME
EOF
}

log() { printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

require_option_value() {
  local option="$1"
  local value="${2:-}"
  [[ -n "${value}" && "${value}" != --* ]] || die "${option} requires a value."
}

while (($#)); do
  case "$1" in
    --avatar-source) require_option_value "$1" "${2:-}"; AVATAR_SOURCE="$2"; shift 2 ;;
    --avatar-id) require_option_value "$1" "${2:-}"; AVATAR_ID="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$(uname -s)" == Linux ]] || die "This script must run on Linux."
[[ "${AVATAR_ID}" =~ ^[A-Za-z0-9._-]+$ ]] || \
  die "Avatar id may contain only letters, numbers, dot, underscore, and hyphen."

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo)
fi

CONDA_BIN="${CONDA_ROOT}/bin/conda"
AVATAR_DIR="${LIVETALKING_DIR}/data/avatars/${AVATAR_ID}"
FRONTEND_ENV="${PROJECT_DIR}/frontend/.env.production"

[[ -x "${CONDA_BIN}" ]] || die "Conda is missing at ${CONDA_ROOT}; run bootstrap_server.sh first."
[[ -d "${LIVETALKING_DIR}/.git" ]] || die "LiveTalking is missing at ${LIVETALKING_DIR}."
[[ -d "${CONDA_ROOT}/envs/${LIVETALKING_ENV}" ]] || die "LiveTalking Conda environment is missing."
[[ -d "${CONDA_ROOT}/envs/${APP_ENV}" ]] || die "Application Conda environment is missing."
[[ -s "${LIVETALKING_DIR}/models/musetalkV15/unet.pth" ]] || die "MuseTalk model is missing; run bootstrap_server.sh first."
[[ -f /etc/systemd/system/livetalking@.service ]] || die "LiveTalking systemd template is missing; run bootstrap_server.sh first."
command -v nvidia-smi >/dev/null || die "nvidia-smi is not available."
command -v curl >/dev/null || die "curl is not available; run bootstrap_server.sh first."
nvidia-smi >/dev/null || die "NVIDIA GPU or driver is not available."

conda_run() {
  local env_name="$1"
  shift
  "${CONDA_BIN}" run --no-capture-output -n "${env_name}" "$@"
}

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  if grep -q "^${key}=" "${file}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${file}"
  fi
}

if [[ -n "${AVATAR_SOURCE}" ]]; then
  [[ -s "${AVATAR_SOURCE}" ]] || die "Avatar source is missing or empty: ${AVATAR_SOURCE}"
  log "Preparing avatar ${AVATAR_ID} from ${AVATAR_SOURCE}"
  AVATAR_ROOT="${LIVETALKING_DIR}/data/avatars"
  mkdir -p "${AVATAR_ROOT}"
  BUILD_ROOT="$(mktemp -d "${AVATAR_ROOT}/.build-${AVATAR_ID}-XXXXXX")"
  cleanup_build() {
    [[ -d "${BUILD_ROOT:-}" ]] && rm -rf -- "${BUILD_ROOT}"
  }
  trap cleanup_build EXIT
  (
    cd "${LIVETALKING_DIR}"
    TORCH_HOME="${TORCH_HOME}" conda_run "${LIVETALKING_ENV}" \
      python -m avatars.musetalk.genavatar \
      --file "${AVATAR_SOURCE}" \
      --avatar_id "${AVATAR_ID}" \
      --save_path "${BUILD_ROOT}" \
      --version v15 --gpu_id 0 --bbox_shift -2 --extra_margin 0 \
      --parsing_mode jaw
  )
  [[ -s "${BUILD_ROOT}/${AVATAR_ID}/latents.pt" ]] || \
    die "Avatar preprocessing completed without producing latents.pt."
  if [[ -e "${AVATAR_DIR}" ]]; then
    AVATAR_BACKUP="${AVATAR_DIR}.backup-$(date '+%Y%m%d-%H%M%S')"
    mv "${AVATAR_DIR}" "${AVATAR_BACKUP}"
    echo "Previous avatar preserved at ${AVATAR_BACKUP}"
  fi
  mv "${BUILD_ROOT}/${AVATAR_ID}" "${AVATAR_DIR}"
  rmdir "${BUILD_ROOT}"
  BUILD_ROOT=""
  trap - EXIT
fi

[[ -s "${AVATAR_DIR}/latents.pt" ]] || \
  die "Prepared avatar is missing at ${AVATAR_DIR}. Supply --avatar-source to create it."

log "Configuring frontend for avatar ${AVATAR_ID}"
if [[ ! -f "${FRONTEND_ENV}" ]]; then
  cp "${PROJECT_DIR}/frontend/.env.example" "${FRONTEND_ENV}"
fi
set_env_value "${FRONTEND_ENV}" VITE_AVATAR_ID "${AVATAR_ID}"
(
  cd "${PROJECT_DIR}/frontend"
  conda_run "${APP_ENV}" npm run build
)

log "Starting LiveTalking avatar ${AVATAR_ID}"
while read -r active_unit; do
  [[ -n "${active_unit}" ]] || continue
  if [[ "${active_unit}" != "livetalking@${AVATAR_ID}.service" ]]; then
    echo "Stopping ${active_unit} because LiveTalking instances share port 8010."
    "${SUDO[@]}" systemctl stop "${active_unit}"
  fi
done < <(systemctl list-units --type=service --state=active \
  'livetalking@*.service' --no-legend --plain | awk '{print $1}')

"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable "livetalking@${AVATAR_ID}.service"
"${SUDO[@]}" systemctl restart "livetalking@${AVATAR_ID}.service"

echo "Waiting for LiveTalking to load the model and listen on port 8010..."
AVATAR_READY=0
for _ in {1..120}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8010/ >/dev/null; then
    AVATAR_READY=1
    break
  fi
  sleep 2
done
if ((AVATAR_READY == 0)); then
  "${SUDO[@]}" systemctl status "livetalking@${AVATAR_ID}.service" --no-pager || true
  die "LiveTalking did not become ready on port 8010. Inspect logs with journalctl."
fi

cat <<EOF

Avatar ${AVATAR_ID} is running.
Public page: open the address printed by bootstrap_server.sh
Status: sudo systemctl status livetalking@${AVATAR_ID}
Logs:   sudo journalctl -u livetalking@${AVATAR_ID} -f
EOF
