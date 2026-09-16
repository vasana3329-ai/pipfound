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
| `fundamental.py` | ~260 | **Fundamental engine.** Reuses `macro_context.get_calendar()`; classifies each High/Medium event (rate/inflation/growth/employment/PMI/…), computes directional effect on major pairs + gold/silver for both beat & miss scenarios, ET+Tehran times, Farsi countdown. Serves the 📰 فاندمنتال page. |
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

## 4. Current backtest baseline — ⚠️ REVISED after structure rebuild (C21–C24)

> **مهم‌ترین یافته‌ی این دور.** ارقامِ قبلی (BTC 83.6٪، XAU 82.4٪، USDJPY 95.8٪) با **پرشدنِ خوش‌بینانه‌ی بازار روی `poi_mid`** تولید شده بودند — نه قیمتی که واقعاً در آن لحظه در دسترس بود. فیکس C8 پرشدن را روی **کلوزِ کندلِ سیگنال** (قیمتِ واقعی) برد و R را نسبت به همان قیمت سنجید. نتیجه: وین‌ریتِ ۸۳٪ فروپاشید. این **رگرسیون نیست؛ افشای حقیقت است**.

**دورِ C21–C24 (بازسازیِ منطقِ تشخیصِ ساختار — درخواستِ صریحِ کاربر):** کاربر مشکلِ بنیادین را درست تشخیص داد: موتور توالیِ صحیحِ خواندنِ چارت را رعایت نمی‌کرد و تعاریفِ ساختاری (روند/BOS/CHoCH/MSS/سوینگ/لیکوئیدیتی/الگوها) دقیق نبودند. مسیرِ اصلاح روی BTCUSDT/day walk=3000:

| دور | Trades | Winrate | total R | نکته |
|---|---:|---:|---:|---|
| C20 (پیش از بازسازی) | 32 | 22٪ | −21.6 | رأی‌گیریِ برچسب؛ market کانونِ ۸۱٪ ضرر |
| C21 (structure state-machine) | 29 | 41٪ | −11.1 | ضرر نصف؛ توالیِ درست |
| C22 (سخت‌کردنِ گیتِ market) | 18 | 67٪ | −0.13 | market حذف شد؛ ≈ سربه‌سر |
| C23 (اعتبارسنجیِ FVG/OB) | 16 | 56٪ | −1.6 | ۳ برنده‌ی کوچکِ نمونه حذف |
| C24 (الگوهای لیکوئیدیتی) | 16 | 56٪ | −1.6 | بی‌تغییرِ روی BTC (الگوی نزدیک‌تری نساخت) |

**مسیر از totalR ۲۱.۶− به تقریباً سربه‌سر رفت و وین‌ریت از ۲۲٪ به ۵۶–۶۷٪.** لبه هنوز مثبت نیست ولی دیگر متورم یا خراب نیست. **قدمِ بعدی:** ران چندنمادی (XAU/FX) برای سنجشِ اثرِ C23/C24 روی نمادهای دارای الگوی واضح‌تر — چون BTC/1d نمونه‌ی کوچکی است.

