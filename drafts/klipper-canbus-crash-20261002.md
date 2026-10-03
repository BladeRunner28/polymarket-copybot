# Klipper crash triage — CAN bus, Manta M8P (CM4) + SB2009 toolhead + Cartographer v4

**Source:** `klippy.log`, rollover **Fri Oct 2 2026 09:22:14**, 33,038 lines, **8 boots**, log ends 12:32:04 (uploaded 12:32).
Read from the log's own resolved config dump (every `[include]` is inlined), so no `printer.cfg` was needed.
Host: Raspberry Pi CM4 (`/home/xsnyde2/klipper`, `~/printer_data`), Klipper **v0.13.0-762-g9871eeef**.

**Verdict: three separate faults, none of them a config error.** The crash that killed the print is a
transport failure on the host↔mainboard link; the restart failures are a can0 lifecycle bug; and behind both
is a CAN bus that degrades under load (143,421 retransmissions in one 2h49m session).

---

## 1. Boot-by-boot timeline (segmented from the log)

| # | Start | MCUs loaded | Died on |
|---|---|---|---|
| 1 | 09:22:14 | **none** | ENETDOWN ×18 → `MCU error during connect` → `Error configuring printer` |
| 2 | 09:25:23 | mcu, EBBCan, scanner | `Error during homing stepper_y: Unable to obtain 'trsync_state' response` → CANCEL_PRINT → `Shutdown due to webhooks request` (09:37:10) |
| 3 | 09:37:10 | **none** | ENETDOWN ×2 |
| 4 | 09:37:20 | mcu, EBBCan, scanner | **`Timeout with MCU 'mcu'` → `Lost communication with MCU 'mcu'`** (≈12:26:53), then scanner + EBBCan timeouts, then `Network is down` / `No such device` |
| 5 | 12:26:53 | **none** | ENETDOWN ×2 |
| 6 | 12:27:00 | mcu, EBBCan, scanner | `Can not update MCU 'mcu' config as it is shutdown` → `Error configuring printer` |
| 7 | 12:27:11 | mcu only | ENETDOWN ×2 |
| 8 | 12:27:23 | mcu, EBBCan, scanner | **current state** — no error; idle, heaters off, log ends 12:32:04 |

All three UUIDs are identical in every boot — `mcu b4bbe36cf8d6`, `EBBCan 336abf1555f3`, `scanner dabce9b69073`
— so there is no stale-UUID problem and nothing to re-query with `canbus_query.py`.

## 2. The crash that killed the print (boot 4)

An ASA job (`right-nozzle-scrubber-remix_ASA_1h3m.gcode`) started inside this session; it exited at
gcode position **3,650,248** when the shutdown hit. The last five `Stats` lines before the failure:

| Field | Trajectory |
|---|---|
| `bytes_write` / `bytes_read` ([mcu]) | frozen at 30,392,343 / 5,161,817 for ~5 s |
| `bytes_retransmit` ([mcu]) | 172 → 495 → 755 → 885 → **1015** |
| `rto` ([mcu]) | 0.025 s → **3.200 s** (128×) |
| final serial dump | `send_seq=579581 receive_seq=579578 retransmit_seq=579581 srtt=0.001 rto=3.200 ready_bytes=14205` |

then:

```
Timeout with MCU 'mcu' (eventtime=10979.229907)
Transition to shutdown state: Lost communication with MCU 'mcu'
MCU 'mcu' shutdown:
MCU 'EBBCan' shutdown:
MCU 'scanner' shutdown:
Timeout with MCU 'scanner' (eventtime=10979.229907)
Timeout with MCU 'EBBCan' (eventtime=10980.230320)
b'Got error -1 in can read: (100)Network is down'
b'Got error -1 in can read: (19)No such device'
Exiting SD card print (position 3650248)
```

**What this means:** Klipper stamps a "Lost communication" when the host stops receiving message
acknowledgements from that MCU inside its retransmit window; the rising `rto` and the climbing
`bytes_retransmit` show the link degrading before it died, and `ready_bytes=14205` means a pile of
partially-received bytes was sitting unparsed. `[mcu]` here is the **Manta M8P's STM32H723** — the board
that is *also* the USB↔CAN bridge for `can0` (its `freq=519,993,162` ≈ 520 MHz identifies the H723;
`EBBCan` is the RP2040 SB2009, `scanner` is the STM32G431 Cartographer). So when it dropped, the two
downstream nodes dropped with it and the kernel interface vanished.

**What the log does not prove:** whether the STM32 reset, the USB link between CM4 and STM32 dropped, or
the kernel took can0 down first. Only the kernel knows — run:

```
journalctl -k -S "2026-10-02 12:20" | grep -iE "can|usb|cdc_acm|xhci|hub"
ip -details -statistics link show can0
dmesg -T | tail -40
```

The host itself was **not** overloaded: `sysload=0.39`, one reactor stall of 0.078 s, 3.4 GB RAM free.

## 3. The restart failures are a can0 lifecycle bug (4 of 8 boots)

Boots 1, 3, 5, 7 never reached the bus at all:

```
mcu 'mcu': Starting CAN connect
Created a socket
mcu 'mcu': Unable to open CAN port: Failed to transmit: [Errno 100] Network is down    ← ENETDOWN, ×18 in boot 1
```

Klipper's CANBUS docs describe exactly this: *"Whenever the 'bridge mcu' is reset, Linux will disable the
corresponding can0 interface. To ensure proper handling of FIRMWARE_RESTART and RESTART commands, it is
recommended to use **allow-hotplug** in the /etc/network/interfaces.d/can0 file."* Every restart resets the
bridge MCU, can0 goes down, and nothing brings it back — so the next `FIRMWARE_RESTART` fails, and the one
after that succeeds. Boot 6 is the same fault caught mid-connect
(`Can not update MCU 'mcu' config as it is shutdown`).

This is the "my printer crashes every time I restart it" symptom, and it is independent of the 12:26 crash.

> **⚠️ Superseded — see §6d for the actual root cause.** The `allow-hotplug` file below assumes Debian's
> `ifupdown`, which is **not installed here** (`ifdown: command not found`); the interface is managed by
> **systemd-networkd** instead, and its CAN config fails on an unsupported option. Fix in §6d, not here.

## 4. The underlying problem: a CAN bus that degrades under load

`canstat_EBBCan tx_retries` across boot 4 (2h49m), by log position:

