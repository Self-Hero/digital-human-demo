#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

DATA_ROOT="${DATA_ROOT:-/data}"
CONDA_ROOT="${CONDA_ROOT:-${DATA_ROOT}/miniconda3}"
LIVETALKING_DIR="${LIVETALKING_DIR:-${DATA_ROOT}/LiveTalking}"
LIVETALKING_REPO_URL="${LIVETALKING_REPO_URL:-https://github.com/lipku/LiveTalking.git}"
LIVETALKING_REF="${LIVETALKING_REF:-c7269433a2b6ecebcd9342445d2ecc882c98b0da}"
GITHUB_PROXY_PREFIX="${GITHUB_PROXY_PREFIX:-https://ghfast.top/}"
PUBLIC_IP="${PUBLIC_IP:-36.103.177.214}"
PUBLIC_PORT="${PUBLIC_PORT:-9000}"
STUN_URL="${STUN_URL:-stun:stun.freeswitch.org:3478}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
TORCH_HOME="${TORCH_HOME:-${DATA_ROOT}/cache/torch}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
CONDA_CHANNEL="${CONDA_CHANNEL:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge}"
MINICONDA_INSTALLER_URL="${MINICONDA_INSTALLER_URL:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh}"

LIVETALKING_ENV="livetalking"
APP_ENV="digitalhuman"
DEFAULT_AVATAR_ID="ma_renda_dynamic"
SKIP_APT=0
SKIP_MODELS=0
SKIP_SERVICES=0
VERIFY_ONLY=0
ENABLE_SILENCE_INFERENCE=0

usage() {
  cat <<'EOF'
Usage: bash deploy/bootstrap_server.sh [options]

Installs the application, LiveTalking, MuseTalk 1.5 weights, systemd units,
and an Nginx public entrypoint on Ubuntu 22.04.

Options:
  --public-ip IP             Public IPv4 used in CORS (default: 36.103.177.214)
  --public-port PORT         Nginx public HTTP port (default: 9000)
  --enable-silence-inference Apply the optional zero-audio MuseTalk patch
  --skip-apt                 Do not install Ubuntu packages
  --skip-models              Do not download model weights
  --skip-services            Do not install/start systemd and Nginx
  --verify-only              Only run deployment checks
  -h, --help                 Show this help

Environment overrides:
  DATA_ROOT, CONDA_ROOT, LIVETALKING_DIR, LIVETALKING_REPO_URL,
  LIVETALKING_REF, GITHUB_PROXY_PREFIX, HF_ENDPOINT, TORCH_HOME,
  PIP_INDEX_URL, PYTORCH_INDEX_URL, NPM_REGISTRY, CONDA_CHANNEL,
  MINICONDA_INSTALLER_URL, STUN_URL, PUBLIC_PORT
EOF
}

log() { printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }
warn() { echo "WARNING: $*" >&2; }

