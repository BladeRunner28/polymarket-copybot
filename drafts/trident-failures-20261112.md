# Voron Trident — failure forensics and a plan ordered by your priorities

**Date:** 2026-11-12 · **Machine:** `trident`, Voron Trident 350, Klipper v0.13.0-762, Manta M8P/CM4
**Read-only.** No config edited, no calibration run, nothing moved. The BC-250 print was in progress
throughout (5 % at 10:46, ETA ~22:40).

Your answers that shape this: **failures are the cost** (not hours); **surface finish > layer
adhesion > speed**; the 16 mm³/s cap is **inherited, not chosen**; calibration allowed **with you
present**; materials **ABS, ASA, PLA, PETG, TPU, PET-CF**.

Because speed is now *last*, the volumetric cap stops being the headline. It is a fact about the
machine, not the next job.

## 1. What the job history actually says

Moonraker `/server/history/list` — **500 jobs, 2025-11-24 → 2026-11-12**.

| status | count |
|---|---|
| completed | 279 |
| cancelled | 178 |
| klippy_shutdown | 38 |
| klippy_disconnect | 2 |
| error / interrupted | 2 |
| in_progress | 1 |

**Raw completion rate 55.9 % is misleading and I am not using it.** 178 "cancelled" includes a long
tail of 0.00 h starts — repeated identical attempts on the same file minutes apart
(`LINK - 200mm_ASA` eleven times on 2026-06-17/18, `Voron_Design_Cube_v7` five times on 06-08) — which
are aborted starts, not failed prints.

**The honest number: 270 of 328 jobs that ran ≥0.1 h completed = 82.3 %.** 58 real failures.
Total print time lost to non-completions: **47.98 h**.

### Worst single losses

| hours lost | status | date | file |
|---|---|---|---|
| 10.32 | **error** | 2026-01-11 | `Shell_Back_Reference_v2_Larger_PSU_42mm_x_82mm…` |
| 3.28 | klippy_shutdown | 2026-10-18 | `BC-250-pro-v2_ASA_5h30m` |
| 2.54 | klippy_shutdown | 2026-03-09 | `Table-Support-Center-x2-SS_ASA_4h21m` |
| 1.83 | cancelled | 2026-06-15 | `LINK - 200mm_ASA_1h54m` |

The 10.32 h `error` is the single largest loss in the record and is its own class — `error` (not
`klippy_shutdown`) means Klipper reached a valid state and the job was judged bad. Worth its own
look.

### `klippy_shutdown` by month — the trend is the finding

```
2025-12: 6   2026-01: 5   02: 3   03: 4   04: 3   05: 1
2026-06: 1   07: 2        08: 9   09: 1   10: 3
```

**Last shutdown: 2026-10-18 — nothing in the 3.5 weeks since.** The distribution is not uniform:
**August alone holds 9 of 38 (24 %)**, and the machine has been quiet since mid-October. A uniform
"the machine is flaky" story does not fit; an episodic one does.

## 2. What I could NOT measure — stated, not papered over

**The causes of those shutdowns are not retrievable.** Available logs under `/server/files/logs`:

- `klippy.log` — current session, **7.29 MB, zero shutdown transitions, zero lost communications,
  zero "Timer too close"**. A clean current log is not evidence of health.
- Dated archives: `2026-06-08`, `2026-10-22`, `2026-10-28`, `2026-11-01`, `2026-11-03`, `2026-11-08`.

There is **no archive for 2026-10-18** (the last shutdown) and **none for August** (the spike). Per the
machine's own history, Moonraker does not reliably retain `klippy.log.1..N`. So today's answer is:
82.3 % completion, 38 shutdowns, **causes unknown**, and the next shutdown must be captured live to be
explained. Any explanation offered now would be invention.

## 3. One live lead with a named discriminator

`crowsnest` is running (a webcam streamer; `crowsnest.log` rotates daily, 3.07 MB/day). My own
diagnostics record on this machine is explicit: **a USB webcam sharing the M8P's internal hub was the
field-confirmed cause of a multi-job `klippy_shutdown` run — removing it ended the crashes.** The M8P's
CAN bridge sits behind the carrier board's own hub, so a camera on those ports shares Klipper's data
path.