### 4.1 baselineِ تاریخیِ منسوخ (پیش از C8 — فیلِ آرمانی، دیگر معتبر نیست)
| Symbol | Style | walk | Trades | Winrate | Exp (R) | market | limit_ote |
|---|---|---|---:|---:|---:|---|---|
| BTCUSDT | day | 3000 | 67 | 83.6٪ | 2.43 | 56/66 | 0/1 |
| XAUUSD | day | 3000 | 34 | 82.4٪ | 2.80 | 28/33 | 0/1 |
| USDJPY | scalp | 5000 | 24 | 95.8٪ | 2.67 | 23/24 | — |

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
| `79e90a4` | افزودنِ PIPFOUND_BLUEPRINT.md (این فایل). |
| `4bf038b` | **فیکس C1+C7:** انکورِ premium_discount و OTE روی پایِ ایمپالسِ واقعی (`_impulse_leg`: مبدأ→مقصدِ دو سوینگِ آخر) به‌جای رِنجِ ساختگیِ پهن‌شده تا قیمت. زون‌های OTEِ engine با `confluence.ote_zone` یکسان شد و دیدِ اشتباهِ خرید=۰.۶۲..۰.۷۹ حذف شد. |
| `32a7cc8` | **فیکس C2+C9:** `killzone_at(ts)` جدید — کیل‌زون از تایم‌استمپِ کندل (بازتولیدپذیریِ بک‌تست)؛ آفستِ EST/EDT از `_is_us_dst()` به‌جای ثابتِ −۴. `analyze_bars` کیل‌زون را از آخرین کندلِ برش حساب می‌کند. |
| `4f310db` | **فیکس C3+C4+C5:** BOS/CHoCH فقط با کندلِ دیسپلیسمنت معتبر (`_break_displaced`؛ شکستِ بی‌جان = سوئیپ). گیتِ توالیِ sweep→MSS (`sequence_ok` + ردیفِ چک‌لیستِ «توالیِ سوئیپ→ام‌اس‌اس»). حذفِ اوبی‌های میتیگیت‌شده در `order_blocks`. |
| `08a51b2` | **فیکس C8:** پرشدنِ واقع‌گرایانه‌ی market روی کلوزِ کندلِ سیگنال (نه `poi_mid`)؛ R نسبت به `fill_price`. **افشا کرد که baselineِ ۸۳٪ متورم بود** (اکسپکتنسی به ~۰ افتاد). |
| `6de2c94` | **فیکس C6+C10+C11:** لیکوئیدیتیِ سشنی (PDH/PDL + رِنجِ آسیایی، `_session_levels`) به اهدافِ بای‌ساید/سل‌ساید. استاپِ ساختاری با بافرِ نسبتِ POI + نگهبانِ استاپِ نامعتبر. ورودِ گلدن‌پاکتِ ۰.۷۰۵/پروگزیمال به‌جای میدِ اوبی. |
| `f818f63` | **فیکس C14+C15+S1 + بازنگریِ ورود:** FVG فقط با کندلِ میانیِ دیسپلیسمنت (بدنه‌به‌بدنه)؛ `by_grade` در خروجیِ بک‌تست؛ استکِ اسکالپِ بک‌تست = اپِ زنده (`1h,30m,15m,5m`). ورودِ market فقط داخلِ OTE، وگرنه limit در گلدن‌پاکت (حذفِ چیسِ بازار در محلِ بد). |
| `7b34f6a` | **فیکس C17:** ورودِ limit_ote با تأییدِ LTF (کندلِ دیسپلیسمنتِ رجکشن طیِ confirm_window)؛ استاپ پشتِ فتیله‌ی سوئیپِ واقعیِ فازِ پولبک + بافر؛ `_simulate` حالا `sl_used` برمی‌گرداند. |
| `d13828f` | **فیکس C18:** مدیریتِ پله‌ایِ پوزیشن (اسکیل‌اوت TP1 در ۱R + برگشتِ رانر به BE)؛ متریک‌های صادقانه (scratch/avg_loss_R جدا، اکسپکتنسی=میانگینِ R واقعی)؛ برد/باخت بر پایه‌ی R. |
| `79c8d66` | **فیکس C19:** هدف روی نزدیک‌ترین لیکوئیدیتیِ مقابل + تزریقِ سوینگ‌های ساختاری. برملا کرد که استاپِ C17 بیش‌ازحد تنگ است (planRR تا ۱۰۹). |
| `114b5be` | **فیکس C20:** بافرِ استاپ با ATRِ محلی مقیاس می‌خورد (`max(0.03%, 0.5×ATR)`). مکانیکِ درست ولی فقط شاخه‌ی limit_ote را لمس کرد؛ رانِ تشخیصی نشان داد ۲۵ ورودِ market کانونِ ۸۱٪ ضررند. |
| `afeed43` | **فیکس C21 (بزرگ‌ترین):** بازنویسیِ کاملِ `structure()` با ماشینِ حالتِ چپ‌به‌راست به‌جای رأی‌گیریِ برچسب. شکست=بسته‌شدنِ کندل (نه فتیله، `_closed_beyond`)؛ BOS=شکستِ هم‌جهت، CHoCH=نخستین شکستِ خلافِ روند، MSS=CHoCHِ دیسپلیسمنت‌دار؛ روند فقط با CHoCH برمی‌گردد. **وین‌ریت ۲۲→۴۱٪، totalR ۲۱.۶−→۱۱.۱−.** |
| `8e65f53` | **فیکس C22:** سخت‌کردنِ گیتِ ورودِ market — علاوه بر بودن در OTE، تریگرِ واقعی (توالیِ سوئیپ→MSS درست + دیسپلیسمنتِ هم‌جهت یا سوئیپِ تازه) هم لازم. **market حذف شد (۱۸→۰)، وین‌ریت ۴۱→۶۷٪، totalR ≈ سربه‌سر (۰.۱۳−).** |
| `f79d218` | **فیکس C23:** اعتبارسنجیِ سخت‌گیرانه‌ی FVG/OB — (۱) FVG با پرشدنِ نصفه (عبور از میدِ گپ) هم باطل؛ (۲) OB معتبر باید ایمبالانس/FVG به‌جا بگذارد (کندلِ i+2 گپ بسازد). |
| `ff11d89` | **فیکس C24:** تشخیصِ الگوهای لیکوئیدیتیِ کلاسیک (double top/bottom، V-top/bottom) و تزریق به اهدافِ بای‌ساید/سل‌ساید + کلید `liquidity_patterns`. پوششِ تعریفیِ الگوها کامل شد. |
| `2087b68` | **قانونِ RR کاربر (گیتِ سخت):** بلوکِ `if tp:` بازنویسی شد — اگر TP نامعتبر یا `rr < 2` → `plan=None` (نه فقط پرچمِ چک‌لیست) تا ستاپ‌های زیرِ ۱:۲ در اپ اصلاً نمایش داده نشوند. هدف روی سقفِ ۳R قفل (رانر تا لیکوئیدیتیِ بعدی کشش می‌گیرد). گیتِ grade: پلنِ نامعتبر → سقفِ C. UIِ app.py: برچسبِ «هدف (۲ تا ۳R)» + ردیفِ کششِ رانر. |
| `(این دور)` | **مدلِ عرضه/تقاضا از ویدیوی Smart Risk + مهرِ تاییدِ ورودِ اختیاری (خواسته‌ی کاربر، نمره>۷۰٪):** `confluence._entry_stamp()` — مهر فقط وقتی می‌خورد که همه‌ی این‌ها برقرار باشند: نمره>۷۰٪ + بدونِ تضادِ HTF↔MTF + زونِ درست + **قانونِ ۳۰٪ ویدیو** (قیمت ≥۳۰٪ داخلِ زونِ POI نفوذ کرده) + تاییدِ چرخشِ LTF (توالیِ سوئیپ→MSS نقض‌نشده و چاک/دیسپلیسمنت/سوئیپِ هم‌جهت). `plan` حالا `poi_top/poi_bottom` هم برمی‌گرداند. بک‌تست: فلگِ `--require-stamp`. UI: بلوکِ مهرِ سبز/خاکستری با دلایل. |
| `(این دور)` | **استراتژیِ سیلوربولتِ نیویورک (اسکلپِ ۱m، ۰۹:۰۰–۱۱:۰۰ ET):** اندازه‌گیریِ فعالیتِ ساعتی (`scripts/kz_measure.py`) ثابت کرد طلا ~۲.۰–۲.۳× و BTC ~۱.۵–۲.۸× در این پنجره تحرک دارد. `smc_engine.silver_bullet_window()` + سبکِ `sb_ny` (`15m,5m,1m`) + گیتِ زمانی در `app.analyze()` (خارج از پنجره → plan=None). UI: دکمه‌ی خاصِ `#sbBtn` (گرادیانِ بنفش/طلایی) + کارتِ `.sbwin` با تایمرِ زنده‌ی شمارشِ معکوس + ۵ مرحله‌ی ستاپ. مستندِ مجزا: `references/silver-bullet-ny.md`. **بینشِ دلیورِ طلا (`gold_delivery`) بک‌تست شد و چون در گریدهای بالا لبه نساخت، برگردانده شد — نگه داشته نشد.**|
| `(این دور)` | **دکمه‌ی ↻ بروزرسانیِ داده‌ها + تبدیل به اپِ نصب‌پذیر (PWA) (خواسته‌ی کاربر):** دکمه‌ی `#refreshBtn` (خاکستریِ ملایم، آیکونِ ↻ که حینِ کار می‌چرخد و بعدِ موفقیت سبز می‌شود) نمادِ آخرین تحلیل را از `window._last` می‌خواند و همان `run()` را دوباره صدا می‌زند — fetchِ زنده بدونِ `location.reload`، پس چارت/کارت بی‌رفرش تازه می‌شوند. اگر هنوز چیزی تحلیل نشده، پیامِ راهنما می‌دهد. **PWA:** `manifest.webmanifest` (نام/آیکون/standalone/rtl/تمِ #0b0f17) + `sw.js` (service worker با استراتژیِ network-first برای HTML/JS، cache-first برای آیکون‌ها، و **هرگز کش‌نکردنِ `/api/*`** تا داده‌ی زنده همیشه تازه بماند؛ POSTها دست‌نخورده). آیکون‌ها با `make_icons.py` ساخته شدند (شمعِ اسمارت‌مانی، ۱۹۲/۵۱۲ + نسخه‌ی maskable + ۱۸۰ برای iOS). endpointهای جدید در `Handler.do_GET`: `/manifest.webmanifest`, `/sw.js`, `/icon-*.png`. `<head>` صفحه‌ی اصلی: لینکِ manifest + apple-touch-icon + theme-color؛ ثبتِ SW فقط روی http/https. **نتیجه:** لوکال مثلِ قبل کار می‌کند، و از منوی مرورگر (Install / افزودن به هوم‌اسکرین) به‌شکلِ اپِ مستقلِ نصب‌پذیر هم درمی‌آید.

| `(این دور)` | **دکمه‌ی 📊 آرشیو اقتصادی (آرشیوِ خبرهای اعلام‌شدهٔ ۶ ساعتِ گذشته):** دکمه‌ی `#archiveBtn` در نوار ابزار است. با کلیک، `/api/fundamental-archive?hours=6` (اندپوینتِ جدید در `do_GET`) را فراخوانی می‌کند خبرهای پرتأثیرِ ۶ ساعتِ گذشته (ارز، ساعتِ اعلام، فاصلهی زمانی، جهتِ اثر روی جفت‌ارزها و طلا/نقره) را در یک پنجرهی داخلی نشان می‌دهد. داده‌ها ۶ ساعت نگه‌داری می‌شوند و بعداً خودکار پاک می‌شوند (TTL). اگر اخبار قدیمی دیدید، روی دکمه «بروزرسانی» بزنید تا data تازه شود. `fundamental_report.md` نمونهٔ خروجیِ آرشیو است. **ترمیم ۲۰۲۶-۰۹-۱۵:** این دکمه در نسخهٔ قبلی خراب اضافه شده بود (بک‌اسلشِ اضافه داخل قالبِ متنیِ JS باعثِ `SyntaxError` می‌شد و کلِ اسکریپتِ صفحه را از کار می‌انداخت، پس همه‌ی دکمه‌ها بی‌اثر شده بودند). اکنون: HTML و JS سالم بازنویسی شد، اندپوینت از `do_DELETE` (کدِ مرده بعد از `return`) به `do_GET` منتقل شد و `FUND.archive(hours)` واقعاً پیاده شد — خروجی در هر درخواست از تقویمِ زنده ساخته می‌شود (بدونِ TTL/ذخیره‌سازی). دکمه‌ی ↻ بروزرسانی و بخشِ PWA که از `app.py` گم شده بودند هم برگردانده شدند. |

| `(این دور)` | **نگهبانِ سلامتِ اپ (`selfcheck.py`) — دیگر یک ویرایشِ خراب اپ را بی‌صدا از کار نمی‌اندازد (خواسته‌ی کاربر):** سه لایه‌ی محافظت. ۱) **چکِ خودِ کد:** سینتکسِ پایتونِ همه‌ی ماژول‌ها با `ast.parse` (بدونِ اجرا)، و متنِ `HTML`/`FUND_PAGE` از `app.py` بیرون کشیده می‌شود و هر بلوکِ `<script>` با `node --check` اعتبارسنجی می‌شود — همان باگی که کلِ صفحه را کشته بود (بک‌اسلش قبل از بک‌تیکِ بستهٔ قالب) با یک ثانیه گرفته می‌شود. ۲) **قراردادِ «هیچ کلیدی گم نشود»:** هر کنترلی که در نسخه‌ی سالم وجود داشت و JS به آن وصل بود، به‌علاوه‌ی هر مسیری (`route`)، باید سرِ جایش باشد — یعنی حذفِ یک دکمه از خودِ فایل هم گرفته می‌شود. ۳) **اسنپ‌شات و بازگردانی:** نسخه‌ی سالم در `~/pipfound/good` (و یک نسل قبل‌تر در `good_prev`) نگه داشته می‌شود؛ با `--guard` اگر کد خراب باشد خودکار همان نسخه برمی‌گردد و لاگ در `~/pipfound/selfcheck.log` می‌نشیند. **راه‌اندازِ `pipfound.app`** (و قالبِ `make_app.py`) قبل از بالا آوردنِ سرور `--guard` را اجرا می‌کند و اگر ترمیم ممکن نبود، دیالوگِ هشدار نشان می‌دهد. **خودِ `app.py`** هم هنگامِ استارتاپ چک می‌کند، اسنپ‌شاتِ سالم را تازه می‌کند و در صورتِ خرابی از سرو کردنِ صفحه‌ی مرده خودداری می‌کند (`exit 2`). اندپوینتِ `/api/selfcheck` گزارشِ سلامت (JSON) می‌دهد. علاوه بر این، یک **نگهبانِ بوت** در `<head>` نشسته: اگر اسکریپتِ اصلی پارس یا اجرا نشود (حتی خطای زمانِ اجرا که چکِ سینتکس نمی‌گیرد)، به‌جای صفحه‌ی ساکت و بی‌دکمه، نواری قرمز بالای صفحه هشدار می‌دهد. **کاربرد:** `python3 selfcheck.py` (گزارش) · `--guard` (ترمیمِ خودکار) · `--live` (چکِ سرورِ در حالِ اجرا) · `--snapshot` (بازتعریفِ مبنای سالم) · `--json`. **راستی‌آزمایی:** در کپیِ آزمایشی، هم باگِ بک‌اسلشِ اصلی و هم حذفِ دکمه‌ی `refreshBtn` درست تشخیص داده شدند و بازگردانی خودکار جواب داد. |

