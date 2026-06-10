# Killing the Two-Pass Dance: Fitting a 30B Multimodal LLM and a TTS Engine on One RTX 5090

*Mushishi stack build notes — June 2026*

## The problem

My comic-narrator pipeline needs two GPU tenants at once: **Nemotron-3-Nano-Omni**
(30B-A3B, NVFP4) reads the page — panels, dialogue, who's speaking, what the
scene sounds like — and **Fish Speech 1.5** turns the script into voiced audio.

The stack's forensic Nemotron config eats ~30 GB of the RTX 5090's 32 GB
(180K context, FP8 KV cache, `gpu-memory-utilization 0.92`). Fish Speech wants
another ~2.5 GB plus inference headroom. They could not coexist, so every
narrated page meant the *two-pass dance*:

```
forensic-mode.sh        → wait ~5 min for model load
run vision phases       → page.json, script.json
audio-mode.sh           → tear down Nemotron, start audio stack
run audio+video phases  → resume from the JSONs
```

Two mode switches and ~10 minutes of loading per session. The pipeline even
grew `--from-page-json` / `--from-script-json` resume flags specifically to
survive this. It worked. It was also miserable.

The obvious fix: a *light* Nemotron config that leaves room for TTS. How hard
can it be — drop the context window, lower the memory cap, done? Here is the
actual record, because the gap between "obvious" and "running" is where all
the lessons live.

## Six attempts

**Attempt 1 — `gpu-memory-utilization 0.68`, 64K context.** Died at startup:
`Free memory on device (20.09/31.36 GiB) is less than desired (21.32 GiB)`.
Two surprises in one line. First, vLLM's utilization knob is a fraction of
*total* VRAM, checked against *free* VRAM at boot — it doesn't adapt to what's
actually available. Second, something was holding ~9 GB that shouldn't have
been: the audio worker's CUDA allocator, still fat from a TTS warmup. Torch
caching allocators don't give memory back just because you finished a job.

**Attempt 2 — same config, retried on a quiet GPU.** New error:
`moe_backend='triton' is not supported for NvFP4 MoE`. I had copied the
engine flags from my own stack *documentation*, which still says the forensic
config uses `--moe-backend triton` and `VLLM_USE_FLASHINFER_MOE_FP4=1`. The
as-built compose file removed both months ago (they break NVFP4 MoE on
SM120). The spec lied; the running system knew better. I had already learned
this exact lesson with the audio gateway's API contract — and stepped on the
same rake from the other side.

**Attempts 3–5 — 0.72, then 0.78, then 0.78 with 32K context.** All died with
`No available memory for the cache blocks`. This is where folk numbers fall
apart. I "knew" the NVFP4 weights were ~18 GB because the docs said so. The
log says otherwise:

```
Checkpoint size: 20.87 GiB
Model loading took 21.5 GiB memory
Available KV cache memory: -1.62 GiB
```

21.5 GiB of weights, ~0.4 GiB of CUDA graphs, and — the real thief — the
**profiling pass**. Before allocating KV cache, vLLM simulates a worst-case
forward pass sized by `--max-num-batched-tokens` (I had 16384, inherited from
the forensic config) and the multimodal limits (8 images). That peak gets
reserved forever. My "light" config was budgeting like the heavy one.

**Attempt 6 — the one that lived.** Right-size the worst case to the actual
workload: the comic pipeline sends *one image per request* and never needs
long batches.

```
--max-model-len 32768            # was 180000
--max-num-seqs 2                 # was 4
--max-num-batched-tokens 4096    # was 16384  ← the fix that mattered
--limit-mm-per-prompt '{"image": 2, ...}'   # was 8
--gpu-memory-utilization 0.82
```

```
Available KV cache memory: 1.1 GiB
GPU KV cache size: 76,608 tokens
```

27.9 GB used with Fish Speech loaded alongside. 4.2 GB of headroom for TTS
inference spikes. One `agent-mode.sh`, one model load, and the whole
pipeline — vision, script, voices, SFX, video — runs in a single command.

## The budget that works

| Tenant | VRAM |
|---|---|
| Nemotron NVFP4 weights | 21.5 GiB |
| CUDA graphs + activations (4K batch profile) | ~2.6 GiB |
| KV cache (FP8, 76K tokens) | 1.1 GiB |
| **vLLM total (util 0.82)** | **~25.7 GiB** |
| Fish Speech 1.5 | ~2.3 GiB |
| Headroom (TTS spikes, display) | ~4 GiB |

## What I'd tell past me

1. **`gpu-memory-utilization` is a promise about total VRAM, validated
   against free VRAM at startup.** Other tenants' allocator bloat will fail
   your boot even if the steady state would fit. Start the big tenant first,
   or restart the small ones before it.
2. **Weights-on-disk ≠ weights-in-VRAM, and docs ≠ deployment.** Read the
   `Model loading took X GiB` line from a real boot, not the model card, not
   your own architecture notes. My docs were wrong about the weights *and*
   about two engine flags.
3. **The profiling pass is sized by your config's worst case, not your
   workload's.** `--max-num-batched-tokens` is the highest-leverage knob
   nobody mentions: 16384 → 4096 freed multiple GiB here. If your requests
   are single-image and short-batch, say so.
4. **Iterate on the error, not the theory.** Six boots at ~3 minutes each
   beat any amount of VRAM arithmetic on paper. The log line
   `Available KV cache memory: -1.62 GiB` told me exactly how far off I was;
   no spreadsheet did.
5. **Keep the heavy config.** Agent-light (32K ctx) is for pipelines and
   agent work. Forensic client jobs still get the full 180K/0.92 exclusive
   mode. Modes are a feature, not a failure — the win is that *this* workload
   no longer needs two of them.

## Payoff

```bash
agent-mode.sh
comic-narrator book.pdf --layout manga -o book.mp4
```

One command. A manga PDF goes in; a narrated, voice-acted, sound-bedded,
camera-animated MP4 comes out. Every model on local silicon, every byte on my
disk — and nobody had to choreograph a VRAM handoff to make it happen.

*Stack: RTX 5090 32GB · Ryzen 9 9900X3D · Ubuntu 24.04 · vLLM 0.20.0 ·
Nemotron-3-Nano-Omni NVFP4 · Fish Speech 1.5 · Mushishi sovereign AI stack v1.7.1*
