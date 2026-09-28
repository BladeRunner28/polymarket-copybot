# Odin (RTX 5070 12 GB) — local model fit & benchmark

**Date:** 2026-09-27 · **Host:** Odin, Win11 Pro 26200, i9-12900K, 63.7 GiB RAM, RTX 5070 12 GB GDDR7 (672 GB/s), 3× 1 TB NVMe
**Runtime:** Ollama 0.34.4, CUDA compute 12.0 (sm_120), driver 13.4 · **Driven over the LAN API from the Mac head (192.168.1.10 → 192.168.1.106:11434)**
**Protocol:** 4 fixed prompts (summarize / classify / code / reason), `temperature 0`, `seed 42`, `num_predict 384`, `think:false`. Each arm: unload everything → cold load (timed separately) → measure warm. First generation after each load discarded as a load artifact.

## Headline

On a 12 GB display-attached card, **the model that wins is decided by KV cache, not parameter count.** `gemma4:12b-it-qat` holds its context cost flat and runs 73 tok/s at 8k, 32k *and* 128k. `qwen3.5:9b` is faster at short context (91 tok/s) but pays ~3.8 GiB of KV to reach 128k, where it partially offloads and drops 18%.

| Model (Q4-class) | ctx 8192 | ctx 32768 | ctx 131072 | Resident footprint |
|---|---|---|---|---|
| `qwen3.5:9b` | **91.0** tok/s | **90.9** | 74.3 (−18%) | 6.59 GB → offloads at 128k |
| `gemma4:12b-it-qat` | 73.1 | 73.1 | **73.0 (flat)** | 7.15 GB → all resident at every ctx |

Prompt eval (prefill) 994–2,668 tok/s both models · cold load 3.4–4.7 s from warm cache.

**Fit verdict at 128k:** `ollama ps` reports `PROCESSOR 8%/92% CPU/GPU` for qwen3.5:9b at 131072 — genuine partial offload, with only **501–552 MiB free** on the card. gemma4 at the same context reports no offload and no growth in footprint (sliding-window attention).

## Cross-host: Odin vs Mac mini M4 Pro (24 GB unified)

| Model | Host | gen tok/s | prompt tok/s |
|---|---|---|---|
| `qwen3.5:9b` | RTX 5070 12 GB | **91.0** | 994–2,668 |
| `qwen3.5:9b` | M4 Pro 24 GB | 37.2 | 182–255 |

**2.45× on generation, ~7× on prompt eval**, identical prompts and harness. The Mac keeps the capacity advantage (24 GB fits what Odin cannot); Odin is the throughput and long-prompt host.

**Caveat on the comparison:** the two hosts are not on the same runtime — **Mac 0.33.1 vs Odin 0.34.4**. Same model, same options, same harness, but a minor version difference is uncontrolled here. Generation speed is dominated by the llama.cpp backend and the gap is far larger than a point release plausibly explains, but it is a confound and should be closed by re-running the Mac arm on 0.33.4-class parity before any fleet decision leans on the exact multiple.

Bandwidth model check: 6.59 GB at 672 GB/s × 0.89 efficiency → predicted ~90 tok/s. Measured 91.0.

## Instrumentation caveats (from the out-of-band nvidia-smi witness on Odin)

- `size_vram` is **weights only** — it excludes KV and CUDA context. "100% on GPU" is a true statement about weights and a misleading one about the card.
- Device-level delta vs `size_vram`: **+1,094 MiB** at 32k, **−266 MiB** at 128k. Agreement is only **±1 GiB**.
- The 32k excess is explained: `size` grows 6.28 → 10.06 GiB from 32k → 128k, i.e. **3,787 MiB of KV over 98k tokens = 29.6 KiB/token** (≈0.9 GiB at 32k). Matches the measured 1,094 MiB excess.
- **No per-process VRAM attribution is possible**: `nvidia-smi --query-compute-apps` returns `[N/A]` for every process under WDDM. Explorer, Edge WebView, Discord, iCUE, StreamDeck, PowerToys and Corsair services all hold VRAM. Idle baseline 2,755 MiB.
- The 128k arm ran at 11,699–11,726 of 12,227 MiB — so "74 tok/s at 131k" is partly a **VRAM-pressure** number, not a pure compute number.

## Practical rules extracted

1. **Cap `num_ctx` at 32k for qwen3.5:9b on Odin** — free, zero penalty. Use `gemma4:12b-it-qat` when 128k context is actually needed.
2. **Discard the first generation after any model load.** A load right after a `pull` (block still being written back) took 60 s and depressed that call to 6.2 tok/s. Pass 1 misread this as a possible spill; pass 2's clean protocol separated it.
3. **Use `ollama ps`'s PROCESSOR split as the fit signal**, not `size_vram == size`.
4. Free ~2.5 GB by running the display off the iGPU (UHD 770) — that removes the compositor competition that the 128k arm was fighting.

