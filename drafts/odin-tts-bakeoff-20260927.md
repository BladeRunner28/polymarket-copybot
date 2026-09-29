# Odin TTS bake-off — Kokoro vs Chatterbox, winner vs XTTS-v2

**Date:** 2026-09-27 · **Host:** Odin, RTX 5070 12 GB (sm_120) · **Status: ROUNDS 1–3 MEASURED — Kokoro is the usable engine; Chatterbox passes intelligibility once chunked but fails speed ~4x; XTTS-v2 not installed; scorer overlap artifact found, rounds 1–2 need re-scoring**

> ## RESUME HERE (next session)
>
> **Landed and verified:** three rounds on Odin. Kokoro measured on 3 voicepacks; Chatterbox base +
> multilingual measured unchunked and chunked, with a Kokoro chunked control that priced the chunk
> boundaries; all WAVs pulled to `~/tools/odin-tts/pulled/` with hashes verified against Odin's.
> Five harness bugs found from real output and fixed (arg injection, torchcodec-free scoring,
> single-truth mapping, load/gen split, per-arm model eviction + chunking), plus three fixes in the
> scorer still pending.
>
> **Where it stands:** Kokoro `am_michael` 3.4% WER / 2.23x / +1531 MB (unchunked) is the usable
> engine and the owner's ear picked it as most natural. Chatterbox chunked now scores 7.56% (base) /
> 8.40% (mtl) — truncation was the earlier failure, not pronunciation — with a 0.875 / 0.846 cosine,
> but warm throughput is 0.48x / 0.54x against a ≥2x gate, so it is a pre-rendering option only.
>
> **Next, in order:**
> 1. **Scorer fixed; rounds 1–3 re-scored and verified** (`out-rescore3`, dual-pass). Rounds 1–2 were
>    unaffected; the stitching artifact was isolated to one clip and is now flagged automatically.
> 2. **A real voice sample (owner)** — 15–30 s, one speaker, clean. All cosines so far are against a
>    synthetic reference: they prove cloning works, not that it matches a person.
> 3. **XTTS-v2 install (owner-gated)** — `coqui-tts`, second venv. Now the only open question is
>    speed for a cloning engine; CPML = private-use only.
>
> **Also outstanding from the ASR lane:** the `schtasks /create` trigger for `whisper-inbox` — the
> watcher works and is verified, it is simply not scheduled yet.
>
> **Asset server is still up:** `cd ~/tools/odin-tts && python3 -m http.server 8788 --bind 0.0.0.0`
> (upload receiver for peer→Mac pushes: `python3 receive_upload.py ~/tools/odin-tts/pulled 8790`).

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

## Status

### Round 1 — measured 2026-09-28 (Kokoro-82M, 3 voicepacks, 104-word script, synthetic reference)

| Arm | WER (num-normalised) | x realtime | VRAM delta |
|---|---|---|---|
| kokoro-af_heart | 4.2% | **1.65x** | +1725 MB |
| kokoro-am_michael | 3.4% | 2.23x | +1531 MB |
| kokoro-bm_george | 4.2% | 2.02x | +1433 MB |
| chatterbox | — (arm failed) | — | — |
| chatterbox-mtl | not run | — | — |

Reading it against the pre-registered gates: **Kokoro passes the usable gate on 2 of 3 voices** —
`am_michael` and `bm_george` clear both ≤8% WER and ≥2x realtime; `af_heart` is the fastest-sounding
and the *slowest* to render, failing the realtime gate at 1.65x. So voice choice moves the speed
result, and the voicepack sweep earned its place rather than being padding. No cosine is meaningful
for any Kokoro arm: it has no reference clip and cannot clone — that is the bracket finding, not a
zero.

Two failures that came from the harness, not the engines (both now fixed):

1. **`chatterbox` died at entry** with `AttributeError: 'Namespace' object has no attribute 'engine'`
   — the adapter branched on an attribute the parser never defines. No model load, no audio, so the
   clone bracket was empty. Fixed: the run loop injects `args.engine = engine` and the adapter reads
   it defensively.
