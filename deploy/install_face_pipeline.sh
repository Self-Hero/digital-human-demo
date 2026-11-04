#!/usr/bin/env bash

set -Eeuo pipefail

DATA_ROOT="${DATA_ROOT:-/data}"
CONDA_ROOT="${CONDA_ROOT:-${DATA_ROOT}/miniconda3}"
LIVEPORTRAIT_DIR="${LIVEPORTRAIT_DIR:-${DATA_ROOT}/LivePortrait}"
CODEFORMER_DIR="${CODEFORMER_DIR:-${DATA_ROOT}/CodeFormer}"
LIVEPORTRAIT_REF="${LIVEPORTRAIT_REF:-9b294b3d0536135442ea73cb01e6cb3ca7029dd3}"
CODEFORMER_REF="${CODEFORMER_REF:-b33cc7d639d6545bfcccc7e0bc6ae51f24e79c2b}"
GITHUB_PROXY_PREFIX="${GITHUB_PROXY_PREFIX:-https://ghfast.top/}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/cu121}"
CONDA_CHANNEL="${CONDA_CHANNEL:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge}"
CONDA_BIN="${CONDA_ROOT}/bin/conda"

log() { printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(uname -s)" == Linux ]] || die "This installer must run on Linux."
[[ -x "${CONDA_BIN}" ]] || die "Conda is missing at ${CONDA_ROOT}."
for command in git ffmpeg curl nvidia-smi; do
  command -v "${command}" >/dev/null || die "Missing command: ${command}"
done
nvidia-smi >/dev/null || die "NVIDIA GPU or driver is unavailable."

clone_at_ref() {
  local repository="$1" directory="$2" ref="$3" proxy_url
  proxy_url="${GITHUB_PROXY_PREFIX%/}/${repository}"
  if [[ ! -d "${directory}/.git" ]]; then
    if ! git -c http.version=HTTP/1.1 clone --filter=blob:none "${proxy_url}" "${directory}"; then
      [[ ! -e "${directory}" ]] || mv "${directory}" "${directory}.failed-$(date '+%Y%m%d-%H%M%S')"
      git -c http.version=HTTP/1.1 clone --filter=blob:none "${repository}" "${directory}"
    fi
  fi
  git -C "${directory}" remote set-url origin "${proxy_url}"
  git -C "${directory}" fetch --depth=1 origin "${ref}"
  git -C "${directory}" checkout --detach "${ref}"
}

ensure_env() {
  local environment="$1"
  if [[ ! -d "${CONDA_ROOT}/envs/${environment}" ]]; then
    "${CONDA_BIN}" create -y -n "${environment}" \
      --override-channels --channel "${CONDA_CHANNEL}" python=3.10 pip
  fi
}

conda_run() {
  local environment="$1"
  shift
  "${CONDA_BIN}" run --no-capture-output -n "${environment}" "$@"
}

download_release_file() {
  local url="$1" destination="$2" temporary="${destination}.part"
  [[ -s "${destination}" ]] && return 0
  mkdir -p "$(dirname "${destination}")"
  if ! curl -fL --retry 5 --retry-delay 3 -o "${temporary}" \
      "${GITHUB_PROXY_PREFIX%/}/${url}"; then
    curl -fL --retry 5 --retry-delay 3 -o "${temporary}" "${url}"
  fi
  mv "${temporary}" "${destination}"
}

log "Installing LivePortrait in an isolated environment"
clone_at_ref "https://github.com/KwaiVGI/LivePortrait.git" \
  "${LIVEPORTRAIT_DIR}" "${LIVEPORTRAIT_REF}"
ensure_env liveportrait
conda_run liveportrait python -m pip install --upgrade pip \
  --index-url "${PIP_INDEX_URL}"
conda_run liveportrait python -m pip install \
  torch==2.3.0+cu121 torchvision==0.18.0+cu121 torchaudio==2.3.0+cu121 \
  --index-url "${PIP_INDEX_URL}" --extra-index-url "${PYTORCH_INDEX_URL}"
conda_run liveportrait python -m pip install \
  --index-url "${PIP_INDEX_URL}" -r "${LIVEPORTRAIT_DIR}/requirements.txt" \
  "huggingface_hub[cli]"
HF_ENDPOINT="${HF_ENDPOINT}" conda_run liveportrait python -c \
  "from huggingface_hub import snapshot_download; snapshot_download('KlingTeam/LivePortrait', local_dir='${LIVEPORTRAIT_DIR}/pretrained_weights', ignore_patterns=['*.git*', 'README.md', 'docs/*'])"

log "Installing CodeFormer in a separate environment"
clone_at_ref "https://github.com/sczhou/CodeFormer.git" \
  "${CODEFORMER_DIR}" "${CODEFORMER_REF}"
ensure_env codeformer
conda_run codeformer python -m pip install --upgrade pip \
  --index-url "${PIP_INDEX_URL}"
conda_run codeformer python -m pip install \
  torch==2.3.0+cu121 torchvision==0.18.0+cu121 torchaudio==2.3.0+cu121 \
  --index-url "${PIP_INDEX_URL}" --extra-index-url "${PYTORCH_INDEX_URL}"
conda_run codeformer python -m pip install \
  --index-url "${PIP_INDEX_URL}" -r "${CODEFORMER_DIR}/requirements.txt"
(
  cd "${CODEFORMER_DIR}"
  conda_run codeformer python basicsr/setup.py develop
)

download_release_file \
  "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth" \
  "${CODEFORMER_DIR}/weights/CodeFormer/codeformer.pth"
download_release_file \
  "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/detection_Resnet50_Final.pth" \
  "${CODEFORMER_DIR}/weights/facelib/detection_Resnet50_Final.pth"
download_release_file \
  "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/parsing_parsenet.pth" \
  "${CODEFORMER_DIR}/weights/facelib/parsing_parsenet.pth"

log "Verifying the installation"
test -s "${LIVEPORTRAIT_DIR}/pretrained_weights/liveportrait/base_models/appearance_feature_extractor.pth"
test -s "${CODEFORMER_DIR}/weights/CodeFormer/codeformer.pth"
conda_run liveportrait python -c "import torch, cv2, onnxruntime; assert torch.cuda.is_available(); print('LivePortrait CUDA:', torch.cuda.get_device_name(0))"
conda_run codeformer python -c "import torch, cv2; assert torch.cuda.is_available(); print('CodeFormer CUDA:', torch.cuda.get_device_name(0))"

echo
echo "Installation completed. No service was changed or restarted."
echo "LivePortrait: ${LIVEPORTRAIT_DIR}"
echo "CodeFormer:   ${CODEFORMER_DIR}"
