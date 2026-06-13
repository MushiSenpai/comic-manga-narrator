#!/bin/bash
# install-expressive.sh — Track H: Parler-TTS (Stage 1) + Seed-VC (Stage 2)
# into the running audio-worker container. Idempotent.
#
# Run AFTER the GPU is free (this pulls ~3-4GB of weights and needs VRAM to
# smoke-test). The audio stack must be up (audio-mode.sh).
#
# Two-stage expressive voice: Parler performs the emotion, Seed-VC re-voices
# to the character. See docs/TTS-RESEARCH.md.
set -e
WORKER=creative-audio-worker
GW=http://localhost:9000

echo "== Track H install: Parler-TTS + Seed-VC =="
docker ps --format '{{.Names}}' | grep -qx "$WORKER" || {
  echo "Audio worker not running. Start with audio-mode.sh first." >&2; exit 1; }

echo "[1/4] Parler-TTS (Stage 1, Apache-2.0)..."
docker exec "$WORKER" pip install --no-cache-dir --break-system-packages \
  git+https://github.com/huggingface/parler-tts.git soundfile

echo "[2/4] Seed-VC (Stage 2, zero-shot VC)..."
# Seed-VC ships as a repo; clone into the worker workspace and expose a
# convert() shim importable as seed_vc_infer.
docker exec "$WORKER" bash -lc '
  set -e
  SVC=/data/ai/01-workspace/audio/seed-vc
  if [ ! -d "$SVC/.git" ]; then
    git clone --depth 1 https://github.com/Plachtaa/seed-vc "$SVC"
  fi
  cd "$SVC" && pip install --no-cache-dir --break-system-packages -r requirements.txt || true
'

echo "[3/4] Pre-download model weights (first run caches them)..."
docker exec "$WORKER" python3 -c "
from transformers import AutoTokenizer
from parler_tts import ParlerTTSForConditionalGeneration
ParlerTTSForConditionalGeneration.from_pretrained('parler-tts/parler-tts-mini-v1')
AutoTokenizer.from_pretrained('parler-tts/parler-tts-mini-v1')
print('Parler weights cached')
" || echo 'WARN: Parler preload failed — check logs'

echo "[4/4] Register the worker on the expressive queue..."
echo "  → add 'expressive' to ROUTES in gateway/intent_router.py and the"
echo "    worker's queue list, then restart creative-audio-worker."
echo ""
echo "Smoke test after registration:"
echo "  curl -s -X POST $GW/audio/job -F job_type=expressive_tts \\"
echo "    -F text='I will become stronger.' \\"
echo "    -F description='A young man, determined and intense, steady.' \\"
echo "    -F voice_profile=male_young_bright"
echo ""
echo "Then flip the pipeline: export COMIC_TWO_STAGE_TTS=1"
