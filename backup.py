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
import datetime
import json

KIND = "pipfound-backup"
VERSION = 1

# سقف‌های اندازه — بسته‌ای که از این‌ها بزرگ‌تر باشد احتمالاً فایلِ اشتباهی است
MAX_JOURNAL = 5000
MAX_ALARMS = 500
MAX_PROBLEMS = 12          # سقفِ خطاهای گزارش‌شده (بقیه فقط شمرده می‌شوند)

# تنها کلیدهای مجازِ هر بخش — فیلدِ ناشناخته در ژورنال/تنظیمات «خطا» است
# (چون نشانهٔ فایلِ اشتباه یا نسخهٔ ناسازگار است)، ولی در آلارم‌ها فقط
# «پاک‌سازی» می‌شود تا آلارمِ ساختِ نسخه‌های قدیمی‌تر هم قابلِ‌انتقال بمانَد.
SETTINGS_KEYS = ("balance", "account_ccy", "risk_pct", "daily_loss_limit_pct",
                 "max_open_risk_pct", "usd_per_quote")
ALARM_KEYS = ("id", "symbol", "mode", "direction", "style", "active", "triggered",
              "created", "last_price", "low", "high", "target", "cross",
              "hit_reason", "triggered_at")


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
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


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
            al.append({k: a[k] for k in ALARM_KEYS if k in a})
    st = {}
    if isinstance(settings, dict):
        for k in SETTINGS_KEYS:
            if k in settings:
                st[k] = settings[k]
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
            if not _s(a.get("id")).strip():
                p.append(tag + " شناسه (id) ندارد")
            if not _s(a.get("symbol")).strip():
                p.append(tag + " نماد (symbol) ندارد")
            if not isinstance(a.get("mode"), str) or not a.get("mode"):
                p.append(tag + " نوع (mode) ندارد")

    # ── تنظیمات ──
    st = doc.get("settings")
    if not isinstance(st, dict):
        p.append("بخشِ settings باید شیء باشد")
    else:
        for k, v in st.items():
            if k not in SETTINGS_KEYS:
                p.append(f"کلیدِ ناشناخته در تنظیمات: {k}")
                continue
            if k == "account_ccy":
                if not isinstance(v, str) or len(v.strip()) != 3:
                    p.append("ارزِ حساب (account_ccy) باید کدِ سه‌حرفی باشد")
            elif k == "usd_per_quote":
                ok = isinstance(v, dict) and all(
                    _num(v2) is not None and _num(v2) > 0 for v2 in v.values())
                if not ok:
                    p.append("نرخ‌های usd_per_quote باید نگاشتِ ارز→عددِ مثبت باشند")
            else:
                n = _num(v)
                if n is None or n < 0:
                    p.append(f"مقدارِ «{k}» باید عددِ ≥۰ باشد")
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
            item = {k: a[k] for k in ALARM_KEYS if k in a}
            out.append(item)
            have_ids.add(_s(item.get("id")))
            have_fp.add(_alarm_fp(item))
    added = skipped = 0
    for a in (incoming or []):
        if not isinstance(a, dict):
            continue
        item = {k: a[k] for k in ALARM_KEYS if k in a}
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
                out[k] = incoming[k]
    return out