github_proxy_url() {
  local url="$1"
  if [[ -n "${GITHUB_PROXY_PREFIX}" && "${url}" == https://github.com/* ]]; then
    printf '%s%s\n' "${GITHUB_PROXY_PREFIX%/}/" "${url}"
  else
    printf '%s\n' "${url}"
  fi
}

preserve_failed_clone() {
  local attempt="$1"
  if [[ -e "${LIVETALKING_DIR}" ]]; then
    local failed_dir="${LIVETALKING_DIR}.clone-failed-$(date '+%Y%m%d-%H%M%S')-${attempt}"
    warn "Preserving the failed clone at ${failed_dir}"
    mv "${LIVETALKING_DIR}" "${failed_dir}"
  fi
}

clone_livetalking() {
  local proxy_url attempt
  if git -c http.version=HTTP/1.1 clone \
    "${LIVETALKING_REPO_URL}" "${LIVETALKING_DIR}"; then
    return 0
  fi

  preserve_failed_clone direct
  proxy_url="$(github_proxy_url "${LIVETALKING_REPO_URL}")"
  [[ "${proxy_url}" != "${LIVETALKING_REPO_URL}" ]] || return 1
  warn "Direct GitHub clone failed; falling back to ${proxy_url}"

  for attempt in 1 2 3; do
    if git -c http.version=HTTP/1.1 clone \
      "${proxy_url}" "${LIVETALKING_DIR}"; then
      return 0
    fi
    preserve_failed_clone "proxy-${attempt}"
    ((attempt < 3)) && sleep $((attempt * 5))
  done
  return 1
}

fetch_livetalking_ref() {
  local proxy_url attempt
  if git -c http.version=HTTP/1.1 -C "${LIVETALKING_DIR}" \
    fetch origin "${LIVETALKING_REF}"; then
    return 0
  fi

  proxy_url="$(github_proxy_url "${LIVETALKING_REPO_URL}")"
  [[ "${proxy_url}" != "${LIVETALKING_REPO_URL}" ]] || return 1
  warn "Direct GitHub fetch failed; falling back to ${proxy_url}"
  for attempt in 1 2 3; do
    if git -c http.version=HTTP/1.1 -C "${LIVETALKING_DIR}" \
      fetch "${proxy_url}" "${LIVETALKING_REF}"; then
      return 0
    fi
    ((attempt < 3)) && sleep $((attempt * 5))
  done
  return 1
}

require_option_value() {
  local option="$1"
  local value="${2:-}"
  [[ -n "${value}" && "${value}" != --* ]] || die "${option} requires a value."
}

while (($#)); do
  case "$1" in
    --public-ip) require_option_value "$1" "${2:-}"; PUBLIC_IP="$2"; shift 2 ;;
    --public-port) require_option_value "$1" "${2:-}"; PUBLIC_PORT="$2"; shift 2 ;;
    --enable-silence-inference) ENABLE_SILENCE_INFERENCE=1; shift ;;
    --skip-apt) SKIP_APT=1; shift ;;
    --skip-models) SKIP_MODELS=1; shift ;;
    --skip-services) SKIP_SERVICES=1; shift ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "${PUBLIC_PORT}" =~ ^[0-9]+$ ]] || die "Public port must be numeric."
((PUBLIC_PORT >= 1 && PUBLIC_PORT <= 65535)) || \
  die "Public port must be between 1 and 65535."
if [[ "${PUBLIC_PORT}" == 80 ]]; then
  PUBLIC_ORIGIN="http://${PUBLIC_IP}"
else
  PUBLIC_ORIGIN="http://${PUBLIC_IP}:${PUBLIC_PORT}"
fi

if [[ "${EUID}" -eq 0 ]]; then
  DEPLOY_USER="${SUDO_USER:-root}"
  SUDO=()
else
  DEPLOY_USER="${SUDO_USER:-${USER}}"
  SUDO=(sudo)
fi
DEPLOY_GROUP="$(id -gn "${DEPLOY_USER}")"

CONDA_BIN="${CONDA_ROOT}/bin/conda"
LIVETALKING_PY="${CONDA_ROOT}/envs/${LIVETALKING_ENV}/bin/python"
APP_PY="${CONDA_ROOT}/envs/${APP_ENV}/bin/python"
BACKEND_PY="${PROJECT_DIR}/backend/.venv/bin/python"
BACKEND_UVICORN="${PROJECT_DIR}/backend/.venv/bin/uvicorn"

conda_run() {
  local env_name="$1"
  shift
  "${CONDA_BIN}" run --no-capture-output -n "${env_name}" "$@"
}

require_file() {
  [[ -s "$1" ]] || die "Required file is missing or empty: $1"
}

verify_sha256() {
  local expected="$1"
  local file="$2"
  require_file "${file}"
  echo "${expected}  ${file}" | sha256sum -c -
}

wait_for_url() {
  local url="$1"
  local attempts="${2:-30}"
  local delay="${3:-2}"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  if grep -qE "^${key}=" "${file}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${file}"
  fi
}

check_platform() {
  [[ "$(uname -s)" == "Linux" ]] || die "This script only supports Linux."
  [[ -d "${PROJECT_DIR}/backend" && -d "${PROJECT_DIR}/frontend" ]] || \
    die "Run this script from the digital-human-demo repository."
  command -v nvidia-smi >/dev/null || die "nvidia-smi is missing; install the NVIDIA driver first."
  nvidia-smi >/dev/null || die "The NVIDIA driver is not working."
  if ((VERIFY_ONLY)); then
    [[ -d "${DATA_ROOT}" ]] || die "${DATA_ROOT} does not exist."
  else
    "${SUDO[@]}" mkdir -p "${DATA_ROOT}" || die "Cannot create ${DATA_ROOT}."
    if [[ ! -w "${DATA_ROOT}" ]]; then
      "${SUDO[@]}" chown "${DEPLOY_USER}:${DEPLOY_GROUP}" "${DATA_ROOT}"
    fi
    [[ -w "${DATA_ROOT}" ]] || die "${DATA_ROOT} is not writable by ${DEPLOY_USER}."

    local available_kb
    available_kb="$(df -Pk "${DATA_ROOT}" | awk 'NR==2 {print $4}')"
    if ((available_kb < 30 * 1024 * 1024)); then
      die "At least 30 GiB free space is required under ${DATA_ROOT}."
    fi
  fi
}