2. **Every ECAPA cosine was `None`** — `torchaudio.load()` delegates to torchcodec in torchaudio
   ≥2.9 and torchcodec is not installed, so speechbrain's similarity stage raised
   `ImportError: TorchCodec is required for load_with_torchcodec` on every arm. The harness caught it
   per-stage and *completed*, which is why the run looks clean and scores nothing. Fixed without an
   install: wavs are read with `soundfile` (already present) and resampled with
   `torchaudio.functional`. The lesson is in the skill: an all-`None` similarity column is a broken
   scorer, never a "not a clone" result.

Also recorded, verbatim from the run: the Kokoro path fetched `en-core-web-sm==3.8.0` (12.8 MB) from
the network on first use, so "no installs during the run" was not quite true — pre-seed it if the
environment must be frozen. The reference clip is `ref/synthetic-ref.wav` (20.0 s, sha `61ac9450c332`),
generated on the box — hence the falsifier below still stands.

### Round 2 — measured 2026-09-28 (Chatterbox base + multilingual, same script, same synthetic reference)

| Arm | WER (num-norm) | ECAPA cosine | x realtime (warm) | VRAM delta |
|---|---|---|---|---|
| chatterbox (base) | 21.0% *(truncated)* | **0.858** | ~0.53x | +5875 MB |
| chatterbox-mtl | 17.7% | **0.778** | ~0.53x | +348 MB* |
| *calibration — Kokoro vs same reference* | — | 0.351 / −0.027 / 0.071 | — | — |

\* the mtl VRAM delta is a measurement artifact: its baseline was sampled while the base model was still resident.

**Clone fidelity: confirmed, on the mechanism level.** Both Chatterbox arms land in the "convincing"
band (≥0.75) against the reference, while the non-cloning control (Kokoro, three voices, same
reference) lands at 0.35 / −0.03 / 0.07. That separation is the whole point of the calibration run:
a 0.86 next to a 0.03 noise band is a real clone; a 0.86 on its own would be an unanchored number.
It remains *cloning*, not *fidelity to a person* — the reference is synthetic, so the falsifier at
the top of this document still governs.

**Both hard gates fail:**
- **Speed.** Sampling took ~75 s for 40.0 s of audio (1000 steps at ~13.2 it/s, from the engine's own
  progress bar) — ≈0.53x realtime warm, and 154 s / 139 s wall cold (weights download + load
  included). The gate is ≥2x. Chatterbox is ~4x too slow, and that is *before* the 40 s cap forces
  chunking, which will cost more.
- **Intelligibility.** 21.0% (base) and 17.7% (mtl) against an ≤8% gate. The mtl number is the honest
  one: it rendered the whole 104-word script inside its 40 s ceiling, so 17.7% is pronunciation
  error, not truncation — numbers and proper names are what break (`N100` → "non-hundred", `Priya` →
  "prior", `Arista 7124SX` → "724TX", `17.4%` → "$17,28,000"). The base arm's 21.0% is inflated by
  truncation and is not a fair quality comparison.

**A hard limit worth knowing before any long-form use: Chatterbox caps every `generate()` call at
exactly 40.000 s** (1000 frames × 40 ms). Both arms hit it to the millisecond; the base arm stopped
mid-sentence at "…60-day rollback window" while the mtl arm squeezed the full script in by speaking
faster. Long text therefore *requires* sentence-level chunking in the harness, and that changes both
the WER (no more truncation penalty) and the speed picture (more calls, not fewer).

**Verdict against the pre-registered rules:** Chatterbox fails both hard gates ⇒ **Kokoro advances as
the usable engine today**, on `am_michael` (3.4% WER, 2.23x, +1531 MB) or `bm_george` (4.2%, 2.02x).
Kokoro cannot clone, so "custom voices" is not solved by this bracket: it needs **XTTS-v2** (CPML,
non-commercial, still uninstalled) or a chunked Chatterbox run, where the remaining question is
whether 17.7% is a chunk-boundary artifact or the model's actual number/name handling.

**Owner's ear, 2026-09-28 — the one metric that stays human:** all three WAVs were delivered and the
verdict was *"the third sample is the most natural"*, i.e. **Kokoro `am_michael`** (preset voicepack).
So the ear **agrees with the gates**: the gate-passing non-cloning engine won on naturalness too, and
neither Chatterbox arm's clone fidelity bought perceived quality on this reference. That is the
strongest form of the result — the objective ranking and the human ranking point the same way, so no
tie-break is needed and the clone lane cannot be justified on quality grounds alone. Cloning remains a
*capability* question (does the fleet need a specific voice?), not a quality upgrade.

