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
| `risk.py` | ~470 | **Risk model.** مشخصاتِ قرارداد (لات/کانترکت/سهم) + سایزِ پوزیشن + سقفِ ضررِ روزانه و ریسکِ باز از دفترِ معاملات + تجزیهٔ نماد به فاکتورهای هم‌بستگی. کاملاً آفلاین؛ `app.analyze` آن را صدا می‌زند (نه `confluence`، تا بک‌تست عوض نشود). |
| `risk_test.py` | ~330 | **Risk-model test.** ۱۹۴ بررسیِ آفلاین و قطعی: فرمولِ سایز، گِردکردنِ کف، گاردها، ماتریسِ سقفِ روزانه، سناریوهای هم‌بستگی، گیتِ `evaluate`، رفت‌وبرگشتِ تنظیمات. در CI لایهٔ ۴.۶. |
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
| GET | `/api/revision` | کدِ **بارشده** در این پروسه: SHA/شاخه/dirty + زمانِ استارت + pid + `uptime_s`، در برابر SHA و mtimeهای دیسک → `stale` و `changed_files`؛ به‌علاوهٔ وضعیتِ ری‌استارتِ خودکار (`enabled/interval_s/waiting/blocked/last`) |
| GET | `/api/analyze?symbol=&style=` | full setup card (grade, plan, OTE, macro) |
| GET | `/api/backtest?…` | walk-forward backtest (walk default 2000) |
| GET | `/api/suggest-range?…` | valid from/to dates for a given walk depth |
| GET | `/api/alarms` | list alarms |
| POST/DELETE | `/api/alarm` | create / delete alarm |
| GET | `/api/screenshots` · GET/POST/DELETE `/api/screenshot` | screenshot gallery |
| POST | `/api/journal` | log a trade via sibling journal module (با درصدِ ریسکِ پیکربندی‌شده) |
| GET | `/api/risk` | تنظیماتِ ریسک + وضعیتِ امروز (ضررِ محقق‌شده، باقی‌مانده تا سقف، ریسکِ باز، پوزیشن‌های باز) — محاسبه‌ی محلی، بدونِ شبکه |
| POST | `/api/risk` | ذخیرهٔ اتمیکِ سرمایه/درصد/سقف‌ها در `~/pipfound/risk.json` (`PIPFOUND_RISK_FILE`) |

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

| `(این دور)` | **تستِ بصری در مرورگرِ headless (خواسته‌ی کاربر):** `ui_visual_check.cjs` صفحه را در کرومِ headless بالا می‌آورد و می‌سنجد: (۱) اسکریپت اجرا شده (چیپ‌های ۸تایی که فقط با JS ساخته می‌شوند)، (۲) هیچ خطای زمانِ اجرا یا کنسول نباشد (همان `SyntaxError` که یک‌بار همه‌ی کلیدها را بی‌اثر کرد)، (۳) نوارِ قرمزِ `#bootWarn` دیده نشود، (۴) کلیدهای همیشه‌حاضر (۱۸ شناسه) سرِ جایشان باشند و سیم‌کشی‌شان زنده باشد — `onclick` تابع باشد و `#sbBtn`/`#styles` رویدادِ کلیک داشته باشند (`DOMDebugger.getEventListeners`) — به‌علاوه‌ی سه رفتارِ واقعی: کلیکِ چیپ نماد را پر کند و دکمه‌ی «تحلیل کن» `pulse` بگیرد، انتخابِ سبک حالتِ `active` را جابه‌جا کند، و «↻ بروزرسانی» تا اولین تحلیل غیرفعال بماند. شناسه‌های `#jbtn`/`#alarmBtn`/`#pipModal` عمداً بعد از تحلیل/باز شدنِ پنجره ساخته می‌شوند و `#bootWarn` فقط در خرابی؛ پس در فهرستِ «باید باشند» نیستند و وجودشان در متنِ سرو‌شده را `selfcheck.py` (قراردادِ ۵۳ کلید) و اسموک‌تست می‌گیرند. **چرا چکِ متنی کافی نبود:** خرابیِ اصلی دکمه‌ها را در HTML نگه می‌داشت ولی همه را بی‌اثر می‌کرد؛ grep این را نمی‌بیند. تست داخلِ همان `job`ِ چکِ اجباری اجرا می‌شود (نه jobِ جدا) تا contextِ ruleset دست‌نخورده بماند، و اسکرین‌شات با `actions/upload-artifact@v7` آپلود می‌شود. **راستی‌آزمایی:** روی صفحه‌ی سالم پاس شد و روی یک کپیِ عمداً خراب (همان باگ) با هفت پیامِ دقیق رد شد. ضمناً همین تست یک ایرادِ واقعی را لو داد: درخواستِ بی‌جوابِ `/favicon.ico` خطای کنسول می‌ساخت — اپ حالا `<link rel="icon" href="/icon-192.png">` دارد و آیکون `200` می‌دهد. |

| `(این دور)` | **مسیرِ ژورنال: قابلِ تنظیم و بی‌وابسته به پوشه‌های محافظت‌شده (خواسته‌ی کاربر):** مسیرِ دفتر حالا `PIPFOUND_JOURNAL_CSV` → `PIPFOUND_JOURNAL_DIR` → پیش‌فرضِ `~/pipfound/journal.csv` است (بیرونِ `~/Desktop` و `~/Documents` که جاب‌های launchd اجازه‌ی نوشتن در آن‌ها را ندارند — TCC مک). یک مهاجرتِ بی‌خطر در استارتاپ اجرا می‌شود: ردیف‌های دفترِ قدیمی (`~/Desktop/trading-journal/journal.csv`) که در فایلِ فعلی نیستند، با شناسه‌ی تازه و یادداشتِ شماره‌ی قبلی افزوده می‌شوند؛ فایلِ قدیمی هرگز پاک/عوض نمی‌شود و اجرای دوباره «۰» می‌دهد. در `journal.py` هم `default_file()` اضافه شد (env → فایلِ اپ اگر هست → مسیرِ قدیمی) تا CLI و اپ یک دفتر را ببینند. **راستی‌آزمایی:** ردیفِ ۱۰ آگوستِ دفترِ قدیمی به‌عنوان `#3` به دفترِ اپ منتقل شد (اجرای دوم بی‌اثر)، جابِ launchd در `~/pipfound` می‌نویسد (`exit 0`)، و ثبتِ واقعیِ معامله زیرِ launchd با `PIPFOUND_JOURNAL_CSV` روی فایلِ آزمایشی `{"added": "1"}` داد بدونِ دست‌زدن به دفترِ واقعی. |

