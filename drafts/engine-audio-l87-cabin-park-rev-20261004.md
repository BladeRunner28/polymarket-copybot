# Cabin park-rev clip with the tachometer in frame — 2021 Silverado L87 6.2L (2026-10-04, afternoon)

**Source file:** `clip-drive.mp4` (name is misleading — see §1), HEVC 3840×2160 @ 59.94 fps, 23.81 s,
AAC 48 kHz stereo, 155,429,264 bytes. Audio decoded to mono 48 kHz for analysis
(`~/video-in/mono48k.wav`, 23.74 s): RMS **−31.8 dBFS**, peak **−14.98 dBFS**, **0 clipped samples**.

## Verdict up front

Three findings, in order of how much they change the picture:

1. **This is not a driving clip.** The instrument cluster says **PARK / P, 0 mph, 56 359 mi, "Fuel Level
   Low", AUTO STOP OFF** at every timestamp I checked. It is a **stationary rev in Park** recorded with
   the phone on the dash, which is actually the *better* test of "does the whine follow rpm" — no road
   or wind noise to hide behind.
2. **The tachometer is real data and it is now extracted frame by frame**: idle **673 rpm**, ramp
   12.5→16 s, plateau **2438 rpm** (16.0–18.5 s), then back to **526 rpm** by 21–23.8 s — an **rpm span
   of 3.6×**. The needle is verified against the dial numerals at three timestamps (t = 12, 17, 21 s).
3. **Nothing in the audio follows rpm.** Every prominent tonal line sits at a near-constant frequency
   while the engine speed doubles: the dominant low line runs **164.1 Hz → 172.1 Hz → 172.9 Hz** as rpm
   goes **1200 → 1850 → 2440** (+5.4% frequency for +103% rpm). The validated order scan (control ladder
   in §3) found **no rpm-locked tone anywhere from 250 Hz to 8 kHz** — down to ~0.10× the recording's RMS
   below 3.5 kHz and 0.30× above it. A clip that carries its own rpm timeline, then, does not reproduce
   the pitch-tracking whine he hears.

What *is* in the clip is a **fixed-frequency family** — ~64.5, ~165–173, ~240–261, ~310, ~368, ~415, ~610,
~750, ~1519, ~2616, ~3206 Hz — which **grows 9–20 dB louder when the engine is revved** but does not
change pitch with it. That is the signature of resonances / fixed-speed devices being excited harder, not
of something whose rotation speed is tied to the crank.

---

## 1. What the file actually contains

| Property | Value | How |
|---|---|---|
| Duration | 23.81 s (video), 23.74 s (decoded mono audio) | `ffprobe`, sample count |
| Video | HEVC 3840×2160, 59.94 fps, 52.2 Mbit/s | `ffprobe` |
| Audio track | AAC, 48 kHz, stereo, ~194 kbit/s | `ffprobe` |
| Cluster at t = 17 s | **PARK**, PRNDL = P, **0 mph**, odometer 56 359 mi, "Fuel Level Low", AUTO STOP OFF | full-frame read |
| Cabin vs hood | cabin microphone (phone on the dash), engine ~1.5–2 m forward | frame content |
| Recording level | RMS −31.8 dBFS, crest 16.8 dB, no clipping | sample domain |

The engine-off / start / idle / rev timeline is recoverable from the tach (below) and matches what the
audio does: silence-ish → crank → idle → rev → back to idle.

## 2. The rpm timeline, extracted from the video and checked three ways

