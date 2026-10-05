# Engine audio analysis — 2021 Silverado 6.2L L87, COLD start (2026-10-04)

**Source file:** `truck_whine_cold_start_20261004-074437.m4a` (received 2026-10-04), 1,098,073 bytes,
SHA-256 `bbf2a3d3baa0227b8e1658eaa22072bc362345836898956c7f9791c1c6148fe3`
**Stated context:** 2021 Chevrolet Silverado, L87 6.2L V8, 93 octane petrol, **cold start**, symptom = whine.
**Baseline for comparison:** yesterday's warm-start take (`engine-whine-warm-start.m4a`, 30.0 s), analyzed
with the same windows, thresholds and normalization — everything below is apples-to-apples.

**Verdict up front — different from yesterday.** Yesterday's take contained *nothing* resolvable above
300 Hz; this one does. The cold take carries a prominent 1.7-2.1 kHz tonal feature and a broadband
8-10 kHz hiss, and after normalizing for recording level both sit **~12 dB stronger relative to the
engine's low-frequency output than in the warm take**. Both decay during the 45 s run. So the
cold-vs-warm difference in the complaint is real and measurable in the audio.

**What it still does not do: name the source.** Neither feature responds to engine events — not to the
start flare, not to two load blips — and when the analysis was re-run properly after the "rises with
acceleration" report (order-spacing/stretch test + autocorrelation speed tracker, §3e), the take turns
out to contain a real engine operating-point change (~26% lower low-frequency periodicity in the final
3 s) that the 1.87-2.02 kHz family and the 8-10 kHz hiss **do not follow** (band structure invariant to
within ±4% across 45 s). So those tones are constant-frequency, not rpm-locked, and are probably *not*
the whine heard under acceleration — a stationary cold idle may simply not contain that sound.
The honest state is: *this clip holds a cold-only, constant-frequency 1.87-2.02 kHz + 8-10 kHz
signature, plus a stationary ~700 Hz line*; §4 lists the candidate sources and §5 is the test sequence
that identifies them instead of guessing (Part A: capture the driving whine with an rpm reference;
Part B: the blower / key-on-engine-off splits for what is in this clip).

---

## 1. What the file is (measured, not assumed)

| Property | Value | How |
|---|---|---|
| Container / codec | MP4/M4A, **AAC ~194 kbps stereo** | `ffprobe` |
| Duration | **45.35 s** | `ffprobe` |
| Sample rate | 48.0 kHz (decoded to 48 kHz mono for analysis) | `ffprobe`, `ffmpeg` |
| Peak | **−0.02 dBFS** | sample domain |
| RMS | **−26.14 dBFS** | " |
| Crest factor | **26.1 dB** | " |
| Clipped samples | **0** (at the 0.9995 threshold) | " |
| Stereo validity | real stereo, corr(L,R) = **+0.80** | band analysis |