| Time into session | `tx_retries` (EBBCan) |
|---|---|
| boot start | 1 |
| early | 76 |
| early print | 529 → 567 |
| mid print | 10,722 → 33,258 |
| late print | 54,935 → 77,818 |
| ~2h20m | 102,081 → 127,981 |
| **at the crash** | **143,421** |

≈ **13 retransmissions per second, on the toolhead node only** — `mcu` and `scanner` sat at **0** for the
whole session. Additionally all three nodes logged non-zero `bytes_invalid` (mcu 260, scanner 123,
EBBCan 91): bytes on the wire that failed framing. On a healthy 1 Mbit CAN segment with three nodes these
should be ~0.

> **⚠️ Correction (2026-10-02, after reading Klipper's CAN drivers): the 0-vs-143,421 contrast is a DRIVER
> ARTIFACT and does not convict the toolhead's wiring.** `tx_retries` is populated by exactly one Klipper CAN
> driver — `src/rp2040/can.c`, from CAN2040's `tx_attempt - tx_total`. `src/stm32/fdcan.c` (which drives both the
> H723 mainboard and the G431 Cartographer) and `src/stm32/can.c` (F-series) **never set the field**, so an STM32
> node reports 0 however bad its cable is; `rp2040/can.c` also hardcodes `bus_state = CANBUS_STATE_ACTIVE`, so the
> toolhead can never report warn/passive/off. CAN2040's counter additionally includes **lost arbitration**, which
> is normal on a busy 1 Mbit bus. So this number is a trajectory to watch (delta idle vs printing), not a finding on
> its own — the physical-layer case rests on the `bytes_invalid` counts, the `rto` ramp with frozen byte counters
> (§2), and the ohmmeter (§10). *(An earlier version of this section said retry growth on one node convicts that
> node's physical layer; retracted.)*

Non-zero `bytes_invalid` on **all three** nodes, by contrast, is the framing-corruption signal and remains the
real argument for a marginal physical layer (termination/cable/connector) rather than firmware or G-code.

Boot 2 is the same fault with a different error string: the print failed during homing with
`Unable to obtain 'trsync_state' response`. trsync is Klipper's cross-MCU endstop synchronisation — the
response travels over this bus, so a lossy segment produces exactly that timeout. `on_error_gcode:
CANCEL_PRINT` (from `[virtual_sdcard]`) is what turned a G-code error into a shutdown, and the job then
died at position 23,279.

Current boot (8): EBBCan is already at 35 retries after ~5 minutes, mcu `bytes_invalid=18`. Calmer than
boot 4, but nothing has been fixed — this needs re-measuring idle vs under load.

## 5. What is NOT the problem

- **Config is clean.** Four boots loaded and configured all three MCUs: `mcu` 137 commands, `EBBCan` 143,
  `scanner` 106 (`CARTOGRAPHER v4 6.2.0`). No `pins.error`, no `Config error`, no rename fallout.
- **The probe works.** `[cartographer] Initialized CARTOGRAPHER v4 6.2.0 MCU`, it homes, and reports
  `probe at 175.000,175.000 is z=316.347593`; `bed_mesh` generated its 400 points.
- **No `Timer too close`, no move-queue overflow, no "too many retries"** anywhere in the log.
- **The toolhead firmware matches the host** (`v0.13.0-762-g9871eeef` on both).

## 6. Three adjacent findings (not the cause, fix in order)

1. **Mainboard firmware is 298 commits behind.** `[mcu]` = `v0.13.0-464-g48f0b3ca`; host and `EBBCan` =
   `762-g9871eeef`. Reflash the M8P from this host (same options it was built with) — but **after** §3, because
   flashing the bridge needs a can0 that stays up.
2. **The 48 V rail may be sagging.** Boot 2 logged `TMC 'stepper_x' reports GSTAT: 00000005 reset=1(Reset)
   uv_cp=1(Undervoltage!)` on `stepper_x`, `stepper_x1`, `stepper_y`, `stepper_y1` (the TMC5160s, driven at
   48 V per the `autotune_tmc` output) while the TMC2209s on Z/extruder reported only a plain reset. Check the
   supply under load and watch for further `uv_cp`.
3. **Half-finished Cartographer migration in SAVE_CONFIG.** It holds *both* generations: `[scanner model
   default]` with `model_fw_version = CARTOGRAPHER 5.0.0` (old) **and** `[cartographer scan_model default]` /
   `[cartographer touch_model default]` with `mcu_version = CARTOGRAPHER v4 6.2.0` (current, plugin 1.8.0b2).
   The live plugin generation is `[cartographer] mcu = scanner` + `[adxl345] cs_pin = scanner:PA3` — correct
   for v4 firmware — so the leftover `[scanner model default]` block should be cleaned up deliberately, not
   left to be latched by mistake. Record the models before deleting anything.

## 6b. Follow-up (2026-10-02): `allow-hotplug` did NOT hold — why, and what replaces it

> **Superseded by §6d:** this section reasons from the `ENETDOWN`/uevent angle, which turned out to be
> irrelevant — the manager fires correctly and its own config is what fails. The watchdog below still works
> but is a workaround, not the fix.

Reported: after adding `allow-hotplug can0` to `/etc/network/interfaces.d/can0`, a **`FIRMWARE_RESTART` still
kills can0** and the interface has to be brought up by hand.

**That is the expected consequence of how `allow-hotplug` is implemented, not a mistake in the file.**
Debian's ifupdown reacts to hotplug through udev's `net` rules
(`/usr/lib/udev/rules.d/85-ifupdown.rules`), which run `ifup --allow=hotplug <iface>` on the **`add` action of
a net device**. A device that is *removed and re-created* fires that action. A device that merely **goes DOWN**
fires nothing at all — and "down" is exactly what Klipper is reporting:

```
mcu 'mcu': Unable to open CAN port: Failed to transmit: [Errno 100] Network is down
```

`[Errno 100] ENETDOWN` = *the interface exists but is not UP*. When Klipper resets the bridge MCU
(`restart_method: command` resets the STM32 internally), the gs_usb device does not re-enumerate, so no udev
`add` event is emitted and `allow-hotplug` has nothing to trigger it. `auto can0` is boot-only. Nothing on a
stock RPi OS Bookworm watches link state for CAN, so can0 stays down until a human runs `ip link set`.

**Decisive one-liner** (which of the two states you are actually in):

```bash
# right after a FIRMWARE_RESTART:
ip -details link show can0 || echo "GONE (device deleted -> hotplug should work, so something else is wrong)"
sudo ifup can0; echo "ifup exit=$?"        # 0 = the file/ifupdown is fine, only the TRIGGER is missing
nmcli device status | grep -i can          # is NetworkManager managing or ignoring can0?
ls /etc/network/interfaces.d/; grep -n "interfaces.d" /etc/network/interfaces
```

**Recommended fix: a 2-second systemd watchdog** (covers both states — it re-ups a downed interface and picks
the interface up whenever it reappears, and it does not care whether a udev event fired):

```bash
sudo tee /usr/local/sbin/can0-keepup.sh >/dev/null <<'EOF'
#!/bin/sh
# Keep can0 up. Klipper's bridge-MCU resets take the interface DOWN without a
# udev 'add' event, so allow-hotplug never fires; ifupdown's 'auto' is boot-only.
IF=can0
ip link show "$IF" >/dev/null 2>&1 || exit 0          # not present (mid re-enumeration) - retry next tick
ip link show "$IF" | grep -qE '<[^>]*\bUP\b' && exit 0
ip link set "$IF" up type can bitrate 1000000
ip link set "$IF" txqueuelen 128
logger -t can0-keepup "brought $IF up (was down)"
EOF
sudo chmod +x /usr/local/sbin/can0-keepup.sh

sudo tee /etc/systemd/system/can0-keepup.service >/dev/null <<'EOF'
[Unit]
Description=Keep can0 up (Klipper CAN bridge)
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/can0-keepup.sh
EOF

sudo tee /etc/systemd/system/can0-keepup.timer >/dev/null <<'EOF'
[Unit]
Description=Poll can0 link state
[Timer]
OnBootSec=5
OnUnitActiveSec=2
AccuracySec=1
[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now can0-keepup.timer
systemctl list-timers can0-keepup.timer --no-pager
```

Proof it works: fire `FIRMWARE_RESTART` from Mainsail and within ~2-4 s
`ip -details -statistics link show can0` reads **UP** with no manual step, and
`journalctl -t can0-keepup -n 5` shows `brought can0 up (was down)`.

**Alternatives, in order of how much I'd trust them here:**

1. **NetworkManager profile** (cleanest if NM is the active manager on this image, which it is by default on
   Bookworm): `sudo nmcli con add type can ifname can0 can.bitrate 1000000 ipv4.method disabled ipv6.method disabled`
   — NM tracks link state and re-activates on its own. Only pick this if `nmcli device status` shows can0 as
   *unmanaged* today and you are willing to hand the interface to NM instead of ifupdown.
2. **udev rule on the add action** — `SUBSYSTEM=="net", KERNEL=="can0", ACTION=="add", RUN+="/sbin/ip link set can0 up type can bitrate 1000000"`.
   Equivalent to `allow-hotplug` and therefore subject to the same caveat: it only helps if the device really is
   re-created.
3. **Do not** try `auto can0` or a bigger `post-up` block — `auto` is evaluated once at boot, and the bridge
   reset happens long after that.

Run the decisive one-liner first and paste the output: if `ifup can0` returns non-zero, the file or ifupdown
itself is the problem (Bookworm ships NetworkManager by default and `ifupdown` is not always installed — check
`dpkg -l ifupdown`), and the watchdog above is then the right answer rather than a patched interfaces file.

**Scope note:** this removes the *restart* pain only. The 12:26 crash and the 143,421 retransmissions are still
the physical-layer item (§4 / option B) — a working can0 watchdog will happily keep an electrically marginal bus
alive right up to the next `Lost communication`.

---

## 6c. Correction (2026-10-02): `ifupdown` is NOT installed on this image

> **Superseded by §6d** for the fix; kept for the account of what was ruled out.

`ifdown` is not found on the CM4, so **`ifupdown` is not installed** — which means
`/etc/network/interfaces.d/can0` is read by *nothing at all*. The `allow-hotplug can0` line was **inert from
the moment it was written**; that is why nothing changed, and it is not evidence about the uevent question in
§6b (the two faults look identical from the outside: "can0 still down after FIRMWARE_RESTART").

This is a well-known mismatch: Klipper's CANBUS page gives the `allow-hotplug` snippet because it assumes
Debian's classic `ifupdown`, while Raspberry Pi OS **Bookworm** ships **NetworkManager** and no longer
installs `ifupdown` by default. So on this host the entire `/etc/network/interfaces*` route is dead code —
delete the file so it cannot mislead the next person:

```bash
sudo rm -f /etc/network/interfaces.d/can0      # inert on this image
dpkg -l ifupdown 2>/dev/null | tail -1         # expect: no packages found
```

**Step 1 — find what actually brings can0 up today.** It comes up on four of the eight boots (2, 4, 6, 8), so
*something* does it; that thing is where the fix belongs:

```bash
ip -br link show can0; echo "---"
systemctl list-units --type=service --state=running --no-pager | grep -iE "can|network"
grep -rls "can0" /etc/systemd/system /etc/systemd/network /usr/lib/systemd/system /etc/udev/rules.d \
  /etc/NetworkManager /lib/systemd/network /etc/rc.local 2>/dev/null
nmcli -t device status | grep -i can; nmcli -t con show | grep -i can
sudo journalctl -b | grep -iE "can0" | head -20
```

The likeliest answers, in order: (a) a **systemd-networkd** `*.network` file with a `[CAN]` section
(`/etc/systemd/network/can0.network`), (b) a **NetworkManager** CAN profile, (c) a small custom unit or
`rc.local` line. Any of them can be extended — but the watchdog below does not need to know which it is.

**Step 2 — the mechanism-agnostic fix (recommended, works with all three).** Idempotent: it acts *only* when
can0 is present and not UP, so it cannot fight NetworkManager, networkd or a custom unit, and it also covers the
case where the interface is briefly deleted and re-created. Script + units: see §6b. Pass = `ip -details
-statistics link show can0` is **UP** within ~2-4 s of a `FIRMWARE_RESTART`, with `journalctl -t can0-keepup`
recording `brought can0 up (was down)`.

**Step 3 (optional, tidier but less certain)** — if the discovery above shows a systemd-networkd
`/etc/systemd/network/can0.network`, add the CAN section there instead of using the watchdog:

```ini
[Match]
Name=can0
[CAN]
BitRate=1M
```

systemd-networkd re-applies link configuration when the link changes state, which is the closest thing to a
native fix; verify it against a `FIRMWARE_RESTART` before trusting it, because whether networkd re-ups an
interface that merely went DOWN (rather than disappeared) is exactly the question at issue — and the watchdog
in §6b is the fallback that does not depend on the answer.

**Scope note** (same as §6b): all of this fixes restart recovery only. The 12:26 `Lost communication` and the
143,421 retransmissions are the physical layer (§4 / option B).

---

## 6d. ROOT CAUSE (2026-10-02, kernel journal): systemd-networkd cannot configure this `gs_usb` bridge — corrected after reading the file

The journal answers everything §6b/§6c could only hypothesise: it is **not** a uevent question, **not** ifupdown,
and **not** a missing watchdog. The manager fires correctly on every re-enumeration and then fails its own apply:

```
12:27:10 kernel:       usb 1-1.4: USB disconnect, device number 9
12:27:10 systemd-networkd: can0: Link DOWN / Lost carrier
12:27:10 kernel:       gs_usb 1-1.4:1.0: Configuring for 1 interfaces
12:27:10 NetworkManager:  (can0): new Generic device
12:27:10 systemd-networkd: can0: Configuring with /etc/systemd/network/25-can.network.
12:27:10 systemd-networkd: can0: Failed to set CAN interface configurations:
                           Device doesn't support restart from Bus Off. Operation not supported
12:27:10 systemd-networkd: can0: Failed
12:27:21 sudo:        xsnyde2 : ip link set can0 up type can bitrate 1000000
12:27:21 systemd-networkd: can0: Link UP / Gained carrier          ← the manual up works instantly
```

**Who is in charge:** `systemd-networkd` (`/etc/systemd/network/25-can.network`), not ifupdown (§6c) and not
NetworkManager — `nmcli` reports `can0:can:unmanaged`, so NM correctly leaves it alone. That also explains the
boot-3→4 and 5→6→7→8 gaps: each `FIRMWARE_RESTART` re-enumerates the STM32, networkd tries to re-apply the
file, **the apply fails atomically**, and the link is left DOWN until a human runs `ip link set`.

**Why the apply fails:** networkd's own message blames the CAN *auto-restart-from-bus-off* timer (the kernel's
`restart-ms` attribute), which `gs_usb` does not implement, and networkd's CAN configuration is **atomic** —
`EOPNOTSUPP` on that one attribute aborts the whole apply, so `BitRate=` never lands either and the link is left
DOWN.