| `(این دور)` | **CI روی گیت‌هاب + مبنای نسخه‌بندی‌شده (خواسته‌ی کاربر):** روی هر پوش و هر PR، همان نگهبانِ سلامت اجرا می‌شود (`.github/workflows/selfcheck.yml`): سینتکسِ پایتون و JS، قراردادِ «هیچ کلیدی گم نشود» و بعد یک اسموک‌تستِ سرورِ واقعی — سرور با پایتونِ سیستم بالا می‌آید، صفحه‌ی سرو‌شده باید هر ۹ کلیدِ اصلی را داشته باشد، `manifest.webmanifest` و `sw.js` باید جواب بدهند و `/api/selfcheck` باید OK بدهد. در صورتِ خطا، ورک‌فلو با `::error::` روی همان کامیت/PR گزارش می‌دهد و لاگِ سرور را هم می‌آورد. چون در CI اسنپ‌شاتِ ماشینِ توسعه دهنده وجود ندارد، مبنای مقایسه حالا از فایلِ کامیت‌شده‌ی `selfcheck-baseline.json` خوانده می‌شود — ترتیب: اسنپ‌شاتِ `~/pipfound/good` → فایلِ ریپو → فهرستِ حداقلیِ ثابت؛ فایلِ مبنا با `python3 selfcheck.py --snapshot` (همراه با اسنپ‌شات) نوشته می‌شود. نتیجه: شاخه‌ی `main` از سه جهت محافظت می‌شود — هوکِ پیش‌کامیت روی همین ماشین، ورک‌فلوی CI روی گیت‌هاب، و بازگردانیِ خودکارِ سرور با `--guard`. |

