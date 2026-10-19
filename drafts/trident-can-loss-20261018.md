# Trident CAN loss — diagnosis of `klippy.log` (2026-10-18)

Hardware history: SB2209 toolhead board replaced (120 Ω jumper fitted on both old and new), CAN cable
replaced, webcam removed, and the probe replaced — a damaged **Cartographer v3 → a new v4 in CAN mode**
(latching connector, can't work loose in motion).

Lost communication 3 h 29 m into `BC-250-pro-v2_ASA_5h30m.gcode`. **The node that died is the Cartographer
probe (`scanner`), not the toolhead board** — and the error density says the fault is local to the probe's
own tap, not the shared cable or the terminator census.

> **Two corrections to the first pass of this doc.** (1) With the 120 Ω jumper confirmed fitted on both
> SB2209s, "the board swap changed the terminator census" is no longer the leading theory — unless the new
> v4 arrived terminated (see the 40 Ω branch below). (2) Heat was my other candidate and **the temperature
> trace kills it outright.**

## Evidence base

Log: `klippy.log`, 29 MB, 19,340 `Stats` lines at 1 Hz, window `eventtime 967,795 → 987,148` (5 h 23 m).
The log is **rotated** — there is no `Start printer at` line, so this covers the tail of one boot only.

Three CAN nodes, all on `can0` (bridge = mainboard):

```
[mcu]         canbus_uuid b4bbe36cf8d6  canbus_interface can0   v0.13.0-464-g48f0b3ca  (137 cmds)
[mcu EBBCan]  canbus_uuid 336abf1555f3                          v0.13.0-762-g9871eeef  (143 cmds)
[mcu scanner] canbus_uuid dabce9b69073                          CARTOGRAPHER v4 6.2.0  (106 cmds)
klippy host                                                     v0.13.0-762-g9871eeef-dirty
```

The print: `SDCARD_PRINT_FILE BC-250-pro-v2_ASA_5h30m.gcode` at `eventtime 968,549.7`, bed 95 °C / extruder
260 °C. Failure at `eventtime 981,086.94` → **12,537 s = 3 h 29 m in**.

## Timeline (the whole finding)

| eventtime | into print | what happened |
|---|---|---|
| 967,795 | −12 m | Stats window opens; all nodes `rx_error=0 tx_error=0` |
| 968,549 | 0 | `BC-250-pro-v2_ASA_5h30m.gcode` starts |
| … | 0 → 2 h 49 m | **all three nodes clean, `rx_error=0 tx_error=0`** |
| 978,722 | 2 h 49 m | first `bus_state=warn` on `scanner` (rx_err 167) |
| 978,700–980,970 | 2 h 49 m → 3 h 25 m | mcu rx_err 0→65, EBBCan 0→56, scanner 0→3,812 |
| 981,074.9 | 3 h 27 m | **`scanner` `bus_state=passive`** (error-passive, rx_err 7,833) |
| 981,078.9 | 3 h 28 m | last `warn` (rx_err 7,899) |
| 981,086.9 | 3 h 29 m | `Timeout with MCU 'scanner'` → `Transition to shutdown state: Lost communication with MCU 'scanner'` |
| 981,087.9 | — | `scanner` gone (`unknown` for the remaining 6,057 s) |
| 981,086.9 | — | `MCU 'mcu' shutdown` + `MCU 'EBBCan' shutdown: Command request` — downstream, expected |
| 981,086 | — | last queued command: `get_canbus_status`; host was polling CAN health as it died |

**39 m 25 s of monotonic degradation**, then the probe went error-passive and silent.

## The three decisive counter readings

Serial dumps captured at the shutdown:

| node | rto | bytes_retransmit | bytes_invalid | verdict |
|---|---|---|---|---|
| `mcu` (bridge) | **0.025 s** | 1,111 | 9,148 | host↔USB link **healthy** (nominal rto, `srtt=0.001`, `ready_bytes=0`) |
| `EBBCan` | **0.025 s** | 229 | 244 | link nominal at shutdown |
| `scanner` | **3.200 s** | 157 | 233 | **128× the nominal rto** — retrying for seconds, then gave up |

`rto = 3.200 s` is the documented 128× backoff signature: the probe's own link was timing out on
retransmission. Its `receive_seq` also sat 7 behind `send_seq` at the end.

Per-node CAN error counters over the session (from `canstat_<mcu>`):

- `mcu`: 0 → **rx_err 128 / tx_err 23** (128 = the error-passive threshold)
- `EBBCan`: 0 → **rx_err 111** (`tx_error` never populated; RP2040 doesn't report it)
- `scanner`: 0 → **rx_err 7,946 / tx_err 104**, with 15 `warn` samples and 1 `passive` sample

**All three nodes climbed from exactly zero inside the same 20-minute window.** A single failing node
corrupts the bus for every node (it emits error frames), which is exactly this pattern — it does not mean
three independent faults.

`bytes_invalid` caution: the bridge's 9,148 is on its **USB** link (0.006 % of 147 MB — bookkeeping, per the
reference's 0.005 % rule), so it is *not* electrical evidence. The CAN-side invalid counts are 244 (EBBCan)
and 233 (scanner).

## What this is NOT — the webcam fix is holding

- No `error -71` / `-EPROTO`, no `USB disconnect`, no hub reset, no over-current.
- No `Unable to open CAN port` / `Network is down` — can0 never dropped.
- Bridge `rto=0.025`, `srtt=0.001`, `ready_bytes=0`, and it kept emitting `Stats` to the last second.
- No `Timer too close`, no `trsync_state` failure.

So the USB-hub/bandwidth failure that the webcam removal fixed is **not** what happened here. Removing the
camera was correct and it did its job; this is a separate, CAN-side fault.

## What the log cannot show

Whether the fault is in **the probe's pigtail and connector**, **the new CAN cable**, or **the terminator
count after the board swap**. All three produce this identical in-log signature (marginal link, degrading
under load/heat, worst at the far node). The log also cannot prove thermal causation — but a fault that is
absent for 2 h 49 m and then monotonic is by definition a **marginal** defect, not a broken wire (a broken
wire fails instantly and permanently).

## Measurement order (this is the whole next step)

Ohmmeter first, powered off at the mains; rails second; console third. Touch the probes together first and
subtract lead resistance (0.2–0.5 Ω). Do not chase ±5 % — the decisions live at 40 / 60 / 120 / 240.

**1. Terminator census — CANH↔CANL at the mainboard connector, printer OFF.**

- **≈60 Ω = correct** (two terminators: M8P fitted + SB2009 fitted). Then go to step 2.
- **≈120 Ω = ONE terminator — the SB2009's 120 Ω jumper is missing or not seated.** This is the single
  most likely consequence of a toolhead board swap, and it produces exactly this degradation. Locate the
  jumper on the new board by its silkscreen (not by a photo of a different revision), check it is *seated*.
- **≈40 Ω = three terminators** — something else is terminated; the probe's pads are the usual suspect
  (v4 ships **off**, so a bridged pad pair is the likely cause).
- Expected census: M8P terminated + SB2009 terminated + Cartographer v4 **unterminated** = 60 Ω. The
  vendor endorses terminating on the toolhead and treating the probe as a spur.

**2. Broken-conductor test — the one a 60 Ω reading cannot see.** H↔L closes its loop through the other
wire, so one open conductor still reads ~60 Ω. Measure end-to-end:

- **CANH↔CANH ≈ 0 Ω** and **CANL↔CANL ≈ 0 Ω** = both conductors intact.
- **one of them ≈ 240 Ω (= 2 × bus resistance) = that conductor is open** — a bad crimp in the new cable,
  the exact failure that passes every other test.

**3. Split the bus** at the mainboard to count each half: mainboard header alone ≈120 Ω, loose cable plug
≈120 Ω, and the two halves must recombine in parallel to the headline reading. **If the arithmetic does not
match, a connector or the cable is intermittent** — that mismatch is the finding.

**4. Wiggle test** — probes on H↔L while flexing each connector and the drag-chain bend. The reading must
not move. This is the only static test that reproduces a load-only crimp.

**5. Delta, not cumulative — but the naive version of this test CANNOT run on this machine.** Klipper refuses
to start when a configured MCU is absent, and `[stepper_z] endstop_pin = probe:z_virtual_endstop` means the
probe is load-bearing for homing, not merely present. "Unplug the probe and soak it" is therefore invalid.
The two tests that do run:

- **Idle hot soak, zero config change.** The probe streams `cartographer_data` + `analog_in_state` at
  ~104 msg/s continuously from boot — its own traffic is on the bus whether or not anything is printing, so
  no print is needed to load the spur. Heat to print temps, leave idle 1–2 h, sample the deltas every 10 min.
  Screens traffic- and heat-driven faults; cannot test motion or drag-chain flex.
- **Stub the probe out (~5 comment-outs).** Comment `[mcu scanner]` (L782), `[cartographer]` (L785),
  `[adxl345] cs_pin = scanner:PA3` (L791) + `[resonance_tester] accel_chip`, and expect `[scanner]` in
  SAVE_CONFIG to complain too. **Z homing is then impossible** — use `G28 X Y` and move with
  `[force_move] enable_force_move = true` (already set, L229–230) or an X/Y-only pattern. Restore by
  uncommenting. Flat counters over an hour = the fault travels with the probe's tap.

Either way the meter is cheaper and strictly more informative than both:

**5b. Delta, not cumulative**, once the machine is healthy again — sample twice 10 min apart idle, then twice
10 min apart printing:

```bash
grep -o "canstat_[A-Za-z ]*: bus_state=[a-z-]* rx_error=[0-9]* tx_error=[0-9]* tx_retries=[0-9]*" \
  ~/printer_data/logs/klippy.log | tail -6
```

Healthy = flat (0–2 per run) with `ip -statistics link show can0` error counters flat. If the delta climbs
with the probe's CAN lead **removed** and stops with it attached, the fault travels with the probe/stub.

**6. Reseat the probe's 4-pin CAN lead at both ends.** It was disturbed by the board swap, it lives in the
hotter, higher-vibration position of the three nodes, and it is the node that died. Cheapest step, do it
even if the numbers pass.

## Adjacent finding 2: the Cartographer config is half-migrated (v3-era ⇄ v4-era)

The SAVE_CONFIG block holds **both generations' model data** — the fingerprint the reference names explicitly:

```
[scanner model default]        model_fw_version = CARTOGRAPHER 5.0.0     <- v3-era
[scanner]                      scanner_touch_threshold = 2000            <- v3-era section
[cartographer scan_model default]   mcu_version = CARTOGRAPHER v4 6.2.0  <- v4-era
[cartographer touch_model default]  mcu_version = CARTOGRAPHER v4 6.2.0  <- v4-era
```

So the live config carries `[cartographer] mcu = scanner` (new plugin) while SAVE_CONFIG still keeps the old
`[scanner model default]` / `[scanner]` blocks from the 5.0.0 era. This is **not** the CAN fault — stale model
data cannot corrupt frames — but it is the next thing that will bite, and the newer plugin's own instructions
say to remove all `[scanner]` lines *including those inside SAVE_CONFIG*. Treat as a separate task; do not
hand-edit SAVE_CONFIG in the middle of bus debugging.

## Adjacent finding (free, do not act on it yet)

**Firmware skew:** host and `EBBCan` are on `v0.13.0-762`, the mainboard `mcu` is on `v0.13.0-464`
(~298 commits behind, 137 vs 143 commands). Worth a reflash — but **after** the bus is fixed, because
flashing the bridge MCU needs a `can0` that stays up. A bridge that drops mid-write is how a board ends up
parked in its bootloader.

## Error density — why the fault is the probe's tap, not the bus

Per-node errors normalised by that node's own message count (`send_seq` at shutdown), because a cable or
terminator fault corrupts the same copper for everyone and therefore scales with traffic:

| node | messages sent | rx_errors | errors per 1,000 msgs |
|---|---|---|---|
| `mcu` (bridge) | 4,343,924 | 128 | **0.029** |
| `EBBCan` | 2,360,854 | 111 | **0.047** |
| `scanner` | 2,006,179 | 7,946 | **3.960** |

The bridge transmits **twice** as much as the probe and error-checks **136× cleaner**. A shared-wire or
termination defect cannot produce a 136:1 outlier, because every node sees the same corrupted bits in
proportion to its own traffic. **This localises the fault to the probe's own tap: its lead/pinout, its
transceiver, or a terminator at the spur.**

## Temperature ruled out — the machine was hottest when it was healthy

`[temperature_sensor scanner]` (the probe's own board) plus `EBB_NTC`:

- Probe peak **76.8 °C at 55 min** — with **zero** errors, and zero for another 2 h.
- At the failure (225 min) the probe was **63.3 °C**, flat at ~61–63 °C since 120 min.
- `EBB_NTC` was already **74.6 °C at 65 min** and held 70.5 °C for 2 h through a completely clean bus.

So the failure is **anti-correlated with temperature**. The onset at 182 min happened at a flat, *lower*
temperature than the 30–75 min window that ran clean. Thermal and "the probe is cooking" are both dead.

## Two things the log shows that nobody asked about

- **The probe was streaming continuously for the whole 5.4 h** — `cartographer_data` + `analog_in_state`
  arrive every ~117 ms at the moment of death (~104 msg/s from the probe), and the plugin logged
  `[cartographer] Stopping stream` **only at the failure** — there is no `Starting stream` anywhere after
  the startup probe sequence. Streaming belongs to probing/scanning, not to a print. That is ~5 h of
  sustained traffic on the spur that the machine should not have been carrying.
- **The print had essentially finished.** `Virtual sdcard (9217054)` current, `Upcoming (9218078)`, and
  `Exiting SD card print (position 9218107)` — the file was read to its end with **~1 KB of gcode left**,
  i.e. the end sequence. The part itself was done; what the crash stole was the park/lift/cooldown tail.

## Ranked reading of the repair history

Three parts were replaced and it still failed, so the ranking is now by what the *evidence* points at, not
by what was touched. Candidates, most to least likely:

1. **The new v4 arrived terminated — pads bridged (~40 Ω).** The reference is explicit that v4 ships off but
   *can* be terminated on the pads, and a third terminator sitting **at the end of the probe's spur** reflects
   faults straight back into that tap — which is exactly the per-node signature measured above. This is the
   first thing the ohmmeter answers.
2. **The probe's own lead — pinout or crimp.** A latching connector at the probe end proves the connector
   cannot vibrate loose; it says nothing about the far end, the crimp, or whether **CANH/CANL are the right
   way round** for this board. A reversed H/L pair runs, marginally, and fails exactly like this.
3. **The v4 board itself (transceiver).** New hardware is a hypothesis, not a guarantee — and this machine
   already had one damaged probe.

Not candidates, on the numbers: the shared CAN cable and the terminator *count* (error density, above), heat
(temperature trace, above), the toolhead board (its errors are collateral — though note EBBCan can never
report warn/passive, `src/rp2040/can.c` hardcodes `bus_state=ACTIVE`, so "EBBCan stayed active" is not
evidence of health either), and the USB side (bridge `rto=0.025` throughout).

---

## MEASURED 2026-10-19 — hypothesis 1 is REFUTED for the two boards, and the topology is 3 nodes

Operator metered the bus with the **CAN cable unplugged** (the M8P↔SB2209 umbilical) and read **120 Ω at
the SB2209 and 120 Ω at the M8P**.

Topology confirmed from `klippy.log` — there are **three** CAN MCUs on this bus, not two:

| node | canbus_uuid | log line |
|---|---|---|
| `[mcu]` (M8P mainboard) | `b4bbe36cf8d6` | L548 |
| `[mcu EBBCan]` (SB2209 toolhead) | `336abf1555f3` | L545 |
| `[mcu scanner]` (**Cartographer v4**) | `dabce9b69073` | L783 |

**120 Ω at each end, measured in isolation, is the textbook healthy state** — one terminator per end,
≈60 Ω once the cable is in. So the two boards are correct and the "did the cable arrive terminated / is a
terminator missing" question is closed.

What is still **not** measured is the third node. If the v4's termination pads are bridged, the assembled bus
reads **≈40 Ω** (three 120 Ω in parallel) instead of 60 Ω — electrically out of spec, and a terminator sitting
at the **end of the probe's spur** reflects faults straight back into that tap. That is the per-node signature
this fault has (scanner 3.96 errors/1,000 msgs vs mcu 0.029 and EBBCan 0.047 — a **136×** gap on a shared bus).

### The two measurements that settle it (≈60 s, meter already out)

1. **Probe isolated** — unplug the Cartographer's CAN lead and meter CANH↔CANL **on the probe's own
   connector**. Expect **open / no continuity**.
   - open → the probe is not terminated; bus termination is correct and hypothesis 1 is fully dead.
   - **≈120 Ω → third terminator confirmed.** Remove the bridge on the v4's pads and the bus returns to spec.
2. **Assembled bus** — cable back in, probe back in, meter CANH↔CANL at either board. Expect **≈60 Ω**.
   - ≈60 Ω → termination correct end-to-end.
   - **≈40 Ω → the probe is terminated** (same finding as (1), no need to repeat).
   - **120 Ω → a line is not conducting**: one conductor, a pin, or a crimp is open even though the other
     line and the terminator read fine. That is a cable/connector fault, and it would look exactly like this
     fault on the wire.

If (1) reads open **and** (2) reads 60 Ω, termination is not the cause and the remaining suspect is the
probe's **spur/stub and connector contact** — the hypothesis-2 family (reversed H/L pair, crimp, far-end
connector), which no resistance reading detects and which the idle hot soak then has to separate from a
thermal/board fault.

**Next in the cost order after the meter: the idle hot soak** (no config change — the probe streams
`cartographer_data` + `analog_in_state` at ~104 msg/s from boot regardless of printing). Printer is currently
powered down (`192.168.1.100` unreachable), so the soak waits on power-on.