- **Hypothesis:** the August cluster (9 shutdowns) is a hub/bus-load event, not thermal or config.
- **Discriminator (cheap, needs the machine idle, not a print):** the August shutdowns' signature is
  kernel-side — `-EPROTO`/`error -71` on bridge URBs followed by `1-1.x` devices dropping. Confirming
  it needs `journalctl -k` over August, which I cannot reach without shell on the Pi.
- **What would refute it:** August shutdowns whose logs show identical bus counters at idle and under
  load, or a non-USB error class (`Timer too close`, thermal, `Move out of range`).
- **Second discriminator, zero risk:** unplug the camera for one long print and compare. That is a
  before/after test, not a theory.

## 4. The plan, in your priority order

### Step 1 — failure ledger (read-only, no machine time, ~1 h) ← I recommend this first

An hourly Moonraker poll that records per job: file, material, duration, status, and — when a job dies
— the `klippy.log` window around the death, **captured while the log still exists**. That is the whole
point: today the causes are gone because nothing preserved them.

Then failure rate by material, duration and file, with the same discipline the trading lane uses: a
population, a clock, and a refutation condition. Until this exists, every improvement claim about
reliability is unfalsifiable.

**Why first:** you named failures as the cost, and this is the only thing that makes the other steps
measurable.

### Step 2 — surface finish (your #1 quality axis)

Not a speed question. In order of measured leverage on this machine:

- **Pressure advance per material** — currently `0.0462` live, tuned for ASA. Six materials sharing one
  PA is a cosmetic defect generator. Cheap, needs the machine, needs you present.
- **Outer walls are already the slow feature** (150 mm/s vs inner 300) which is correct for finish —
  the volumetric cap clamps them to ~133 anyway, so the cap is *not* currently hurting outer walls.
- **Scarf seams / wipe** — the profile does not set `scarf_seam_type`. Free finish improvement on
  visible seams; slicer-only, no machine risk.

### Step 3 — layer adhesion

The material-specific risk, and where your six materials genuinely diverge:

| material | adhesion lever | trap |
|---|---|---|
| ABS / ASA | chamber temp (40 °C now), low fan | too much fan = delamination; CPAP cooling would *hurt* this |
| PLA | part cooling | one 5015 is the classic cap above ~150 mm/s |
| PETG | temp + slow first layer | over-cooling = poor bonding |
| TPU | extruder grip, slow | CHT back-pressure fights a soft filament |
| PET-CF | nozzle hardness + temp | **abrasive** — see the question below |

### Step 4 — speed (last, as you ranked it)

The measured levers, when we get there: the inherited **16 mm³/s** cap (≈133 mm/s at 0.2 × 0.6) versus
~30 mm³/s the Rapido UHF + 0.6 CHT should sustain on ASA; `SCV 7 → 15` nearly free (Y shaper budget
11,653 → 11,079 mm/s²); `minimum_cruise_ratio 0.5 → 0.2` for +26 % on short moves, which **demands +26 %
flow** — so it pairs with the cap, never replaces it. **`max_accel` stays put:** live is 10,000 and the
Y shaper ceiling is 11,653, so raising it buys corner blur, not speed.

## 7. Update — the operator's answers reframe the failure class

**The 0.6 CHT is hardened**, so PET-CF stays on the material list. And **the cancels are the operator
aborting after seeing a defect** (delamination, warping) — which turns 178 "cancels" from noise into
the largest quality signal on this machine.

Re-measured with that in mind, across the same 328 jobs that ran ≥ 0.1 h:

| class | jobs | time lost |
|---|---|---|
| completed | 270 (82.3 %) | — |
| **cancelled by you after a visible defect** | **44 (13.4 %)** | **23.85 h** |
| machine failure (`klippy_shutdown` / disconnect / error) | 14 (4.3 %) | 23.3 h |

**Your defect catches are 3× more frequent than machine failures**, and they are almost entirely one
material: **40 of 44 are ASA**. So "the printer is unreliable" is the wrong frame — ASA part quality is.

