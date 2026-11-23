#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پشتیبان‌گیریِ دادهٔ کاربر — برون‌بری/درون‌بریِ JSON (ژورنال، آلارم‌ها، تنظیمات).

چرا این ماژول لازم بود: اپ روی هر دستگاهِ نصب‌شده یک دفترِ ژورنال، یک فایلِ آلارم و
یک فایلِ تنظیماتِ **جدا** دارد؛ بدونِ راهِ انتقال، «نصب روی دستگاهِ تازه» یعنی
«شروعِ از صفر». این ماژول همان حلقه را می‌بندد و سه عملیاتِ خالص و قابلِ‌آزمون
می‌دهد (هیچ I/O و هیچ شبکه‌ای این‌جا نیست — همه آفلاین و قطعی):

  ۱) `build(...)` — ساختِ بستهٔ پشتیبان از دادهٔ واقعی: یک شیءِ JSON با نشانِ
     نوع (`kind = "pipfound-backup"`)، نسخه (`version`)، زمان، و سه بخشِ
     `journal` / `alarms` / `settings` به‌علاوهٔ شمارش‌ها.
  ۲) `validate(doc, fields)` — اعتبارسنجیِ **کاملِ پیش از هر نوشتن**. نشانِ نوع،
     نسخه، شکلِ هر بخش، نمادهای اجباری، فیلدهای ناشناخته، و بازهٔ عددیِ
     تنظیمات. خروجی: فهرستِ خطاهای فارسی (خالی = سالم). چون هیچ نوشتنی این‌جا
     نیست، بدنهٔ خراب هیچ‌وقت «نیمه‌کاره» اعمال نمی‌شود.
  ۳) `merge_journal` / `merge_alarms` / `merge_settings` — ادغامِ **بی‌خطر و
     تکرارپذیر**: هیچ ردیفی پاک/بازنویسی نمی‌شود؛ ردیف‌های تازه با کلیدِ
     (datetime, symbol, direction, entry) — همان کلیدِ مهاجرتِ دفترهای قدیمی —
     و آلارم‌ها با `id` در برابر تکرار حفاظت می‌شوند. اجرای دوبارهٔ همان بسته
     «۰ افزوده» می‌دهد، پس درون‌بری روی دستگاهِ خودت هم بی‌خطر است.

