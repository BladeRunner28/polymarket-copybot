# Engine audio analysis — 2021 Silverado 6.2L L87, "warm start" whine

**Source file:** `engine-whine-warm-start.m4a` (received 2026-10-03), saved at
`/Users/xsnyde2/.hermes/cache/documents/doc_cfbcd641080f_engine-whine-warm-start.m4a`
**Stated context:** 2021 Chevrolet Silverado, L87 6.2L V8, 93 octane petrol, warm start, symptom = whine.

**Verdict up front: this file cannot support a component-level diagnosis, and the limit is the recording, not the
method.** There is no stable narrowband tone anywhere in the take, and no defensible order grid to tie one to. What
follows is what it *does* contain, measured, plus the field test that actually settles a whine on this truck.

---

## 1. What the file is (measured, not assumed)

| Property | Value | How |
|---|---|---|
| Container / codec | MP4/M4A, **AAC 128 kbps stereo** | `ffprobe` |
| Duration | **30.00 s** | `ffprobe` |
| Sample rate | 44.1 kHz (decoded to 48 kHz mono for analysis) | `ffprobe`, `ffmpeg` |
| Peak | **−1.4 dBFS** | sample-domain RMS/peak |
| RMS | **−24.8 dBFS** | " |
| Crest factor | **23.4 dB** | " |
| Clipped samples | **0** | " |

Analysis windows: 0.68 s Hann, 0.34 s hop → 0.37 Hz bins, 86 frames.

## 2. Level structure — the take swings 17 dB

Relative level per 0.34 s frame, median-centred:

```
t=0.3s  ##### loud          t=11.9-17.4s  # quietest stretch
t=1.0s  ###### loudest      t=18.1s       ###### 2nd loud passage (1.0 s)
t=2.4s  ###                 t=20.8s       ####
t=4.4-8.5s ####  bumps      t=21.5-29.0s  #  steady quiet
```

Two loud passages — **0.3-1.7 s** and **18.1-19.1 s** — and a ~17 dB swing between them and the quiet stretches.
Energy is overwhelmingly low-frequency: the **10-40 Hz** and **40-100 Hz** bands are the loudest in the take, then
100-300 Hz; everything above 1 kHz sits 12-15 dB lower.

**Correlation between the low band (15-150 Hz) and 1.5-4 kHz across frames: `-0.28`.** Two bands from one engine
should rise and fall together (positive). A *negative* correlation is what a gain-control pump or handling noise
produces — i.e. the microphone path, not the engine, is driving the level behaviour of this take.

## 3. The three findings that decide the answer

**3a. There is no stable narrowband tone — so there is no "whine" in the file.**
Per-frame strongest peak inside progressively narrower bands:

| Band | Median | Spread (std) | Frames where the winner stays within ±5 Hz of the median |
|---|---|---|---|
| 280-420 Hz | 300 Hz | 35.8 Hz | **23%** |
| 650-780 Hz | 722 Hz | 25.6 Hz | **15%** |
| 1.2-1.8 kHz | 1422 Hz | 160 Hz | — |
| 2-3.5 kHz | 2792 Hz | 399 Hz | — |
| 300-3000 Hz (whole band) | 393 Hz | 348 Hz | — |

Across the take, the loudest peak in 300-3000 Hz wanders from 300 Hz to 2800 Hz. Best "line persistence" anywhere
above 300 Hz: a bin that is a prominent local maximum in only **17%** of frames. A real whine — an alternator, idler,
water pump, belt or transmission-pump tone — is one line holding inside ~1% for the whole recording. Nothing here
does that.

**3b. The 300-400 Hz content is a dense cluster, not a tone.**
Peak-picking inside 290-400 Hz finds *many* comparable peaks (299, 301, 302, 305, 309, 312, 317, 319, 322, 325, 333,
339, 352, 354, 375, 376, 386 Hz in different passages), each only 4-8 dB above that band's own median. A cluster
that wide and that flat is the signature of a broad hump excited by the engine's pulses (a drone/boom), not of a
rotating-part whistle. A related family sits at 700-731 Hz, i.e. ≈2× the cluster.

**3c. The rotation speed cannot be recovered from this take.**
Best harmonic-comb fits, per passage (score = level at the harmonics minus the level at the halfway points):

| Passage | Best f0 | Implied rpm if that f0 is the V8 firing rate (4 pulses/rev) | Score |
|---|---|---|---|
| 0.30-1.75 s | 33.50 Hz | 502 | +3.5 dB |
| 8-17 s (idle) | 44.00 Hz | 660 | +5.0 dB |
| 18.1-19.1 s | 66.25 Hz | 994 | +13.7 dB |
| 20-30 s | 64.25 Hz | 964 | +5.9 dB |

The fits *disagree* and all are weak. 44 Hz and 66 Hz are consistent with the 4th and 6th orders of one ~650-660 rpm
idle (both are common strong orders on a V8), and 64-66 Hz is consistent with a ~960-990 rpm fast idle — but the
evidence does not distinguish those readings, so **no rpm is claimed here.** Without a defensible rpm there is no
order number, and without an order number a noise cannot be attributed to a component. That is the whole ballgame.