Progress reached at cancel (against Orca's own estimate embedded in each filename): **median 24 %**,
quartiles 10 % / 60 %, and **26 of 44 cancelled below 35 %**. The defects surface **early** — which
points at bed adhesion and early thermal contraction, not a slow mid-print layer split.

### Three slicer facts that fit that signature

From the running job's resolved footer and the live config:

1. **`brim_type = no_brim`** (`brim_width = 0`). Large ASA parts run with no brim at all — the
   cheapest known guard against corner lift, switched off.
2. **`full_fan_speed_layer = 2`** with `close_fan_the_first_x_layers = 1`. Part cooling reaches full
   ASA fan speed by **layer 2**; warping and delamination are driven by exactly that. One layer of
   fan-off is not a warm-up.
3. **There is no chamber thermistor.** Klipper exposes `EBB_NTC`, `BTT-MCU`, `SOC`, `scanner` and
   `cartographer_coil` — nothing for the chamber. The slicer's `chamber_temperature = 40` is therefore
   **aspirational and unverified**: the machine cannot tell you whether the chamber ever reached 40 °C,
   and a 12-hour ASA print in a cold shop may never have.

### The 09:00 session, in order

Everything below needs the machine idle and you present. Nothing is applied without your say-so.

**A. Five-minute reads (no motion, no heat)**
- Confirm the three slicer facts above against the *live* profile rather than this print's footer.
- Read `heater_bed` and every temperature sensor while the chamber is closed, to state the real
  starting chamber temperature.

**B. ASA warping controls — slicer only, no printer risk (the highest-value fix)**
- `brim_type: no_brim → outer_only` (the enum value is `outer_only`; "outer" is not a valid value in
  2.5.0), `brim_width: 0 → 5 mm` for ASA.
- `close_fan_the_first_x_layers: 1 → 3–5`.
- `full_fan_speed_layer: 2 → 8`, or lower `fan_max_speed` from 30 % → 20 % for the ASA profile.
- Note the split: brim is a **process** setting, both fan fields are **filament** settings.
- Expected: cancels-at-<35 % fall. **Refuted if** the next 10 ASA jobs still cancel early at the same
  rate with brim on and fan delayed — that would move the cause to bed prep or chamber temperature.

**C. Pressure advance per material (needs heat)**
- Live PA is **0.0462** everywhere, which is an ASA number. All six materials share it.
- ASA first (it is 93 % of history), then PETG, PLA, TPU; PET-CF only if the hardened nozzle's flow
  behaviour is in doubt.
- Method: Orca PA tower per filament; record the printed value per profile immediately.

**D. Only after A–C: the volumetric cap.** The inherited 16 mm³/s stays until reliability and finish
have moved, per your ranking.

**Stop signal:** say **"stop calibration"** and I stop at the next safe point — never mid-move.

**Ledger is live:** `copybot`-style hourly `printer-failure-ledger` (cron, `:10`), writing
`data/printer/job-ledger.jsonl` and, for any failure, copying the matching `klippy.log` window into
`data/printer/failures/<job_key>.txt` **before the log rotates away**. That is the fix for the
unrecoverable-cause problem in §2. Note it can only capture from now on: the 38 historical shutdowns
have no logs left, and the current ledger run correctly recorded `0 evidence lines` for them rather
than pretending.

## 8. Questions — all answered 2026-11-12

- **0.6 CHT hardened? → YES.** PET-CF stays on the list; the nozzle-hardness risk is closed.
- **Cancels: you or the machine? → YOU**, after seeing delamination/warping. This is the §7 reframe:
  44 cancels that ran ≥0.1 h, 23.85 h, 96 % ASA, median 24 % progress. They stay in the failure
  denominator — they are quality failures, not noise.
- **Calibration window → tomorrow (2026-11-13) 09:00 CST**, operator present.

The original three questions are kept below for the record.

1. **Is the 0.6 CHT nozzle hardened?** PET-CF is abrasive. A standard brass CHT will be drilled out by
   it, and that would wreck surface finish on everything else afterwards — which is your #1 axis. If it
   is not hardened, PET-CF should come off the list until it is.
2. **Are the 178 `cancelled` mostly you aborting** (changing your mind, restarting with an edit) or the
   machine stopping? If mostly you, they leave the failure denominator; if the machine, that is a second
   failure class hiding inside the count.
3. **The calibration session:** the print finishes ~22:40 tonight. Do you want to do PA-per-material
   then (needs you present, machine idle, ~20 min for the ones that matter), or on a later evening?

## 6. Not doing yet, on purpose

- No config edits — including the 16 mm³/s cap. It is inherited, but changing it changes every material's
  behaviour at once, and you ranked speed last.
- No CPAP work. It needs a new toolhead, and it is the wrong tool for ABS/ASA (chamber heat wants *less*
  airflow). It is the right tool for PLA/PETG speed — a Step 4 conversation after a toolhead exists.
- No raising `max_accel`, per the shaper arithmetic above.