## Installed on Odin now

`qwen3.5:9b` 6.59 GB · `gemma4:12b-it-qat` 7.15 GB. `llama3.2-vision:11b` was removed on 2026-09-27 (owner instruction; re-pullable in ~2 min). Disk free: 336 GB at pull time.

## Security item — RESOLVED 2026-09-27

Odin's Ollama was listening on **`0.0.0.0:11434` with no auth** — anything on 192.168.1.0/24 could pull models, spend GPU time or fill the disk. Residual: an IPv6 listener may still be bound; default-deny covers it only because no allow rule matches, so confirm if the network ever gains routable v6.

Closed by scoping the firewall instead of a hard loopback rebind, because the sentiment lane (below) needs the head to reach it:

- The installer rule could not be scoped in place — Windows refuses to add an address condition to a rule carrying the **"defer to user"** flag (`Set-NetFirewallRule -RemoteAddress` errors: *"Defer to user setting can only be used in a firewall rule where program path and TCP/UDP protocol are specified with no additional conditions"*). The rule was disabled and replaced with a port-scoped allow for `192.168.1.10`, relying on default-deny for everything else.
- **Verified both halves:** from 192.168.1.10 → `http=200`; from WSL on Odin (a genuine non-`.10`, 172.x source) → `000` with curl **exit 28, timeout** where it previously returned 200.
- **Not verified:** the rule list itself — the peer's rule-dump request timed out, so the config state is confirmed behaviorally, not by inspection.

## The lane move: what the measurement actually showed

Moving the research bot's shadow sentiment lane to Odin was gated on parity, and the gate is what found the real problem.

**Parity — 80-item frozen sample, both hosts, production module, identical prompt/params:**

| Comparison | exact label (±0.1) | sign | mean \|Δsentiment\| | speed |
|---|---|---|---|---|
| Mac 0.33.1 → 0.34.4 (runtime only) | **80/80 = 100%** | 100% | 0.0000 | 2.07 → 2.05 s (−1.0%, noise) |
| Mac 0.34.4 vs Odin 0.34.4, ctx mismatched | 77/80 = 96.2% | 98.8% | 0.0031 | 1.97× |
| Odin: ctx 131072 → 4096 | **80/80 = 100%** | 100% | 0.0000 | 1.02 → **0.55 s (−46.8%)** |
| **Mac vs Odin, version+ctx matched** | 96.2% | 98.8% | 0.0031 | **3.75×** |

- **The pre-registered n≥200 was unobtainable.** 80 unique texts is the *entire* eligible population — 680 logged `qwen3.5:9b` rows dedupe to 80, and no length filter changes it. Tested at the population, not at the registered size; recorded rather than quietly re-scoped.
- **Confound 1 — runtime.** Mac upgraded 0.33.1 → 0.34.4 (official `Ollama-darwin.zip`, sha256 checked against the release digest). Upgrading the runtime under a *live* lane produced **zero output drift** at 80 items. While doing it, a **second, older Ollama was discovered on the Mac**: a Homebrew formula (0.30.10) registered as a launchd agent, silently failing to bind 11434 while the app owned it and taking the port the instant the app stopped (caught answering `{"version":"0.30.10"}` mid-upgrade). Which Ollama served the lanes was decided by process start order. Service stopped; `brew uninstall ollama` still recommended.
- **Confound 2 — context, and it was the big one.** Odin defaulted this lane to **131072 ctx** while the Mac defaulted to **4096**, so Odin was allocating a 128k KV (10.56 GB, 9.66 GB in VRAM, partial CPU offload) to score 500-character items. Pinning `num_ctx: 4096` (`local_sentiment.py`, env `LOCAL_SENTIMENT_NUM_CTX`) loads 5.49 GB fully resident: −46.8% with **identical labels**.
- **The honest headline:** the first cross-host number (2.03×) was the smallest of the three. Version parity and context parity each moved it, to **3.75×** — and neither would have been found without insisting on the parity test rather than accepting a plausible-looking speedup.

**Implementation notes that matter more than the speedup:** every A/B row now carries a `host` field (both boxes report `model=qwen3.5:9b`, so `compare-sentiment.py`'s per-model windows could not otherwise tell them apart); the run's EXIT trap unloads **remotely** (`POST /api/generate {keep_alive:0}`, verified — `/api/ps` empty after the live 16:26 run) where the old local `ollama stop` would have silently stopped firing; and an unreachable Odin warns loudly instead of falling back to the local model, which would have blended two hosts into one stats window.