## 4. What this take *is* consistent with

- An engine running throughout, with strong low-frequency content and engine-pulse excitation of a ~300-400 Hz
  resonance — normal-sounding structure, nothing that reads as a fault.
- A recording dominated by the phone's own path: near-full-scale transients (−1.4 dBFS peak against −24.8 dBFS RMS),
  a 17 dB level swing, an anti-correlated HF band, and an elevated 6-12 kHz floor relative to 1-3 kHz (−4.8 dB,
  i.e. much higher than an idle engine's natural spectrum would put it).

**Nothing in the above says the whine is not real.** It says the recording does not contain it in a resolvable form.
A whine that is obvious to a person sitting in the truck can be absent from a 30 s phone clip: masked by the
low-frequency content, filtered by the phone's processing, or simply not resolvable at this distance.

## 5. The field test that settles it (10 minutes, no tools beyond a 15 mm socket)

Do these in order and note which one changes the noise:

1. **Hood open, listen at the front accessory drive** (alternator, idler/tensioner pulleys, water pump, A/C
   compressor) at idle, then hold ~2000-2500 rpm for 10 s. A belt-driven whine tracks rpm immediately and is loudest
   at the belt plane.
2. **A/C on vs off** with the blower off. The compressor clutch engaging/disengaging is a one-button test — if the
   whine appears only when the clutch is in, you are done.
3. **Park vs Drive (foot on brake) at idle.** A transmission-pump whine changes with converter load and input speed;
   an accessory whine does not.
4. **The decisive one: serpentine belt off, engine cold, 30-60 s run.**
   - Whine **gone** → the accessory drive (pulley, tensioner, idler, alternator, water pump, A/C clutch bearing).
     Spin each pulley by hand and feel for roughness, and check belt tracking/glazing.
   - Whine **still there** → not the accessory drive; next suspects are internal (timing chain, oil/vacuum pump) or
     the transmission. Do not run long — no water pump means no cooling.
5. **If a check-engine light is or was on, pull codes.** The L87's known failure modes that get described as "a
   noise" (DFM/AFM lifter collapse, direct-injection pump/injector tick) show up as misfire or fuel-trim codes, and
   a code reading is worth more than any audio analysis.

Safety on step 4: engine **off and cold** before you touch the belt, belt routing photographed first, and the
rollback is that the belt goes back on — it is a single-bolt idle/tensioner release on this engine.

## 6. If you want the audio analyzed properly, record it like this

The codec is not the problem (AAC 128 k holds a steady tone fine). Placement, gain control and the engine's own
low-frequency dominance are.

1. **Hood open, phone 30-50 cm from the front accessory drive**, aimed along the belt plane, phone not touching
   metal (set it on a rag or have someone hold it).
2. **Disable AGC / "noise reduction"** in the recorder if the app has the setting, and record **WAV** where possible.
   If only the voice-memo app is available, that is usable — just keep the phone still and avoid handling noise.
3. **Four 20 s clips, one condition each** (the isolation matters more than the total length):
   - warm idle, A/C off
   - warm idle, A/C on
   - steady 2000-2500 rpm held by hand (or via cruise trickery — do not do this while driving)
   - **the same conditions from inside the truck at the driver's ear** if that is where you hear it, because a
     cabin-resonance drone and an engine-bay whine are different faults with different fixes.
4. **Include an RPM reference in the same file**: film the tachometer while recording, or log RPM through an OBD-II
   dongle to CSV and send that alongside. With rpm logged, every peak above becomes an order, and a component can be
   named. Without it, the best any analysis can do is what §3 did.
5. Note the conditions that change it — cold vs warm, gear vs park, A/C, steering at full lock. Ten seconds of
   description is worth more than ten more minutes of audio.

## 7. Evidence (files on this machine)

- `~/.hermes/cache/scratch/engine/engine_fft.py` → `full.json` — levels, band energies, peaks, tone tracks, segments
- `~/.hermes/cache/scratch/engine/engine_orders.py` → `engine-orders.json` — level timeline, per-frame f0, line
  persistence, event list, burst spectrum
- `~/.hermes/cache/scratch/engine/engine_whine_hunt.py` — per-frame peak tracker, per-passage peaks, comb test,
  mic-path diagnostics, autocorrelation
- `~/.hermes/cache/scratch/engine/engine_orders2.py` — full-range comb fits, low-band peak grid, family stability
- `~/.hermes/cache/scratch/engine/spec_8k.png` (0-8 kHz log) and `spec_low.png` (0-600 Hz linear) — spectrograms

## 8. Limits stated plainly

- No component is named, because the measurement does not support naming one.
- Nothing here substitutes for the belt-off test, a code scan, or a mechanic with a stethoscope.
- GM's known L87 failure modes (DFM lifter collapse, DI pump/injector tick, 10-speed pump whine) are **not**
  presented as findings — none of them can be confirmed or excluded from this recording, and asserting one from a
  smeared 30 s clip would be inventing a diagnosis.