| `(این دور)` | **حفاظتِ شاخه‌ی main: هوکِ pre-push + یافته‌ی محدودیتِ پلن:** روی ریپوی خصوصیِ پلنِ رایگان، هم branch protection و هم rulesets با ۴۰۳ («Upgrade to GitHub Pro or make this repository public to enable this feature») رد می‌شوند — پس آن زمان حفاظتِ سروریِ شاخه در دسترس نبود (در ردیفِ بعدی با عمومی‌کردنِ ریپو حل شد). به‌جای آن، هوکِ `hooks/pre-push` اضافه شد: پیش از هر پوش، نگهبانِ سلامت اجرا می‌شود و پوشِ کدِ خراب به `main` بسته می‌شود؛ پوش به شاخه‌های دیگر فقط هشدار می‌گیرد و اگر سرور بالا باشد چکِ اندپوینت‌ها (`--live`) هم انجام می‌شود. عبورِ اضطراری: `PIPFOUND_SKIP_SELFCHECK=1 git push ...`. تبدیل این به تضمینِ سروری یا با GitHub Pro ممکن است یا با عمومی‌کردنِ ریپو؛ آن‌وقت چکِ «نگهبانِ سلامت + اسموک‌تستِ سرور» به‌عنوان required status check روی `main` تنظیم می‌شود. |