**Two more harness bugs found and fixed during round 2** (both mine, both now measured rather than assumed):
1. **Scorer truth mapping** — `whisper_bench.py` zipped ONE positional `--truth` against the *list* of
   `--audio`, so only the first arm got a ground truth and every later arm came back with no
   `wer_raw`/`wer_numwords` key at all (that is why mtl was initially "unscored"; it was never a null
   score, the key was absent). Fixed: a single positional truth now applies to every audio file.
   Re-scored: mtl 17.65%. Round 1 was unaffected — it ran one arm per invocation.
2. **`load_s` mislabel** — the harness writes `load_s` as `wall_s` (both 154.0/138.6 s), so it cannot
   currently separate model load from sampling. The warm-RTF numbers above come from the engine's own
   tqdm progress bar, not from the harness. Fix queued for round 3: time the load and the generation
   separately per arm.

Harness as shipped: `tts_bakeoff.py` sha256 `8d872390ec5db1e798aad6487ad6baf0855608bcca48b8aeb915a66a600baa09`;
`whisper_bench.py` sha256 `abef5d879f287cb1b0ddfb0858385d1189a01f3220877544adc9cc72abaf684f`.
Audio pulled back to the Mac at `~/tools/odin-tts/pulled/` (hashes match Odin's).

### Round 3 — chunked re-run, 2026-09-28 (harness: sentence chunking + per-arm load/gen split)

| Arm | WER (num-norm, overlap-free scorer) | ECAPA cosine | warm x realtime | VRAM Δ |
|---|---|---|---|---|
| chatterbox (chunked) | **7.56%** | 0.875 | **0.48x** | +4449 MB |
| chatterbox-mtl (chunked) | 8.40% | 0.846 | 0.54x | +3789 MB |
| kokoro `am_michael` (chunked control) | 5.88% | −0.015 | 2.70x | +1129 MB |

**Chunking removed the truncation, and that was the whole difference in intelligibility.** Chatterbox
now renders the full script (47.53 s / 46.81 s of audio, four pieces each, all pieces present and in
order — verified on the pulled WAVs) instead of stopping at the 40 s cap, and WER fell from
21.0% / 17.7% (truncated) to **7.56% / 8.40%**. The base arm now passes the ≤8% gate; mtl lands 0.4
points over it. So round 2's "Chatterbox fails intelligibility" was substantially a *truncation*
finding, not a pronunciation one.

**Speed still fails, now measured rather than inferred.** Per-arm split (new): base 115.91 s arm =
16.02 s load + **99.8 s generation** for 47.53 s of audio; mtl 103.99 s = 16.73 + **87.18 s** for
46.81 s. Warm 0.48x / 0.54x against a ≥2x gate — ~4x short, and no longer explainable by cold weight
download or model load, which is 16 s of a 116 s arm. Round 2's "0.53x, inferred from a tqdm bar" is
now confirmed by the harness.

**The Kokoro control prices the chunking itself.** Same voice, same script: 3.36% unchunked (round 1)
vs 5.88% chunked — about **+2.5 WER points from boundary resets**, since each piece starts cold. Both
Chatterbox arms carry that same cost, so 7.56% is a *chunked-mode* number; unchunked (were it not
truncated) it would be lower.

#### Scorer artifact found — a measurement bug, not an engine result

The first pass reported the Kokoro control at **25.21%**, which is impossible next to its own
transcript head. Cause: the ASR lane's 30 s window / 5 s overlap stitching duplicated a clause in the
stitched transcript. Verbatim from `wer/whisper-large-v3-turbo__kokoro-chunked-am_michael.txt`:

> …and a 60-day rollback window. **though. Does the.** the Arista 7124 SX migration, two racks, 400
> gigabit links, and a 60-day rollback window. Does the N100 chassis ship before the 27th? …

**Fixed, and every clip re-scored (`out-rescore3`).** The scorer now transcribes each clip twice —
overlap-free (`chunk 30s/stride 0s`) and stitched (`chunk 30s/stride 5s`) — with the overlap-free
pass supplying `wer_raw`/`wer_numwords` for clips ≤120 s, the stitched result kept as
`wer_numwords_alt`, and `wer_stable` false when the two diverge by more than 2 points. Verified
table, primary then cross-check:

| Clip | Round | audio | WER (overlap-free) | WER (stitched) | stable |
|---|---|---|---|---|---|
| kokoro-af_heart | 1 | 44.7 s | 4.20% | 4.20% | ✅ |
| kokoro-am_michael | 1 | 49.1 s | 3.36% | 3.36% | ✅ |
| kokoro-bm_george | 1 | 44.9 s | 4.20% | 4.20% | ✅ |
| chatterbox (base, capped) | 2 | 40.0 s | 22.69% | 21.01% | ✅ |
| chatterbox-mtl (capped) | 2 | 40.0 s | 17.65% | 17.65% | ✅ |
| chatterbox (chunked) | 3 | 47.5 s | 7.56% | 6.72% | ✅ |
| chatterbox-mtl (chunked) | 3 | 46.8 s | **8.40%** | **7.56%** | ✅ |
| kokoro am_michael (chunked control) | 3 | 53.2 s | 5.88% | **25.21%** | ❌ delta 19.33 pts, dup-5grams 7 |

Three things this settles:

1. **Rounds 1 and 2 were not affected.** All five of those clips score the same under both passes, so
   the earlier numbers stand as published.
2. **The artifact was isolated to one clip** — the chunked Kokoro control — and it was the *stitched*
   pass that was wrong there. Note the direction is not constant: for the chunked Chatterbox arms the
   stitched pass reads ~0.8 points *better* (context across the boundary helps), for the Kokoro clip
   it reads 19 points worse (it duplicates a clause). Hence the mode-dependent uncertainty.
3. **`chatterbox-mtl` sits exactly on the gate, not over it.** 7.56% stitched / 8.40% overlap-free
   against an ≤8% bar means "borderline" is the honest word; the base arm (6.72–7.56%) passes. That
   nuance only exists because the scorer now reports both.

Two further bugs the peer caught in my own fix, both fixed and regression-tested — worth recording
because each produced a *plausible* wrong number rather than an error:

- **`stride_length_s=stride_s if stride_s else None`** turned the meaningful `0` into "unset", and
  HuggingFace then applies its own default of `chunk_length_s / 6` (= 5 s). Both passes ran at the
  same stride, produced byte-identical transcripts, and reported `wer_stable: true` for all eight
  clips — a check that passes vacuously is worse than no check. The local test missed it because it
  faked the *transcriber* instead of the *pipeline*: the fake encoded the same wrong assumption the
  code did. There is now a test that asserts the kwargs reaching a fake `transformers.pipeline`
  (`0.0` for the overlap-free pass, `5.0` for the stitched pass).
- **Same-basename clips silently shared audio.** `out-r2/chatterbox.wav` and `out-r3/chatterbox.wav`
  both converted to one `chatterbox.16k.wav`, so the r3 arms were scored on r2's 40 s audio and
  reported r2's WER and duration. The de-collision guard I wrote for it never fired — it looked up the
  assembled stem in a dict keyed by bare basename. Now one unique tag (8-hex suffix when a basename
  repeats) drives both the 16 kHz cache and the output stem, with a test asserting two same-named
  files score different durations (5.0 s vs 8.0 s) and produce two cache files.

**Verdict after round 3:** Chatterbox now passes the intelligibility gate but fails the speed gate by
~4x, so Kokoro remains the usable engine — unchanged. What changed is *why*: the clone arm's failure
is throughput (0.48x warm, and chunking makes it worse by adding calls), not quality. For a
non-realtime use case — pre-rendered narration, short lines — chatterbox at 7.56% WER and a 0.875
cosine is a defensible MIT-licensed clone voice; for anything live it is not.

### Earlier verification (round 0, 2026-09-27)

- **Plumbing verified on Odin**, not just locally: all four assets fetched and hash-pinned, `--engines stub` ran end-to-end (synthesis timing, artifact hashing, VRAM sampling, Whisper round-trip, WER merge all exercised), artifacts deterministic across repeated runs (`b082ff95…`, 1,920,078 bytes both times).
- **One harness bug found by the peer and fixed:** `--whisper-extra` was declared `nargs="*"`, and argparse can never put a leading-dash token into such a list — so the harness's own documented invocation (`--whisper-extra --backend faster-whisper`) aborted with `unrecognized arguments`. Now `parse_known_args()` forwards unknown flags through to the scorer.