Method (carried over from yesterday's tach work): the dial centre and the tick ring are re-fitted in every
frame (top-hat mask on small bright features + Kasa circle fit, ±45 px prior), and the needle is found as
the elongated red component; its tip angle is converted with the dial-fixed geometry
(0 rpm at 276.69° clockwise from 12 o'clock, 29.209° per 1000 rpm) measured off the dial's own numerals.
476 samples at 20 fps.

| Phase | Time window | rpm (median) | range |
|---|---|---|---|
| Engine off (needle below the 0 mark) | 0–4.0 s | — | needle parked below zero |
| Cranking / start flare | 4.0–10.0 s | — | needle tracker unreliable here (motion blur) |
| Idle | 10.5–12.5 s | **673** | 617–911 |
| Ramp up | 12.5–14.0 s | 1185 | 945–1441 |
| Ramp up | 14.0–15.5 s | 1696 | 1450–1914 |
| Plateau ("the rev") | 16.0–18.5 s | **2438** | 1982–2512 |
| Fall | 19.5–21.0 s | 1166 | 742–2043 |
| Back to idle | 21.0–23.8 s | **526** | 458–753 |

**Verification by eye against the dial** (overlay frames in the evidence list): t = 12 s → needle at
≈ 0.67 × 1000 rpm ✓ matches the trace's 673; t = 17 s → ≈ 2.4 × 1000 ✓ matches 2438; t = 21 s → ≈ 0.6 ×
1000 ✓ matches 526. The drawn 1000…6000 rpm rays land on the dial's digits 1…6, so the scale is right.

Plateau 2438 rpm ⇒ crank **40.63 Hz**, and a 4-stroke V8 fires at order 4 ⇒ **162.5 Hz**. Worth holding
onto: the strongest low line during the rev is at **172.9 Hz**, which is *not* 162.5 Hz — the engine's
firing line is not the dominant line here.

## 3. Is any tone tied to rpm? The instrument, and why it needed validating

The naive test — "walk a candidate order through the spectrogram and average" — fails on real recordings
for two reasons I hit in this session and had to fix:

- **Averaging over all frames hides a tone that only exists during the rev.** Fixed by scoring
  *persistence* (fraction of frames above +8 dB) and the 75th percentile, not just the mean.
- **A phone video's audio track can be offset from its video by tenths of a second**, which smears a
  swept tone across several orders. Fixed by scanning the time offset as a free parameter
  (Δ = −1.5 … +1.5 s in 0.05 s steps).

So the instrument is a joint **(Δt, order)** scan on a whitened spectrum (0.34 s Hann window, 0.043 s hop,
1.46 Hz bins, ±150 Hz median envelope removed), and it is only trusted because of this control ladder —
synthetic tones whose frequency *is* order 20 × the tach rpm, injected into this exact recording:

| Injection | Recovered | Score (p75) | Frames > 8 dB | Verdict |
|---|---|---|---|---|
| order 20 at 0.30 × RMS | order 19.96 **@ Δt = 0.00 s** | +16.4 dB (mean) | 157 frames | found, offset pinned |
| order 20 at 0.10 × RMS | order 19.96 **@ Δt = 0.00 s** | +12.9 dB | 45.9 % | found, offset pinned |
| order 20 at 0.03 × RMS | not recovered | — | — | **below the detection limit** |
| order 150 at 0.30 × RMS, 3–8 kHz scan | order 150.10 **@ Δt = −0.05 s** | +19.3 dB (mean) | 59.5 % | found — and this one is in-band only during the rev |

Two useful by-products: the audio/video offset of this recording is **≈ 0** (the injected tone pins at
Δt = 0.00 s, and score collapses to +3 dB at ±0.3 s), and the detection limit for an rpm-locked tone is
between **0.03 and 0.10 × the recording's RMS** (≈ 30–35 dB below the take's overall level).

## 4. Result: no rpm-locked tone in this take

Running the validated scan on the real audio (250–3500 Hz, 3.6× rpm span, 293 usable frames):

| Rank | Δt | order | Score (p75) | Frames > 8 dB | What it is |
|---|---|---|---|---|---|
| 1 | −0.05 s | **6.42** | +13.2 dB | 43.3 % | the ~260 Hz line, present only during the rev |
| 2 | −1.20 s | 5.68 | +8.6 dB | 50.0 % | fluke (10 frames only) |
| 3 | +0.60 s | 17.26 | +7.2 dB | 20.7 % | noise |
| 4 | +1.50 s | 6.92 | +7.1 dB | 20.3 % | noise |

The best candidate scores the same as the 0.10 × RMS control — but the control appears at a **single
pinned offset** while the real candidate appears at Δt = −0.05 s with nothing coherent around it, and its
"order" is the arithmetic artefact of one fixed line: the ledger in §5 shows the 260.7 Hz line is
**absent at idle and at coast-down**, i.e. it is not a harmonic that exists at all engine speeds.

The ramp makes the same point without any order model at all:

| Low-band census (80–420 Hz) | rpm (median) | Strongest line | 2nd |
|---|---|---|---|
| 13.0–14.4 s | ~1200 | **164.1 Hz** +11.2 dB (98 % frames) | 232.9 Hz +3.3 |
| 14.6–16.0 s | ~1850 | 104.0 Hz +10.1 (77 %) | **172.1 Hz** +6.8 (76 %) |
| 16.0–18.5 s | ~2440 | **172.9 Hz** +20.7 (92 %) | 260.7 Hz +10.5 (72 %) |

Engine speed doubles; the dominant low line moves **+5.4 %**. An order-locked line would have moved
**+103 %**. Same story for the 240.2 Hz line (ramp, ~1850 rpm) vs 260.7 Hz (rev, ~2440 rpm): +8.5 %
frequency for +32 % rpm.

**Above 3 kHz, measured rather than assumed.** Two independent checks:

*(i) Line census, 3–8 kHz.* Nothing rises above **+6 dB** over its local floor: the rev window's best are
3206 Hz (+5.8, 51 % of frames), 5320 Hz (+5.3, 62 %), 4665 Hz (+5.0, 52 %); the idle window's best is
3721 Hz (+6.0, 62 %). Against this take's own residual noise (median ~4 dB, p90 11–14 dB) those are
noise-floor features, and the ones near 3.7, 5.2, 6.3 and 7.44 kHz are still present with the **engine
off** (+3–4 dB).

*(ii) The same validated order scan, extended to orders 2…1200 so it covers 3–8 kHz.* The control — a
synthetic order-150 tone (6 254 Hz at 2 500 rpm) that is inside the band **only during the rev** — comes
back at order 150.10, Δt = −0.05 s, **+19.3 dB mean / +33.4 dB p75, 59.5 % of frames**, with every
neighbouring order ranking below it. On the real audio the best candidate in that band is order 79.0 at
+1.05 dB mean / +6.6 p75 — no coherent, offset-pinned line anywhere.

So: no rpm-locked tone above 3 kHz either, and the HF region is *covered*, not merely unexamined. What the
cabin mic does up there is broadband hiss (17–30 dB darker in relative HF than the hood takes, §6).

## 5. What actually gets louder when he revs — the fixed-line ledger

Whitened residual (dB above the frame's own local spectral floor) at fixed frequencies, per window of the
same take. "%fr" = fraction of frames above +6 dB. Engine-off is the control.

| Line | OFF 0.3–1.8 s | idle 673 rpm | ramp ~1500 | **rev 2438 rpm** | coast 526 rpm |
|---|---|---|---|---|---|
| **64.5 Hz** | +6.6 / 59 % | **+23.8 / 100 %** | +5.1 / 43 % | **+32.4 / 100 %** | **+18.3 / 100 %** |
| 162.6 Hz | −0.7 / 4 % | +9.0 / 65 % | +6.8 / 53 % | −2.2 / 17 % | +5.8 / 48 % |
| **172.9 Hz** | +1.1 / 0 % | +6.6 / 56 % | +5.6 / 48 % | **+19.9 / 90 %** | +2.7 / 34 % |
| 228.5 Hz | −2.4 / 0 % | +2.4 / 0 % | −1.3 / 19 % | −3.5 / 5 % | +1.2 / 9 % |
| **260.7 Hz** | −0.3 / 0 % | +1.5 / 3 % | +2.2 / 12 % | **+13.9 / 74 %** | −1.4 / 6 % |
| **610 Hz** | −2.9 / 0 % | −0.6 / 0 % | −1.2 / 8 % | **+11.0 / 64 %** | −3.0 / 0 % |
| **750 Hz** | −1.8 / 0 % | +0.1 / 23 % | −1.6 / 9 % | **+8.9 / 61 %** | −0.7 / 0 % |
| 996 Hz | −8.3 / 0 % | +3.9 / 43 % | −5.0 / 13 % | −0.2 / 9 % | −0.5 / 14 % |
| 1519 Hz | −2.7 / 0 % | −2.6 / 0 % | +0.5 / 9 % | +6.0 / 50 % | −6.7 / 0 % |
| 2616 Hz | −3.9 / 0 % | +4.0 / 22 % | +2.3 / 29 % | +8.2 / 72 % | +4.5 / 21 % |
| 3206 Hz | −1.3 / 0 % | −3.0 / 0 % | −2.0 / 0 % | +6.3 / 50 % | −0.9 / 0 % |

Reading it:

- **64.5 Hz is always there** when the engine runs (100 % of frames, +18 to +32 dB) and is even there with
  the **engine off** (+6.6 dB, 59 %) — so it is not evidence about the engine at all (ignition-on devices,
  or a body/cabin mode being fed by something else).
- The lines that **only appear when hot and revved** — 172.9, 260.7, 610, 750, 1519, 2616, 3206 Hz — are
  the ones a driver would describe as "it whines when I rev it". They are the audible complaint in this
  clip. They do not change pitch with rpm (§4).
- Several of these sit suspiciously close to integer orders **at the rev speed** (610 Hz = order 15.0;
  2616 Hz = order 64.4; 172.9 Hz = order 4.25 at 2438 rpm). That coincidence is exactly why the order
  scan in §4 had to exist: it walks those same orders through the whole rpm sweep, and they do not come
  back coherent. Treat the coincidence as a coincidence until a driving capture says otherwise.

## 6. The cabin take does not contain the cold-start signature

Same metrics, same windows, all four recordings (levels are band power relative to *that take's own* mean
power density, so rows are comparable to each other, not to the absolute numbers in yesterday's notes):

| Take / window | 1.7–2.1 kHz peak | 7.5–11 kHz peak | 6–12 kHz rel | 40–100 Hz rel | HF−LF |
|---|---|---|---|---|---|
| cabin park-rev, engine OFF | 1858 Hz +1.2 (8 %) | 10258 Hz +3.3 (31 %) | +13.2 | +55.0 | −41.7 |
| cabin park-rev, idle 673 | 1890 Hz +2.0 (5 %) | 8897 Hz +1.2 (26 %) | +11.3 | +62.8 | −51.5 |
| cabin park-rev, rev 2438 | 2015 Hz +0.9 (24 %) | 10301 Hz +5.2 (56 %) | +16.9 | +62.6 | −45.7 |
| hood COLD, flare 1–5 s | 2019 Hz +5.1 (45 %) | 10135 Hz +0.8 (10 %) | +39.1 | +60.1 | −20.9 |
| hood COLD, body 5–20 s | 1945 Hz +3.4 (32 %) | 8607 Hz +2.3 (26 %) | +43.3 | +51.5 | −8.2 |
| hood COLD, tail 25–44 s | 1874 Hz +3.2 (22 %) | 8264 Hz −1.4 (3 %) | +34.7 | +53.6 | −18.9 |
| hood WARM take | 1967 Hz −2.5 (3 %) | 8311 Hz −3.2 (2 %) | +30.1 | +59.2 | −29.2 |

Two things fall out of it:

- The **cold-vs-warm HF difference reproduces** (hood cold +43.3 vs hood warm +30.1 = **+13.2 dB** versus
  the +12.1 dB measured in yesterday's note through different code — the finding is robust to method).
- The **cabin take is 13–32 dB "darker" in relative HF** than either hood take (pairing the closest windows
  with the closest hood windows), and the 1.9 kHz family
  there is only 1–2 dB above its local floor — and present **with the engine off** (+1.2 dB at 1858 Hz,
  31 % of frames at 10.3 kHz). So the cabin recording cannot resolve the cold-start HF feature: that
  signature lives in the hood recording, and the cabin mic does not hear it.

## 7. What this rules out, and what it leaves

**Ruled out, in this clip:** any narrowband tone whose frequency is proportional to engine speed, anywhere
from **250 Hz to 8 kHz** — the whole range this recording can see — stronger than roughly 0.10 × RMS
(≈ 30 dB below the take's level) below 3.5 kHz and 0.30 × RMS above it, with the scan validated in both
bands by injected controls (§3, §4). That includes any harmonic of a belt-driven accessory (alternator,
water pump, A/C, idler, fan) whose speed is locked to the crank. A whine that tracks rpm and is audible in
the cabin would have to appear here: the rev sweeps 673 → 2438 rpm with the phone 60 cm from the vents.

**Not ruled out:**

- A whine that only exists **under load / while moving** (transmission, transfer case, differential, wheel
  bearing, or an accessory loaded only in gear). A Park rev cannot reproduce it, which is exactly what
  this clip shows.
- A whine that only exists **when the engine is cold**. This clip's start sequence (engine off → crank →
  idle) is consistent with a cold start, but the ambient/heat state is not verifiable from the file; if it
  was a warm re-fire, a cold-only noise would be genuinely absent.
- A **constant-frequency** HF tone below about +6 dB over the local floor — a resonance or a fixed-speed
  device whistling in 3–8 kHz would be at or under the cabin mic's own hiss, and this take cannot separate
  it. (The *rpm-locked* HF case is excluded, §4.)
- Source identity. The fixed lines in §5 are consistent with resonances/excitations, or with fixed-speed
  devices; **this recording cannot name one**, and no order number can be quoted from it.

## 8. The captures that will actually name it

The analysis chain is now built, validated against a known injected tone, and takes ~5 minutes per clip —
so the next recordings decide this. In priority order:

1. **The whine while driving, with an rpm timeline** (this is the whole ball game). Phone on the dash,
   tach in frame **or** an OBD-II/ELM327 rpm log alongside; 20 s clips of (a) gentle acceleration with the
   whine audible, (b) steady cruise, (c) coast-down. With rpm on the timeline the scan returns an **order**,
   and an order names a shaft.
2. **Belt-off, engine cold, rev in Park** — one step that deletes the entire accessory drive (alternator,
   water pump, A/C, idler, tensioner, fan). Whine gone → it is in the belt drive and the driving capture
   only has to say which pulley. Whine still there → internal or transmission, and no audio will name it.
   (Rollback: key off, belt back on, single tensioner release.)
3. **Condition tags on every clip**: cold/warm, Park vs moving, A/C on/off, blower off/high, gear. One
   line of text per file. Two of today's three open questions exist only because the condition wasn't
   recorded with the file.
4. **Blower and fuel-pump splits** if the fixed lines are the complaint: blower OFF vs HIGH (engine cold),
   key ON/engine OFF for 3 s (fuel pump prime), then 10 s of nothing — that isolates electrically driven
   constant-speed devices, which is what §5's fixed lines look like.

## 9. Limits, stated plainly

- One microphone position (dash), one cabin take, no reference level. Levels are relative to each take's
  own energy, which is why §6 is a comparison of *ratios*, not of absolute sound pressure.
- The rpm timeline has a 0.05 s grid and its own fit error; the plateau is solid (±60 rpm spread over 50
  samples, verified against the dial), the ramps are single-pass.
- The audio/video offset check (§3) says Δt ≈ 0 for this file — that is a property of this recording, not
  a guarantee for the next one, which is why the offset stays a free parameter in the scan.
- No component is named. Nothing here says "it is the alternator", and the two candidates that a human ear
  would swear are rpm-locked (172.9 and 260.7 Hz) are demonstrably *not* rpm-locked in this data.

## 10. Evidence (files on this machine)

`~/video-in/`:
- `mono48k.wav`, `stereo48k.wav`, `clip-drive.mp4` (source), `frames/` (raw frames), `full/` (4K stills +
  cluster crops at t = 2, 17 s)
- `tach4.py` → `tach4-trace.json` (476-sample rpm trace), `tile_*.png` (dial overlays at t = 1, 6, 12, 17,
  21, 23.5 s)
- `order_delta.py` → `real3.txt` (the validated order scan, 250–3500 Hz), `ctl3-010.txt`, `ctl3-003.txt`
  (control ladder), `inj-delta.txt`, `ctl-mid-030.txt` (earlier controls); HF band: `real4-hf.txt`,
  `ctl4-hf.txt` (`--band 3000 8000 --omax 1200 --ostep 0.1 --stride 6`, order-150 control)
- `line_ledger.py` → ledger table (§5); `tonality.py` → per-window line censuses (§4 ramp table)
- `order_lean.py`, `order_track.py`, `fine_ridge.py`, `scatter_peaks.py` → `peak-scatter.png`,
  `scatter2.png`, `fine-ridge.png` (the pictures that show horizontal bands, no diagonal ridges)
- `hf_compare.py` → §6 cross-take table
- earlier takes: `~/.hermes/cache/scratch/engine-cold/` (cold hood), `~/.hermes/cache/scratch/engine/`
  (warm hood)