verify_deployment() {
  log "Verifying deployment"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
  require_file "${LIVETALKING_DIR}/models/musetalkV15/unet.pth"
  require_file "${LIVETALKING_DIR}/models/musetalkV15/musetalk.json"
  require_file "${LIVETALKING_DIR}/models/sd-vae/diffusion_pytorch_model.bin"
  require_file "${LIVETALKING_DIR}/models/whisper/pytorch_model.bin"
  require_file "${LIVETALKING_DIR}/models/face-parse-bisent/79999_iter.pth"
  require_file "${LIVETALKING_DIR}/models/face-parse-bisent/resnet18-5c106cde.pth"
  require_file "${TORCH_HOME}/hub/checkpoints/s3fd-619a316812.pth"
  verify_sha256 \
    7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007 \
    "${LIVETALKING_DIR}/models/musetalkV15/unet.pth"
  verify_sha256 \
    468e13ca13a9b43cc0881a9f99083a430e9c0a38abd935431d1c28ee94b26567 \
    "${LIVETALKING_DIR}/models/face-parse-bisent/79999_iter.pth"
  verify_sha256 \
    5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8 \
    "${LIVETALKING_DIR}/models/face-parse-bisent/resnet18-5c106cde.pth"
  verify_sha256 \
    619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543 \
    "${TORCH_HOME}/hub/checkpoints/s3fd-619a316812.pth"
  [[ "$(git -C "${LIVETALKING_DIR}" rev-parse HEAD)" == "${LIVETALKING_REF}" ]] || \
    die "LiveTalking is not at the pinned revision ${LIVETALKING_REF}."
  [[ -x "${LIVETALKING_PY}" ]] || die "LiveTalking Conda environment is missing."
  [[ -x "${BACKEND_UVICORN}" ]] || die "Backend virtual environment is missing."
  require_file "${LIVETALKING_DIR}/server/pcm_stream.py"

  (
    cd "${LIVETALKING_DIR}"
    conda_run "${LIVETALKING_ENV}" python -c \
      "import torch, cv2, aiortc, diffusers, transformers, soxr; import face_recognition_models, face_recognition; import avatars.musetalk_avatar; import avatars.musetalk.genavatar; import server.pcm_stream; assert torch.__version__.startswith('2.9.1+cu128'), torch.__version__; assert torch.cuda.is_available(); print('LiveTalking imports OK; torch', torch.__version__, 'cuda', torch.version.cuda, 'gpu', torch.cuda.get_device_name(0))"
  )
  "${BACKEND_PY}" -c "import fastapi, httpx, websockets; print('backend imports OK')"
  conda_run "${APP_ENV}" node --version
  command -v nginx >/dev/null && "${SUDO[@]}" nginx -t

  if systemctl is-active --quiet digital-human-backend.service; then
    wait_for_url http://127.0.0.1:8001/api/v1/health 30 2 || \
      die "Backend service did not become healthy; inspect it with journalctl."
    echo "Backend health check: OK"
  else
    warn "digital-human-backend.service is not running."
  fi

  echo "Deployment verification completed."
}

check_platform

if ((VERIFY_ONLY)); then
  [[ -x "${CONDA_BIN}" ]] || die "Conda is missing at ${CONDA_ROOT}."
  verify_deployment
  exit 0
fi

if ((SKIP_APT == 0)); then
  log "Installing Ubuntu packages"
  "${SUDO[@]}" apt-get update
  "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential ca-certificates curl ffmpeg git libgl1 libglib2.0-0 \
    libsm6 libxext6 nginx pkg-config wget
fi

if [[ ! -x "${CONDA_BIN}" ]]; then
  log "Installing Miniconda into ${CONDA_ROOT}"
  mkdir -p "${DATA_ROOT}/cache"
  installer="${DATA_ROOT}/cache/Miniconda3-latest-Linux-x86_64.sh"
  curl --fail --location --retry 10 --continue-at - \
    "${MINICONDA_INSTALLER_URL}" \
    --output "${installer}"
  bash "${installer}" -b -p "${CONDA_ROOT}"
  rm -f "${installer}"
fi

