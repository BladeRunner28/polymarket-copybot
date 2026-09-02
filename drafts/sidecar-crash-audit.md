# Sidecar Crash Audit — Rust Execution Engine (:3014)

**Status:** COMPLETE — 2026-08-29 21:40 CT
**Trigger:** Tuning review #9 rec 2 ("Sidecar crash root-cause") + user request ("audit the sidecar crash issue").
**Investigation plan used:** `drafts/c200-execution-leak-investigation.md` Steps 1–2 (execution-path audit).

---

## What the data says

### The offline window (Aug 17–28): 284 skipped C-200 executions
- Monitor log: **284 × `Rust Execution Engine offline or failed: TypeError: fetch failed`** (Node-side fetch to :3014 refused).
- Per-day: Aug 20 (54), 19 (43), 21 (43), 18 (30), 23 (24), 25 (25), 26 (17), 27 (8), 28 (5). Declining to zero by Aug 28 10:04.
- Offline skips appear at **all hours of day with the machine awake** — these were real deaths, not sleep alone.

### The sidecar cannot crash on its own code
- `rust-sidecar/src/main.rs`: `main()` = bind :3014 → `axum::serve(...).await?` — an **infinite server loop**. The only returns are the bind (port conflict) and serve teardown.
- `start_whale_subscriber()` (the Polygon WS loop): every fallible step is `if let Ok(...)` — **no unwrap/panic paths** (only `.unwrap_or("unknown")`).
- **Zero macOS crash reports** in `~/Library/Logs/DiagnosticReports` (no polyhydra-whale entries) → **never panicked**.
- `rust-sidecar.err.log` **never created** → no panic/error stderr output, ever.

### Therefore: the deaths were external kills or environment, not code
Consistent with: (a) the machine-sleep era (Aug 17–28 cadence collapse — launchd cannot restart a job while the Mac is asleep; on wake the job is left in a bad state or restarted), (b) admin kills from Hermes sessions (prior session ran `kill 15564 && launchctl bootstrap …` on Aug 28), (c) session/agent reloads.

### The restart machinery
- launchd plist has `KeepAlive: true` → auto-restart on exit (default throttle). The sidecar came back on its own (e.g., Aug 28 10:04–10:18).
- **The watchdog cron NEVER fired during the whole loop** (`last_run_at: null` as of Aug 28 10:29) — so silent deaths went unalarmed for 12 days. (It fires normally now; restart-frequency alert added today.)
- Since Aug 28 10:04: PID 15564 (31h up) → PID 60034 (17:09→21:15 today, 4h) → PID 80372 (current, verified executing intents at 21:22). **The crash-loop is over; deaths are now occasional, not looping.**

### Evidence-loss bug (the reason root-cause was hard)
launchd **truncates `StandardOutPath` on every job start** — each restart erased the previous instance's stdout, destroying the only diagnostic trail. The current log (288 bytes) contains only the latest instance. Fix implemented (below).

---

## Step-1 diagnostics (execution-leak plan) — run while auditing

| Check | Finding |
|---|---|
| H1: PnL by venue (C-200) | **Kalshi +$1.39/trade (49 trades, +$68.18) — best venue, NOT a leak.** Polymarket −$0.15/trade (851, −$130.27). Cross-venue routing is fine; decision-tree fix "drop Kalshi" would have been wrong. |
| H4: realized vs unrealized | **STANDARD's +EV is real resolved PnL: +$7,455.67 on 1,097 resolved.** Not a measurement artifact. C-200: closed 854 (−$250.48) vs resolved 46 (+$188.39) → C-200's realized leak is in the **early-exit path** (dead-market expiry / stale exits), now being recycled by v33/v35 sweeps. |
| Step-2: log forensics | Done above. |

---

## Actions taken

1. **Watchdog restart-frequency alert** (earlier today): ≥4 restarts/hour → 🔴 CRASH-LOOP Discord escalation; restart log at `/tmp/copybot-sidecar-restarts.log`. Converts silent deaths into alerts.
2. **Caffeinate 24/7** (earlier today): eliminates the sleep-era environment that contributed to the loop.
3. **Observability fix** (this audit): `scripts/rust-sidecar-launcher.sh` wrapper — appends every instance's stdout+stderr to a dated archive (`logs/rust-sidecar-YYYYMMDD.log`) with `=== start / EXITED code=N ===` markers, keeps the live log for the current instance, propagates the exit code. Plist updated to run the wrapper. **Reload required (user shell):**
   ```bash
   launchctl bootout gui/$(id -u)/com.xsnyde2.copybot-rust-sidecar && \
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.xsnyde2.copybot-rust-sidecar.plist
   ```
   After this, the NEXT death leaves an exit code + last stdout lines in the archive — definitive root cause on first occurrence.

## Still open / recommendations

- If the sidecar dies again post-wrapper: read `logs/rust-sidecar-*.log` tail for the EXITED line → root cause will be immediately visible.
- Consider adding `ThrottleInterval` 30 to the plist to stop launchd's exponential backoff leaving the sidecar down for hours after a startup-failure burst.
- C-200's realized leak is the early-exit path, not execution: watch closed-vs-resolved split in the daily report now that v33/v35 recycling books exits at market price.
