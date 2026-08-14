# pipfound — Project Blueprint & Living Log

> **Purpose of this file.** This is the single cornerstone document for the *pipfound* project. It is written for **any agent, model, or human** picking up the work cold, with zero prior context. Read this top to bottom and you will fully grasp: what the app is, how it is built, every design decision made so far, the full change history, the known-open problems, and the roadmap. **Keep this file updated** — whenever you change architecture, fix a class of bug, or make a decision, append to the relevant section and to the Changelog. Treat it as both blueprint (forward) and log (backward).
>
> **Last updated:** 2026-08 (see Changelog for the precise commit trail).
> **Repo:** `github.com/vasana3329-ai/pipfound` (PRIVATE). Auth via `gh` CLI as `vasana3329-ai`.
> **Local path:** `~/.hermes/skills/trading/smc-ict-analysis/scripts/` (this is the app folder).

---

## 0. Non-negotiable constraints (read before touching anything)

These are hard project rules. Violating them breaks the product for the user.

1. **Output language: FULL Farsi, transliterated.** All user-facing strings (UI, analysis output, backtest labels) are in **Persian script**. ICT/SMC jargon is **transliterated by sound into Persian script** (not translated by meaning), because mixing Latin + Farsi breaks RTL rendering. Prices stay as digits.
   - اردر بلاک = Order Block · فیرولیوگپ = FVG · لیکوئیدیتی سوئیپ = liquidity sweep · بایاس = bias · بی او اس = BOS · چاک = CHoCH · پریمیوم/دیسکانت = premium/discount · کیل‌زون = killzone · اکسپکتنسی = expectancy.
2. **Pure Python stdlib only.** No third-party packages except `certifi` (SSL) which is optional/graceful-fallback. No pip installs, no frameworks.
3. **Free data, no API keys.** Binance public REST (crypto) + Yahoo Finance chart API (FX/metals/oil) + gold-api.com (spot metals) + faireconomy ForexFactory mirror (news calendar). All keyless.
4. **Localhost only, no auth.** The web app binds `127.0.0.1:8787`. It is a personal local tool; no authentication layer by design (acceptable because it is loopback-only and never network-exposed).
5. **Zero logic duplication between live analysis and backtest.** The backtest MUST call the exact same `confluence.score()` and `smc_engine.analyze_bars()` used live. No parallel/forked scoring logic — otherwise backtest winrate stops reflecting what the app actually recommends.
6. **No look-ahead in backtest.** Each walk step slices every timeframe strictly up to the "now" bar's timestamp.
7. **Git workflow:** auto-commit locally after each code change (Farsi commit messages, stage only relevant source files). **Push to remote ONLY with explicit user approval each time.** Never push to `main` without permission. Global git config untouched.
8. **Single-pass artifact delivery.** When the user asks for a file/PDF/artifact, build it in ONE pass — no multi-message "working on it" narration.

---

## 1. What pipfound is

**pipfound** is a professional, local-first **ICT + SMC trade-setup grader and backtester** with a web UI. The user is a serious ICT/SMC trader; the tool's job is to produce **reliable, rule-based setup grades and numeric trade plans** — removing guesswork from "is this a good setup?" — and to let the user **backtest the exact same logic** over historical data.

It covers:
- **All markets:** crypto (Binance), FX majors (Yahoo), metals XAU/XAG/XPT/XPD, oil WTI/Brent.
- **Three styles:** scalp / day / swing — each maps to a top-down timeframe stack.
- **Combined ICT + SMC methodology:** market structure (BOS/CHoCH), liquidity sweeps, order blocks, FVGs, premium/discount + OTE, killzones, macro news gate.
- **Live features:** analysis card with grade + numeric plan, OTE zone, live price alarms, live chart, screenshot upload, and a walk-forward backtest with user-selectable range / timeframe / direction.

The methodology reference is the sibling skill **`smc-ict-playbook`** (the knowledge base). This app is the executable engine behind the **`smc-ict-analysis`** skill.