> **⚠️ Correction (2026-10-02, after inspecting the file):** `/etc/systemd/network/25-can.network` contains **no
> `RestartSec=` line at all** — it is exactly this:
>
> ```ini
> [Match]
> Name=can*
> [CAN]
> BitRate=1M
> [Link]
> RequiredForOnline=no
> ```
>
> So the rejected attribute is **sent by systemd-networkd itself**, not requested by the file — and the earlier
> "delete the `RestartSec` line" instruction was wrong (it reasoned from the error string to a file line instead of
> asking for the file first). **Do not replace that guess with a second one:** the follow-up measurement
> (`restart-ms 0` accepted by iproute2, below) shows the driver is *not* simply missing restart-ms, so what
> networkd trips on is still **unconfirmed** — either another attribute or the moment it applies. What IS settled:
> networkd marks the link failed, never retries, and leaves it DOWN, so the practical fix has to move the
> configuration out of the `.network` file.

**What was MEASURED (2026-10-02) and what is still open:**

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 restart-ms 0   # MEASURED: accepted, NO "Operation not supported"
sudo ip link set can0 type can bitrate 1000000                # accepted (the line that works by hand)
```

So `bitrate` **+** `restart-ms 0` in one request, issued over iproute2 while the link is down, is accepted by this
`gs_usb` driver. The earlier claim that the driver "does not implement restart-ms" is therefore **not confirmed** —
networkd's `EOPNOTSUPP` must come from either (a) a different attribute in the request networkd builds, or (b) the
*time* at which it sends it (networkd applies within the same second as `gs_usb ... Configuring for 1 interfaces`,
i.e. possibly before the CAN device is fully registered — and networkd does **not** retry a link it has marked
failed).

**Decisive repro, no USB cycle needed** (`networkctl reconfigure` re-applies the same `.network` file to an
already-stable device):

```bash
sudo ip link set can0 down
sudo networkctl reconfigure can0; echo "reconfigure exit=$?"
sleep 1; ip -br link show can0
sudo journalctl -b --since "30 sec ago" | grep -i can0
```

- **Fails again while the device is stable** → genuine config incompatibility; name the attribute by running
  networkd in the foreground with `sudo systemctl stop systemd-networkd && sudo /usr/lib/systemd/systemd-networkd --log-level=debug`
  and re-issuing the reconfigure in a second shell.
- **Succeeds while stable** → it is a **race with re-enumeration**, not a config problem; networkd simply gives up on
  the first attempt and has no retry.

Either outcome leads to the same fix below, which is why the fix is worth applying without waiting for the answer.

**Fix — take can0 out of networkd and configure it out-of-band with the exact command that already works.**

```bash
sudo cp /etc/systemd/network/25-can.network /etc/systemd/network/25-can.network.bak
sudo tee /etc/systemd/network/25-can.network >/dev/null <<'EOF'
[Match]
Name=can*

