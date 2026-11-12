#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DATA_ROOT="${DATA_ROOT:-/data}"

PUBLIC_IP=""
PUBLIC_PORT="9000"
PUBLIC_PATH=""
AVATAR_SOURCE=""
AVATAR_ID="ma_renda_dynamic"
ENABLE_SILENCE_INFERENCE=0
ENABLE_GFPGAN=0

usage() {
  cat <<'EOF'
Usage: bash deploy/install_full_stack.sh OPTIONS

Installs the application, LiveTalking, MuseTalk and the optional realtime
GFPGAN runtime, plus Nginx and systemd services. If an avatar source is
supplied, it also preprocesses that avatar and starts its LiveTalking instance.

LivePortrait, SoulX-FlashHead and CodeFormer are intentionally excluded from
the default real-time stack. CodeFormer has a separate explicit installer.

Options:
  --public-ip IP          Public IPv4 used by the frontend (required)
  --public-port PORT      Nginx HTTP port (default: 9000)
  --public-path PATH      Public URL suffix, for example fengyucai
  --avatar-source PATH    Source video/image to preprocess
  --avatar-id ID          Avatar id (default: ma_renda_dynamic)
  --enable-gfpgan         Enable the optimized RTX 4090 realtime profile
  --enable-silence-inference
                          Enable optional zero-audio MuseTalk inference
  -h, --help              Show this help

Default mirrors:
  GitHub: https://ghfast.top/
  Conda:  Tsinghua conda-forge
  PyPI:   Tsinghua PyPI
  Models: https://hf-mirror.com
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }
require_value() {
  [[ -n "${2:-}" && "${2:-}" != --* ]] || die "$1 requires a value"
}

while (($#)); do
  case "$1" in
    --public-ip) require_value "$1" "${2:-}"; PUBLIC_IP="$2"; shift 2 ;;
    --public-port) require_value "$1" "${2:-}"; PUBLIC_PORT="$2"; shift 2 ;;
    --public-path) require_value "$1" "${2:-}"; PUBLIC_PATH="$2"; shift 2 ;;
    --avatar-source) require_value "$1" "${2:-}"; AVATAR_SOURCE="$2"; shift 2 ;;
    --avatar-id) require_value "$1" "${2:-}"; AVATAR_ID="$2"; shift 2 ;;
    --enable-gfpgan) ENABLE_GFPGAN=1; shift ;;
    --enable-silence-inference) ENABLE_SILENCE_INFERENCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "${PUBLIC_IP}" ]] || die "--public-ip is required"
[[ "${PUBLIC_PORT}" =~ ^[0-9]+$ ]] || die "--public-port must be numeric"
((PUBLIC_PORT >= 1 && PUBLIC_PORT <= 65535)) || die "Invalid public port"
PUBLIC_PATH="${PUBLIC_PATH#/}"
PUBLIC_PATH="${PUBLIC_PATH%/}"
[[ -z "${PUBLIC_PATH}" || "${PUBLIC_PATH}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || \
  die "Invalid public path; use lowercase letters, numbers, and hyphens"
[[ "${AVATAR_ID}" =~ ^[A-Za-z0-9._-]+$ ]] || die "Invalid avatar id"
if [[ -n "${AVATAR_SOURCE}" ]]; then
  [[ -s "${AVATAR_SOURCE}" ]] || die "Avatar source is missing: ${AVATAR_SOURCE}"
fi
[[ -d "${DATA_ROOT}" ]] || die "Data root is missing: ${DATA_ROOT}"
available_kb="$(df -Pk "${DATA_ROOT}" | awk 'NR == 2 {print $4}')"
((available_kb >= 30 * 1024 * 1024)) || \
  die "Full-stack installation requires at least 30 GiB free under ${DATA_ROOT}"

export GITHUB_PROXY_PREFIX="${GITHUB_PROXY_PREFIX:-https://ghfast.top/}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export CONDA_CHANNEL="${CONDA_CHANNEL:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge}"

bootstrap_args=(
  --public-ip "${PUBLIC_IP}"
  --public-port "${PUBLIC_PORT}"
)
if [[ -n "${PUBLIC_PATH}" ]]; then
  bootstrap_args+=(--public-path "${PUBLIC_PATH}")
fi
if ((ENABLE_SILENCE_INFERENCE)); then
  bootstrap_args+=(--enable-silence-inference)
fi
if ((ENABLE_GFPGAN)); then
  bootstrap_args+=(--enable-gfpgan)
fi

echo "[1/3] Installing the digital-human application, LiveTalking and MuseTalk"
bash "${PROJECT_DIR}/deploy/bootstrap_server.sh" "${bootstrap_args[@]}"

if ((ENABLE_GFPGAN)); then
  echo "[2/3] Installing and enabling the realtime GFPGAN RTX 4090 profile"
else
  echo "[2/3] Installing the optional realtime GFPGAN runtime (disabled by default)"
fi
bash "${PROJECT_DIR}/deploy/install_gfpgan.sh"

if [[ -n "${AVATAR_SOURCE}" ]]; then
  echo "[3/3] Preparing and starting avatar ${AVATAR_ID}"
  bash "${PROJECT_DIR}/deploy/start_avatar.sh" \
    --avatar-source "${AVATAR_SOURCE}" --avatar-id "${AVATAR_ID}"
else
  echo "[3/3] Avatar preparation skipped because --avatar-source was not supplied"
fi

cat <<EOF

Full-stack installation completed.
EOF
if ((ENABLE_GFPGAN)); then
  echo "Realtime GFPGAN: enabled (MuseTalk batch 8, GFPGAN batch 2, interval 2, mouth protected, wait 500ms)"
else
  echo "Realtime GFPGAN: disabled (MuseTalk batch 4)"
fi
if [[ "${PUBLIC_PORT}" == 80 ]]; then
  public_origin="http://${PUBLIC_IP}"
else
  public_origin="http://${PUBLIC_IP}:${PUBLIC_PORT}"
fi
echo "Public page: ${public_origin}${PUBLIC_PATH:+/${PUBLIC_PATH}}"
if [[ -z "${AVATAR_SOURCE}" ]]; then
  cat <<EOF
Prepare and start an avatar later with:
  bash deploy/start_avatar.sh --avatar-source /data/source/avatar.mp4 --avatar-id ${AVATAR_ID}
EOF
fi