---

## 2. Architecture

### 2.1 Module map (data flow bottom-up)

```
                    ┌─────────────────────────────────────────────┐
                    │  app.py  (HTTP server, UI, endpoints)        │
                    │  ThreadingHTTPServer @ 127.0.0.1:8787        │
                    │  serves HTML/JS + JSON APIs + alarm worker   │
                    └───────────────┬─────────────────────────────┘
                                    │ imports & calls in-process
        ┌───────────────────────────┼──────────────────────────────┐
        ▼                           ▼                              ▼
┌───────────────┐          ┌──────────────────┐          ┌──────────────────┐
│ confluence.py │  calls   │   backtest.py    │  calls   │ macro_context.py │
│ score()       │◄─────────│ walk-forward sim │          │ news gate,       │
│ ote_zone()    │          │ (reuses score()  │          │ sessions,        │
│ grade logic   │          │  + analyze_bars) │          │ correlations     │
└───────┬───────┘          └────────┬─────────┘          └──────────────────┘
        │ calls E.analyze()          │ calls E.analyze_bars() on slices
        ▼                            ▼
┌─────────────────────────────────────────────┐
│  smc_engine.py  (structure detection core)   │
│  fetch/resolve · swings · structure(BOS/CHoCH)│
│  fvgs · order_blocks · liquidity · sweeps    │
│  premium_discount · displacement · killzone  │
│  analyze_bars() = the shared analysis kernel │
└─────────────────────────────────────────────┘
        │ HTTP (keyless)
        ▼
Binance REST · Yahoo chart API · gold-api.com · faireconomy (ForexFactory)
```

### 2.2 Files (in this folder)

| File | Lines | Role |
|---|---|---|
| `smc_engine.py` | ~406 | **Structure core.** Data fetch + all SMC/ICT primitive detectors. `analyze_bars()` is the shared kernel used by both live and backtest. |
| `confluence.py` | ~517 | **Grader.** Top-down multi-TF scan → weighted checklist → grade (A+/A/B/C/no-trade) + numeric plan (entry/SL/TP/RR) + OTE zone. `score()` is the single source of truth for a setup verdict. |
| `backtest.py` | ~439 | **Walk-forward backtester.** Reuses `score()` + `analyze_bars()` with no logic duplication. User-selectable style/tfs/date-range/direction. Segments winrate by entry type & direction; flags small samples. |
| `app.py` | ~1396 | **Web app.** stdlib `ThreadingHTTPServer`; serves the HTML/JS UI and JSON APIs; background alarm worker; screenshot upload; journal bridge. |
| `macro_context.py` | ~215 | **Macro engine.** ForexFactory calendar (cached 3h), trading sessions in ET, news gate (red/amber/green), correlation clusters, session focus movers. |
| `make_app.py` | — | Generator/helper script (historical; app.py is the live artifact). |
| `.ff_cache.json` | — | 3-hour cache of the ForexFactory weekly calendar. |
| `PIPFOUND_BLUEPRINT.md` | — | **This file.** |

Sibling module reused (not in this folder): `../../trade-journal/scripts/journal.py` — CSV trade journal, bridged by `app.py` for the `/api/journal` endpoint.

### 2.3 Symbol resolution (`smc_engine.resolve`)

- Crypto ending `USDT/USDC/BUSD` (or `…BTC/…ETH` len>6) → **Binance** (paginated, up to ~60 requests back for deep history).
- Metals: `XAUUSD/GOLD→GC=F`, `XAGUSD/SILVER→SI=F`, `XPTUSD→PL=F`, `XPDUSD→PA=F` → **Yahoo** futures, then **basis-shifted** to live spot via gold-api.com so levels sit on the spot chart (structure untouched).
- Oil: `WTI/USOIL/CRUDE→CL=F`, `BRENT/UKOIL→BZ=F` → Yahoo.
- FX majors / any 6-letter alpha → **Yahoo** `SYMBOL=X`.
- Yahoo has no native 4h → **1h fetched and resampled to 4h** (`resample(bars, 4)`).

