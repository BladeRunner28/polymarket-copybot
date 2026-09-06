# NVIDIA PAIR — Local AI Cluster Setup Guide (fleet-specific)

**Date:** 2026-09-04 · **Source:** NVIDIA PAIR FAQ + build.nvidia.com playbook (`pair.md`, updated 2026-09-03) + Tom's Hardware IFA 2026 coverage · **Status:** research/plan — nothing installed

## What PAIR is (and isn't)

**Personal AI Router**: installs per-machine, exposes **Ollama-compatible + OpenAI-compatible proxy endpoints**, routes each *independent* request to the best eligible node (engine availability / model availability / current load). Ideal for multi-agent fan-out (agent swarms, cron pipelines).

**Not:** VRAM pooling, GPU merging, or splitting one model/request across machines ("PAIR sends each request to one system" — NVIDIA's own playbook). For model-splitting, the alternative is llama.cpp RPC (see Alternatives).

## Fleet fit

| Node | GPU / VRAM | PAIR-eligible | Role |
|---|---|---|---|
| Odin — i9-12900K, 64GB DDR5 | RTX 5070, 12GB | ✅ RTX 20+ (Blackwell) | **Primary serving node** — fastest arch, mid/large models |
| Miles — Ryzen 9, 32GB DDR5 | RTX 3080, 10GB | ✅ | Serving node — tier-1 models, second copy for load spreading |
| Xander — i7-13th, 64GB DDR5 | RTX 3060 (laptop), 6GB | ✅ | Light node — small models only (≤ ~9B Q4), off-peak |
| Mac Mini — M4 Pro, 24GB unified | Apple Silicon | ✅ (M4+ per Tom's) | **Head node** (PAIR + Hermes + agents) AND serving node (qwen2.5:7b stays; up to 14B comfortably) |
| Stormbreaker — Threadripper 1920X, 64GB DDR4 | GTX 1080, 8GB (Pascal) | ❌ not RTX 20+ | Out. Optional: CPU-only Ollama for tiny models — low value, skip unless bored |

Support matrix (official): Windows 11 / Linux / macOS, x64 + arm64, **mixable**; engines = Ollama + LM Studio only. Installers: Windows `.exe`, Linux `.deb`, macOS `.dmg` from github.com/NVIDIA/Personal-AI-Router/releases. GTX 1080 is Pascal → excluded regardless of OS.

## Network setup (best practices)

1. **Wire the serving nodes.** All PAIR traffic + Ollama model loads cross the LAN. A gigabit switch + cables for Odin/Miles/Xander beats Wi-Fi for jitter. Mac mini's 1GbE is currently **unplugged** (on Wi-Fi 6E ~2.4 Gbps PHY) — fine for light traffic, cable it if the mini becomes the always-on head doing real routing.
2. **One trusted subnet.** PAIR assumes a trusted network; the 6-digit PIN is a short-lived setup code, **not** a long-term credential. Keep nodes on the same private subnet; don't run on guest/shared/untrusted Wi-Fi (read `SECURITY.md` in the repo).
3. **One PAIR interface per machine** — desktop app XOR terminal interface (they conflict over ports/engines).
4. **Elastic QoS** — PAIR uses spare cycles, never reserves; a node gaming on its GPU gracefully sheds load. Fine for cron/agent workloads, not for latency-critical serving.
5. **Head node needs no GPU** — install PAIR on the machine where your *applications/agents* run; it can route to engines elsewhere.

## Install (per node, ~10 min + model downloads)

Every **serving** node (Odin, Miles, Xander, Mac mini):
1. Install Ollama (already present on the mini for the qwen shadow) → `ollama pull` the models it should serve (see sizing table).
2. Download + install the PAIR package for that OS/arch; launch the app (or terminal setup headless/SSH).
3. Pair: head node initiates, enter the 6-digit PIN on each node (trusted-LAN assumption).

**Head node** (Mac mini): install PAIR app; it exposes `http://<mini>:port` OpenAI-compatible endpoint. Point Hermes/cron/research tools at it instead of a single local engine — PAIR then picks the least-loaded eligible node per request.

## Model sizing table (Q4_K_M, ±context overhead)

| Model class | VRAM ~ | Odin 12GB | Miles 10GB | Xander 6GB | Mac 24GB |
|---|---|---|---|---|---|
| 7–9B | 4.4–5.5GB | ✅ | ✅ | ✅ tight | ✅ |
| 14B | ~8.5–9.5GB | ✅ | ✅ tight ctx | ❌ | ✅ |
| 32B | ~19–21GB | ⚠️ CPU-offload (64GB RAM, slow) | ❌ | ❌ | ⚠️ small ctx |
| 70B | ~40GB+ | ❌ | ❌ | ❌ | ❌ |

**Payoff for this project:** the sentiment shadow-A/B lane runs qwen2.5:7b on the mini today. With PAIR, a **14B model on Odin/Miles** becomes the A/B candidate (bigger model, same Ollama plumbing) — and Hermes cron agents get a fleet-backed local OpenAI-compatible endpoint instead of one 24GB Mac. PAIR does *not* give you 32B-class on this fleet without CPU offload; if that's the real goal, see Alternatives.

## Verification

- `curl http://<head>:<port>/v1/models` → node-available models.
- Send one request, watch which node serves it (PAIR logs); run two parallel requests → should spread across nodes.
- Time a 14B prompt on Odin vs the mini alone; expect the 5070 to win decisively on prefill.

## Rollback / security

- Rollback per playbook: remove paired systems → uninstall PAIR → remove engines/models no longer needed. Clean, low risk.
- All prompts/responses stay on-LAN **only if** the app, model source, engines, and nodes are all local (PAIR's design constraint — verify no cloud model source is configured).

## Caveats

- **Days-old product** (IFA 2026 launch; playbook updated 2026-09-03). Expect rough edges; Ollama direct mode remains the fallback (PAIR is a proxy — nothing breaks if you bypass it).
- Headline claims ("pool VRAM / shard models") exceed what the official playbook says it does. Set expectations at request-routing, not model-splitting.
- RTX 5070 = 12GB (not 16) and RTX 3080 = 10GB: both run 14B-class, neither runs 32B in VRAM.

## Alternatives (if the goal is one BIG model, not request fan-out)

- **llama.cpp RPC** — true tensor/pipeline split across LAN boxes; e.g., 5070(12GB) + 3080(10GB) ≈ 22GB combined → 32B-class Q4. Heterogeneous → limited by slowest card + network; needs llama-server on each node, manual split config.
- **Exo** — elegant but MLX-centric (Apple); the dev.to writeup notes heterogeneous NVIDIA+Apple splits are blocked for exo-style runtimes; llama.cpp RPC abstracts backends → better fit for this mixed fleet.
- **Petals / vLLM multi-node (Ray)** — overkill / same-runtime constraints for a 4-node home fleet.