| `(این دور)` | **قفلِ شاخه‌ی `main` روی گیت‌هاب (تصمیمِ کاربر: عمومی‌کردنِ ریپو):** اول اسکنِ تاریخچه انجام شد (هیچ کلید/توکن/ژورنال/کش کامیت نشده بود؛ تنها یک مسیرِ شخصی در `kz_measure.py` که بعداً اصلاح شد) و بعد ریپو از خصوصی به عمومی تغییر کرد تا features پلنی آزاد شود. سپس یک ruleset فعال ساخته شد (`id 23494038`، نامِ `pipfound main guard`) روی `~DEFAULT_BRANCH` با چهار قانون: `deletion`، `non_fast_forward`، `pull_request` (تعدادِ تاییدِ لازم = ۰، چون تک‌کاربره) و `required_status_checks` با contextِ دقیقِ «نگهبانِ سلامت + اسموک‌تستِ سرور» و `strict_required_status_checks_policy`. `bypass_actors` خالی است و API می‌گوید `current_user_can_bypass = never` — یعنی حتی مالک هم نمی‌تواند رد شود و برای عبورِ اضطراری باید خودِ ruleset را موقتاً عوض کرد. **راستی‌آزماییِ زنده:** پوشِ مستقیم به `main` با `GH013: Changes must be made through a pull request` رد شد؛ PRِ آزمایشی با کدِ سالم `CLEAN/MERGEABLE` بود؛ همان PR بعد از یک کامیتِ خراب `FAILURE + BLOCKED` شد و `gh pr merge` با «the base branch policy prohibits the merge» رد شد و `main` کاملاً دست‌نخورده ماند. از این پس مسیرِ تغییرِ main: شاخه → پوش → PR → سبز شدنِ نگهبان → ادغام؛ هوکِ محلیِ `pre-push` هم به‌عنوان لایه‌ی اول سرِ جایش است. |