### 2.4 Timeframe stacks (style → tfs, HTF first, entry = last)

| Style | Live app (`app.STYLES`) | Backtest (`backtest.tf_map`) | Entry TF |
|---|---|---|---|
| scalp | `1h, 30m, 15m, 5m` | `1h, 15m, 5m, 1m` | 5m / 1m |
| day | `1d, 4h, 1h, 15m` | `1d, 4h, 1h, 15m` | 15m |
| swing | `1w, 1d, 4h, 1h` | `1w, 1d, 4h, 1h` | 1h |

> **Note the scalp mismatch:** live app uses `1h,30m,15m,5m`; backtest uses `1h,15m,5m,1m`. This is a known inconsistency (see §6, item S1) — backtest scalp numbers do not reflect the live scalp stack exactly.

### 2.5 The confluence checklist (`confluence.score`)

Weighted, rules-based. Points normalized to % of max, so adding factors never inflates grades.

| # | Check | Weight |
|---|---|---|
| 1 | HTF bias clarity | 1.0 |
| 2 | Multi-TF alignment (top-down) | 2.0 |
| 3 | Correct premium/discount zone | 1.5 |
| 3b | OTE (0.62–0.79 fib) | 1.0 |
| 4 | Fresh liquidity sweep in trade direction | 1.5 |
| 5 | Fresh CHoCH on LTF | 1.0 |
| 6 | Displacement (institutional move) | 1.0 |
| 7 | POI present (OB/FVG) | 0.5 |
| 8 | HTF POI confluence | 1.0 |
| 9 | Killzone / session timing | 0.5 |
| 10 | Macro news gate | 0.5 |
| 11 | RR ≥ 1:2 feasibility | 1.0 |

**Grade thresholds:** ratio ≥0.85 → A+ · ≥0.70 → A · ≥0.50 → B · ≥0.30 → C · else no-trade.
**Hard gates:** (a) HTF-vs-MTF conflict caps the grade; (b) *location gate* — buying in premium OR selling in discount **while also outside OTE** caps grade at C (worst amateur mistake: chasing price).

**Plan construction (check 11):** entry is market if price already inside OTE/discount; else `limit_ote` only when HTF confluence is present (else market on POI mid). SL behind structure with a **0.15% minimum stop**. TP = nearest opposing liquidity beyond entry (falls back to range edge).

### 2.6 Backtest mechanics (`backtest.backtest`)

1. Fetch deepest history per TF (Binance paginated; Yahoo range-capped).
2. Walk the entry-TF bars. At each step "now" = that bar's time; every TF sliced up to now (**no look-ahead**).
3. Build `d` dict of `analyze_bars()` per TF → inject into `score()` → get the same plan/grade the live app would show.
4. If a qualifying plan (grade in set, RR≥2): **market** fills at signal-bar close; **limit_ote** waits up to `fill_window` bars for price to touch, else cancels.
5. After fill, follow bars: SL-first if both hit same bar (conservative). Win = TP first.
6. No overlapping trades. Output: count, winrate, avg R, expectancy, per-entry-type & per-direction segmentation, small-sample flag (<20 trades = statistically unreliable).

---

## 3. Environment & how to run

- **Host:** macOS (Apple Silicon M1, 8GB RAM). Python via Hermes venv: `~/.hermes/hermes-agent/venv/bin/python3` (3.11).
- **Run the app:**
  ```bash
  cd ~/.hermes/skills/trading/smc-ict-analysis/scripts
  ~/.hermes/hermes-agent/venv/bin/python3 app.py            # → http://127.0.0.1:8787
  ~/.hermes/hermes-agent/venv/bin/python3 app.py --port 9000
  ```