Analysis windows identical to yesterday: 0.68 s Hann, 0.34 s hop, 4× zero pad → 0.37 Hz bins, 131 frames.
(This take is 5.4 dB hotter and 1.4 dB closer to full scale than yesterday's — hence §2 normalizes.)

## 2. Cold vs warm, gain-normalized (band level **minus the file's own RMS**)

| Band | Cold (this take) | Warm (yesterday) | Δ cold−warm |
|---|---|---|---|
| 10-40 Hz | +77.8 dB | +84.8 dB | **−7.0** |
| 40-100 Hz | +80.6 dB | +84.4 dB | **−3.8** |
| 100-300 Hz | +73.1 dB | +82.1 dB | **−9.0** |
| 300-1000 Hz | +72.4 dB | +72.8 dB | −0.4 |
| 1-3 kHz | +76.5 dB | +69.6 dB | **+6.9** |
| 3-6 kHz | +73.5 dB | +63.9 dB | **+9.6** |
| 6-12 kHz | **+87.0 dB** | +74.9 dB | **+12.1** |

That is the whole story in one table: yesterday's take was dominated by the engine's low band
(10-300 Hz ≈ +82…+85 dB, spectrum falling monotonically above 1 kHz). Today's is dominated by
**6-12 kHz**, which is the *loudest* band in the take — 9.5 dB *below* the low band becomes 6.4 dB
*above* it. Normalized, this take carries ~12 dB more relative HF energy than the warm take.

## 3. The three findings that decide the answer

> **REVISION (added after the 2026-10-04 follow-up).** The user reports the whine **rises in pitch under
> acceleration and falls under deceleration** — i.e. it is speed-coupled. That invalidates the form of
> §3c below: it tested *fixed-band levels* against events I assumed were rpm changes. Re-run with
> order-spacing (stretch) analysis and an autocorrelation speed tracker, this take **does** contain an
> engine operating-point change, and the tones do **not** follow it — see §3e. §3c is kept verbatim
> because its per-event numbers are still correct; its conclusion is superseded by §3e.

**3a. There is a real, resolvable 1.7-2.1 kHz feature — for the first time.**
Per-frame tracker (strongest bin inside 1.9-2.0 kHz vs that band's local floor):

| Metric | Cold (45 s) | Warm (30 s) |
|---|---|---|
| Median line SNR | **13.1 dB** | 8.8 dB |
| Frames above 10 dB SNR | **101 / 131 (77%)** | 23 / 86 (27%) |
| Fine-spectrum peak (10 s windows) | 2016.0 → 1945.5 → 1883.2 → 1872.6 → 1882.1 Hz | 1720.5 Hz (only peak) |

Two caveats that keep this honest:
- **It is a family, not one clean line.** At 0.09 Hz resolution the 1.7-2.1 kHz region holds many
  comparable peaks (e.g. 1945.5/1974.7/1931.4/2017.3/1830.3 Hz in 5-15 s), spaced 8-70 Hz apart. The
  strongest single bin does sharpen late in the take (1872.6 Hz at +28.7 dB prominence, 25-35 s).
- **It drifts −9.7% across the take** (2074.7 Hz first frame → 1872.5 Hz last), settling after ~25 s.
  Its ~1.9 kHz band level falls **−19 dB** over 20 s → 45 s (20.6 → 1.5 dB) while the engine's low band
  falls only **−5 dB** over the same span (28.1 → 23.1 dB) — i.e. the feature fades on its own schedule.

**3b. The 6-12 kHz content is broadband hiss, not a line — but it is loud and it is cold.**
1/3-octave profile: 6300 → 5.2 dB, 7300 → 9.7, **8300 → 16.4**, **9300 → 15.1**, 10300 → 7.6,
11300 → 2.9. Spectral flatness 6-12 kHz = **0.347** (warm take 0.567), peak spacings irregular
(119-1000 Hz) → no harmonic/blade-pass skeleton. Its timeline is the take's cleanest event:
8.3-9.2 kHz band **36 dB at t≈1 s** (the crank/fire) → ~19.5 dB by 20 s → ~7.5 dB at 44 s, decaying
~28 dB from its own 1 s peak while the low band decays ~21 dB from its 3 s post-flare peak. It is
relatively strongest at 5-15 s (6-12 kHz minus 40-100 Hz = −8.3 dB) and drops to ≈ −19 dB after 20 s.

**3c. Neither feature responds to the engine — this is the decisive negative.**
Three engine events, measured (LF = 40-100 Hz band, the engine's own output):

| Event | LF band | 1.9 kHz feature | 6-12 kHz hiss |
|---|---|---|---|
| Cold-start flare (0.5-3.5 s vs 5-10 s) | **+8.7 dB** | **−0.1 dB** | +1.1 dB |
| Load blip at 23.5 s | **+8.5 dB** | −3.7 dB | −1.5 dB |
| Load blip at 34.5 s | +3.1 dB | −0.9 dB | −0.3 dB |
| (warm take) blip at 18.6 s | **+9.3 dB** | −2.4 dB | +2.6 dB |

Both blips are LF-only events — at 23.5 s the total level rises 7 dB while the 6-12 kHz band does not
move (9.9 vs 10.3 dB), so they are real engine load changes, not handling noise. On the same events the
1.9 kHz feature does not rise at all. Fast (<3 s) fluctuation correlations with the LF band:
**corr = −0.08** (1.9 kHz feature) and **−0.00** (6-12 kHz hiss). A source driven by the engine —
belt, pulley, pump, exhaust resonance — has to move when the engine is asked for power.

Amplitude-modulation side-note: the 1.9-2.0 kHz band is amplitude-modulated at **43.9/43.6/44.3 Hz**
(5-18 s) and **41.4/42.9/42.1 Hz** (26-40 s) — a ~5% AM-rate drop that mirrors its ~5% frequency drop,
i.e. a rotating-ish source whose speed sagged slightly and then held. The engine's own LF band is
modulated at **29.7-30.0 Hz in both plateaus** with no shift. (No rpm is claimed from either number —
see 3d.)

**3d. Engine speed is still not recoverable — every estimator disagrees.**
- Harmonic-product-spectrum f0 per frame: median **19.9 Hz** (would be 298 rpm as a V8 firing rate)
- Strongest low-band peak per frame: median **50.9 Hz**, IQR 41.6-79.8 Hz (623-1198 rpm implied)
- Comb fits per passage: 30.5 / 50.25 / 50.25 / 40.5 / 65.25 / 60.0 Hz (458-979 rpm implied)
- Log-spectrum stretch test, plateau A (5-18 s) vs plateau B (26-40 s): best scale **1.010**
  (corr +0.24; curve spread only 0.30 → weak) — this excludes a large ~1.8× fast-idle drop but cannot
  resolve a ~10% change.

So: no rpm → no order number → no component attribution. The tone *could* still be engine-driven at an
unknown order; the measurements above are what exclude the *load-driven* mechanisms, not all of them.

**3e. Speed-coupling test (runs after the "rises with acceleration" report).**
Two independent instruments, because a swept tone needs order analysis, not fixed bands.

*(i) The engine's operating point DID change inside this take.* Autocorrelation of the 20-150 Hz band
(1 s window, 0.25 s hop) tracks the dominant low-frequency periodicity without having to pick a
harmonic:

| Span | Periodicity | Autocorr peak height r |
|---|---|---|
| 2-4 s | 30.5 → 26.9 Hz (decaying) | 0.77-0.94 |
| 4-23 s | 26.2 → 27.4 Hz | 0.51-0.68 |
| 33 s | 24-25 Hz | 0.26-0.58 |
| **42-45 s** | **19.0-20.3 Hz** | **0.61-0.82** |

So the last three seconds run ~26% lower in dominant low-frequency periodicity than the 4-23 s body of
the take, with the highest per-window confidence in the file — consistent with a cold fast idle
settling, plus the 6-7 dB low-band level step at ~23-25 s. (The exact rpm ratio is ambiguous — the
comb-matching branch is unresolved between 0.86 and 1.34 — but "unchanged" is excluded.)

*(ii) The 1.5-2.6 kHz tones do not move with it.* Window-pair stretch test — the factor `s` by which one
window's log-spectrum must be stretched to match another; `s = 1.00` means identical spacing:

| Window pair | Engine band 40-300 Hz | Whine band 1.5-2.6 kHz |
|---|---|---|
| 5-10 s → 13-18 s | s = 0.992 (r 0.93) | s = 1.000 (r 0.89) |
| 5-10 s → 20-23 s | s = 0.984 (r 0.92) | s = 0.984 (r 0.77) |
| 13-18 s → 40-45 s | **s = 1.35** (r 0.61) | s = 1.044 (r 0.72) |
| 26-31 s → 40-45 s | **s = 1.33** (r 0.75) | s = 1.006 (r 0.80) |

Every engine-band pair involving the last window needs a 13-35% stretch; every whine-band pair lands
inside ±4%. In the whine band the correlation at `s = 1.00` is 0.77-0.90 — those 45 s-apart spectra
are nearly the same shape — while the engine band only reaches that alignment after a large stretch.
A tone at a fixed order of a shaft cannot behave that way; a constant-frequency source (or a fixed
resonance) does. The ~694-700 Hz line is the same story: present in 131/131 frames at >6 dB
prominence, median 699.5 Hz, corr(frequency, time) = +0.14.

**Consequence: the 1.87-2.02 kHz family (with its strong ~950 Hz companion) and the 8-10 kHz hiss in
this cold-start clip are not rpm-locked, so they are probably NOT the whine heard under acceleration.**
This clip is a stationary cold idle; the driving whine may simply not be in it. That is a hypothesis
the next recording settles, and it is why §5 now leads with the driving-condition captures.

## 4. Candidate sources, and what separates them

| Candidate | Fits | Argues against | Test that settles it |
|---|---|---|---|
| In-tank **electric fuel pump** | runs whenever key is on; speed set by voltage, not rpm; AM from motor/commutation; classic cold-louder-whine | 1.9 kHz is lowish for a pump whine | **key ON, engine OFF** — pump primes 2-3 s (§5.1) |
| **Cooling fan / HVAC blower** | constant speed, load-independent, broadband HF + blade-pass tone, exactly why a cold morning (defrost on high) is louder than a warm take | speed should *rise* as alternator voltage comes up, not sag 5% | blower OFF vs HIGH; A/C off/on (§5.2, §5.3) |
| **Secondary-air / emissions air pump** (cold-start only, 30-60 s) | hiss loud at t≈1 s, gone by ~40 s; exactly a cold-start-only device | hiss is broadband, no tonal skeleton | engine-off vs engine-on key test, and a code scan |
| **Combustion-excited resonance** (heat shield, pipe, bracket) | tone AM'd at ~42-44 Hz, near a V8 firing rate; drifts with temperature | a resonance driven by combustion should track load — it did not (−0.08) | hold 2500 rpm cold vs 2500 warm; resonance follows temperature, not rpm |
| **Recording chain** (phone AGC + mic HF self-noise + codec) | the take is 1.4 dB from full scale; a few dB of the −3.7 dB blip response can be AGC gain pull | AGC does not create a 45 s tone with a stable 42-44 Hz AM | record the same 20 s with the engine **off** (§5.1) |

## 5. The test sequence that identifies it

**Part A — capture the whine that he actually hears (this is now the priority; a stationary cold idle
may not contain it at all).** Phone fixed, don't hold it against metal, cabin or engine bay as before:

> **The tach does not have to be in frame.** The requirement is an *rpm timeline that can be aligned to
> the audio*, and there are three ways to get one — the electronic throttle (no cable on an L87) means
> someone is in the cab either way:
>
> 1. **Voice annotation — no extra gear, works with the phone under the hood.** Helper in the driver's
>    seat runs the pattern below and **says the tach reading aloud at each hold** ("twenty-five hundred
>    … twenty-five hundred"). The speech lands in the same file, so the rpm ladder arrives with the
>    audio, at 1-2 m of distance it is clearly audible against the accessory drive.
> 2. **OBD-II dongle + logging app → RPM CSV.** Exact numbers, no annotation; any BLE ELM327 (~$20) with
>    Car Scanner / Torque / OBD Fusion. Start the log and the audio within a few seconds of each other —
>    the rev pattern then aligns them.
> 3. **Cabin take with the tach filmed** (same phone, dash mount, windows up, blower off): the simplest
>    if the whine is audible in the cabin, which it should be if it is audible while driving. Cabin
>    acoustics cost the HF detail but the rpm ↔ tone relationship survives. A hood take and a cabin take
>    recorded with the *same* rev pattern can be aligned to each other afterwards.
>
> **Pattern (hold-based beats a slow ramp — two known points fix the order line):**
> idle 5 s → hold ~2500 rpm 5 s → back to idle 5 s, repeating the announcement at each steady point.

1. **Three 20 s clips while driving, tachometer in frame** (or an OBD-II rpm log to CSV alongside):
   (a) gentle acceleration with the whine audible, (b) steady cruise, (c) coast-down/deceleration.
   With rpm on the timeline every peak becomes an order, and an order names the component —
   that is the missing ingredient, not more DSP. If the tach can't be filmed safely, the OBD log alone
   is enough.
2. If any of those clips exists, this same analysis chain runs on it and returns orders instead of
   "unknown tone".

**Part A0 — the test that outranks all audio from here.** The whine is audible standing still in Park,
so the accessory drive can be excluded without any recording: engine **cold**, serpentine belt off,
start and run 30-60 s. Whine gone → it is in the accessory drive, and the rpm capture above only names
which pulley. Whine still there → it is internal or the transmission pump, and no amount of audio will
name it. Rollback: key off, belt back on (single tensioner release on this engine; photograph the
routing first).

**Part B — the 2-minute splits for the idle tones found in this clip** (they are constant-frequency,
so a constant-speed device or a fixed resonance is the leading explanation):

3. **HVAC blower OFF, then HIGH** (engine cold, A/C off), 20 s each. A cold morning = defroster on high;
   that is a constant-speed electric fan whose broadband output sits exactly where the 8-10 kHz hiss
   sits, and it is the single best explanation for why the cold take has ~12 dB more relative HF than
   the warm one. If the hiss and the 1.87-2.02 kHz family drop when the blower goes off, that's it.
4. **Key ON, engine OFF** (hold 3 s: the fuel pump primes, fans and pumps may run), then key OFF and
   record 10 s of nothing. Splits electric-device / engine / recording chain — the one thing no amount
   of DSP can split from this file. Send both clips.
5. **A/C off vs on** (blower off) — compressor clutch bearing is a classic cold-only front-end whine.
6. **Phone position sweep in one continuous take**: driver's ear → dash → 30-50 cm in front of the
   accessory drive → outside at the fuel filler / rear wheel → back to the driver's ear. The position
   where the tone jumps ~10 dB is the source.
7. If all of the above are negative, the belt-off test from yesterday's note stands unchanged (engine
   cold, belt off, 30-60 s run; whine gone = accessory drive; still there = internal or transmission),
   and a code scan is worth more than any audio.

Record each condition as its own short file at a fixed phone position; I can run this exact analysis
chain per clip and report the line SNR, the 6-12 kHz ratio and the load-response test per condition.

## 6. Limits stated plainly

- No component is named. The measurements exclude load-driven mechanisms; they do not name a source.
- Engine speed is not recoverable from this take, so no order number exists to hang a component on.
- The 8-10 kHz hiss could be an air/vacuum leak rather than a rotating device — a leak's hiss changes
  with throttle/vacuum, so §5.4 plus a cold-idle-vs-2500-rpm pair separates that too.
- A 45 s phone recording still cannot substitute for a stethoscope, a code scan, or the belt-off test.
- GM's known L87 modes (DFM/AFM lifter, DI pump/injector tick, 10-speed pump) are **not** asserted here;
  none can be confirmed or excluded from this recording.

## 7. Evidence (files on this machine)

Directory `~/.hermes/cache/scratch/engine-cold/`:
- `cold.m4a` — byte-identical copy of the attachment, SHA-256 as above; `mono48k.wav`, `stereo48k.wav`
  — the decodes every number above came from
- `cold_analysis.py` → `cold-analysis.txt`, `cold-report.json` — levels, band levels, per-frame f0 and
  300-4000 Hz peak, line persistence, tone tracking, comb fits, mic-path diagnostics, 3 s block test
- `cold_forensics.py` → `cold-forensics.txt` — exact line frequency, HF flatness, per-frame timelines of
  the 1.9 kHz / 8.7 kHz / low-band levels, harmonic test, AM test, low-band peak tracker, cross-take
- `cold_stage3.py` → `cold-stage3.txt` — stereo channel diagnostics, rolling ratios, order-comb stretch
  test, per-plateau envelope modulation, gain-normalized cold-vs-warm band comparison
- `cold_stage4.py` → `cold-stage4.txt` — detrended load-response test and the four event-response tests
- `cold_stage5.py` → `cold-stage5.txt` — per-frame 1.9 kHz frequency/SNR trajectory, fine 5 s spectra
- `cold_stage6.py` → `cold-stage6.txt` — line-family structure in 1.7-2.1 kHz, sibling bands, HF skeleton
- `cold_stage7.py` → `cold-stage7.txt` — four-band ridge tracker at 0.17 s hop, autocorrelation
  firing-rate tracker, ridge/speed ratio test, fine look at the events
- `cold_stage8.py` → `cold-stage8.txt` — whine-fundamental HPS tracker, per-band stretch test around the
  23.5 s event, fine ridges in five bands
- `cold_stage9.py` → `cold-stage9.txt` — full window-pair stretch matrix (engine vs whine band) and the
  ~700 Hz line tracker
- `cold_stage10.py` → `cold-stage10.txt` — stretch-curve branch listing, to expose the comb-matching
  order-alias ambiguity instead of reporting one branch as fact
- `spec_cold_12k.png`, `spec_cold_3k_att.png`, `spec_cold_low_lin.png` — spectrograms
- yesterday's take re-measured through the same code paths (in `~/.hermes/cache/scratch/engine/`)