[Link]
Unmanaged=yes
EOF
sudo systemctl restart systemd-networkd
```

With `Unmanaged=yes` neither networkd nor NetworkManager (already `unmanaged` there) touches the interface, so
there is no half-applied CAN config and no `can0: Failed` any more. Bring-up is done by the §6b watchdog, whose two
commands are character-for-character the ones that work by hand:

```
ip link set can0 up type can bitrate 1000000
ip link set can0 txqueuelen 128
```

Same-command alternatives to the watchdog: a udev rule on `ACTION=="add"`
(`SUBSYSTEM=="net", KERNEL=="can0", ACTION=="add", RUN+="/usr/sbin/ip link set can0 up type can bitrate 1000000"`),
or a oneshot unit ordered after the device appears. The watchdog is preferred because it also recovers a link that
goes DOWN without ever disappearing.

**Do not** "just drop the `[CAN]` section": that removes the bitrate along with the failure, and an interface that
is UP with no bitrate is useless to Klipper.

**Pass test:** fire `FIRMWARE_RESTART` from Mainsail and check, with **no manual command**:

```bash
ip -br link show can0                                     # expect: can0  UP
sudo journalctl -b --since "2 min ago" | grep -i can0 | grep -iE "Configuring|Failed|Link UP"
# expect: "Configuring with /etc/systemd/network/25-can.network." then "Link UP" and NO "Failed to set CAN ..."
ip -details -statistics link show can0                    # bitrate 1000000, no BUS-OFF
```

**Consequences for the earlier advice:** the §6b watchdog is now **the fix** rather than belt-and-braces, and the
NetworkManager profile from §6b-option-1 stays off — can0 should be left unmanaged by *every* manager, with exactly
one mechanism (the watchdog) responsible for its parameters.

### 6d-i. The 12:25 crash in kernel terms (separate from the can0-up problem)

```
12:25:02 kernel: gs_usb 1-1.4:1.0 can0: failed to xmit URB 0/2/3/4/5/6/7: -EPROTO      ← 7 URBs, 1 second
12:25:06 kernel: usb 1-1.1: USB disconnect, device number 3
12:25:07 kernel: usb 1-1.2: USB disconnect, device number 4
12:25:07 kernel: usb 1-1.4: USB disconnect, device number 6                           ← gs_usb bridge = 1-1.4
12:25:09 kernel: gs_usb 1-1.4:1.0: Configuring for 1 interfaces                       ← back 3 s later
```

`-EPROTO` on xmit means the device stopped answering URBs per the protocol — i.e. the STM32 bridge itself
crashed/reset mid-transfer, taking the whole `1-1.x` USB hub segment (three devices) with it, and re-enumerated
3 s later. Klipper's `Lost communication with MCU 'mcu'` at 12:26:5x is the host's delayed detection of exactly
this: USB died at 12:25:06, klippy spent ~1.5 min timing out and writing its shutdown dump, then boot 5 started.

This is the fault that killed the print, and it is independent of the can0-up bug. Two follow-ups, in order:
(a) **the physical layer** (§4 / option B — the bridge is the single STM32 that both runs Klipper's own duties
*and* forwards every CAN frame over USB; ~13 retransmissions/s from the toolhead node is a plausible way to starve
it, but that is a hypothesis, not a measurement); (b) **USB power/hub**, if it recurs — check the 5 V rail and
look for hub-level events around the timestamp:

```bash
sudo journalctl -k -S "2026-10-02 12:24:00" --until "2026-10-02 12:26:00" | grep -iE "hub|over-current|usb|error -71|reset"
```

The TMC `uv_cp=1(Undervoltage!)` flags from boot 2 (§6) belong in the same bucket: two independent signs of a
supply that sags under load.

---

## 7. Recommended order (A → B → C)

**A — make can0 survive a reset (~5 min, host only, fully reversible).** See §6d: mark the interface
`Unmanaged=yes` in `/etc/systemd/network/25-can.network` (the file systemd-networkd already uses and whose CAN apply
fails), restart networkd, and let the §6b watchdog own bring-up with the two commands that work by hand.
*(Corrected 2026-10-02 — the earlier text here said to delete a `RestartSec=` line from that file; there is no such
line, and that instruction is retracted in §6d.)*
The one number that selects it: after the change, a `FIRMWARE_RESTART` must leave can0 UP with no manual
command, and the journal must show `Configuring with /etc/systemd/network/25-can.network.` followed by
`Link UP` with **no** `Failed to set CAN interface configurations`.

**B — measure the physical layer (~20 min, power off, ohmmeter).**
The one number that selects it: **~60 Ω across CANH–CANL** = two terminators, correct. ~40 Ω = three
terminators (remove the third — most likely the probe's bridged pads). ~120 Ω = only one (add the second at the far
end). Then re-run a print and watch `canstat_EBBCan tx_retries` — it must stop climbing.

**C — reflash the M8P to the host's build (~15 min).**
The one number that selects it: the `Loaded MCU 'mcu'` version line must read `v0.13.0-762-g9871eeef`
(now `464`).

**D — if you would rather buy a part than measure: a dedicated USB-CAN adapter, not a new Manta.** See §12.

## 8. Paste-ready block

> **⚠️ INERT ON THIS HOST (§6c):** `ifupdown` is not installed, so this file is read by nothing. Kept only
> for reference / for hosts that do have ifupdown. Use the §6b watchdog or §6c Step 3 instead.

`/etc/network/interfaces.d/can0` on the CM4 (create if absent; keep the bitrate line — Linux ignores it, the
speed is compiled into each MCU, but the vendor tooling reads it):

```ini
allow-hotplug can0
iface can0 can static
    bitrate 1000000
    up ip link set $IFACE txqueuelen 128