- **The server cannot self-restart from inside a Hermes gateway process** (SIGTERM self-kill). Restart from a separate shell. Kill stale PID on the port first (`lsof -nP -iTCP:8787 -sTCP:LISTEN`).
- **Health check:** `curl -s http://127.0.0.1:8787/api/health` → `{"ok": true}`.
- **CLI use of the engines directly:**
  ```bash
  python3 smc_engine.py BTCUSDT --tf 4h --json
  python3 confluence.py XAUUSD --md
  python3 backtest.py USDJPY --style scalp --walk 5000 --side both --json
  python3 macro_context.py --symbol XAUUSD --json
  ```
- **State/output dirs:** alarms `~/pipfound/alarms.json`; screenshots `~/pipfound/screenshots/`; journal CSV `~/Desktop/trading-journal/journal.csv`.
- **Skill backup:** `~/Documents/trading-skills-backup/`.
- **Long backtests time out over HTTP** (heavy compute); prefer running the engine directly in a background process for walk≥3000. HTTP `_send` is hardened against `BrokenPipeError`/`ConnectionReset` from clients that disconnect mid-compute.

### 3.1 Web API endpoints (`app.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness `{"ok": true}` |
| GET | `/api/analyze?symbol=&style=` | full setup card (grade, plan, OTE, macro) |
| GET | `/api/backtest?…` | walk-forward backtest (walk default 2000) |
| GET | `/api/suggest-range?…` | valid from/to dates for a given walk depth |
| GET | `/api/alarms` | list alarms |
| POST/DELETE | `/api/alarm` | create / delete alarm |
| GET | `/api/screenshots` · GET/POST/DELETE `/api/screenshot` | screenshot gallery |
| POST | `/api/journal` | log a trade via sibling journal module |

---

## 4. Current backtest baseline (as of latest commit `263c524`)

Run: `grades=(A+,A,B)`, `side=both`, engine direct (not HTTP). **These already include Fix #1 (OTE limit gating).**

| Symbol | Style | walk | Trades | Winrate | Expectancy (R) | Σ R | market | limit_ote |
|---|---|---|---:|---:|---:|---:|---|---|
| BTCUSDT | day | 3000 | 67 | 83.6% | 2.43 | 162.64 | 56/66 | 0/1 |
| XAUUSD | day | 3000 | 34 | 82.4% | 2.80 | 95.36 | 28/33 | 0/1 |
| USDJPY | scalp | 5000 | 24 | 95.8% | 2.67 | 64.15 | 23/24 | — |
| USDJPY | swing | 5000 | 8 | 62.5% | 0.93 | 7.47 | 5/8 | — |
| EURUSD | day | 3000 | 1 | 100% | 2.07 | 2.07 | 1/1 | — |

**Reading these numbers critically:**
- Winrates look strong, BUT they are dominated by **market entries**. `limit_ote` has collapsed to essentially **0/1** — Fix #1 (previous session) raised winrate by *nearly removing OTE limit entries entirely*. This is a **metric-gaming symptom, not a real fix** (see §6, item C1). OTE is the heart of ICT entry; killing it is not acceptable long-term.
- USDJPY `day` and `EURUSD` `day` produce almost no trades — small-sample / low-signal for that style. USDJPY is better on scalp (95.8%) and swing.
- High winrates with a fixed RR≥2 and market-on-close fills also reflect the **optimistic market fill** assumption (see §6, item C4).

---

## 5. Full history / Changelog

Commits are on `main`, remote `origin`. Farsi commit messages (summarized here in English).

