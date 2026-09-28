# Odin — local transcription pipeline (Whisper) — build + measurement

**Date:** 2026-09-27 · **Host:** Odin, Win11 Pro, i9-12900K, 63.7 GiB RAM, RTX 5070 12 GB (driver 13.4) · **Driven over A2A from the Mac head (192.168.1.10)**
**Model:** `openai/whisper-large-v3-turbo` fp16 (1.6 GB, HF cache, no auth) · **Artefacts on Odin:** `C:\Users\Xander\whisper-bench\`
**Protocol:** both backends run sequentially (never concurrently — GPU contention corrupted an earlier pass), each on the same two files, same model, one warm-up-exposed first call per backend.

## Headline

**The backend is worth 3.8–9.8x, and it costs one DLL path.** CTranslate2 (faster-whisper) does a 6.4-minute recording in **11.1 s of inference** (34.9x realtime) — and **21 s wall for the entire job**, ffmpeg normalisation + transcription + local-LLM summary included. The transformers pipeline needs 38.4 s of inference alone on the same file with the same weights. Accuracy is a wash — the honest limitation is not speed, it's **timestamps on repeated/looping audio**, where the chunked transformers pipeline collapses entire minutes into one segment.

## Clean head-to-head (identical audio, sequential runs, RTX 5070)

| backend | audio | infer | x realtime | segments | WER raw | WER num-norm |
|---|---|---|---|---|---|---|
| faster-whisper | 96.5 s | **2.65 s** | **36.4x** | 18 (VAD) | 11.91% | 5.76% |
| faster-whisper | 386.0 s | **10.1 s** | **38.2x** | 55 (VAD) | 11.81% | 5.14% |
| transformers | 96.5 s | 25.85 s | 3.73x | 7 (chunk 30/5) | 12.77% | 6.17% |
| transformers | 386.0 s | 38.36 s | 10.06x | 9 (chunk 30/5) | 11.17% | 4.63% |

- **Speed:** 3.8x on the long clip, 9.8x on the short one.
- **Accuracy:** too close to call (faster-whisper wins the short clip, transformers the long one, both 5–6% after number normalisation). They do not even segment the same way — VAD gives 55 segments where chunking gives 9 — so a WER spread this small is within the segmentation difference, not a quality difference.
- **Warm-up is a measurement artefact, and it lands differently.** Decomposing transformers as `infer = F + r·audio`: `r = 0.0432 s/s`, `F ≈ 21.7 s` — the first call pays ~22 s of CUDA init *inside `infer_s`*. faster-whisper's equivalent cost lands in `load_s` (1.8–2.1 s) and its first inference showed no penalty. Throughput per audio-minute: **34.9x vs 9.5x including load**.
- Not comparable: faster-whisper reports `peak_vram_gb: null` (CTranslate2 exposes no `max_memory_allocated`); transformers measured **1.87 GB peak**. So "fits comfortably in 12 GB alongside the summariser" is measured for transformers and only inferred for faster-whisper.

## End-to-end pipeline (the actual deliverable)

`transcribe.py <file-or-dir> [--outdir D] [--summarize] [--backend auto]` — ffmpeg → 16 kHz mono → Whisper → `<stem>.md / .json / .txt`, then optional summary + action items from local Ollama.

Verified on Odin, 386 s clip, `--backend auto` (resolves to faster-whisper) + `--summarize`:

```
[19:13:34] backend faster-whisper | model openai/whisper-large-v3-turbo
[19:13:34] normalising meeting-clip-long.wav -> 16kHz mono
[19:13:35] transcribing 386.0s of audio with openai/whisper-large-v3-turbo
[19:13:48] summarising with gemma4:12b-it-qat
[19:13:55] wrote transcripts-fw\meeting-clip-long.md  (34.9x realtime, RTF 0.029)
[19:13:55] complete: 1 transcribed, 0 failed
```
**21 s wall for a 6.4-minute recording, transcript + summary + action items.** Idempotent (skips files that already have a `.json`), so pointing it at a folder on a schedule is safe.

Run line on Odin:
```
python transcribe.py <file-or-dir> --outdir transcripts --summarize \
  --cuda-lib-dir "C:/Users/Xander/AppData/Local/Programs/Python/Python310/Lib/site-packages/torch/lib"
