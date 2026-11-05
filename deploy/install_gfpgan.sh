#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DATA_ROOT="${DATA_ROOT:-/data}"
CONDA_ROOT="${CONDA_ROOT:-${DATA_ROOT}/miniconda3}"
LIVETALKING_DIR="${LIVETALKING_DIR:-${DATA_ROOT}/LiveTalking}"
GFPGAN_DIR="${GFPGAN_DIR:-${DATA_ROOT}/GFPGAN}"
GFPGAN_REF="${GFPGAN_REF:-v1.3.8}"
GITHUB_PROXY_PREFIX="${GITHUB_PROXY_PREFIX:-https://ghfast.top/}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
CONDA_BIN="${CONDA_ROOT}/bin/conda"
LIVETALKING_ENV="livetalking"
MODEL_PATH="${GFPGAN_DIR}/experiments/pretrained_models/GFPGANv1.4.pth"

log() { printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }
conda_run() {
  "${CONDA_BIN}" run --no-capture-output -n "${LIVETALKING_ENV}" "$@"
}

[[ "$(uname -s)" == Linux ]] || die "This installer must run on Linux."
[[ -x "${CONDA_BIN}" ]] || die "Conda is missing: ${CONDA_BIN}"
[[ -d "${CONDA_ROOT}/envs/${LIVETALKING_ENV}" ]] || \
  die "LiveTalking environment is missing. Run bootstrap_server.sh first."
[[ -d "${LIVETALKING_DIR}/avatars" ]] || die "LiveTalking is missing: ${LIVETALKING_DIR}"

log "Installing GFPGAN source"
proxy_url="${GITHUB_PROXY_PREFIX%/}/https://github.com/TencentARC/GFPGAN.git"
repository_url="https://github.com/TencentARC/GFPGAN.git"
if [[ ! -d "${GFPGAN_DIR}/.git" ]]; then
  if git -c http.version=HTTP/1.1 clone "${proxy_url}" "${GFPGAN_DIR}"; then
    fetch_url="${proxy_url}"
  else
    git -c http.version=HTTP/1.1 clone "${repository_url}" "${GFPGAN_DIR}"
    fetch_url="${repository_url}"
  fi
else
  fetch_url="${proxy_url}"
fi
if [[ -z "$(git -C "${GFPGAN_DIR}" status --porcelain --untracked-files=no)" ]]; then
  if ! git -C "${GFPGAN_DIR}" fetch --depth=1 \
      "${fetch_url}" "${GFPGAN_REF}"; then
    [[ "${fetch_url}" != "${proxy_url}" ]] || \
      git -C "${GFPGAN_DIR}" fetch --depth=1 \
        "${repository_url}" "${GFPGAN_REF}"
  fi
  git -C "${GFPGAN_DIR}" checkout --detach "${GFPGAN_REF}"
else
  log "Keeping existing GFPGAN checkout because it has tracked changes"
fi

log "Installing GFPGAN runtime into the LiveTalking environment"
conda_run python -m pip install --no-build-isolation --no-deps \
  addict==2.4.0 future==1.0.0 lmdb==1.7.5 scikit-image==0.25.2 \
  yapf==0.43.0 basicsr==1.4.2 facexlib==0.3.0 \
  --index-url "${PIP_INDEX_URL}" --timeout 180 --retries 10
conda_run python -m pip install --no-build-isolation --no-deps \
  -e "${GFPGAN_DIR}"
site_packages="$(conda_run python -c \
  'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
basicsr_degradations="${site_packages}/basicsr/data/degradations.py"
if [[ -f "${basicsr_degradations}" ]]; then
  sed -i \
    's/from torchvision.transforms.functional_tensor import rgb_to_grayscale/from torchvision.transforms.functional import rgb_to_grayscale/' \
    "${basicsr_degradations}"
fi

log "Downloading GFPGAN v1.4 weights"
mkdir -p "$(dirname "${MODEL_PATH}")"
if [[ ! -s "${MODEL_PATH}" || "$(stat -c %s "${MODEL_PATH}")" -lt 300000000 ]]; then
  temporary="${MODEL_PATH}.part"
  model_url="https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth"
  if ! curl -fL --retry 20 --retry-delay 3 -C - \
      -o "${temporary}" "${GITHUB_PROXY_PREFIX%/}/${model_url}"; then
    curl -fL --retry 20 --retry-delay 3 -C - \
      -o "${temporary}" "${model_url}"
  fi
  mv "${temporary}" "${MODEL_PATH}"
fi

log "Installing the LiveTalking GFPGAN hook"
cp "${PROJECT_DIR}/deploy/livetalking_gfpgan.py" \
  "${LIVETALKING_DIR}/avatars/gfpgan_enhancer.py"
python3 "${PROJECT_DIR}/backend/scripts/configure_livetalking_gfpgan.py" \
  --livetalking-dir "${LIVETALKING_DIR}"

log "Verifying GFPGAN"
(
  cd "${LIVETALKING_DIR}"
  export LIVETALKING_GFPGAN=1
  conda_run python -c \
    "import torch; from avatars.gfpgan_enhancer import RealtimeGFPGANEnhancer; enhancer = RealtimeGFPGANEnhancer(); assert enhancer.enabled; print('GFPGAN realtime runtime:', torch.cuda.get_device_name(0), 'torch', torch.__version__)"
)

echo
echo "GFPGAN realtime runtime installed. The feature remains disabled by default."
echo "Model: ${MODEL_PATH}"
