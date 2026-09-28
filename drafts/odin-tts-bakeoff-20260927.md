# Odin TTS bake-off — Kokoro vs Chatterbox, winner vs XTTS-v2

**Date:** 2026-09-27 · **Host:** Odin, RTX 5070 12 GB (sm_120) · **Status: PRE-REGISTERED, INSTRUMENTED, NOT YET RUN**

> ## RESUME HERE (next session)
>
> **Landed and verified:** harness + eval assets on Odin in `C:\Users\Xander\tts-bakeoff\` (all four
> hashes pinned and re-verified), stub run exercised every code path, harness bug found by the peer
> and fixed. Mac source of truth: `~/tools/odin-tts/`.
>
> **Pending, in order:**
> 1. **TTS install (owner-gated)** — the block in "Plan of record" step 1: dedicated venv
>    `C:\Users\Xander\tts-bakeoff\venv`, torch cu128 + `kokoro soundfile espeakng-loader chatterbox-tts
>    speechbrain transformers`. ~4–6 GB, 10–20 min. Then re-fetch `tts_bakeoff.py` at
>    `19cf334b354ce2ab6e2d23dbbd3285b51d4e1b84f4d885914d34bb62985dedc1` (the peer's copy is the
>    pre-fix revision).
> 2. **Round 1:** Kokoro (3 voicepacks) + Chatterbox on the synthetic reference → WER, ECAPA cosine,
>    RTF, VRAM; deliver WAVs for the owner's ear.
> 3. **A real voice sample (owner)** — 15–30 s, one speaker, clean. Without it the round-2 cosine
>    cannot be interpreted as fidelity to a human voice.
> 4. **Round 2:** winner vs XTTS-v2 (`coqui-tts`, second venv — its dependency pins are hostile).
>
> **Also outstanding from the ASR lane:** the `schtasks /create` trigger for `whisper-inbox` — the
> watcher works and is verified, it is simply not scheduled yet.
>
> **Nothing is running overnight:** no LAN file server is up, nothing is scheduled on Odin, and no
> GPU job is resident. Restart the asset server with
> `cd ~/tools/odin-tts && python3 -m http.server 8788 --bind 0.0.0.0` (swap the directory for
> `~/.hermes/cache/scratch/whisper-test` when re-serving the ASR assets).

Companion to the ASR work: [`odin-whisper-transcription-20260927`](odin-whisper-transcription-20260927). Whisper runs audio → text; this is the other direction, and the same Whisper harness scores the output.

## The bracket (owner's call, 2026-09-27)

- **Round 1 — Kokoro-82M vs Chatterbox** (both permissive licences; only Chatterbox clones)
- **Round 2 — Round-1 winner vs XTTS-v2**, cloning from the **same reference clip**, same script, same metrics

**Why Kokoro is in a cloning bracket at all:** it cannot clone, so it cannot win the dimension that matters. It enters as the *permissive baseline* — if Chatterbox fails a hard gate, Kokoro is what remains usable today, and its naturalness result is the bar Chatterbox must beat to justify the install.

## Engines, as of 2026-09-27 (facts checked, not assumed)

| Engine | Params / size | Licence | Clones? | Reference needed |
|---|---|---|---|---|
| Kokoro-82M | 82M, ~327 MB weights, <2 GB VRAM, CPU-capable | **Apache-2.0** (weights) | **No** — fixed voicepacks | none |
| Chatterbox | 0.5B | **MIT** | Yes, zero-shot | **~5 s** clip |
| XTTS-v2 (Coqui) | ~1.8 GB | **CPML — non-commercial** | Yes, zero-shot | 6–30 s clip |

Notes that matter operationally:
- **Kokoro needs espeak-ng** for out-of-dictionary words and non-English G2P. On Windows that is normally an MSI; `espeakng-loader` ships the binaries via pip and avoids the installer.
- **Chatterbox outputs are watermarked** (Resemble's PerTh, imperceptible). Harmless for WER, but it means "clean output" is not literally clean, and it is worth knowing before anything is published.
- **Chatterbox wants Python 3.10 on Windows** — 3.11+ forces `onnx` to build from source. Odin's Python310 is exactly right.
- **XTTS-v2 must come from the maintained fork** (`coqui-tts` on PyPI, Windows wheels since 0.24.2); the original `pip install TTS` is abandoned and capped at Python 3.11.

## Assets (already written, hashes pinned per file)

- `eval-script.txt` — 104 words, fixed script covering digits, ordinals, currency, percent, a proper name, acronyms, question/colon/em-dash punctuation, and a long clause. **Doubles as the WER ground truth** — the only reason an objective intelligibility number is possible.
- `eval-short.txt` — "Acknowledged. Testing one, two, three. Done." Short-input stability check.
- `tts_bakeoff.py` — harness. Per engine, sequentially, never concurrently: synthesize → time it → poll VRAM → round-trip through Whisper for WER → ECAPA cosine against the reference.
- `whisper_bench.py` — reused unchanged from the ASR work; it is the scoring half.

## Metrics, and why each one

1. **Intelligibility — round-trip WER** (number-normalised), via Whisper `large-v3-turbo`. Objective, and the same harness that produced 5.1% on the ASR side.
2. **Clone fidelity — ECAPA-TDNN speaker-embedding cosine** between synthesized audio and the reference (`speechbrain/spkrec-ecapa-voxceleb`; the standard objective measure in the zero-shot TTS literature, where it tracks listening tests). Reported **only** for clone-capable engines — "N/A" for Kokoro is the finding, not a gap.
3. **Cost — RTF / x-realtime**, cold-load and warm separated, plus **peak VRAM** polled during synthesis. VRAM is reported as a *delta* against a sampled baseline, because `memory.used` includes the Windows display tax (~2.7 GB idle on this box).
4. **Friction** — install result, library versions, licence, watermark, and any failure recorded verbatim in the artifact.

## Pre-registered gates (fixed before any number exists)

**Hard gate — usable:** round-trip WER (number-normalised) **≤ 8%**, and **≥ 2x realtime** (RTF ≤ 0.5). Fail either ⇒ the engine is out, regardless of how pleasant it sounds.

**Hard gate — clone-capable engines only:** ECAPA cosine vs the reference —
- **≥ 0.75** convincing clone · **0.65–0.75** same family, not the same person · **< 0.65** not a clone.
- Below 0.65 on both clone arms ⇒ the answer to "can we do custom voices?" is *not with these*.

**Decision rules:**
- **Round 1:** Chatterbox advances if it passes both hard gates. Kokoro advances only if Chatterbox fails one — otherwise Kokoro's role is the fallback narration voice, scored on WER/speed alone.
- **Round 2:** primary = ECAPA cosine; WER must pass; RTF and VRAM break ties.
- **Licence is a shipping gate, not a quality gate:** if XTTS-v2 wins on quality but CPML blocks the intended use, the permissive winner ships and XTTS-v2 is documented as the private-use option.

**What would falsify the whole exercise:** if the reference clip used for cloning is itself synthetic (round 1 uses one, as a mechanism check), the cosine measures "can it clone at all", **not** fidelity to a human target. Only a real voice sample makes the round-2 number meaningful — which is why one is being requested.

## Plan of record

1. **Owner authorizes / runs the install block** (dedicated venv at `C:\Users\Xander\tts-bakeoff\venv` — isolation chosen deliberately so TTS dependency pins cannot churn the torch build the Whisper lane's fallback uses).
2. Fetch harness + assets, pin hashes, smoke test with `--engines stub` (proves the plumbing before any GPU time).
3. **Round 1:** Kokoro (voicepack sweep: 3 voices) and Chatterbox on the synthetic reference → WER, cosine, RTF, VRAM.
4. Deliver the WAVs for the owner's ear (naturalness is the one metric that stays human).
5. **Round 2:** winner vs XTTS-v2, same script, same reference, second venv.
6. Verdict against the gates above, in this document, plus the dashboard copy.

## Status — nothing measured yet; harness verified on the target box

- **Plumbing verified on Odin**, not just locally: all four assets fetched and hash-pinned, `--engines stub` ran end-to-end (synthesis timing, artifact hashing, VRAM sampling, Whisper round-trip, WER merge all exercised), artifacts deterministic across repeated runs (`b082ff95…`, 1,920,078 bytes both times).
- **One harness bug found by the peer and fixed:** `--whisper-extra` was declared `nargs="*"`, and argparse can never put a leading-dash token into such a list — so the harness's own documented invocation (`--whisper-extra --backend faster-whisper`) aborted with `unrecognized arguments`. Now `parse_known_args()` forwards unknown flags through to the scorer, with the forwarded list logged. Re-verified locally against a stub scorer; `tts_bakeoff.py` re-pinned at `19cf334b354ce2ab6e2d23dbbd3285b51d4e1b84f4d885914d34bb62985dedc1`.
- **Still zero TTS engines installed on Odin.** The install is gated on the owner: Odin's peer agent will not accept a relayed approval, and a dedicated venv is being used deliberately so TTS dependency pins cannot churn the torch build that the transcription lane's fallback depends on.

*Ask: one copy-paste block from the owner, or an authorization in Odin's own session.*