```

**The summarisation leg works on messy input.** `gemma4:12b-it-qat` (7 s) extracted the three named owners and the implicit deadline correctly from the transcript, including the one masked by a number-formatting difference: `Marcus: send the switch throughput numbers · Dana: confirm the N100 ship date · Priya: reconcile the power invoice (Monday)`.

## What the errors actually are

Raw WER (11–13%) is dominated by a **formatting convention, not mishearing**: Whisper emits digits/punctuation where the speech contains spelled-out text — `twenty-fourth → 24th`, `four hundred gigabytes per second → 400GB per second`, `sixty degrees → 60`, `ninety-seven percent → 97%`, `eleven cents → 11 cents`, `$16`, `250 watts`, `96%`. Normalising numbers/ordinals ("the twenty fourth" == "the 24th") drops WER to **4.6–6.2%**.

What survives normalisation is **proper nouns**, which is exactly what a meeting note must get right:
- `Oyelaran → Oyeloran` (a genuine mishearing, the only one in the clean pass)
- `Arista 7124 SX → Arista 7124SX`, `rackmount N100 → rack mount N100` (spacing)
- `Procurement Sync → Procurement Sink` (one instance, inside the degenerate segment below)

## The timestamp failure (read this before wiring it to anything)

On the 386 s clip the **transformers chunked pipeline** (`chunk_length_s=30`, `stride_length_s=5`) produced a segment at `00:01:24` containing **3,797 characters** — the whole recording repeated verbatim three more times, as one run-on segment — then resumed normal granularity at `00:06:06`. Transformers itself warns that `chunk_length_s` is *"very experimental with seq2seq models"* and recommends long-form `generate` instead.

Two things follow:
1. **faster-whisper's VAD segmentation is materially more usable** for anything where you want to jump to a moment (55 segments vs 9, no collapse).
2. **The test clip is worst-case by construction** — the 386 s file is the same 96.5 s audio concatenated 4x, which is precisely the input that provokes Whisper's repeat/degeneration behaviour. Real, non-looping audio should behave better — **untested**.

## Scope limits (do not overquote these numbers)

- **Ground truth is TTS** (edge neural voice): one clean synthetic speaker, no crosstalk, no compression, no accent. **5% WER is a floor, not a prediction** for real meeting or phone audio.
- **One content sample**, of which the "long" file is a concatenation of the "short" one. Effective n = 1, at two durations.
- **No diarization** — nobody knows who said what; that needs pyannote, not Whisper.
- **No real-audio test** (voice memo through a phone mic, Zoom capture, or a room recording) has been run.
- faster-whisper VRAM unmeasured (above); timestamps on organic long audio untested.

## Pitfalls found and fixed

1. **faster-whisper has its own model aliases.** `openai/whisper-large-v3-turbo` is rejected (`ValueError: Invalid model size`); it needs `large-v3-turbo`. The harness now strips the `whisper-` prefix.
2. **CTranslate2 does not bundle CUDA 12 / cuDNN 9 DLLs.** On Windows the CUDA path dies with `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded` unless those DLLs are on PATH — they live in the *torch* install's `torch/lib` (Python310), not in the faster-whisper venv. `transcribe.py` now takes `--cuda-lib-dir` / `TRANSCRIBE_CUDA_LIB` and `auto` falls back to transformers if CUDA still fails.
3. **A wedged CUDA process silently inflates every later timing.** A failed 19:02 run held a CUDA context and inflated the next short-clip measurement from 2.65 s to 19.6 s (~7x) with *identical* WER. Kill and verify VRAM before trusting a speed number.

## Files

- **Source of truth (Mac):** `~/tools/odin-whisper/` — `whisper_bench.py` (bench + WER harness), `transcribe.py` (pipeline), test clips + ground truth, `SHA256SUMS`. (The scratch copy under `~/.hermes/cache/scratch/` is pruned after 24 h — do not keep the only copy there.)
- **Odin:** `C:\Users\Xander\whisper-bench\` — same tools + `bench-out/ bench-tf-clean/ bench-fw-clean/` results, `transcripts/ transcripts-fw/`, and the deployment files (`watch.py`, `watch.cmd`). Both tools are in sync with the Mac copy as of 2026-09-27 19:25 (`watch.py` 6390cc73…, `transcribe.py` 226fba5c…).

## Deployment — drop folder on Odin

**Wired 2026-09-27, verified on the box.**

- **Inbox:** `C:\Users\Xander\whisper-inbox\` — drop audio/video here (mp3, wav, m4a, mp4, mkv, mov, webm, flac, ogg…).
- **Out:** `C:\Users\Xander\whisper-out\<stem>.md | .json | .txt` + `whisper-watch.log`. The `.md` is the transcript with timestamped segments plus the summary and action items.
- **After success** the source moves to `whisper-inbox\_done\` (timestamp-prefixed if the name recurs, never clobbered), so the inbox always shows what is still outstanding.
- **Runner:** `C:\Users\Xander\whisper-bench\watch.cmd` → `watch.py` → `transcribe.py`. The `.cmd` pins the absolute interpreter path **and** prepends `Python310\...\torch\lib` to `PATH` (the CTranslate2 CUDA requirement), so it does not depend on the scheduler's environment.
- **Log:** `whisper-out\whisper-watch.log` — one line per file, plus `OK … (Ns) -> path` or `FAILED …` with the error tail.

**Idempotence is keyed on content, not filename** — this matters because a drop folder gets the same name reused (`meeting.m4a`, every week). `transcribe.py` now records `source_sha256`/`source_bytes`; `watch.py` decides per file:
- identical content already transcribed → **skip** (source still gets filed away)
- same name, different content → transcribe as `<stem>__<YYYYmmdd-HHMMSS>`, **nothing overwritten**
- transcription fails → `<name>.failed` marker written next to it; the file is skipped until the marker is deleted (so one corrupt file cannot hot-loop every run)

**Test evidence (real pipeline, on Odin, not a stub):** three drops of `meeting.m4a` under one name — clip-a → `meeting.*`; clip-long (different content) → `meeting__20260927-192707.*`; clip-a again (identical) → `skip (identical content already transcribed)`. All three runs exit 0, inbox empty afterwards, `_done\` holds all three distinct sources with nothing overwritten. Earlier dry run: `dryrun.m4a` → 11.9 s → `.md/.json/.txt`.

**Not yet scheduled — one owner action outstanding.** Odin's peer agent will not create a persistent host-level scheduled task on a relayed approval, so the 5-minute trigger has to be registered by the owner (or authorized by him in Odin's own session):

```
schtasks /create /tn "whisper-inbox" /tr "C:\Users\Xander\whisper-bench\watch.cmd" /sc minute /mo 5 /f
```
Rollback is `schtasks /delete /tn "whisper-inbox" /f`. Verify with `schtasks /query /tn "whisper-inbox" /v /fo LIST`, force one fire with `schtasks /run /tn "whisper-inbox"`, then read `whisper-out\whisper-watch.log`.

**Optional hardening (also gated on owner authorization):** `pip install --upgrade faster-whisper` into `Python310` would remove the wrapper's dependency on the Hermes venv (which Hermes itself may rebuild) and make the transformers fallback reachable from one interpreter. Dry-run audited by the peer: 8 packages, all new, **zero** existing packages upgraded or downgraded. Not required for the current setup to work.

## Verdict

**Ship faster-whisper as the default backend, keep transformers as the fallback.** faster-whisper is 3.8–9.8x faster at equal accuracy and produces the more usable segmentation; transformers is the zero-setup path (no DLL juggling), is the only backend that reports VRAM, and is the safety net when CUDA libs are missing. The pipeline is proven end-to-end on Odin and is safe to schedule (idempotent). Nothing is scheduled yet.

**Not yet earned:** any claim about accuracy on real audio, and any claim about timestamps on organic long recordings.
