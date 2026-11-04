#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DATA_ROOT="${DATA_ROOT:-/data}"
CONDA_ROOT="${CONDA_ROOT:-${DATA_ROOT}/miniconda3}"
LIVETALKING_DIR="${LIVETALKING_DIR:-${DATA_ROOT}/LiveTalking}"
LIVEPORTRAIT_DIR="${LIVEPORTRAIT_DIR:-${DATA_ROOT}/LivePortrait}"
CODEFORMER_DIR="${CODEFORMER_DIR:-${DATA_ROOT}/CodeFormer}"
TORCH_HOME="${TORCH_HOME:-${DATA_ROOT}/cache/torch}"
CONDA_BIN="${CONDA_ROOT}/bin/conda"

INPUT_VIDEO=""
INPUT_AUDIO=""
AVATAR_ID=""
OUTPUT=""
WORK_DIR=""
REBUILD_AVATAR=0
FIDELITY=1.0
BLEND=0.68
TEMPORAL_STRENGTH=0.12

usage() {
  cat <<'EOF'
Usage: bash deploy/render_face_pipeline.sh OPTIONS

Required:
  --video PATH          Original speaking video
  --audio PATH          Replacement speech audio
  --avatar-id ID        New MuseTalk avatar id
  --output PATH         Final MP4 path

Optional:
  --work-dir PATH       Intermediate directory (default: /data/output/<avatar-id>)
  --rebuild-avatar      Rebuild an existing avatar after preserving a backup
  --fidelity NUMBER     CodeFormer fidelity, 0..1 (default: 1.0)
  --blend NUMBER        Restored-face blend, 0..1 (default: 0.68)
  --temporal NUMBER     Low-motion temporal strength, 0..1 (default: 0.12)
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }
require_value() {
  [[ -n "${2:-}" && "${2:-}" != --* ]] || die "$1 requires a value"
}

while (($#)); do
  case "$1" in
    --video) require_value "$1" "${2:-}"; INPUT_VIDEO="$2"; shift 2 ;;
    --audio) require_value "$1" "${2:-}"; INPUT_AUDIO="$2"; shift 2 ;;
    --avatar-id) require_value "$1" "${2:-}"; AVATAR_ID="$2"; shift 2 ;;
    --output) require_value "$1" "${2:-}"; OUTPUT="$2"; shift 2 ;;
    --work-dir) require_value "$1" "${2:-}"; WORK_DIR="$2"; shift 2 ;;
    --rebuild-avatar) REBUILD_AVATAR=1; shift ;;
    --fidelity) require_value "$1" "${2:-}"; FIDELITY="$2"; shift 2 ;;
    --blend) require_value "$1" "${2:-}"; BLEND="$2"; shift 2 ;;
    --temporal) require_value "$1" "${2:-}"; TEMPORAL_STRENGTH="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "${INPUT_VIDEO}" && -n "${INPUT_AUDIO}" && -n "${AVATAR_ID}" && -n "${OUTPUT}" ]] || {
  usage >&2
  exit 2
}
[[ "${AVATAR_ID}" =~ ^[A-Za-z0-9._-]+$ ]] || die "Invalid avatar id"
[[ -s "${INPUT_VIDEO}" ]] || die "Video is missing: ${INPUT_VIDEO}"
[[ -s "${INPUT_AUDIO}" ]] || die "Audio is missing: ${INPUT_AUDIO}"
[[ -x "${CONDA_BIN}" ]] || die "Conda is missing: ${CONDA_BIN}"
[[ -d "${LIVEPORTRAIT_DIR}" ]] || die "Run deploy/install_face_pipeline.sh first"
[[ -d "${CODEFORMER_DIR}" ]] || die "Run deploy/install_face_pipeline.sh first"
[[ -d "${LIVETALKING_DIR}" ]] || die "LiveTalking is missing: ${LIVETALKING_DIR}"

WORK_DIR="${WORK_DIR:-${DATA_ROOT}/output/${AVATAR_ID}}"
mkdir -p "${WORK_DIR}" "$(dirname "${OUTPUT}")"
NEUTRAL_VIDEO="${WORK_DIR}/01_neutral_lips.mp4"
NORMALIZED_AUDIO="${WORK_DIR}/02_audio_16k_mono.wav"
MUSETALK_VIDEO="${WORK_DIR}/03_musetalk.mp4"
CODEFORMER_OUTPUT="${WORK_DIR}/04_codeformer"
CODEFORMER_VIDEO="${CODEFORMER_OUTPUT}/03_musetalk.mp4"
AVATAR_DIR="${LIVETALKING_DIR}/data/avatars/${AVATAR_ID}"

