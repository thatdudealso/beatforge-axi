#!/usr/bin/env bash
# Install the pinned ACE-Step-1.5 checkout and verified MIT turbo checkpoint bundle
# for BeatForge --engine acestep. Idempotent where practical.
set -euo pipefail

PINNED_COMMIT="6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0"
PINNED_REVISION="19671f406d603126926c1b7e2adc169acbcade22"
DEFAULT_ROOT="${BEATFORGE_ACESTEP_PROJECT_ROOT:-${HOME}/src/ACE-Step-1.5}"
ROOT="${1:-$DEFAULT_ROOT}"

echo "ACE-Step project root: ${ROOT}"
echo "Pinned commit: ${PINNED_COMMIT}"
echo "Pinned model revision: ${PINNED_REVISION}"

if [[ ! -d "${ROOT}/.git" ]]; then
  mkdir -p "$(dirname "${ROOT}")"
  git clone https://github.com/ace-step/ACE-Step-1.5.git "${ROOT}"
fi

git -C "${ROOT}" fetch --depth 1 origin "${PINNED_COMMIT}"
git -C "${ROOT}" checkout "${PINNED_COMMIT}"
HEAD="$(git -C "${ROOT}" rev-parse HEAD)"
if [[ "${HEAD}" != "${PINNED_COMMIT}" ]]; then
  echo "error: checkout HEAD ${HEAD} != pinned ${PINNED_COMMIT}" >&2
  exit 1
fi

command -v uv >/dev/null || {
  echo "error: uv is required; install from https://docs.astral.sh/uv/" >&2
  exit 1
}
command -v ffmpeg >/dev/null || {
  echo "warning: ffmpeg not on PATH (BeatForge synth/export needs it)" >&2
}

(
  cd "${ROOT}"
  uv sync --frozen || uv sync
)

mkdir -p "${ROOT}/checkpoints"
if command -v hf >/dev/null; then
  HF_BIN=hf
elif [[ -x "${ROOT}/.venv/bin/hf" ]]; then
  HF_BIN="${ROOT}/.venv/bin/hf"
else
  uv pip install --python "${ROOT}/.venv/bin/python" 'huggingface_hub[cli]'
  HF_BIN="${ROOT}/.venv/bin/hf"
fi

"${HF_BIN}" download ACE-Step/Ace-Step1.5 \
  --revision "${PINNED_REVISION}" \
  --local-dir "${ROOT}/checkpoints"

REQUIRED=(
  "acestep-v15-turbo/model.safetensors"
  "acestep-v15-turbo/silence_latent.pt"
  "vae/diffusion_pytorch_model.safetensors"
  "Qwen3-Embedding-0.6B/model.safetensors"
  "acestep-5Hz-lm-1.7B/model.safetensors"
)
for rel in "${REQUIRED[@]}"; do
  path="${ROOT}/checkpoints/${rel}"
  if [[ ! -f "${path}" ]]; then
    echo "error: missing required weight ${path}" >&2
    exit 1
  fi
  echo "present: ${rel} ($(wc -c < "${path}") bytes)"
done

Expose the pinned package to BeatForge by setting BEATFORGE_ACESTEP_PROJECT_ROOT.
BeatForge appends that checkout to sys.path so ``import acestep`` works without
shadowing BeatForge's ``cli`` package. Do **not** put the checkout on PYTHONPATH
and do **not** editable-install ACE-Step into the BeatForge venv (both expose
ACE-Step's top-level cli.py and break ``beatforge-axi``).

  export BEATFORGE_ACESTEP_PROJECT_ROOT="${ROOT}"
  # Apple Silicon daily Mac:
  export BEATFORGE_ACESTEP_DEVICE=mps
  # Linux CPU smoke (slow):
  # export BEATFORGE_ACESTEP_DEVICE=cpu
  # export BEATFORGE_ACESTEP_USE_MLX_DIT=0
  # export BEATFORGE_ACESTEP_OFFLOAD_TO_CPU=1
  # export ACESTEP_INIT_LLM=false

  # ACE-Step deps still live in the checkout's own .venv from uv sync.
  # BeatForge needs the acestep import; torch/etc must be importable too.
  # Prefer running BeatForge with the ACE-Step interpreter after installing BeatForge
  # into that venv, OR ensure shared site-packages provide torch.
  #
  # Recommended on the daily Mac (ACE-Step owns the heavy stack):
  #   cd "${ROOT}" && uv pip install -e /path/to/beatforge-axi
  #   "${ROOT}/.venv/bin/beatforge-axi" --engine acestep generate ...

  uv run beatforge-axi --engine acestep generate \\
    --prompt "dusty lo-fi beat with warm Rhodes" --duration 60 --out /tmp/auraflow-bf-daily.mp3

EOF