| `(این دور)` | **نامِ پایدارِ چکِ اجباری (خواسته‌ی کاربر):** contextِ چکِ اجباریِ ruleset به نامِ *فارسیِ* job گره خورده بود و هر ویرایشِ متنی در آن نام (حتی یک نیم‌فاصله) همه‌ی PRها را الکی «منتظرِ چک» می‌گذاشت. حالا jobِ ورک‌فلو با کلیدِ `selfcheck` و نامِ **`pipfound-selfcheck`** (لاتینِ پایدار) اجرا می‌شود و ruleset هم همان را اجباری می‌داند. **مهاجرتِ بی‌قفل:** برای اینکه اگر کار وسطِ راه قطع شد `main` با «چکِ ناموجود» قفل نشود، ترتیب این بود: ۱) PR #3 نامِ job را عوض کرد و **هم‌زمان** یک jobِ پلِ موقت (`legacy_name_bridge`) با همان نامِ *قدیمی* اضافه شد تا rulesetِ فعلی همچنان ارضا شود؛ ۲) پس از سبز شدنِ هر دو context، contextِ ruleset با یک `PUT` به `pipfound-selfcheck` عوض شد (بقیه‌ی سه قاعده و `bypass_actors` دست‌نخورده، `strict` فعال)؛ ۳) PR #4 پلِ موقت را برداشت و با تنها همان چکِ جدید `CLEAN` شد. در هر نقطه‌ی قطع‌شدن، `main` یا محافظت‌شده می‌ماند یا نهایتاً PRها بسته‌اند — هیچ‌وقت با نامِ ناموجود قفل نمی‌شود. **نکته‌ی عملی:** در YAML، مقدارِ درون‌خطیِ `run:` نباید «دونقطه + فاصله» داشته باشد؛ کامیتِ اولِ همین کار با خطای «Invalid workflow file» در ۰ ثانیه رد شد (و `gh run list` هم آن را `failure` با زمانِ ۰ ثانیه نشان می‌دهد). از بلوکِ `run: |` استفاده کن. |

| `(این دور)` | **حذفِ اجرای تکراریِ CI (خواسته‌ی کاربر):** چون قواعدِ شاخه ورودِ به `main` را فقط از راهِ PR می‌گذارد، پوشِ شاخه‌های فیچر عملاً همیشه همراهِ PR است — و همان یک پوش هم رویدادِ `push` و هم `pull_request` را می‌افروخت، پس چکِ `pipfound-selfcheck` دوبار اجرا و دوبار در پنلِ PR گزارش می‌شد (۲ برابر دقیقهٔ CI). حالا triggerها اینهاست: `push` فقط روی `main` (یعنی بعد از ادغام)، `pull_request` برای باز شدن/پوشِ تازه/بازگشایی، و `workflow_dispatch` برای اجرای دستی. گروهِ `concurrency` دست‌نخورده ماند تا پوش‌های پشت‌سرهمِ یک PR اجراهای قدیمی را کنسل کنند. **راستی‌آزماییِ زنده:** پوشِ شاخهٔ فیچر ۰ اجرا داد، ساختِ PR دقیقاً ۱ اجرا (`pull_request/success`) و PR با یک ردیفِ چک `CLEAN` شد؛ پوشِ دوم روی همان PR هم فقط ۱ اجرا داد و ادغام مسدود نشد. |

| `(این دور)` | **تستِ بصری در مرورگرِ headless (خواسته‌ی کاربر):** `ui_visual_check.cjs` صفحه را در کرومِ headless بالا می‌آورد و می‌سنجد: (۱) اسکریپت اجرا شده (چیپ‌های ۸تایی که فقط با JS ساخته می‌شوند)، (۲) هیچ خطای زمانِ اجرا یا کنسول نباشد (همان `SyntaxError` که یک‌بار همه‌ی کلیدها را بی‌اثر کرد)، (۳) نوارِ قرمزِ `#bootWarn` دیده نشود، (۴) کلیدهای همیشه‌حاضر (۱۸ شناسه) سرِ جایشان باشند و سیم‌کشی‌شان زنده باشد — `onclick` تابع باشد و `#sbBtn`/`#styles` رویدادِ کلیک داشته باشند (`DOMDebugger.getEventListeners`) — به‌علاوه‌ی سه رفتارِ واقعی: کلیکِ چیپ نماد را پر کند و دکمه‌ی «تحلیل کن» `pulse` بگیرد، انتخابِ سبک حالتِ `active` را جابه‌جا کند، و «↻ بروزرسانی» تا اولین تحلیل غیرفعال بماند. شناسه‌های `#jbtn`/`#alarmBtn`/`#pipModal` عمداً بعد از تحلیل/باز شدنِ پنجره ساخته می‌شوند و `#bootWarn` فقط در خرابی؛ پس در فهرستِ «باید باشند» نیستند و وجودشان در متنِ سرو‌شده را `selfcheck.py` (قراردادِ ۵۲ کلید) و اسموک‌تست می‌گیرند. **چرا چکِ متنی کافی نبود:** خرابیِ اصلی دکمه‌ها را در HTML نگه می‌داشت ولی همه را بی‌اثر می‌کرد؛ grep این را نمی‌بیند. تست داخلِ همان `job`ِ چکِ اجباری اجرا می‌شود (نه jobِ جدا) تا contextِ ruleset دست‌نخورده بماند، و اسکرین‌شات با `actions/upload-artifact@v7` آپلود می‌شود. **راستی‌آزمایی:** روی صفحه‌ی سالم پاس شد و روی یک کپیِ عمداً خراب (همان باگ) با هفت پیامِ دقیق رد شد. ضمناً همین تست یک ایرادِ واقعی را لو داد: درخواستِ بی‌جوابِ `/favicon.ico` خطای کنسول می‌ساخت — اپ حالا `<link rel="icon" href="/icon-192.png">` دارد و آیکون `200` می‌دهد. |