| Commit | Summary |
|---|---|
| `473a787` | Initial commit — pipfound ICT+SMC analysis app. |
| `7d20c44` | Fix #2 of the fake-bullish-bias bug in CHoCH detection (nearest-swing, not stale-swing). |
| `a1394b8` | Add range / timeframe / direction selection to the backtest UI. |
| `eb40de5` | Enforce step ordering in UI — cancel auto-run of analysis. Also Farsi/Arabic digit parsing in `_parse_when`; `/api/suggest-range` endpoint. |
| `646d6cf` | Fix backtest date-format error + auto range suggestion based on 600-candle depth. |
| `d06632e` | **Winrate improvement pack:** (1) gate OTE-limit entry to HTF confluence only [Fix #1]; (2) sample-adequacy banner (<20 yellow, 0 red); (3) winrate segmentation by entry-type/direction; (4) better-style suggestion for low-signal symbols (threshold 5); (5) raise backtest default depth to 2000. |
| `263c524` | Harden `_send` against BrokenPipe/ConnectionReset (client disconnecting mid-heavy-backtest no longer produces tracebacks). |

### 5.1 Root-cause findings established so far
- **Fake bullish bias bug (RESOLVED, `7d20c44`):** original BOS/CHoCH looped backward and flagged any old swing price had passed → always fabricated a bullish bias, killed all bearish signals on FX. Fixed to nearest-swing break.
- **Low-winrate diagnosis (PARTIAL):** walk=600 gave meaningless 3–6 trade samples. walk≥3000 gives valid samples. The *real* weakness was OTE-limit entries in deep pullbacks (market 76–83% vs limit_ote 12–40% pre-fix). Fix #1 gated limit_ote to HTF confluence — but effectively removed it (see §6 C1: this was "sweeping it under the rug", not solving it).
- **Server traceback (RESOLVED, `263c524`):** was only `BrokenPipeError` from timed-out test curls, not a logic bug.

---

## 6. Known open problems / critical review (the real backlog)

This is the most valuable section for the next agent. A professional ICT/SMC critique (Huddleston / Priceaction Vinny lens) of the engine. Ordered by impact on output reliability. **Items are candidates to fix properly — resist metric-gaming.**

### Tier 1 — makes output genuinely unreliable
- **C1 — OTE / premium-discount anchored on an arbitrary range, not the impulse leg.** `smc_engine.premium_discount` builds the range from the extremes of the last 8 swings and then *widens it to include current price* (lines ~294–295), shifting equilibrium and mislabeling premium as discount. `confluence.ote_zone` fibs on this synthetic range. **This is the root cause of OTE losses.** The previous "fix" (gate limit_ote to HTF) just disabled OTE. Real fix: anchor the fib to the actual impulse leg (origin swing → BOS swing) coming from `structure()`, place limit at 0.705, stop behind 1.0.
- **C2 — Killzone in backtest uses wall-clock "now".** `killzone_now()` always returns the current time; `analyze_bars` calls it, so every historical signal is scored with the killzone of the moment the backtest runs, not the bar's own time. Backtests are non-reproducible morning vs night. Fix: `analyze_bars` should take a `ts` and compute the killzone from the last bar's timestamp.
- **C3 — BOS/CHoCH require no displacement.** `structure()` only checks "did close cross the swing?" Weak breaks (often liquidity sweeps) generate fake BOS/CHoCH. MSS should require the breaking candle(s) to have a displacement body.
- **C4 — Sequence gate missing.** Checklist scores sweep / CHoCH / entry independently; nothing enforces the sacred order **sweep → MSS → entry** in time. A setup can score A with CHoCH occurring *before* the sweep.

### Tier 2 — eats quality
- **C5 — Mitigated / structure-irrelevant order blocks still offered.** `order_blocks()` doesn't check mitigation, whether the OB caused a BOS, or PD side. Trading a burnt OB → stop-out. Fix: drop mitigated OBs; prefer OBs that caused a BOS.
- **C6 — No core ICT liquidity: PDH/PDL, session highs/lows, Asian range.** `liquidity()` only sees fractal equal-highs/lows with a fixed 0.0007 tolerance for all markets. Half the methodology's liquidity concept is absent.
- **C7 — Two modules disagree on OTE location.** `smc_engine.premium_discount` computes long OTE as `bot+0.62..0.79×rng` (that's *premium* — wrong for a buy); `confluence.ote_zone` correctly uses `bot+0.21..0.38×rng` (discount). `score()` uses the correct one, so the engine's version is misleading dead code — delete or fix it.
- **C8 — Unrealistic market fill in backtest.** `_simulate` fills market at `plan["entry"]=poi_mid` regardless of where signal-bar price actually is; in the no-HTF-confluence fallback that can be far from the POI. Inflates results. Market entry should fill at signal-bar close (or next-bar open).
- **C9 — Killzone hardcodes EDT (−4h).** Winter (EST) should be −5h. Killzone windows are an hour off half the year.
- **C10 — Fixed-percent stop overrides structure.** `sl=struct_low×0.999` with `min_stop=0.15%`. When structural distance is small, min_stop pushes SL off the real invalidation level → fake RR and broken invalidation logic. Stop should sit behind swing/OB + spread buffer.
- **C11 — Entry at POI mid, not proximal edge / 0.705.** ICT entry is the proximal edge price touches first, or the 0.705 golden pocket — not the middle of the OB.

### Tier 3 — missing for "professional" (features, not bugs)
- **C12 — No SMT divergence.** Addable with correlated pairs (BTC↔ETH, EURUSD↔GBPUSD, XAU↔XAG) and especially **DXY** for FX bias.
- **C13 — No Power of 3 / Judas swing / Silver Bullet** in scoring.
- **C14 — FVG has no displacement filter.** Every 3-candle gap counts, even in slow chop; quality FVGs come from displacement.
- **C15 — Grade B accepted in backtest** dilutes quality; report A+/A separately for a clean read.
- **C16 — Fixed fractal swing n=2 on all TFs** — noisy on 1m/5m, leaks into whole structure.

### Structural inconsistencies
- **S1 — scalp TF stack differs** between live app (`1h,30m,15m,5m`) and backtest (`1h,15m,5m,1m`). Reconcile so backtest reflects the live scalp stack.

---

## 7. Roadmap (recommended fix order, by impact)

1. **C1 + C7** — Anchor OTE/premium-discount to the real impulse leg; unify the two modules. *Biggest impact; genuinely restores OTE entries instead of disabling them.* Re-backtest and prove limit_ote winrate recovers to a real (not zeroed) number.
2. **C2 + C9** — Killzone from bar timestamp + EST/EDT fix. Makes backtest reproducible. (Keep `analyze_bars` backward-compatible: default = now for live.)
3. **C3 + C4** — Require displacement on breaks + enforce sweep→MSS→entry sequence gate.
4. **C5 + C8** — Drop mitigated OBs + realistic market fill in backtest.
5. **C6 + C10** — Add PDH/PDL & Asian range + structural stop.
6. **C11, C12–C16, S1** — Proximal/0.705 entry; SMT/DXY; FVG displacement filter; reconcile scalp stack.

**Verification discipline for every fix:** after applying, re-run a large-sample backtest (walk≥3000, side=both) across BTCUSDT/XAUUSD/USDJPY/EURUSD and *prove the fix improved (not merely changed) winrate + expectancy*. A fix that raises winrate by removing the entries it was supposed to fix is a regression, not a fix. Auto-commit locally (Farsi msg); push only on explicit approval.

---

## 8. Persona / working method

The user asks the agent to wear two hats simultaneously:
- **A professional ICT/SMC trader-critic** (Huddleston / Priceaction Vinny lens) whose only goal is reliable output, who never sweeps a problem under the rug, and who after every proposed fix asks *"am I actually solving this, or am I just getting it off my plate — could I do better?"*
- **A programmer** who implements the fixes, verifies each against the trader-critic until it is genuinely flawless, then lists all changes for the user to review before any push.

---

## 9. Quick-start for a fresh agent

1. Read §0 (constraints), §2 (architecture), §6 (open problems).
2. `curl -s http://127.0.0.1:8787/api/health` — if down, start per §3 from a separate shell.
3. Reproduce the baseline (§4) with the engine directly (background process; HTTP times out on deep walks).
4. Pick the top open item in §7, implement, re-backtest to prove improvement, auto-commit locally, list changes, wait for "پوش کن" before pushing.
5. **Update this file** — Changelog (§5) + close/adjust items in §6 — as part of the same work.