mkdir -p \
  "${DATA_ROOT}/cache/pip" \
  "${DATA_ROOT}/cache/huggingface" \
  "${DATA_ROOT}/cache/npm" \
  "${DATA_ROOT}/cache/uv" \
  "${TORCH_HOME}/hub/checkpoints"
export PIP_CACHE_DIR="${DATA_ROOT}/cache/pip"
export HF_HOME="${DATA_ROOT}/cache/huggingface"
export TORCH_HOME
export HF_ENDPOINT HF_HUB_DISABLE_XET=1
export UV_DEFAULT_INDEX="${PIP_INDEX_URL}"
export UV_CACHE_DIR="${DATA_ROOT}/cache/uv"
export NPM_CONFIG_REGISTRY="${NPM_REGISTRY}"
export NPM_CONFIG_CACHE="${DATA_ROOT}/cache/npm"

if [[ ! -x "${LIVETALKING_PY}" ]]; then
  log "Creating LiveTalking Conda environment"
  "${CONDA_BIN}" create -y -n "${LIVETALKING_ENV}" --override-channels \
    -c "${CONDA_CHANNEL}" python=3.12 ffmpeg=7
fi

if [[ ! -x "${APP_PY}" ]]; then
  log "Creating application build environment"
  "${CONDA_BIN}" create -y -n "${APP_ENV}" --override-channels \
    -c "${CONDA_CHANNEL}" python=3.12 nodejs=20
fi

conda_run "${LIVETALKING_ENV}" python -c \
  "import sys; assert sys.version_info[:2] == (3, 12), sys.version"
conda_run "${APP_ENV}" python -c \
  "import sys; assert sys.version_info[:2] == (3, 12), sys.version"
if ! conda_run "${APP_ENV}" node --version >/dev/null 2>&1; then
  log "Repairing Node.js in the application build environment"
  "${CONDA_BIN}" install -y -n "${APP_ENV}" --override-channels \
    -c "${CONDA_CHANNEL}" nodejs=20
fi

log "Installing pinned CUDA PyTorch"
if ! conda_run "${LIVETALKING_ENV}" python -c \
  "import torch; assert torch.__version__.startswith('2.9.1+cu128') and torch.cuda.is_available()" \
  >/dev/null 2>&1; then
  conda_run "${LIVETALKING_ENV}" python -m pip install --upgrade pip setuptools wheel \
    -i "${PIP_INDEX_URL}"
  conda_run "${LIVETALKING_ENV}" python -m pip install \
    torch==2.9.1+cu128 torchvision==0.24.1+cu128 torchaudio==2.9.1+cu128 \
    -i "${PIP_INDEX_URL}" --extra-index-url "${PYTORCH_INDEX_URL}" \
    --timeout 180 --retries 10
fi

if [[ ! -d "${LIVETALKING_DIR}/.git" ]]; then
  [[ ! -e "${LIVETALKING_DIR}" ]] || \
    die "${LIVETALKING_DIR} exists but is not a Git checkout. Move it aside and rerun."
  log "Cloning LiveTalking"
  clone_livetalking || die "Unable to clone LiveTalking from GitHub or its configured proxy."
fi

current_ref="$(git -C "${LIVETALKING_DIR}" rev-parse HEAD)"
if [[ "${current_ref}" != "${LIVETALKING_REF}" ]]; then
  [[ -z "$(git -C "${LIVETALKING_DIR}" status --porcelain --untracked-files=no)" ]] || \
    die "LiveTalking has local tracked changes; refusing to switch commits."
  log "Pinning LiveTalking to ${LIVETALKING_REF}"
  fetch_livetalking_ref || \
    die "Unable to fetch LiveTalking revision ${LIVETALKING_REF}."
  git -C "${LIVETALKING_DIR}" checkout --detach "${LIVETALKING_REF}"
fi

log "Installing LiveTalking dependencies"
conda_run "${LIVETALKING_ENV}" python -m pip install -r \
  "${PROJECT_DIR}/deploy/livetalking-requirements.lock" -i "${PIP_INDEX_URL}" \
  --timeout 180 --retries 10
conda_run "${LIVETALKING_ENV}" python -m pip install \
  "huggingface_hub[cli]" gdown -i "${PIP_INDEX_URL}" \
  --timeout 180 --retries 10