| `(این دور)` | **مسیرِ ژورنال: قابلِ تنظیم و بی‌وابسته به پوشه‌های محافظت‌شده (خواسته‌ی کاربر):** مسیرِ دفتر حالا `PIPFOUND_JOURNAL_CSV` → `PIPFOUND_JOURNAL_DIR` → پیش‌فرضِ `~/pipfound/journal.csv` است (بیرونِ `~/Desktop` و `~/Documents` که جاب‌های launchd اجازه‌ی نوشتن در آن‌ها را ندارند — TCC مک). یک مهاجرتِ بی‌خطر در استارتاپ اجرا می‌شود: ردیف‌های دفترِ قدیمی (`~/Desktop/trading-journal/journal.csv`) که در فایلِ فعلی نیستند، با شناسه‌ی تازه و یادداشتِ شماره‌ی قبلی افزوده می‌شوند؛ فایلِ قدیمی هرگز پاک/عوض نمی‌شود و اجرای دوباره «۰» می‌دهد. در `journal.py` هم `default_file()` اضافه شد (env → فایلِ اپ اگر هست → مسیرِ قدیمی) تا CLI و اپ یک دفتر را ببینند. **راستی‌آزمایی:** ردیفِ ۱۰ آگوستِ دفترِ قدیمی به‌عنوان `#3` به دفترِ اپ منتقل شد (اجرای دوم بی‌اثر)، جابِ launchd در `~/pipfound` می‌نویسد (`exit 0`)، و ثبتِ واقعیِ معامله زیرِ launchd با `PIPFOUND_JOURNAL_CSV` روی فایلِ آزمایشی `{"added": "1"}` داد بدونِ دست‌زدن به دفترِ واقعی. |

### 5.1 Root-cause findings established so far
- **Fake bullish bias bug (RESOLVED, `7d20c44`):** original BOS/CHoCH looped backward and flagged any old swing price had passed → always fabricated a bullish bias, killed all bearish signals on FX. Fixed to nearest-swing break.
- **Low-winrate diagnosis (PARTIAL):** walk=600 gave meaningless 3–6 trade samples. walk≥3000 gives valid samples. The *real* weakness was OTE-limit entries in deep pullbacks (market 76–83% vs limit_ote 12–40% pre-fix). Fix #1 gated limit_ote to HTF confluence — but effectively removed it (see §6 C1: this was "sweeping it under the rug", not solving it).
- **Server traceback (RESOLVED, `263c524`):** was only `BrokenPipeError` from timed-out test curls, not a logic bug.

---

## 6. Known open problems / critical review (the real backlog)

This is the most valuable section for the next agent. A professional ICT/SMC critique (Huddleston / Priceaction Vinny lens) of the engine. Ordered by impact on output reliability. **Items are candidates to fix properly — resist metric-gaming.**

### Tier 1 — makes output genuinely unreliable
- **C1 — ✅ RESOLVED (`4bf038b`).** OTE/premium-discount حالا روی پایِ ایمپالسِ واقعی (`_impulse_leg`) لنگر می‌شود؛ دیگر رِنج تا قیمت پهن نمی‌شود.
- **C2 — ✅ RESOLVED (`32a7cc8`).** `killzone_at(ts)` کیل‌زون را از تایم‌استمپِ کندل می‌گیرد؛ بک‌تست بازتولیدپذیر شد.
- **C3 — ✅ RESOLVED (`4f310db`).** BOS/CHoCH نیازمندِ کندلِ دیسپلیسمنت‌اند (`_break_displaced`).
- **C4 — ✅ RESOLVED (`4f310db`).** گیتِ توالیِ sweep→MSS (`sequence_ok`) در چک‌لیست.