```

Then:

```bash
sudo ifdown can0 2>/dev/null; sudo ifup can0
ip -details -statistics link show can0          # want: UP, bitrate 1000000, no BUS-OFF, flat error counters
~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0   # roll call: 3 UUIDs expected
```

Retry telemetry, before/after (run it while a print is going, not only idle):

```bash
grep -o "canstat_EBBCan: bus_state=[a-z]* rx_error=[0-9]* tx_error=[0-9]* tx_retries=[0-9]*" \
  ~/printer_data/logs/klippy.log | tail -20
```

Physical check (power **off**, cable still connected, measured at both ends):

```bash
# at the Manta CAN header, then at the toolhead board — both should read ~60 ohm
# 120 ohm alone = missing terminator, 40 ohm = one terminator too many
```

Reflash the M8P (after A), from the CM4:

```bash
cd ~/klipper && make clean && make menuconfig     # Manta M8P / STM32H723, USB-to-CAN bridge on, same options as now
make -j4                                          # then flash per BTT's CM4-on-Manta CAN procedure
~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0
# after restart, the log must read: Loaded MCU 'mcu' 137 commands (v0.13.0-762-g9871eeef / ...)
```

## 10. Ohmmeter walkthrough (option B, step by step)

Goal: settle whether the CAN segment is terminated correctly and whether the cable/connectors are sound, and
reduce it to **numbers** that can be compared before/after any change.

### Prep (2 minutes)

1. Power the printer **off at the mains and unplug it**, then wait a minute for the PSU to bleed down. Measuring
   resistance in a live circuit gives garbage and can damage the meter; the CAN transceivers on powered boards
   also skew the reading.
2. Meter on resistance (200 Ω range or auto). **Touch the two probes together first** and note the reading
   (typically 0.2-0.5 Ω) — that is your lead resistance and it must be subtracted from every number below.
3. **Photograph both CAN connectors before touching them** (Manta end and toolhead end), including which wire
   sits in which pin. The only risky action here is unplugging — it is fully reversible, and the photos are the
   rollback.

### Step 1 — the headline number: total bus resistance

Cable connected, printer dead, probe **CANH ↔ CANL at the Manta's CAN header**.

| Reading | Meaning |
|---|---|
| **~60 Ω** | exactly two 120 Ω terminators on the bus — correct |
| ~40 Ω | **three** terminators (one board too many) |
| ~120 Ω | only one terminator — under-terminated, reflections under load |
| open / very high | none fitted, or CANH/CANL are not continuous through the cable |

Key point: on a healthy bus this number reads the same **wherever** you probe — it is the parallel combination of
every terminator on the segment. So 60 Ω tells you the *count* is right, not *where* they are. Only a
disconnection tells you that (Step 2).

**What THIS machine should read, from the vendors' own docs (checked 2026-10-02):**

| Node | Terminator | Source |
|---|---|---|
| Manta M8P (bridge, one end) | 120 Ω jumper, **should be ON** | BTT: "Do not forget the 120R jumper just above the canbus connector" |
| SB2009 toolhead (other end) | 120 Ω jumper, **should be ON** | BTT SB2xxx family: "120 ohm Termination Resistor" header |
| Cartographer v4 (spur off the toolhead) | **OFF by default** | Cartographer docs: "Cartographer V4 USB/CAN — Disabled"; V3-ADXL and V4 "we were not able to enable the pre-terminated 120ohm resistor … terminating on the probe is not essential, and we have hundreds of users who terminate on their toolhead with no detrimental issues" |

So the target here is **2 × 120 Ω → ~60 Ω**, and 40 Ω would mean a **third** terminator exists — most likely the
Cartographer's two/three solder pads bridged by a previous owner (V4 *can* be terminated, just not from the factory),
or a stray 120R jumper. Read the vendor warning too: *"Do NOT measure your resistance while the probe is powered on"* —
and on the V3-lis2dw variant the on-probe resistor is only *active* while powered, so a powered reading understates
the count. Power off, as in Prep.

**What this measurement cannot see:** a single broken conductor. With everything connected, the current path from
CANH at one end to CANL at the other closes through the *other* wire, so H-break, L-break and both-intact all read
~60 Ω. Localizing a break is Step 3's job, not Step 1's.

### Step 2 — locate the terminators: split the bus at the Manta

Unplug the CAN cable at the Manta, then measure the two halves separately, H↔L each time:

- **Manta header itself** → ~120 Ω means the Manta's terminator is fitted; open means it is not.
- **The cable plug that goes to the toolhead chain** → ~120 Ω means one terminator out there, ~60 Ω means two.

Arithmetic check: Manta 120 Ω + chain 120 Ω in parallel = 60 Ω = Step 1. If Step 2 disagrees with Step 1, the
cable or a connector is intermittent — go to Step 3.

This is also where the fixed-target rule matters: you want the two terminators at the **two physical ends** of the
main run, not both at one end and none at the other.

### Step 3 — cable and connector integrity (still powered off)

Under-termination and a broken wire are different failures and only this step tells them apart.

- **Localize a break without disconnecting anything (do this first — it is one measurement per conductor).**
  With the bus assembled, CANH at the Manta and CANH at the toolhead are the *same node*, so H↔H should read
  **~0 Ω**. If one conductor is broken, that same measurement instead reads **~2 × 120 = ~240 Ω**, because the
  meter's path is forced the long way round: Manta H → Manta terminator → L wire → toolhead terminator →
  toolhead H. Measure H↔H and L↔L and compare:
  - both ~0 Ω → both conductors continuous (this is the only pass);
  - exactly one ~240 Ω → **that conductor is open** (bad crimp, broken strand, cold solder joint);
  - both ~240 Ω, or ~480 Ω → both broken, or the readers are floating; re-check the probe contact.
  The 240 Ω figure assumes 2 terminators; if Step 1 gave 40 Ω use 2 × 40 = 80 Ω as the "long way round" value.
- **Then check continuity conductor-by-conductor on the cable itself** (unplug one end): H pin to H pin end-to-end
  < 1 Ω, same for L. Compare the two wires — a 5 Ω difference is a bad crimp, not a cable.
- **Shorts:** CANH ↔ CANL should read open (MΩ). CANH → GND, CANL → GND, and both → the shield: all open.
- **Wiggle test (the one that matters):** keep the probes on H↔L and flex the cable — at both connectors, and
  through the drag-chain bend. The reading must not move. Intermittent crimps and broken strands pass a static
  ohmmeter every time and fail exactly like this fault does.
- **Shield/ground:** note whether the shield is bonded at one end or both. Bonded at both ends creates a ground
  loop that shows up as bus errors at 1 Mbit, especially once a stepper or the bed starts switching.
- **Wire routing:** H/L should be a twisted pair, not two of four flat conductors, and the run should not be
  bundled with stepper, hotend or bed wiring.

### Step 4 — while the meter is out (the crash is a power question too)

At the PSU terminal block, measure rails with the printer **on** but idle, then again with a print running (bed
and hotend at temperature): 24 V, 48 V and 5 V. Anything sagging under load belongs in the same investigation as
the TMC `uv_cp=1(Undervoltage!)` flags and the `-EPROTO` USB death. Clip the probes rather than holding them on
fine-pitch pins.

### Step 5 — power up: console side (this is the software half)

```bash
ip -details -statistics link show can0          # UP, bitrate 1000000, no BUS-OFF; note bus-error / error-pass counters
# retry delta, idle for 10 minutes:
grep -o "canstat_EBBCan: bus_state=[a-z-]* rx_error=[0-9]* tx_error=[0-9]* tx_retries=[0-9]*" \
  ~/printer_data/logs/klippy.log | tail -3