# LiveTalking's MuseTalk avatar preprocessor imports face_recognition, but the
# pinned upstream requirements omit it. Use a prebuilt pip wheel so Conda does
# not replace the environment's NumPy or pull in a second CUDA runtime.
mapfile -t conda_dlib_packages < <(
  "${CONDA_BIN}" list -n "${LIVETALKING_ENV}" | \
    awk '$1 == "dlib" || $1 == "libdlib" { print $1 }'
)
if ((${#conda_dlib_packages[@]})); then
  log "Removing incompatible Conda dlib packages"
  "${CONDA_BIN}" remove -y -n "${LIVETALKING_ENV}" --override-channels \
    -c "${CONDA_CHANNEL}" \
    "${conda_dlib_packages[@]}"
fi

if ! conda_run "${LIVETALKING_ENV}" python -c \
  "import numpy, cv2; assert numpy.__version__ == '2.5.4'" >/dev/null 2>&1; then
  log "Repairing NumPy and OpenCV after the dlib dependency check"
  conda_run "${LIVETALKING_ENV}" python -m pip install --force-reinstall \
    --no-cache-dir numpy==2.5.4 opencv-python-headless==5.0.0.93 \
    -i "${PIP_INDEX_URL}" --timeout 180 --retries 10
fi

if ! conda_run "${LIVETALKING_ENV}" python -c \
  "import dlib, face_recognition_models, face_recognition" >/dev/null 2>&1; then
  log "Installing MuseTalk face landmark dependencies"
  conda_run "${LIVETALKING_ENV}" python -m pip install --force-reinstall --no-deps \
    setuptools==80.9.0 dlib-bin==20.0.1.post1 \
    face-recognition-models==0.3.0 face-recognition==1.3.0 \
    -i "${PIP_INDEX_URL}" \
    --timeout 180 --retries 10
fi

if ((SKIP_MODELS == 0)); then
  log "Downloading MuseTalk 1.5 runtime models"
  mkdir -p "${LIVETALKING_DIR}/models"
  conda_run "${LIVETALKING_ENV}" hf download TMElyralab/MuseTalk \
    "musetalkV15/musetalk.json" "musetalkV15/unet.pth" \
    --local-dir "${LIVETALKING_DIR}/models"
  conda_run "${LIVETALKING_ENV}" hf download stabilityai/sd-vae-ft-mse \
    "config.json" "diffusion_pytorch_model.bin" \
    --local-dir "${LIVETALKING_DIR}/models/sd-vae"
  conda_run "${LIVETALKING_ENV}" hf download openai/whisper-tiny \
    "config.json" "pytorch_model.bin" "preprocessor_config.json" \
    --local-dir "${LIVETALKING_DIR}/models/whisper"

  # This mirrors the exact face parser files referenced by MuseTalk's official
  # download script. Fixed LFS digests prevent accepting altered mirror files.
  conda_run "${LIVETALKING_ENV}" hf download ManyOtherFunctions/face-parse-bisent \
    "79999_iter.pth" "resnet18-5c106cde.pth" \
    --local-dir "${LIVETALKING_DIR}/models/face-parse-bisent"
  conda_run "${LIVETALKING_ENV}" hf download n0x1103/s3fd \
    "s3fd-619a316812.pth" \
    --local-dir "${TORCH_HOME}/hub/checkpoints"

fi

log "Installing application dependencies"
conda_run "${APP_ENV}" python -m pip install uv -i "${PIP_INDEX_URL}"
conda_run "${APP_ENV}" uv sync --project "${PROJECT_DIR}/backend" --frozen
(
  cd "${PROJECT_DIR}/frontend"
  conda_run "${APP_ENV}" npm ci
)

if [[ ! -f "${PROJECT_DIR}/backend/.env" ]]; then
  cp "${PROJECT_DIR}/backend/.env.example" "${PROJECT_DIR}/backend/.env"
  chmod 600 "${PROJECT_DIR}/backend/.env"
fi
set_env_value "${PROJECT_DIR}/backend/.env" APP_HOST 127.0.0.1
set_env_value "${PROJECT_DIR}/backend/.env" APP_PORT 8001
set_env_value "${PROJECT_DIR}/backend/.env" \
  CORS_ORIGINS "${PUBLIC_ORIGIN},http://${PUBLIC_IP}:5173,http://${PUBLIC_IP}:4173"
set_env_value "${PROJECT_DIR}/backend/.env" \
  LIVETALKING_BASE_URL http://127.0.0.1:8010

if [[ ! -f "${PROJECT_DIR}/frontend/.env.production" ]]; then
  cp "${PROJECT_DIR}/frontend/.env.example" "${PROJECT_DIR}/frontend/.env.production"
fi
set_env_value "${PROJECT_DIR}/frontend/.env.production" VITE_AVATAR_ID "${DEFAULT_AVATAR_ID}"
set_env_value "${PROJECT_DIR}/frontend/.env.production" VITE_STUN_URL "${STUN_URL}"
(
  cd "${PROJECT_DIR}/frontend"
  conda_run "${APP_ENV}" npm run build
)

log "Applying maintained LiveTalking compatibility patches"
# Upstream's utils directory is missing a package marker. Without it, an
# unrelated top-level utils module can shadow utils.logger on Python 3.12.
if [[ ! -f "${LIVETALKING_DIR}/utils/__init__.py" ]]; then
  printf '%s\n' '"""LiveTalking utility package."""' > \
    "${LIVETALKING_DIR}/utils/__init__.py"
fi
cp "${PROJECT_DIR}/deploy/livetalking_pcm_stream.py" \
  "${LIVETALKING_DIR}/server/pcm_stream.py"
"${BACKEND_PY}" \
  "${PROJECT_DIR}/backend/scripts/configure_livetalking_pcm_stream.py" \
  --livetalking-dir "${LIVETALKING_DIR}"
"${BACKEND_PY}" "${PROJECT_DIR}/backend/scripts/configure_livetalking_video.py" \
  --livetalking-dir "${LIVETALKING_DIR}"
if ((ENABLE_SILENCE_INFERENCE)); then
  "${BACKEND_PY}" \
    "${PROJECT_DIR}/backend/scripts/configure_livetalking_silence_inference.py" \
    --livetalking-dir "${LIVETALKING_DIR}"
fi

if ((SKIP_SERVICES == 0)); then
  log "Installing systemd services and Nginx entrypoint"
  "${SUDO[@]}" tee /etc/systemd/system/digital-human-backend.service >/dev/null <<EOF
[Unit]
Description=Digital Human FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_GROUP}
WorkingDirectory=${PROJECT_DIR}/backend
EnvironmentFile=${PROJECT_DIR}/backend/.env
ExecStart=${BACKEND_UVICORN} app.main:app --host 127.0.0.1 --port 8001
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

  "${SUDO[@]}" tee /etc/systemd/system/livetalking@.service >/dev/null <<EOF
[Unit]
Description=LiveTalking MuseTalk avatar %i
After=network-online.target
Wants=network-online.target
ConditionPathExists=${LIVETALKING_DIR}/data/avatars/%i/latents.pt

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_GROUP}
WorkingDirectory=${LIVETALKING_DIR}
Environment=TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
Environment=TORCH_HOME=${TORCH_HOME}
Environment=LIVETALKING_PCM_PREBUFFER_MS=200
ExecStart=${LIVETALKING_PY} app.py --transport webrtc --model musetalk --avatar_id %i --batch_size 4 --fps 25 --listenport 8010 --stun ${STUN_URL}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  "${SUDO[@]}" tee /etc/nginx/sites-available/digital-human >/dev/null <<EOF
server {
    listen ${PUBLIC_PORT} default_server;
    listen [::]:${PUBLIC_PORT} default_server;
    server_name _;
    root ${PROJECT_DIR}/frontend/dist;
    index index.html;
    client_max_body_size 100m;

    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    location /avatar-api/ {
        rewrite ^/avatar-api/(.*)\$ /\$1 break;
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

  "${SUDO[@]}" rm -f /etc/nginx/sites-enabled/default
  "${SUDO[@]}" ln -sfn /etc/nginx/sites-available/digital-human \
    /etc/nginx/sites-enabled/digital-human
  "${SUDO[@]}" nginx -t
  "${SUDO[@]}" systemctl daemon-reload
  "${SUDO[@]}" systemctl enable digital-human-backend.service nginx
  "${SUDO[@]}" systemctl restart digital-human-backend.service
  "${SUDO[@]}" systemctl reload-or-restart nginx

fi

verify_deployment

cat <<EOF

Installation finished.
Public page: ${PUBLIC_ORIGIN}/
Backend env: ${PROJECT_DIR}/backend/.env
LiveTalking: ${LIVETALKING_DIR}

Prepare and start an avatar separately with:
  bash deploy/start_avatar.sh \\
    --avatar-source /data/source/avatar.mp4 --avatar-id ${DEFAULT_AVATAR_ID}

For microphone access, bind a domain and enable trusted HTTPS.
EOF