| `(این دور)` | **تستِ رفت‌وبرگشتِ ژورنال در CI (خواسته‌ی کاربر):** `journal_roundtrip_test.py` (فقط stdlib) سه چیز را قفل می‌کند: (۱) `POST /api/journal` واقعاً ردیف را می‌نویسد و از CSV **خوانده** می‌شود (شناسه‌ی بعدی درست بالا می‌رود و long/short درست ثبت می‌شود)، (۲) هر دو راهِ env کار می‌کنند — `PIPFOUND_JOURNAL_CSV` (فایلِ دقیق) و `PIPFOUND_JOURNAL_DIR` (پوشه‌ای که اگر نباشد ساخته می‌شود)، (۳) بدونِ env، ردیفِ دفترِ قدیمی منتقل می‌شود، فایلِ قدیمی **دست‌نخورده** می‌ماند، یادداشتِ ردیف منبع و شماره‌ی قبلی را نگه می‌دارد و اجرای دوباره ردیفِ تکراری نمی‌سازد. ضمناً چک می‌کند با env صریح مسیرِ پیش‌فرض ساخته نشود و مسیرِ پیش‌فرض هرگز داخلِ `Desktop/Documents` نباشد (همان محدودیتِ TCC جاب‌های launchd). هر نمونه با `HOME` و env کنترل‌شده و پورتِ تصادفی بالا می‌آید، پس به دفترِ واقعیِ کاربر دست نمی‌زند؛ اجرا داخلِ همان `job`ِ چکِ اجباری است. **راستی‌آزمایی:** لوکال ۲۰/۲۰ چک سبز و همان‌طور داخلِ CI. |

| `(این دور)` | **ری‌استارتِ خودکارِ «کدِ کهنه» (خواسته‌ی کاربر):** نشانگرِ بازنگری فقط هشدار می‌داد و دخالتِ دستی لازم داشت. حالا یک thread نگهبان (پیش‌فرض هر ۵ ثانیه، `PIPFOUND_AUTORESTART_INTERVAL`) کدِ بارشده را با دیسک می‌سنجد و اگر فایلی از استارتِ پروسه تازه‌تر شد، سه شرط را قبل از اقدام رعایت می‌کند: (۱) **سلامتِ کدِ تازه** — اول `selfcheck.run_checks` روی فایل‌های دیسک اجرا می‌شود و **اگر کدِ تازه خراب باشد ری‌استارت نمی‌شود** (سرورِ سالم برای یک ویرایشِ نیمه‌کاره کشته نمی‌شود؛ وضعیت در `autorestart.blocked` و در tooltip چیپ گزارش می‌شود)؛ (۲) **آرامشِ نوشتن** — تازه‌ترین mtime باید از `PIPFOUND_AUTORESTART_SETTLE` (پیش‌فرض ۳s) گذشته باشد تا وسطِ ذخیره‌کردنِ فایل اقدام نکند؛ (۳) **خالی بودنِ درخواست‌ها** — شمارنده‌ی `handle_one_request` می‌گوید درخواستی در جریان است یا نه و تا تمام شدنشان (حداکثر `PIPFOUND_AUTORESTART_MAXWAIT`، پیش‌فرض ۱۸۰s) صبر می‌شود تا وسطِ یک بک‌تستِ چنددقیقه‌ای قطع نشود. سپس با **`os.execv` خود را در همان PID** از نو اجرا می‌کند: چون PID عوض نمی‌شود، جابِ `launchd` و ثبتِ پیش‌نمایش معتبر می‌مانند (سوکتِ شنونده در Python غیرقابل‌ارث است، پس پورت آزاد می‌شود). خروجی: `♻️ ... ری‌استارتِ خودکار` در لاگ و رکوردِ `~/pipfound/autorestart.json` که بعد از exec هم می‌ماند و در `/api/revision` گزارش می‌شود. خاموش‌کردن: `--no-autorestart` یا `PIPFOUND_AUTORESTART=0`. چیپِ رابط چهار حالت را تفکیک می‌کند: به‌روز / در حالِ ری‌استارت (♻) / کدِ تازه خراب است (⚠) / خودِ صفحه قدیمی است و باید رفرش شود (⟳). **اضافه‌ی جانبی:** بدونِ `-u`، خروجیِ ریدایرکت‌شده به فایل بافر می‌شد و لاگِ ری‌استارت گم می‌شد؛ حالا خودِ اپ آن را خط‌بافر می‌کند. |

| `(این دور)` | **تستِ ری‌استارتِ خودکار در CI (خواسته‌ی کاربر):** `autorestart_test.py` (stdlib، روی کپیِ موقتِ پروژه و پورتِ تصادفی — بدونِ دست‌زدن به کد/دفتر/سرورِ واقعی) سه چیز را قفل می‌کند: (الف) **ری‌استارتِ واقعی**: با تغییرِ کدِ روی دیسک، سرور خودش را از نو اجرا می‌کند، مارکرِ HTML جدید واقعاً در صفحه سرو می‌شود، وضعیت در `autorestart.json` ثبت می‌شود و ری‌استارتِ تکراری/حلقه‌ای رخ نمی‌دهد؛ (ب) **محافظت از کدِ خراب**: با SyntaxError در `app.py`، پروسه کشته/ری‌استارت نمی‌شود و همان صفحه‌ی سالم سرو می‌ماند؛ پس از سالم شدنِ فایل خودش ترمیم می‌شود؛ (ج) **ری‌استارتِ تمیز**: یک درخواستِ نیمه‌کاره (بدنه‌ی ناقصِ `POST /api/journal`) روی سوکتِ خام باز نگه داشته می‌شود تا ثابت شود تا تمام شدنِ درخواست ری‌استارت انجام نمی‌شود و به‌محضِ آزاد شدن، فوراً انجام می‌شود. هر سه حالت **PID ثابت** را هم تأیید می‌کنند (هستهٔ سازگاری با launchd و ثبتِ پیش‌نمایش). امکانِ قطعِ این قابلیت هم پوشش دارد: تستِ بصری اگر `autorestart.enabled=false` ببیند PR را رد می‌کند. |