# then the same snapshot after 10 minutes of printing
```

Healthy: `tx_retries` flat (0-2 per run) and the `ip -statistics` error counters flat. Unhealthy: the 13/s climb
seen on 2026-10-01/02. Compare the **delta**, never the cumulative value.

### Step 6 — if the numbers are all correct and retries still climb

Then it is not termination; isolate by node. The Cartographer is the third CAN node — temporarily remove its CAN
lead and repeat the Step 5 delta. If the disturbance stops, the fault travels with that node (or its stub); if it
continues, it is the segment or the toolhead node. Only one change at a time.

### What to record and send back

Total Ω (Step 1) · Manta-end Ω and chain Ω (Step 2) · H↔H and L↔L readings + shorts + wiggle result (Step 3) ·
rail voltages idle/loaded (Step 4) · `ip -statistics` error counters and the two `tx_retries` deltas (Step 5).
With those seven numbers the verdict is arithmetic, not opinion.

Two things to photograph before unplugging anything, because they are the rollback and they are also evidence:
which wire sits in which pin at each CAN connector (H/L are marked on the PCB silkscreen — trust that, not the wire
colour), and the 120R jumper position on both the Manta and the toolhead board. A jumper that is *present but not
seated* is a classic intermittent, and only a photo taken before the teardown lets you tell whether it moved.

---

## 11. Evidence log (every claim above is one of these)

| Claim | Where |
|---|---|
| 8 boots, MCU load sets | `grep -n "Start printer at\|Loaded MCU" klippy.log` |
| ENETDOWN ×18 / connect abort | L1021-1065 (boot 1), L4901, L29376, L31675 |
| Boot 4 byte freeze + retransmit ramp | L27582-27589 (`Stats 10975.2`…`10978.2`) |
| Timeout + Lost communication | L27590-27591, L27820 |
| All MCUs shut down, can0 gone | L27826, L28031, L28238-28254 |
| Print position at death | L28244 `Exiting SD card print (position 3650248)` |
| EBBCan retry trajectory | `canstat_EBBCan tx_retries` at L6012 → L25541 → 143,421 at L27589 |
| Homing trsync failure (boot 2) | L3764-3790 |
| TMC undervoltage | L3078-3084 |
| Cartographer dual-generation models | L947-1016 (SAVE_CONFIG), L2232-2233 (init) |
| UUIDs / firmware versions | L554-558, L791-792, `Loaded MCU` lines per boot |

---

## 12. "Would it be simpler to just replace the Manta?" (asked 2026-10-02)

**Short answer: no — it is more expensive, more invasive, and it does not reach either of the two faults that are
actually proven.** The Manta's STM32H723 is implicated in exactly one of the three faults (the 12:25 `-EPROTO` USB
death), and that is the one fault with a free test in front of it.

### What each fault says about the Manta specifically

| Fault | Evidence | Points at the Manta? |
|---|---|---|
| can0 dead after every `FIRMWARE_RESTART` (4 of 8 boots) | `systemd-networkd: can0: Failed to set CAN interface configurations: … Operation not supported` | **No** — a driver/networkd property of *any* `gs_usb` bridge. A brand-new Manta reproduces §6d identically. |
| 143,421 retransmissions, all on the toolhead node | `canstat_EBBCan tx_retries` climbs to 143k while `mcu` and `scanner` sit at **0** | **No** — `mcu` *is* the Manta, and its own counters are clean. The suspect is the toolhead end. |
| 12:25:02 USB death, whole `1-1.x` hub segment re-enumerates | `gs_usb 1-1.4:1.0 can0: failed to xmit URB 0/2/3/4/5/6/7: -EPROTO` then `USB disconnect` ×3 | **Possibly** — this is the one real piece of evidence against the board. |

### The steelman, then the cheap discriminators

The honest case for a swap: the STM32 stopped servicing URBs, which is what a dying MCU/USB peripheral looks like,
and a board swap is one action instead of a measurement campaign. Fair. But two free tests sit in front of it, and
either can convict or exonerate the board without buying anything:

1. **Reflash (option C).** `[mcu]` is 298 commits behind the host (`v0.13.0-464-g48f0b3ca` vs `762-g9871eeef`).
   A USB/CAN-stack bug in that build costs nothing to rule out, and the flash has to happen anyway on the
   "replacement board" path — so doing it first costs no extra work.
2. **The `-EPROTO` was on a shared hub segment** (`1-1.1`, `1-1.2`, `1-1.4` all dropped inside 5 s). Rails sagging
   under load plus TMC `uv_cp=1(Undervoltage!)` on four drivers is at least as good an explanation as a dead MCU,
   and Step 4 of §10 measures it.

If a reflashed, well-powered board still kills USB mid-transfer → **then you have a board case**, and it is the only
finding that justifies touching the hardware.

### If you'd rather spend money than time: the part to buy is a USB-CAN adapter, not a mainboard

Esoterical's CANBus guide (the de-facto reference this community follows) puts it plainly: *"The simplest
plug-and-play option is to use a dedicated USB to Can device such as the BigTreeTech U2C, Mellow Fly UTOC, Fysetc
UCAN."* Bridging through a printer mainboard is described as the cheaper **second** option.

| | New Manta M8P V2.0 | U2C/UTOC + Manta as plain USB MCU |
|---|---|---|
| Cost | ~$83 (3DJake) + drivers/spares | ~$17 (U2C V2.1) |
| Work | Full rewire (8 drivers, heaters, thermistors, fans), CM4 re-seat, new canbus UUID → `printer.cfg` edit, reflash | Flash Manta as ordinary USB MCU, move one USB cable, add CAN cable to adapter, edit `[mcu]` |
| Fault 1 (can0 lifecycle) | **Unchanged** — still a `gs_usb` bridge | **Fixed structurally:** can0 belongs to the adapter, so resetting the Manta no longer disables the interface |
| Fault 2 (toolhead retries) | **Unchanged** | Unchanged (this is the ohmmeter's job) |
| Fault 3 (`-EPROTO`) | New board, same single-point topology | Manta stops forwarding every CAN frame over USB — load removed; if it recurs, the board/USB power is convicted for $17 instead of $83 |
| New risk | Miswired connector during a full rewire, invalidated baseline | Needs a spare USB port on the host (check — the journal shows a shared `1-1.x` hub) |

Note the machine is an **M8P V2.0** (`freq=519,993,162` ≈ 520 MHz = STM32H723, per the two revisions' MCU table), so
a like-for-like replacement is the V2.0 part.

### Verdict

Don't replace the Manta. Do, in this order: **§6d fix** (5 min, kills fault 1) → **ohmmeter** (§10, kills or confirms
fault 2) → **reflash** (free, tests the only hypothesis the Manta is actually a suspect for) → and **if you want to
buy something rather than measure, buy the $17 adapter** (§12, kills fault 1 structurally and shrinks fault 3). A new
Manta is the last item on that list, not the first, and only if a reflashed board still drops USB mid-print.

---

## 13. New evidence (2026-10-02): a chronically flaky USB webcam on the same host

**Reported by the user:** a USB webcam on one of the host's ports frequently drops its stream and runs at very low
frame rates. **This is material, and it moves the leading hypothesis for the 12:25 `-EPROTO` event off the Manta and
onto the shared USB path.**

### The topology, from BTT's own documentation

> "MANTA M8P has a USB 2.0 Hub. To save power, the USB port of the CM4 is disabled by default." — BTT M8P V2.0 wiki, *System Settings (CM4) → USB 2.0 Hub Port*

A CM4 exposes **one USB 2.0 controller** and this carrier board adds a hub, which is what `1-1` in the journal is.
Every device in that tree — the gs_usb bridge at `1-1.4`, the webcam, and the third `1-1.x` device — therefore shares
**one 480 Mbit/s bus and one 5 V feed**, and a streaming webcam is *isochronous*: it reserves bandwidth rather than
competing for leftovers. Adding ports does not add bandwidth; the ceiling is the single CM4 controller.

### The tree, as measured (`lsusb -t`, 2026-10-02)

```
Bus 01.Port 1: Dev 1, Class=root_hub, Driver=xhci-hcd/1p, 480M
    |__ Port 1: Dev 2, If 0, Class=Hub, Driver=hub/4p, 480M
        |__ Port 1: Dev 7, usbhid,      12M      <- HID (keyboard / wireless dongle)
        |__ Port 2: Dev 8, uvcvideo*2 + snd-usb-audio*2, 480M   <- THE WEBCAM
        |__ Port 4: Dev 11, gs_usb,     12M      <- Klipper's CAN bridge (the mainboard)