echo "[1/5] Closing the original lips with LivePortrait"
"${CONDA_BIN}" run --no-capture-output -n liveportrait python \
  "${PROJECT_DIR}/backend/scripts/neutralize_lips_liveportrait.py" \
  --liveportrait-dir "${LIVEPORTRAIT_DIR}" \
  --input "${INPUT_VIDEO}" --output "${NEUTRAL_VIDEO}" \
  --source-max-dim 1920

echo "[2/5] Normalizing replacement audio"
ffmpeg -hide_banner -loglevel error -y -i "${INPUT_AUDIO}" \
  -ac 1 -ar 16000 -c:a pcm_s16le "${NORMALIZED_AUDIO}"

if [[ -d "${AVATAR_DIR}" && "${REBUILD_AVATAR}" -eq 1 ]]; then
  mv "${AVATAR_DIR}" "${AVATAR_DIR}.backup-$(date '+%Y%m%d-%H%M%S')"
fi
if [[ ! -s "${AVATAR_DIR}/latents.pt" ]]; then
  echo "[3/5] Preprocessing the neutral source for MuseTalk"
  (
    cd "${LIVETALKING_DIR}"
    TORCH_HOME="${TORCH_HOME}" TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
      "${CONDA_BIN}" run --no-capture-output -n livetalking \
      python -m avatars.musetalk.genavatar \
      --file "${NEUTRAL_VIDEO}" --avatar_id "${AVATAR_ID}" \
      --save_path "${LIVETALKING_DIR}/data/avatars" \
      --version v15 --gpu_id 0 --bbox_shift -2 --extra_margin 0 \
      --parsing_mode jaw
  )
else
  echo "[3/5] Reusing prepared avatar ${AVATAR_ID}"
fi

echo "[4/5] Generating new lip motion with MuseTalk"
(
  cd "${LIVETALKING_DIR}"
  TORCH_HOME="${TORCH_HOME}" TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
    LIVETALKING_MOUTH_STABILIZER=0 \
    "${CONDA_BIN}" run --no-capture-output -n livetalking \
    python "${PROJECT_DIR}/backend/scripts/render_musetalk_offline.py" \
    --livetalking-dir "${LIVETALKING_DIR}" --avatar-id "${AVATAR_ID}" \
    --audio "${NORMALIZED_AUDIO}" --output "${MUSETALK_VIDEO}" \
    --fps 25 --batch-size 8
)

echo "[5/5] Restoring the complete face and stabilizing low-motion detail"
if [[ -e "${CODEFORMER_OUTPUT}" ]]; then
  mv "${CODEFORMER_OUTPUT}" \
    "${CODEFORMER_OUTPUT}.backup-$(date '+%Y%m%d-%H%M%S')"
fi
(
  cd "${CODEFORMER_DIR}"
  "${CONDA_BIN}" run --no-capture-output -n codeformer \
    python inference_codeformer.py --input_path "${MUSETALK_VIDEO}" \
    --output_path "${CODEFORMER_OUTPUT}" --fidelity_weight "${FIDELITY}" \
    --upscale 1 --only_center_face --detection_model retinaface_resnet50
)
[[ -s "${CODEFORMER_VIDEO}" ]] || die "CodeFormer output is missing: ${CODEFORMER_VIDEO}"
"${CONDA_BIN}" run --no-capture-output -n livetalking python \
  "${PROJECT_DIR}/backend/scripts/blend_face_restoration.py" \
  --source "${MUSETALK_VIDEO}" --restored "${CODEFORMER_VIDEO}" \
  --output "${OUTPUT}" --blend "${BLEND}" \
  --temporal-strength "${TEMPORAL_STRENGTH}"

echo
echo "Completed: ${OUTPUT}"
echo "Neutral-lip preview: ${NEUTRAL_VIDEO}"
echo "MuseTalk preview:    ${MUSETALK_VIDEO}"