| `(این دور)` | **نشانگرِ بازنگریِ کد: تشخیصِ فوریِ «پروسه‌ی کهنه» (خواسته‌ی کاربر):** پایتون کد را لحظهٔ استارت می‌خواند، پس پروسه‌ای که بعد از یک ادغام زنده مانده، رابطِ قدیمی را سرو می‌کند و این دقیقاً به‌ظاهرِ «کلیدها گم شدند» دیده می‌شود (همین گمراهی یک‌بار وقت گرفت). حالا `GET /api/revision` جواب می‌دهد: `loaded` (SHA/شاخه/dirty که در حافظه بار شده) در برابر `disk` (وضعیتِ همین حالای ریپو)، `boot_local`/`boot_ts` (زمانِ استارتِ پروسه)، `pid`، `uptime_s`، و `stale` + `changed_files` — یعنی فایل‌هایی که mtimeشان از استارتِ پروسه تازه‌تر است. `stale` هم از mtimeِ فایل‌های تعیین‌کننده‌ی رابط (`app.py`, موتورها، `sw.js`, مانیفست) می‌آید و هم از تفاوتِ SHA. در رابط، چیپِ کنارِ عنوان (`#revChip`) هر ۳۰ ثانیه همین را می‌خواند: پیش‌فرض `4c1926c · 14s · ±dirty` و در حالتِ کهنه قرمز ＋ `⚠` با tooltipی که می‌گوید کدام فایل تازه‌تر است. **راستی‌آزمایی:** با یک `touch` روی `app.py` بعد از استارت، `stale` از `false` به `true` رفت و `changed_files=[app.py]` شد؛ تستِ بصریِ CI روی همان سرور با پیامِ `::error::پروسه‌ی سرو‌کننده نسخه‌ی کهنه است` رد شد؛ روی سرورِ تازه `stale=false` و چیپ سبز/خاکستری است. `#revChip` هم به قراردادِ کلیدها (۵۳) و به فهرستِ ۱۹ شناسهٔ تستِ بصری اضافه شد و `selfcheck-baseline.json` با `--snapshot` به‌روز رسید تا حذفِ تصادفی‌اش بعداً گرفته شود. |

| `(این دور)` | **نوشتارگرِ داخلیِ ژورنال — یافته‌ی تستِ CI:** اولین اجرای تستِ رفت‌وبرگشت روی رانر لو داد که ماژولِ ژورنال **بیرونِ ریپو** است (`~/.hermes/skills/trading/trade-journal/scripts`)، پس در CI مقدارِ `J is None` می‌ماند و `/api/journal` بی‌صدا فقط خطا برمی‌گرداند — یعنی یک وابستگیِ پنهان که در یک کلونِ تازه (یا بعد از جابه‌جا شدنِ پوشهٔ مهارت) ژورنال را از کار می‌انداخت. حالا `_JournalFallback` (همان ستون‌ها و همان رفتارِ افزودنِ ماژول) در خودِ `app.py` هست: ماژولِ sibling اگر باشد اولویت دارد، وگرنه نوشتارگرِ داخلی. لاگِ استارتاپ نوعش را چاپ می‌کند (`[ماژولِ trade-journal]` یا `[نوشتارگرِ داخلی]`) و دیگر خبری از پیامِ «ماژولِ ژورنال یافت نشد» نیست. **راستی‌آزمایی:** تستِ رفت‌وبرگشت هم محلی با ماژولِ واقعی و هم در یک کپیِ بدونِ ماژول (شبیه‌سازِ CI) سبز شد. |