قراردادِ نگهبان (لایهٔ ۱): `selfcheck.backup_problems` همین سه ویژگی را استاتیک
می‌سنجد — برون‌بری هر سه بخش را بردارد، درون‌بری پیش از اعتبارسنجی ننویسد، و
بازنویسیِ دفتر اتمیک باشد — وگرنه بوت قصدِ سروِ کدِ خراب نمی‌کند.
"""
import copy
import datetime
import json
import math
import re

import risk as RK

KIND = "pipfound-backup"
VERSION = 1

# سقف‌های اندازه — بسته‌ای که از این‌ها بزرگ‌تر باشد احتمالاً فایلِ اشتباهی است
MAX_JOURNAL = 5000
MAX_ALARMS = 500
MAX_PROBLEMS = 12          # سقفِ خطاهای گزارش‌شده (بقیه فقط شمرده می‌شوند)
MAX_TEXT = 65536
MAX_SEEN = 5000
MAX_HITS = 1000           # سقفِ ایمنیِ انتقال؛ کارگر فعلی فقط ۲۰ هشدار نگه می‌دارد
MAX_JSON_DEPTH = 8
MAX_JSON_NODES = 300000
MAX_SAFE_COUNT = 2 ** 53 - 1

# تنها کلیدهای مجازِ هر بخش — فیلدِ ناشناخته در ژورنال/تنظیمات «خطا» است
# (چون نشانهٔ فایلِ اشتباه یا نسخهٔ ناسازگار است)، ولی در آلارم‌ها فقط
# «پاک‌سازی» می‌شود تا آلارمِ ساختِ نسخه‌های قدیمی‌تر هم قابلِ‌انتقال بمانَد.
SETTINGS_KEYS = ("balance", "account_ccy", "risk_pct", "daily_loss_limit_pct",
                 "max_open_risk_pct", "usd_per_quote")
ALARM_KEYS = ("id", "symbol", "mode", "direction", "style", "active", "triggered",
              "created", "last_price", "low", "high", "target", "cross",
              "hit_reason", "triggered_at", "tf", "seeded", "seen", "hits",
              "alerts", "last_scan", "scanned", "reliable_now")
ALARM_MODES = ("ote", "price", "gap")
ALARM_TFS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w")
_SYMBOL_RE = re.compile(r"[A-Za-z0-9^][A-Za-z0-9._=^/\-]{0,63}\Z")
_JOURNAL_NUMBERS = ("entry", "sl", "tp", "rr", "risk_pct", "exit", "realized_r")


def _s(v):
    """هر مقدارِ JSON را به رشتهٔ امنِ CSV تبدیل می‌کند (None → "")."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _num(v):
    """عددِ متناهی از ورودی، وگرنه None (بولین عدد نیست)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _json_problem(doc):
    """Bound work before schema checks, including ignored extension fields.

    Only JSON values may enter an import. Iteration avoids recursive validation
    of hostile nesting; numeric strings are checked by their field's schema.
    """
    stack = [(doc, 0)]
    seen = 0
    while stack:
        value, depth = stack.pop()
        seen += 1
        if seen > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            return "سندِ پشتیبان از سقفِ اندازه/عمقِ مقادیرِ تودرتو بیشتر است"
        if isinstance(value, dict):
            if len(value) > MAX_JSON_NODES:
                return "شیءِ پشتیبان از سقفِ اندازه بیشتر است"
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > MAX_TEXT:
                    return "کلیدِ پشتیبان باید رشتهٔ کوتاه باشد"
                stack.append((child, depth + 1))
        elif isinstance(value, list):
            if len(value) > MAX_JSON_NODES:
                return "آرایهٔ پشتیبان از سقفِ اندازه بیشتر است"
            stack.extend((child, depth + 1) for child in value)
        elif isinstance(value, str):
            if len(value) > MAX_TEXT:
                return "رشتهٔ پشتیبان از سقفِ اندازه بیشتر است"
        elif isinstance(value, bool) or value is None:
            continue
        elif isinstance(value, (int, float)):
            if _num(value) is None:
                return "مقدارِ عددیِ پشتیبان باید متناهی باشد"
        else:
            return "مقادیرِ پشتیبان باید فقط از نوع‌های JSON باشند"
    return None


def _text(value, limit=MAX_TEXT, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and len(value) <= limit)


def _symbol(value):
    return isinstance(value, str) and _SYMBOL_RE.fullmatch(value) is not None


def _alarm_problems(a, tag):
    p = []
    aid = a.get("id")
    if not ((isinstance(aid, str) and 0 < len(aid.strip()) <= 256)
            or (type(aid) is int and abs(aid) <= MAX_SAFE_COUNT)):
        p.append(tag + " شناسه (id) معتبر ندارد")
    if not _symbol(a.get("symbol")):
        p.append(tag + " نماد (symbol) معتبر ندارد")
    mode = a.get("mode")
    if not isinstance(mode, str) or mode not in ALARM_MODES:
        p.append(tag + " نوع (mode) نامعتبر است")
    if "tf" in a and (not isinstance(a["tf"], str) or a["tf"] not in ALARM_TFS):
        p.append(tag + " تایم‌فریم (tf) نامعتبر است")
    if mode == "gap" and "tf" not in a:
        p.append(tag + " گپ‌بان بدونِ تایم‌فریم (tf) قابلِ بازگردانی نیست")
    for key in ("active", "triggered", "seeded"):
        if key in a and not isinstance(a[key], bool):
            p.append(tag + f" مقدارِ {key} باید بولین باشد")
    for key in ("last_price", "low", "high", "target"):
        if key in a and not (key == "last_price" and a[key] is None) and _num(a[key]) is None:
            p.append(tag + f" مقدارِ {key} باید عددِ متناهی باشد")
    if mode == "ote":
        lo, hi = _num(a.get("low")), _num(a.get("high"))
        if lo is None or hi is None or lo == hi:
            p.append(tag + " محدودهٔ OTE (low/high) معتبر ندارد")
    if mode == "price" and _num(a.get("target")) is None:
        p.append(tag + " هدفِ قیمت (target) معتبر ندارد")
    if "cross" in a and a["cross"] not in ("any", "above", "below", "up", "down"):
        p.append(tag + " جهتِ عبور (cross) نامعتبر است")
    for key in ("created", "triggered_at", "last_scan", "style", "hit_reason"):
        if key in a and not _text(a[key], nullable=True):
            p.append(tag + f" مقدارِ {key} باید متن باشد")
    if "direction" in a:
        v = a["direction"]
        if not (_text(v, 128, nullable=True) or (type(v) is int and v in (-1, 1))):
            p.append(tag + " جهت (direction) معتبر نیست")
    for key in ("alerts", "scanned", "reliable_now"):
        if key in a and not (type(a[key]) is int and 0 <= a[key] <= MAX_SAFE_COUNT):
            p.append(tag + f" مقدارِ {key} باید شمارشِ صحیحِ نامنفی باشد")
    if "seen" in a:
        seen = a["seen"]
        if not (isinstance(seen, list) and len(seen) <= MAX_SEEN
                and all(_text(k, 512) and bool(k) for k in seen)):
            p.append(tag + " فهرستِ seen نامعتبر یا بیش از سقف است")
    if "hits" in a:
        hits = a["hits"]
        if not isinstance(hits, list) or len(hits) > MAX_HITS:
            p.append(tag + " فهرستِ hits نامعتبر یا بیش از سقف است")
        else:
            for h in hits:
                if not isinstance(h, dict):
                    p.append(tag + " هشدارِ hits باید شیء باشد")
                    continue
                if "tf" in h and (not isinstance(h["tf"], str) or h["tf"] not in ALARM_TFS):
                    p.append(tag + " تایم‌فریمِ هشدار (hits.tf) نامعتبر است")
                if "grade" in h and h["grade"] not in ("A+", "A"):
                    p.append(tag + " درجهٔ هشدار (hits.grade) نامعتبر است")
                if "symbol" in h and not _symbol(h["symbol"]):
                    p.append(tag + " نمادِ هشدار (hits.symbol) نامعتبر است")
                for key in ("at", "key", "state_fa", "why"):
                    if key in h and not _text(h[key]):
                        p.append(tag + f" مقدارِ hits.{key} باید متن باشد")
                for key in ("bottom", "top", "percent"):
                    if key in h and _num(h[key]) is None:
                        p.append(tag + f" مقدارِ hits.{key} باید عددِ متناهی باشد")
                pc = _num(h.get("percent"))
                if pc is not None and not 0 <= pc <= 100:
                    p.append(tag + " درصدِ هشدار (hits.percent) بیرونِ بازه است")
                lo, hi = _num(h.get("bottom")), _num(h.get("top"))
                if lo is not None and hi is not None and lo >= hi:
                    p.append(tag + " محدودهٔ هشدار (hits.bottom/top) نامعتبر است")
    return p


def _cap(probs):
    """فهرستِ خطاها را به سقفِ خوانا می‌برد (وگرنه یک فایلِ خراب صد خط پیام می‌دهد)."""
    if len(probs) > MAX_PROBLEMS:
        extra = len(probs) - MAX_PROBLEMS
        return probs[:MAX_PROBLEMS] + [f"…و {extra} خطای دیگر"]
    return probs


def build(journal_rows, fields, alarms, settings, now=None):
    """بستهٔ پشتیبان را از دادهٔ واقعی می‌سازد (بدونِ I/O).

    `fields` = ستون‌های دفتر (تا بسته با شکلِ همان دفتر بخواند) و `now` برای
    تستِ قطعی. ردیف‌های ژورنال به متنِ امن تبدیل می‌شوند و آلارم‌ها/تنظیمات
    فقط با کلیدهای شناخته‌شده در بسته می‌نشینند.
    """
    fields = list(fields)
    rows = []
    for r in journal_rows or []:
        if isinstance(r, dict):
            rows.append({f: _s(r.get(f, "")) for f in fields})
    al = []
    for a in (alarms or []):
        if isinstance(a, dict):
            al.append(copy.deepcopy({k: a[k] for k in ALARM_KEYS if k in a}))
    st = {}
    if isinstance(settings, dict):
        for k in SETTINGS_KEYS:
            if k in settings:
                st[k] = copy.deepcopy(settings[k])
    return {
        "kind": KIND,
        "version": VERSION,
        "exported_at": now or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "counts": {"journal": len(rows), "alarms": len(al)},
        "journal_fields": fields,
        "journal": rows,
        "alarms": al,
        "settings": st,
    }


def validate(doc, fields):
    """اعتبارسنجیِ کاملِ بسته **پیش از هر نوشتن** → فهرستِ خطاهای فارسی."""
    fields = list(fields)
    p = []
    if not isinstance(doc, dict):
        return ["سندِ پشتیبان باید یک شیءِ JSON باشد (بالاترین سطح)"]
    json_problem = _json_problem(doc)
    if json_problem:
        return [json_problem]
    if doc.get("kind") != KIND:
        p.append("این فایل پشتیبانِ pipfound نیست — کلیدِ kind باید «pipfound-backup» باشد")
    ver = doc.get("version")
    if isinstance(ver, bool) or not isinstance(ver, int) or ver != VERSION:
        p.append(f"نسخهٔ سندِ پشتیبان پشتیبانی نمی‌شود (version={ver!r}؛ این اپ فقط "
                 f"نسخهٔ {VERSION} را می‌خوانَد)")

    # ── ژورنال ──
    jr = doc.get("journal")
    if not isinstance(jr, list):
        p.append("بخشِ journal باید فهرستِ ردیف‌ها باشد")
    else:
        if len(jr) > MAX_JOURNAL:
            p.append(f"ردیف‌های ژورنال از سقف بیشتر است ({len(jr)} > {MAX_JOURNAL})")
        fset = set(fields)
        for i, r in enumerate(jr):
            tag = f"ردیفِ {i + 1} ژورنال"
            if not isinstance(r, dict):
                p.append(tag + " شیء نیست")
                continue
            bad = sorted(set(map(str, r.keys())) - fset)
            if bad:
                p.append(tag + " فیلدِ ناشناخته دارد: " + "، ".join(bad[:4]))
            if not _s(r.get("symbol")).strip():
                p.append(tag + " نماد (symbol) ندارد")
            if any(isinstance(v, (dict, list)) for v in r.values()):
                p.append(tag + " مقدارِ شیء/آرایه دارد؛ مقادیر باید ساده باشند")
            for key in _JOURNAL_NUMBERS:
                v = r.get(key)
                if v is None or (isinstance(v, str) and not v.strip()):
                    continue  # ستون‌های تهیِ دفترهای قدیمی همچنان مجازند
                n = RK._num(v)
                if n is None or (key in ("risk_pct", "rr") and n < 0):
                    p.append(tag + f" مقدارِ {key} باید عددِ متناهیِ معتبر باشد")

    # ── آلارم‌ها ──
    al = doc.get("alarms")
    if not isinstance(al, list):
        p.append("بخشِ alarms باید فهرست باشد")
    else:
        if len(al) > MAX_ALARMS:
            p.append(f"آلارم‌ها از سقف بیشتر است ({len(al)} > {MAX_ALARMS})")
        for i, a in enumerate(al):
            tag = f"آلارمِ {i + 1}"
            if not isinstance(a, dict):
                p.append(tag + " شیء نیست")
                continue
            p.extend(_alarm_problems(a, tag))

    # ── تنظیمات ──
    st = doc.get("settings")
    if not isinstance(st, dict):
        p.append("بخشِ settings باید شیء باشد")
    else:
        for k, v in st.items():
            if k not in SETTINGS_KEYS:
                p.append(f"کلیدِ ناشناخته در تنظیمات: {k}")
                continue
        p.extend(RK.validate_settings(st))
    return _cap(p)


def merge_journal(existing_rows, incoming_rows, fields):
    """ردیف‌های تازه را می‌افزاید و هیچ‌چیز را پاک نمی‌کند.

    → (همهٔ ردیف‌ها، شمردهٔ افزوده‌شده، شمردهٔ تکراری). کلیدِ یکتایی همان کلیدِ
    مهاجرتِ دفترهای قدیمی است — پس درون‌بریِ دوبارهٔ همان بسته ردیفِ تکراری
    نمی‌سازد — و شناسهٔ ردیف‌های تازه از «بیشترین شناسهٔ موجود + ۱» ادامه می‌یابد.
    """
    fields = list(fields)
    rows = [{f: _s(r.get(f, "")) for f in fields} for r in (existing_rows or [])]

    def key(r):
        return (_s(r.get("datetime")), _s(r.get("symbol")).upper(),
                _s(r.get("direction")), _s(r.get("entry")))

    have = {key(r) for r in rows}
    ids = [int(str(r.get("id")).strip()) for r in rows
           if str(r.get("id", "")).strip().isdigit()]
    nid = (max(ids) + 1) if ids else 1
    added = skipped = 0
    for r in (incoming_rows or []):
        if not isinstance(r, dict):
            continue
        k = key(r)
        if k in have:
            skipped += 1
            continue
        nr = {f: _s(r.get(f, "")) for f in fields}
        nr["id"] = str(nid)
        nid += 1
        rows.append(nr)
        have.add(k)
        added += 1
    return rows, added, skipped


def _alarm_fp(a):
    """اثرِ انگشتِ آلارم (بدونِ شناسه) — برای تشخیصِ «همان آلارم» از «شناسهٔ برخوردی»."""
    return json.dumps({k: a.get(k) for k in ALARM_KEYS if k in a and k != "id"},
                      sort_keys=True, ensure_ascii=False)


def merge_alarms(existing, incoming):
    """آلارم‌های تازه را می‌افزاید → (همه، افزوده، تکراری).

    سه حفاظت: (۱) آلارمِ عیناً موجود — حتی با شناسهٔ دیگر — دوباره اضافه نمی‌شود،
    پس اجرای دوبارهٔ همان بسته «۰ افزوده» می‌دهد؛ (۲) اگر شناسهٔ آلارمِ تازه با
    شناسهٔ موجودی برخورد کند و محتوا **متفاوت** باشد، شناسهٔ پسونددار می‌گیرد تا
    هیچ آلارمی بی‌صدا گم نشود؛ (۳) کلیدهای ناشناخته پاک می‌شوند.
    """
    out, have_ids, have_fp = [], set(), set()
    for a in (existing or []):
        if isinstance(a, dict):
            item = copy.deepcopy({k: a[k] for k in ALARM_KEYS if k in a})
            out.append(item)
            have_ids.add(_s(item.get("id")))
            have_fp.add(_alarm_fp(item))
    added = skipped = 0
    for a in (incoming or []):
        if not isinstance(a, dict):
            continue
        item = copy.deepcopy({k: a[k] for k in ALARM_KEYS if k in a})
        fp = _alarm_fp(item)
        if fp in have_fp:
            skipped += 1
            continue
        aid = _s(item.get("id"))
        if aid in have_ids:
            n = 2
            while f"{aid}-{n}" in have_ids:
                n += 1
            item["id"] = f"{aid}-{n}"
            aid = item["id"]
        out.append(item)
        have_ids.add(aid)
        have_fp.add(fp)
        added += 1
    return out, added, skipped


def merge_settings(current, incoming):
    """تنظیمات را بی‌خطر ادغام می‌کند: فقط کلیدهای شناخته‌شدهٔ بسته اعمال می‌شوند."""
    out = dict(current or {})
    if isinstance(incoming, dict):
        for k in SETTINGS_KEYS:
            if k in incoming:
                out[k] = copy.deepcopy(incoming[k])
    return out