```

Three things fall out of it, and they are the point of this section:

1. **The bridge runs at 12M and BTT's own build recipe says it must.** `Communication interface: USB to CAN bus
   bridge (USB on PA11/PA12)` — that is the STM32H723's OTG_FS peripheral. Full speed is therefore *correct* here,
   not a misconfiguration, and it **cannot be raised on this board** (there is no ULPI PHY for OTG_HS). So the host's
   entire link to the Manta has 1/40th of the camera's nominal bandwidth.
2. **That 12M device is behind the hub (`1-1.4`), not on a port of its own.** The printer's own USB hub is
   load-bearing for Klipper's link: anything plugged into the Manta's USB ports is plugged into the printer's data
   path.
3. **The camera is the busiest device on that hub and it is a sibling of the bridge.** A 480M isochronous UVC stream
   reserves bandwidth in the same frame schedule that the hub's split transactions to the full-speed bridge must fit
   into. The keyboard on Port 1 is a *second* full-speed device sharing the same transaction translator.

### Updated leading hypothesis for the 12:25 `-EPROTO`

The chain `-EPROTO` on the bridge's URBs → hub reset → **all three** `1-1.x` devices disconnecting inside 5 s is a
documented Linux USB failure mode, not an MCU failure — kernel bugzilla #196747, on a different controller and driver,
describes it exactly: *"When this device is exposed to traffic to other usb devices connected to the same hub, it
disconnects … the usb hub resets so that all sibling and child devices are disconnected, too."* The full-speed device
is simply the one that logs first, because it streams URBs continuously.

So: **the strongest hypothesis is now that the camera's traffic (and/or a 5 V sag shared by the hub) took the hub
down, and the STM32 was a victim rather than the cause.** That is testable for free, tonight, and it is a third
independent reason not to buy a mainboard (§12).

### Why the webcam changes the reading of the crash

| Observation | Reading before | Reading with a flaky webcam on the same hub |
|---|---|---|
| `-EPROTO` on `gs_usb` xmit, then `USB disconnect` on `1-1.1`, `1-1.2`, `1-1.4` inside 5 s (= keyboard, webcam, bridge — i.e. **every** device on the hub) | "The STM32 bridge died and took the hub segment with it" | "The **hub** went down." Three devices leaving together is a hub-level event (power/over-current/TT-reset), not three coincidences — and gs_usb is the device *most* likely to log the first error, because it streams bulk URBs continuously. Ordering in the log does not by itself decide the direction of causation. |
| Chronic webcam drops + low FPS | (not known) | Independent evidence that the shared path is marginal **whether or not Klipper is running** — a fault that predates the crash. |
| TMC `uv_cp=1(Undervoltage!)` on four drivers | "48 V rail sags" | Same family: a printer whose rails sag under load will brown out a hub and a 200–500 mA camera with it. |

**What it does not explain, stated plainly:** the toolhead's `tx_retries` (§4 — and see the correction there: the
0-vs-143k contrast is a driver artifact anyway), and the can0 lifecycle bug (§6d), which is host-side networkd and has
nothing to do with USB devices.

### Consequence for the §12 recommendation

The U2C/UTOC option still fixes the thing it was chosen for — can0 belongs to the adapter, so resetting the Manta no
longer kills the interface. But if the root cause here is USB **power/bandwidth**, adding another USB device does not
relieve congestion, it joins it. The fix for that half is to take the camera off the shared bus (a CSI camera uses
dedicated MIPI lanes and zero USB bandwidth) or to power it explicitly.

> ⚠️ Check before buying a CSI camera: BTT's own issue tracker carries open reports of CSI camera/display problems on
> the M8P (`bigtreetech/Manta-M8P#95`), so treat CSI as "verify on this board" rather than a guaranteed clean path.