| `(این دور)` | **نگهبانِ بازگشتِ خودکار — آخرین خطِ دفاع (خواسته‌ی کاربر):** اگر `selfcheck` چند بارِ پشت‌سرهم رد شود (پیش‌فرض ۳)، `selfcheck_watcher.py` خودش `main` را به **آخرین کامیتِ سبزِ CI** برمی‌گرداند. چون ruleset پوشِ مستقیم به `main` را می‌بندد، برگشت هم از همان مسیرِ مجاز می‌رود: در یک `git worktree` جدا `git revert --no-commit <green>..HEAD` ساخته می‌شود (فایل‌های زنده‌ی سرور هیچ‌وقت دست نمی‌خورند)، شاخه پوش می‌شود، PR باز می‌شود و با `gh pr merge --squash --auto` بعد از سبز شدنِ چکِ همان PR ادغام می‌شود؛ در پایان `git pull --ff-only` و صفر شدنِ شمارنده — و چون سرور ری‌استارتِ خودکار دارد، بی‌فاصله روی کدِ سالم می‌رود. **هفت شرطِ امنیت قبل از هر برگشتی:** worktree تمیز (فقط فایل‌های ردیابی‌شده؛ untracked یعنی لاگ/کش مانع نمی‌شود)، دسترسیِ `fetch` (بدونِ شبکه تصمیم نمی‌گیریم)، `HEAD` روی `main`، پیدا شدنِ سبزِ آخر با `gh run list`، `HEAD ≠ سبزِ آخر` (وگرنه شکست محیطی است نه کدی)، سبزِ آخر **پدرِ** `HEAD` باشد (`merge-base`؛ تاریخچه‌ی بازنویسی‌شده برگشت نمی‌خورد)، فاصله ≤ ۱۰ کامیت، و نبودِ PRِ برگشتِ باز (ضدِ تکرار). یک قفلِ `flock` هم از دو نمونه‌ی همزمان جلوگیری می‌کند و **اثباتِ درون‌برنامه‌ای** دارد: درختِ برگشتی با `git diff --quiet <green> HEAD` با درختِ سبز مقایسه می‌شود و اگر یکی نبود هرگز پوش نمی‌کند. تنظیم با `PIPFOUND_WATCH_*` و `--status`/`--reset`/`--dry-run`/`--no-pr`. **نصبِ دوره‌ای:** جابِ launchd `pipfound-selfcheck-watcher` با `--loop 300`؛ حالت و لاگ در `~/pipfound/` (بیرونِ پوشه‌های محافظت‌شده‌ی TCC). **راستی‌آزمایی:** `selfcheck_watcher_test.py` روی سندباکسِ کامل (`origin`ِ بَرِ محلی + `gh`ِ جعلی، بدونِ شبکه و بدونِ دست‌زدن به گیت‌هابِ واقعی) **۵۶ بررسی** را سبز می‌کند: حلقه‌ی کاملِ revert→PR→ادغام→pull با درختِ بایت‌به‌بایت برابرِ سبز، و مسدودماندن در شش حالتِ ناایمن (کثیفِ ردیابی‌شده، `HEAD`=سبز، تاریخچه‌ی بازنویسی‌شده، فاصله‌ی زیاد، PRِ باز، `--dry-run`) به‌علاوهٔ `--no-pr` و تحملِ فایلِ untracked و کرشِ `selfcheck` بدونِ JSON. روی ریپوی واقعی هم گاردها درست ارزیابی می‌شوند: روی `main`ِ سالم، شرطِ «`HEAD` = سبزِ آخر» جلوی کار را می‌گیرد. |
| `(این دور)` | **ری‌استارت روی «فقط SHA عوض شده» — باگِ واقعیِ همان چیزی که به‌نظر «کلیدها گم شدند» می‌آید:** `/api/revision` دو نشانه‌ی مستقلِ کهنگی دارد (mtimeِ فایل‌های تعیین‌کننده‌ی رابط، و تفاوتِ SHAِ بارشده با دیسک) ولی محرکِ ری‌استارتِ خودکار فقط نشانه‌ی اول را می‌دید: `_rev_watch_once` وقتی `changed_files` خالی بود زود برمی‌گشت. پس هر کامیتی که هیچ‌کدام از آن ۹ فایلِ فهرست‌شده را لمس نکرده باشد (مستندات/CI/ابزار — دقیقاً مثلِ همین PR #12 که فقط نگهبانِ برگشت و ورک‌فلو را اضافه کرد) پروسه را **تا ابد** کهنه می‌گذاشت: چیپ قرمز و tooltip می‌گفت «ری‌استارتِ خودکار به‌زودی انجام می‌شود» بدونِ اینکه هیچ‌وقت بیاید — یعنی همان «بی‌صدا نسخه‌ی کهنه سرو می‌شود» که یک‌بار خود را به‌شکلِ «کلیدها گم شدند» نشان داده بود. حالا هر دو نشانه محرک‌اند و برای حالتِ SHA (که mtimeی برای مقایسه نیست) خودِ «دیده‌شدنِ زوجِ loaded>disk» مرجعِ آرامش است تا وسطِ یک `checkout`/`pull`ِ نیمه‌کاره exec نکنیم؛ علت هم صریح ثبت می‌شود (`فقط SHA عوض شده` در لاگ و در `autorestart.json`). **راستی‌آزماییِ زنده روی سرورِ در حالِ اجرا:** یک کامیتِ خالی روی شاخه‌ی موقت (`b016906 → 1494709`) بدونِ تغییرِ mtimeِ هیچ فایلِ ردیابی‌شده‌ای، ری‌استارتِ درجا با **همان PID** آورد و `stale` به `false` برگشت؛ با `git checkout main` هم به‌همان شکل روی `b016906` ترمیم شد. **رگرسیون:** سناریوی تازه‌ی `case_sha_drift_restart` در `autorestart_test.py` (کامیتِ `--allow-empty` در یک ریپوی تازه) همین را قفل می‌کند و برابریِ mtimeها را هم تأیید می‌کند — روی کدِ قبلی رد می‌شد. |
| `(این دور)` | **انتخابِ سریعِ نماد: جفت‌ارزهای مهم + کامودیتی + اندیکس + استاک در همان کادرِ جستجو (خواسته‌ی کاربر):** چیپ‌های قدیمی (XAUUSD/XAGUSD + چهار جفت‌ارز + BTC/ETH) از صفحه رفتند و جایش چهار ردیفِ برچسب‌دار نشست: «جفت‌ارزهای مهم» (۷ جفت‌ارزِ اصلی + EURJPY/GBPJPY)، «کامودیتی» (طلا، نقره، WTI، برنت، گاز، مس)، «اندیکس» (SPX500، NAS100، US30، GER40، UK100، JP225) و «استاک» (NVDA، AAPL، MSFT، TSLA، AMZN، GOOGL، META). چیپ‌ها حالا **داخلِ همان کارتِ جستجو و بلافاصله زیرِ کادرِ نماد** رندر می‌شوند (قبلاً پایین‌تر و بعد از پنلِ ستاپ‌ها بودند و دیده نمی‌شدند)، هر چیپ `data-sym` دارد و کریپتو از چیپ‌ها حذف شد ولی در اتوکامپلیت ماند. **سمتِ داده (بخشِ اصلیِ کار):** فهرست در پایتون به‌صورتِ `SYMBOL_GROUPS` تعریف شد (یک منبعِ حقیقت برای چیپ + اتوکامپلیت) و `smc_engine.resolve` یاد گرفت اندیکس/کامودیتی/استاک را به تیکرِ درست ببرد: SPX500→`^GSPC`، NAS100→`^NDX`، US30→`^DJI`، GER40→`^GDAXI`، UK100→`^FTSE`، JP225→`^N225`، NATGAS→`NG=F`، COPPER→`HG=F`، DXY→`DX-Y.NYB`، و تیکرِ ساده برای سهام (۱ تا ۵ حرفِ لاتین) — قبلاً این‌ها به Binance می‌رفتند و قطعاً شکست می‌خوردند (پس چیپِ بی‌داده نمی‌سازیم). `tvmap` هم برای لینکِ چارتِ همان نمادها گسترده شد. **راستی‌آزمایی:** نگاشتِ `resolve` برای ۲۵ نماد آفلاین تأیید شد؛ در رابطِ زنده چهار برچسب و ۲۸ چیپ و جای‌گیریِ درست زیرِ کادرِ نماد و کلیکِ چیپِ **اندیکس** (NAS100 → پر شدنِ کادر + pulse + awaiting) تأیید شد. تستِ بصریِ CI سخت‌تر شد: وجودِ هر چهار برچسب (و نبودنِ دستهٔ خالی)، حضورِ پنج نمادِ نماینده، و کلیک روی چیپِ اندیکس به‌جای اولین چیپ. **محدودیتِ صادقانه:** دانلودِ واقعیِ داده برای دسته‌های تازه در همین نوبت تأیید نشد، چون یک کاوشِ دسته‌ایِ خودم (۲۹ نماد × ۳ تایم‌فریم) از Yahoo کد ۴۲۹ گرفت و آن محدودیتِ نرخ تا پایانِ کار باز بود؛ نگاشت‌ها استاندارد و همان مسیرِ طلا/جفت‌ارزهاست، ولی تأییدِ سرتاسری بعد از باز شدنِ محدودیت انجام می‌شود. |
| `(این دور)` | **اصلاحِ برداشت: هیچ کلیدِ نمادی در نمای اصلی نباشد (توضیحِ کاربر):** برداشتِ اول این بود که چیپ‌ها را داخلِ کارتِ جستجو و زیرِ کادر بگذاریم، ولی کاربر روشن کرد که در نمای اصلی **نباید هیچ کلیدی دیده شود** و فهرست فقط وقتی نشانگر/فوکوس داخلِ کادرِ نماد می‌رود باید دیده و انتخاب شود. پس هر چهار گروه از نمای اصلی حذف شدند و داخلِ یک پنلِ کشوییِ مطلق زیرِ خودِ کادرِ نماد نشستند (`.symwrap` + `.chips`) که پیش‌فرض `display:none` است: با `mouseenter`/`focus`/کلیک روی کادر باز می‌شود و با خروجِ نشانگر (۲۰۰ms مهلت برای عبور از فاصله‌ی ۶ پیکسلی)، کلیکِ بیرون، `Esc` یا انتخابِ یک نماد بسته می‌شود. `autofocus` از کادر برداشته شد چون در بارگذاری پنل را باز می‌کرد و همان «کلیدهای دیده‌شده» را برمی‌گرداند. انتخاب‌ها به `<button>` تبدیل شدند (کیبورد-دسترس)، با تایپ‌کردن پنل بسته می‌شود تا با اتوکامپلیتِ بومیِ مرورگر تداخل نکند و با خالی‌شدنِ کادر برمی‌گردد، و ارتفاعِ پنل `min(430px,64vh)` شد تا چهار گروه روی دسکتاپ بدونِ اسکرول جا شوند. **راستی‌آزماییِ زنده:** در بارگذاری `display:none`؛ با ورودِ نشانگر `flex` و چهار گروه (۹/۶/۶/۷) کامل و بدونِ اسکرول داخلِ پنل؛ انتخابِ SPX500 کادر را پر کرد، دکمه نبض گرفت و پنل بست؛ کلیکِ بیرون/Esc هم می‌بندد. تستِ بصریِ CI سه چکِ تازه گرفت: بسته‌بودنِ پنل در بارگذاری، بازشدنش با نشانگر، و بسته‌شدنش پس از انتخاب. |
| `(این دور)` | **D1+D2 — صداقتِ داده: تحلیل فقط روی کندلِ بسته + سنِ داده/باز-بسته در API و رابط + حذفِ نگاهِ به آینده در بک‌تست:** بازبینیِ حرفه‌ای (سندِ `PIPFOUND_AUDIT.md`) دو خطای هم‌ریشه را برجسته کرد: (۱) **repaint** — مسیرِ زنده کندلِ در حالِ تشکیل را هم تحلیل می‌کرد، پس هر سطح (سوینگ/FVG/OB/PD/کیل‌زون) تا لحظهٔ بسته‌شدن جابه‌جا می‌شد و بک‌تست (که فقط کندلِ بسته می‌دید) هرگز این حالت را اعتبارسنجی نکرده بود؛ (۲) **لحنِ سیگنال روی بازارِ بسته** — همین حالا که شنبه است، اپ روی دادهٔ جمعه (۱۵ ساعت کهنه) درجه و پلن می‌داد. **راه‌حل:** `smc_engine.drop_unclosed(bars, tf, now)` کندلِ ناقص را از انتها می‌اندازد و `fetch()` (مسیرِ زنده) همیشه آن را صدا می‌زند — فقط `_live_price` (آلارم) با `unclosed=True` استثناست چون آن‌جا *خودِ* کندلِ جاری همان قیمتِ زنده است. `freshness_from(last_bar_ts, tf, sym, src)` سنِ **بسته‌شدنِ** آخرین کندلِ بسته را می‌سنجد و حالت را برمی‌گرداند: `open` (≤۱.۵ برابرِ طولِ کندل) · `delayed` (≤۳ برابر) · `closed` (بیشتر، یا آخرِ هفتهٔ تقویمی برای هرچیز جز کریپتو، یا نبودِ داده) · `thin` (سهام خارج از ۰۹:۳۰–۱۶:۰۰ ET). همهٔ اینها **بدونِ شبکه** حساب می‌شوند، پس `/api/data_status` می‌تواند هر ۳۰ ثانیه سن را *همین‌حالا* بازمحاسبه کند. **در گریدر:** ردیفِ تازهٔ «تازگیِ داده و باز بودنِ بازار» (وزن ۱، ◐ برای عقب‌افتاده)، و گیتِ سخت: بازارِ بسته ⇒ درجه سقف C + `plan.executable_now=False` + `blocked_reason` + مهرِ ورود صادر نمی‌شود؛ دادهٔ عقب ⇒ سقفِ B. **در بک‌تست:** `_build_d` حالا با `t_decision = t_now + tf_seconds(entry_tf)` برش می‌زند و کندلِ هنوز-بازِ هر تایم‌فریم را می‌اندازد — پیش‌تر کندلِ ۴ساعته‌ای که کندلِ ورود داخلش بود با **کلوز/های/لویِ نهاییِ خودش** تحلیل می‌شد، یعنی دادهٔ آینده. **رابط:** چیپِ تازهٔ `#dataChip` کنارِ `#revChip` («🟢 داده زنده · ۳ دقیقه» / «🔴 بازار بسته»، قرمز/کهربایی) + بنرِ `datanote` بالای کارتِ نتیجه با کندلِ آخر (UTC)، سنِ داده، ساعتِ نیویورک و دلیل؛ برچسبِ پلن هم وقتی بازار بسته است «الان قابلِ اجرا نیست (بازار بسته)» می‌شود. **راستی‌آزمایی:** تستِ آفلاینِ `data_freshness_test.py` (**۵۰ بررسی**، در CI) — حذفِ کندلِ ناقص در همهٔ تایم‌فریم‌ها + مرزِ دقیق، حذف در مسیرِ واقعیِ `analyze`، ماتریسِ state/timing (وسطِ هفته/شنبه/جمعه‌ی پیش-و-پس از ۱۷:۰۰ ET/کریپتو/سهام)، گیت‌های گریدر، و باگِ look-ahead بک‌تست. **جهش‌آزمایی:** با بی‌اثر کردنِ `drop_unclosed` (مونکی‌پچ) تست **۱۵ بررسی** را رد می‌کند و exit=1 می‌دهد، یعنی تست دندان دارد. **زنده:** XAUUSD (شنبه) → `state=closed`، درجه C، `executable_now=False`، بنر و چیپِ قرمز در رابط با اسکرین‌شات؛ BTCUSDT → `state=open`، سنِ ۳ دقیقه، `executable_now=True`؛ `/api/data_status` برای هر دو درست جواب داد. **ماندگاری:** وضعیتِ آخرین تحلیل‌ها در `~/pipfound/data_seen.json` ذخیره می‌شود (نوشتنِ اتمیک) چون خودِ اپ با هر تغییرِ کد ری‌استارتِ درجا می‌کند و اگر در حافظه می‌ماند، چیپ بعد از هر ادغام خالی می‌شد؛ سن دوباره همین‌حالا از `last_bar_ts` حساب می‌شود، نه از مقدارِ یخ‌زدهٔ تحلیلِ قبلی. |
| `(این دور)` | **D8 — مدلِ ریسک: سایزِ پوزیشن + سقفِ ضررِ روزانه + هشدارِ هم‌بستگی (خواسته‌ی کاربر):** تا پیش از این فقط «۱:۳» بود و هیچ‌جا نمی‌گفت این ستاپ با سرمایه‌ی تو چند لات است، و در مسیرِ ژورنال هم `risk_pct` رشتهٔ ثابتِ `"1"` بود. **ماژولِ تازهٔ `risk.py`** (فقط stdlib، صفر شبکه): (۱) **سایزِ پوزیشن** — جدولِ مشخصاتِ قرارداد (لاتِ فارکس ۱۰۰٬۰۰۰ · طلا ۱۰۰ اونس · نقره ۵٬۰۰۰ · نفت ۱۰۰۰ بشکه · اندیکس ۱ دلار/پوینت · سهم ۱ · کریپتو ۱) + قاعدهٔ عمومیِ جفت‌ارزِ ۶حرفی و سهمِ ۱–۵حرفی (همان قاعدهٔ `resolve`، پس دو جای مختلف دو جواب نمی‌دهند). فرمول: `ریسکِ هر لات = فاصلهٔ استاپ × اندازهٔ قرارداد × نرخِ تبدیلِ مظنه→ارزِ حساب`، و `سایز = (سرمایه × درصدِ ریسک) ÷ ریسکِ هر لات`. **گِردکردن به کفِ پله** (نه نزدیک‌ترین) تا هرگز از ریسکِ هدف بیشتر نشود، و اگر ریسکِ هدف از کوچک‌ترین پله هم کمتر بود، سایزِ حداقلی با هشدارِ صریحِ «بیش از هدف». (۲) **سقفِ ضررِ روزانه** — از ردیف‌های **بستهٔ امروزِ** ژورنال: `realized_r` (و اگر خالی بود استنتاج از `result`: win→+rr · loss→‎-۱ · be→۰)، درصدِ ریسکِ همان ردیف، باقی‌مانده تا سقف، و ریسکِ بازِ فعلی (مجموعِ ریسکِ پوزیشن‌های باز). (۳) **هم‌بستگی/تمرکز** — هر نماد به فاکتورهای ریسک با علامت تجزیه می‌شود: `USD` (یک نامِ واحد، پس خریدِ EURUSD + خریدِ GBPUSD = یک شرطِ دلاری)، `CCY:*`، `METALS`، `OIL/ENERGY`، `EQ:US/EU/UK/JP/HK`، `STK:*`، `CRYPTO:*`. اگر پوزیشن‌های باز روی همان فاکتور با این معامله جمع شوند (|خالص| ≥ ۲) → هشدارِ «ریسکِ تکراری»؛ و تمرکزِ از قبل موجود در پوزیشن‌های باز **جدا** گزارش می‌شود تا به این ستاپ نسبت داده نشود. **گیتِ سخت:** عبور از سقفِ روزانه یا سقفِ ریسکِ باز ⇒ درجه سقف C، `plan.executable_now=False`، `blocked_reason` پر و **مهرِ ورود صادر نمی‌شود** (همان الگوی «گیتِ صداقت» بازارِ بسته). عمداً در حلقهٔ `app.analyze` و نه در `confluence.py`، چون به تنظیماتِ کاربر و دفترِ معاملات نیاز دارد و بک‌تست نباید بی‌دلیل عوض شود. **API:** `GET /api/risk` (تنظیمات + وضعیتِ امروز + ریسکِ باز) · `POST /api/risk` (ذخیرهٔ اتمیک در `~/pipfound/risk.json`، قابلِ جابه‌جایی با `PIPFOUND_RISK_FILE`) · هر پاسخِ `/api/analyze` بلوکِ `risk` دارد. **رابط:** پنلِ «💰 مدیریتِ ریسک» با سرمایه/درصد/سقف‌ها + خطِ وضعیتِ امروز، بنرِ هشدارِ ریسک در کارتِ نتیجه، و در کارتِ پلن یک ردیفِ سبزِ «سایزِ پوزیشن» + «ریسکِ این معامله» + «سود در هدف» + «ارزشِ هر پوینت / فاصلهٔ استاپ» با یادداشتِ گِردکردن. درصدِ ریسکِ پیکربندی‌شده حالا در ردیفِ ژورنال هم می‌نشیند (قبلاً ثابتِ ۱٪). **راستی‌آزمایی:** `risk_test.py` — **۱۹۴ بررسیِ آفلاین** (مشخصاتِ ۱۷ نماد، فرمولِ سایز با اعدادِ دستی‌محاسبه‌شده، گِردکردنِ کف، گاردهای صفر/منفی/ناشناخته، تبدیلِ ارزِ مظنه، ماتریسِ سقفِ روزانه، ۱۰ سناریوی هم‌بستگی با مثبتِ کاذب، گیتِ `evaluate`، رفت‌وبرگشتِ تنظیمات، و چکِ نبودِ هر وابستگیِ شبکه‌ای) در CI به‌عنوان لایهٔ ۴.۶؛ **جهش‌آزمایی:** سه جهشِ عمدی (گِردِ نزدیک‌ترین / خاموش‌کردنِ آستانهٔ هم‌بستگی / نادیده‌گرفتنِ سقفِ روزانه) هر سه تست را رد می‌کنند. تستِ بصریِ CI هم پنلِ ریسک، پر شدنش از اندپوینت و مسیرِ ذخیره را می‌سنجد (۲۷ کلید). تستِ ژورنال هم حالا `risk_pct=0.75` را تا ردیفِ CSV دنبال می‌کند. **زنده:** XAUUSD → «سایزِ پوزیشن 0.14 لات» با ریسکِ ۹۸.۸۴ دلار، هشدارِ تمرکزِ دلاری روی سه پوزیشنِ بازِ واقعی. **یافتهٔ جانبی:** فهرستِ دستیِ `REV_TRACKED` ماژولِ تازهٔ `risk.py` را از قلم انداخته بود، پس ویرایشِ آن ری‌استارتِ خودکار را تریگر نمی‌کرد و پروسه نسخهٔ قدیمی را سرو می‌کرد (بی‌صدا) — حالا فهرست از خودِ ماژول‌های `import`شده ساخته می‌شود. |

| `(این دور)` | **«بروزرسانی» دیگر بچه‌گانه نمی‌چرخد — قراردادِ «حالت، نه افکت» (خواسته‌ی کاربر):** کاربر گفت دکمه‌ی بروزرسانی «به شکلِ بچه‌گانه‌ای می‌چرخد». سه علتِ واقعی پیدا شد: (۱) چرخش با `cubic-bezier(.55,.15,.45,.85)` بود، پس حلقه در هر دور تند-و-کند می‌شد — همان نشانه‌ی آماتوری؛ (۲) سه حرکتِ همزمان روی یک دکمه (حلقه + نوارِ خزنده‌ی پایین + عبورِ نورِ مورب) که کلِ حالت را شلوغ و افکتی می‌کرد؛ (۳) دکمه در حینِ کار `disabled` است و قاعده‌ی `:disabled{opacity:.5}` کلِ حالتِ کار را محو می‌کرد. **قراردادِ تازه:** حلقه = یک رینگِ کم‌رنگِ زمینه (accent با ۱۶٪) + یک کمانِ اکسنت، چرخش `.9s linear` و فقط دُم نفس می‌کشد (`rfdash` ۱.۵s ease-in-out) — easing فقط روی طولِ کمان، نه روی چرخش؛ **هیچ `::before/::after`ی روی دکمه نیست** (نور/نوار برداشته شدند)؛ حالتِ کار به‌جای افکت با *وضعیت* دیده می‌شود: حاشیه‌ی اکسنت + واشِ گرادیانِ ملایم + هالهٔ نرم؛ `.loading:disabled{opacity:1}` تا وضعیتِ کار روشن بماند؛ پایانِ کار = تیکِ «کشیده» + واشِ سبزِ ملایم که با ترنزیشنِ .3s برمی‌گردد؛ اسلاتِ یکنواختِ ۱۶px که عرضِ دکمه را قفل می‌کند (۱۳۱px). نشانگرِ خطِ وضعیت (`.spin` در «در حالِ تحلیلِ دیتای زنده…» و «در حالِ بکتستِ walk-forward…») هم همین درمان را گرفت: چرخشِ `linear` (قبلاً easing داشت)، رینگِ یکنواختِ ۲px و دُمِ نرم‌تر — چون کاربر هر دو را می‌بیند. **دسترسی‌پذیری:** با `prefers-reduced-motion: reduce` چرخش خاموش می‌شود ولی نشانگر *ناپدید نمی‌شود* (تپشِ نرم) — بازخوردِ کار نباید حذف شود. **CI:** تستِ بصری حالا همین را قفل می‌کند — `linear` بودنِ تابعِ زمان (جهشِ عمدی به cubic-bezier رد می‌شود)، نبودِ افکت‌های `::before/::after`، `opacity≥۰.۹۹` در حالِ کار، تفاوتِ حاشیه/هاله با حالتِ عادی، ثابت‌بودنِ عرض، کشیده‌شدنِ تیکِ پایان، و یک بخشِ تازه با `emulateMediaFeatures` برای کاهشِ حرکت. **دو یافته‌ی صادقانه در خودِ تست:** بخشِ قبلی عملاً هیچ‌چیز را نمی‌سنجید — `animationName` را از `.rf-spin` (خودِ عنصر) می‌خواند درحالی‌که انیمیشن روی `<svg>`ِ داخلش است، پس اگر اجرا می‌شد رد می‌شد؛ و خواندنِ computed style بی‌درنگ بعد از افزودنِ کلاسِ دارای ترنزیشن، مقدارِ *قبل از تغییر* را برمی‌گرداند (پلِ ترنزیشن) — حالا بعد از هر تغییرِ کلاس از پل رد می‌شویم. **راستی‌آزمایی:** صفحه‌ی سالم پاس (۲۷/۲۷ کلید + بخشِ کاهشِ حرکت)، و کپیِ جهش‌یافته (easing + برگرداندنِ نور) با همان دو پیامِ موردنظر رد شد. |

### 5.1 Root-cause findings established so far
- **Fake bullish bias bug (RESOLVED, `7d20c44`):** original BOS/CHoCH looped backward and flagged any old swing price had passed → always fabricated a bullish bias, killed all bearish signals on FX. Fixed to nearest-swing break.
- **Low-winrate diagnosis (PARTIAL):** walk=600 gave meaningless 3–6 trade samples. walk≥3000 gives valid samples. The *real* weakness was OTE-limit entries in deep pullbacks (market 76–83% vs limit_ote 12–40% pre-fix). Fix #1 gated limit_ote to HTF confluence — but effectively removed it (see §6 C1: this was "sweeping it under the rug", not solving it).
- **Server traceback (RESOLVED, `263c524`):** was only `BrokenPipeError` from timed-out test curls, not a logic bug.

---

## 6. Known open problems / critical review (the real backlog)

> 📄 **بازبینیِ کاملِ حرفه‌ایِ ۲۰۲۶-۰۹-۱۹ (تریدرِ SMC/ICT) در `PIPFOUND_AUDIT.md` است** — ۱۰ ایرادِ فنی با شاهدِ `فایل:خط`، کمبودهای متدولوژی (Draw on Liquidity، SMT، Power of 3، مدلِ ریسک)، وضعیتِ نصب‌پذیری (دو دیوارِ سخت: `127.0.0.1` + نبودِ TLS) و راهِ به‌روزرسانی/نصب. آن‌جا نقشهٔ راهِ P0/P1/P2 هم هست.

### Tier 0 — صداقتِ داده (از بازبینیِ ۲۰۲۶-۰۹-۱۹)
- **D1 — ✅ RESOLVED (`این دور`).** تحلیل روی کندلِ ناقص (repaint) + اپ روی بازارِ بسته درجهٔ «قابلِ اجرا» می‌داد. جزئیات در changelog همین دور.
- **D2 — ✅ RESOLVED (`این دور`).** بک‌تست کندلِ HTFِ هنوز-باز را با کلوزِ **نهاییِ** خودش تحلیل می‌کرد (نگاه به آینده). حالا با `drop_unclosed(now=t_decision)` همان چیزی دیده می‌شود که در لحظهٔ تصمیم وجود داشت.
- **D3 — ⏳ OPEN. بازنمونه‌گیریِ ۴ساعته ناهم‌تراز است:** `resample()` گروه‌ها را از ابتدای آرایه می‌چیند، نه از مرزِ ساعت. روی XAUUSD سنجیده شد: **۲۲۸/۳۰۰ کندل روی شبکهٔ ۴ساعته نیست** (فاز `hour%4=2`). یعنی دیلینگ‌رنج/OTE روی چارتی لنگر می‌خورد که با چارتِ کارگزار یکی نیست. کریپتو سالم است (۴ساعتهٔ Binance بومی)، پس یک سبک روی دو دارایی دو هندسه می‌دهد.
- **D4 — ⏳ OPEN. تولرانس‌های نسبتیِ ثابت:** `tol=0.0007` (equal-high) و `tol=0.0015` (الگو) با نوسان مقیاس نمی‌خورند → روی USDJPY ≈ ۱۰ پیپ و روی NAS100 ≈ ۳۰ پوینت «هم‌سطح» حساب می‌شود. باید ATR-محور شود.
- **D5 — ⏳ OPEN. گیتِ خبر در بک‌تست با ساعتِ دیوار:** `news_gate()` از `now_et()` می‌خواند (نه تایم‌استمپِ کندل) و آفستِ ET را `-4` ثابت گرفته (بدونِ DST) → بک‌تست ناتکرارپذیر و در زمستان یک ساعت جابه‌جا.
- **D6 — ⏳ OPEN. کیل‌زونِ London Close (۱۰–۱۲ ET) عملاً مرده است:** بازه‌ها به‌ترتیب چک می‌شوند و `NY AM (8.5–11)` در ۱۰:۰۰–۱۱:۰۰ آن را می‌بلعد؛ برچسبِ رِنجِ آسیا هم برای ۰۰:۳۰ ET اشتباه است.
- **D7 — ⏳ OPEN. صفر واقع‌گراییِ اجرا در بک‌تست:** نه اسپرد، نه کمیسیون، نه سوآپ، نه اسلیپیج (جست‌وجو خالی). برای اسکالپِ ۵m/۱m بزرگ‌ترین عاملِ فریبِ RR است. ضمناً معامله‌ی ناتمام `None` می‌شود و **کلاً از آمار حذف** می‌شود (سوگیریِ خوش‌بینانه).
- **D8 — ✅ RESOLVED (`این دور`).** مدلِ ریسک اضافه شد: سرمایه/درصدِ ریسک/سقف‌ها، سایزِ پوزیشن (لات/کانترکت/سهم/واحد) در کارتِ پلن، سقفِ ضررِ روزانه و ریسکِ باز از ژورنال، و هشدارِ هم‌بستگی/تمرکز با گیتِ سخت. جزئیات در changelog همین دور. **باقی‌ماندهٔ مرتبط:** هم‌بستگی‌های عددی (ضریبِ واقعیِ هم‌بستگی) و سایزِ خودکار سفارش (ارسال به کارگزار) هنوز نیست — این‌ها Tier 3اند.
- **D9 — ⏳ OPEN. تایم‌فریمِ میانیِ استک‌ها بی‌نقش است:** `score()` فقط `tfs[0]`، `tfs[1]`، `tfs[-1]` را می‌بیند (۱۵m در اسکالپ، ۱h در روزانه).
- **D10 — ⏳ OPEN. سطوحِ HTF ناقص:** PWH/PWL، PMH/PML، IPDA ۲۰/۴۰/۶۰ روزه، NDOG/NWOG، و اوپنِ ۰۰:۰۰ ET نیستند؛ SMT/جوتاس/کلاسترهای همبستگی فقط **متنِ آموزشی**اند (`macro_context.py`) و محاسبه نمی‌شوند. سطوحِ روزانه برای اندیکس/استاک هم روی تعریفِ سشنِ تقویمی حساب می‌شود (سشنِ آتی ۱۸:۰۰ ET باز می‌شود).
- **D11 — ⏳ OPEN. تستِ عددیِ موتور نیست:** ۵۶ بررسیِ نگهبان فقط «کلید/مسیر» را می‌سنجد، نه سوینگ/FVG/ساختار/PD را. (تستِ تازه‌ی `data_freshness_test.py` فقط لایهٔ کندلِ بسته/بازار/فعالیت را پوشش می‌دهد.)
- **D12 — ⏳ OPEN. نصب روی «هر دستگاه» دو دیوارِ سخت دارد:** سرور پیش‌فرض `127.0.0.1` است (`app.py:2798`) و **هیچ پشتیبانیِ TLS ندارد** → سرویس‌ورکر/نصبِ PWA روی مبدأِ ناامن کار نمی‌کند؛ احرازِ هویت هم صفر است. راه‌حل‌ها در `PIPFOUND_AUDIT.md` §۴.

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

### ۷.۱ ترتیبِ تازه‌ی کار پس از بازبینیِ ۲۰۲۶-۰۹-۱۹ (جزئیات و برآورد در `PIPFOUND_AUDIT.md` §۶)
0. **D1 + D2 ✅ انجام شد (این دور)** — تحلیل فقط کندلِ بسته، سنِ داده/باز-بسته در API و رابط، گیتِ درجه، و حذفِ look-ahead بک‌تست. تست: `data_freshness_test.py` (۵۰ بررسی، در CI).
1. **D8 ✅ انجام شد (این دور)** — مدلِ ریسک و سایزِ پوزیشن (سرمایه + درصدِ ریسک → لات/کانترکت/سهم، سقفِ ضررِ روزانه، سقفِ ریسکِ باز، هشدارِ هم‌بستگی و گیتِ سخت). تست: `risk_test.py` (۱۹۴ بررسی، در CI). باقی‌مانده (Tier 3): هم‌بستگیِ عددی و ارسالِ خودکارِ سفارش.
2. **D3** — برشِ ۴ساعته بر پایه‌ی `t // 14400` (یا منبعِ درستِ ۴ساعته) تا PD/OTE با چارتِ کارگزار یکی شود.
3. **D7** — اسپرد/کمیسیون/سوآپ + علامت‌زدنِ معاملاتِ ناتمام به‌جای حذفِ آن‌ها.
4. **D5 + D6** — گیتِ خبر از تایم‌استمپِ کندل + DSTِ درست + کشِ تاریخیِ تقویم؛ و اصلاحِ ترتیب/برچسبِ کیل‌زون‌ها.
5. **D11** — تستِ عددیِ طلایی برای موتور (سوینگ/FVG/OB/ساختار/PD) + تستِ هم‌ترازیِ ۴ساعته.
6. **D10** — سطوحِ HTF (PWH/PWL، PM/PML، اوپنِ نیمه‌شب، NDOG/NWOG) + تعریفِ سشنِ درست برای اندیکس/استاک؛ سپس SMT/DXY و Power of 3.
7. **D4 + D9** — تولرانسِ ATR-محور و استفادهٔ واقعی از تایم‌فریمِ میانی در امتیاز.
8. **D12** — مسیرِ نصب: TLS + توکن + QR + تقویتِ مانیفست/سرویس‌ورکر (PWA)، سپس ایمیجِ Docker و `/api/version`/CHANGELOG، بعد برون‌بری/درون‌بریِ دادهٔ کاربر.

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