### Tier 2 — eats quality
- **C5 — ✅ RESOLVED (`4f310db`).** اوبی‌های میتیگیت‌شده کنار گذاشته می‌شوند.
- **C6 — ✅ RESOLVED (`6de2c94`).** PDH/PDL + رِنجِ آسیایی (`_session_levels`) به اهدافِ لیکوئیدیتی افزوده شد.
- **C7 — ✅ RESOLVED (`4bf038b`).** دو ماژول روی زون‌های OTE یکسان شدند.
- **C8 — ✅ RESOLVED (`08a51b2`).** پرشدنِ market روی کلوزِ کندلِ سیگنال؛ **افشا کرد baseline متورم بود** (§4).
- **C9 — ✅ RESOLVED (`32a7cc8`).** آفستِ EST/EDT بر پایه‌ی DST.
- **C10 — ✅ RESOLVED (`6de2c94`).** استاپِ ساختاری با بافرِ نسبتِ POI + نگهبانِ استاپِ نامعتبر (به‌جای درصدِ ثابت).
- **C11 — ✅ RESOLVED (`6de2c94`/`f818f63`).** ورودِ گلدن‌پاکتِ ۰.۷۰۵/پروگزیمال؛ market فقط داخلِ OTE.

### Tier 3 — missing for "professional" (features, not bugs)
- **C12 — ⏳ OPEN. No SMT divergence.** Addable with correlated pairs (BTC↔ETH, EURUSD↔GBPUSD, XAU↔XAG) and especially **DXY** for FX bias.
- **C13 — ⏳ OPEN. No Power of 3 / Judas swing / Silver Bullet** in scoring.
- **C14 — ✅ RESOLVED (`f818f63`).** FVG اکنون کندلِ میانیِ دیسپلیسمنت (بدنه‌به‌بدنه ≥۱.۳×) می‌خواهد.
- **C15 — ✅ RESOLVED (`f818f63`).** `by_grade` وین‌ریت را per-grade تفکیک می‌کند.
- **C16 — ⏳ OPEN. Fixed fractal swing n=2 on all TFs** — noisy on 1m/5m.

### Structural inconsistencies
- **S1 — ✅ RESOLVED (`f818f63`).** استکِ اسکالپِ بک‌تست = اپِ زنده (`1h,30m,15m,5m`).

### دورِ بازسازیِ ساختار — C17–C24 (درخواستِ بنیادینِ کاربر: توالی + تعاریفِ درست)
- **C17 — ✅ RESOLVED (`7b34f6a`).** ورودِ limit_ote با تأییدِ LTF (کندلِ دیسپلیسمنتِ رجکشن)؛ استاپ پشتِ فتیله‌ی سوئیپِ واقعی + بافر.
- **C18 — ✅ RESOLVED (`d13828f`).** مدیریتِ پله‌ای (اسکیل‌اوت ۱R + رانر به BE)؛ متریک‌های صادقانه.
- **C19 — ✅ RESOLVED (`79c8d66`).** هدف روی نزدیک‌ترین لیکوئیدیتیِ مقابل + سوینگ‌های ساختاری. برملا کرد که استاپِ C17 بیش‌ازحد تنگ است.
- **C20 — ✅ RESOLVED (`114b5be`).** بافرِ استاپ با ATR مقیاس می‌خورد. رانِ تشخیصی نشان داد ریشه بالاتر است (گیتِ market).
- **C21 — ✅ RESOLVED (`afeed43`) — بزرگ‌ترین.** بازنویسیِ `structure()` با ماشینِ حالتِ چپ‌به‌راست. شکست=بسته‌شدنِ کندل (نه فتیله)؛ BOS/CHoCH/MSS با تعاریفِ درست؛ روند فقط با CHoCH برمی‌گردد. وین‌ریت ۲۲→۴۱٪.
- **C22 — ✅ RESOLVED (`8e65f53`).** گیتِ market: علاوه بر OTE، تریگرِ واقعی (توالیِ سوئیپ→MSS + دیسپلیسمنت/سوئیپِ تازه) لازم. وین‌ریت ۴۱→۶۷٪، totalR ≈ سربه‌سر.
- **C23 — ✅ RESOLVED (`f79d218`).** FVG با پرشدنِ نصفه هم باطل؛ OB معتبر باید FVG/ایمبالانس به‌جا بگذارد.
- **C24 — ✅ RESOLVED (`ff11d89`).** الگوهای لیکوئیدیتیِ کلاسیک (double top/bottom، V-shape) تشخیص و به اهداف تزریق شدند.

### 🟡 قدمِ بازِ فعلی — ران چندنمادی + لبه‌ی مثبت
پس از C21–C24 لبه از totalR ۲۱.۶− به تقریباً سربه‌سر رسید (BTC/1d walk=3000). **هنوز مثبت نیست.** قدمِ بعدیِ صادقانه: (۱) ران بزرگ‌نمونه روی XAU/FX برای سنجشِ C23/C24 (نمادهای دارای الگوی واضح‌تر)؛ (۲) بررسیِ اینکه چرا limit_ote هنوز تقریباً سربه‌سر است نه مثبت — احتمالاً باید نسبتِ اسکیل‌اوت (C18) یا فاصله‌ی هدفِ اول بازنگری شود. مقصدِ باز: C12 (SMT/DXY)، C13 (Power of 3)، C16 (سوینگِ تطبیقی به‌جای n=2 ثابت).

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