### The three tests, cheapest first

0. **Was the camera actually streaming during the killed ASA print at 12:25?** An idle-but-plugged UVC camera sits at
   a zero-bandwidth alt setting and reserves nothing; a camera being *viewed* by Mainsail/Fluidd or recorded holds an
   isochronous reservation for as long as the stream is open. If nothing had the stream open, the contention half of
   this hypothesis weakens and the power half (hub 5 V, `over-current`) becomes the candidate.
1. **Separate power from bandwidth — heat only, no motion.** Bring the bed and hotend to print temperature and stream
   the camera, with the printer *not* moving. Heaters add current but essentially no extra USB traffic.
   - FPS collapses when the heaters come on → **power** (5 V sag), same bucket as `uv_cp`; measure the rail (§10 Step 4).
   - FPS is fine at temperature but degrades while printing → **bandwidth/contention** on the shared controller.
2. **Characterise the path** (run on the CM4):
   ```bash
   lsusb -t                                   # tree + negotiated speed per device: 480M vs 12M
   lsusb -v 2>/dev/null | grep -iE "^(Bus|Device|  idVendor|  idProduct)|MaxPower"
   journalctl -k -b | grep -icE "error -71|over-current|cannot enable|reset high-speed"
   journalctl -k -b | grep -iE "hub|over-current|error -71" | tail -40
   for d in /sys/bus/usb/devices/*/; do echo "$(basename $d) $(cat $d/power/control 2>/dev/null) $(cat $d/bMaxPower 2>/dev/null)"; done
   ```
   Want: the camera at **480M** (a 12M negotiation = cable/port problem, and explains the low FPS on its own), no
   `over-current`, no repeated `error -71`, and `power/control` = `on` rather than `auto` (kernel autosuspend will
   suspend a camera mid-stream).
3. **One change at a time:** unplug the webcam for a full print. Does the retry delta change, and does the
   `-EPROTO`-class event recur? That is the same discipline §10 Step 6 prescribes for the Cartographer's lead.
