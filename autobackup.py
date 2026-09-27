#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پشتیبانِ خودکارِ زمان‌بندی‌شده — اسنپ‌شاتِ دوره‌ای + نگه‌داشتِ چند نسخهٔ اخیر.

چرا این ماژول لازم بود: `backup.py` راهِ *دستیِ* انتقال را ساخت، ولی هیچ‌کس
دستی پشتیبان نمی‌گیرد — پس در عمل کاربر همچنان بی‌پشتیبان می‌مانْد و اولین
خرابیِ دیسک/حذفِ اشتباهی، کلِ دفتر و آلارم‌ها و تنظیمات را می‌بُرد. این ماژول
همان حلقه را می‌بندد: خودِ اپ هر N ساعت یک اسنپ‌شاتِ کامل می‌نویسد و فقط
چند نسخهٔ آخر را نگه می‌دارد.

قراردادهای مهم (همه عمدی و قابلِ‌آزمون):

  ۱) **فقط فایلِ پشتیبان حذف می‌شود.** `prune` هرگز فایلی را که الگوی نامِ
     پشتیبان (`is_backup_name`) را ندارد لمس نمی‌کند؛ پوشهٔ پشتیبان ممکن است
     فایلِ دیگری هم داشته باشد و هیچ‌کدام قربانی نمی‌شوند.
  ۲) **هرگز روی پشتیبانِ موجود نمی‌نویسیم.** اگر نامِ همان ثانیه موجود باشد،
     پسوندِ شمارهٔ یکتا می‌گیرد — پس یک اسنپ‌شاتِ تازه هیچ‌وقت نسخهٔ قبلی را
     پاک نمی‌کند.
  ۳) **نوشتنِ اتمیک.** اسنپ‌شات اول در فایلِ موقت نوشته و بعد با `os.replace`
     جایش را می‌گیرد؛ خطای وسطِ راه، فایلِ پشتیبانِ نیمه‌کاره نمی‌گذارد.
  ۴) **محتوا همان بستهٔ برون‌بری است.** ماژول بسته را از بیرون می‌گیرد (بدونِ
     وابستگی به app) و بایتی که می‌نویسد همان چیزی است که `POST /api/import`
     می‌خوانَد؛ پس هر پشتیبانِ خودکار فوراً قابلِ‌درون‌بری است.
  ۵) **حالت (state) از تنظیمات جدا است:** تنظیمات انتخابِ کاربر است
     (`~/pipfound/autobackup.json`) و state تنها «آخرین اجرا» را برای محاسبهٔ
     نوبت نگه می‌دارد. اگر state گم شود، سنِ آخرین فایلِ موجود ملاک است تا با
     هر ری‌استارتِ اپ یک نسخهٔ اضافه ساخته نشود.

محل‌ها (همه با env قابلِ جابه‌جایی، برای تستِ قطعی):

  * تنظیمات: `PIPFOUND_AUTOBACKUP_FILE` → `~/pipfound/autobackup.json`
  * پوشهٔ نسخه‌ها: `PIPFOUND_BACKUP_DIR` → `~/pipfound/backups`
  * حالت: `PIPFOUND_AUTOBACKUP_STATE` → `~/pipfound/autobackup_state.json`

قراردادِ نگهبان (لایهٔ ۱): `selfcheck.autobackup_problems` همین ویژگی‌ها را
استاتیک می‌سنجد — فیلترِ نام در `prune`، نوشتنِ اتمیک، وجودِ زمان‌بندِ روشن،
و مسیرِ خواندنِ نسخه با نامِ سنجیده‌شده (بدونِ بیرون‌زدن از پوشه).

خودآزمون:
    python3 autobackup.py
"""
import datetime
import json
import os
import re

HOME = os.path.expanduser("~")

# تنظیماتِ کاربر — این‌ها همان کلیدهای API و رابط‌اند
DEFAULTS = {
    "enabled": True,       # پشتیبانِ خودکار روشن باشد؟
    "interval_h": 24.0,    # هر چند ساعت یک اسنپ‌شات
    "keep": 7,             # چند نسخهٔ آخر نگه داشته شود
}
MIN_INTERVAL_H = 1.0
MAX_INTERVAL_H = 720.0     # ۳۰ روز
MIN_KEEP = 1
MAX_KEEP = 50
MAX_PROBLEMS = 8

# نامِ استانداردِ نسخه: pipfound-backup-YYYYmmdd-HHMMSS.json (+ پسوندِ یکتا در برخورد)
NAME_RE = re.compile(r"^pipfound-backup-\d{8}-\d{6}(?:-\d+)?\.json$")


# ═══════════════════════════════════════════════════════════════════
#  محل‌ها
# ═══════════════════════════════════════════════════════════════════
def settings_path():
    """مسیرِ فایلِ تنظیماتِ پشتیبانِ خودکار (env → پیش‌فرض)."""
    f = os.environ.get("PIPFOUND_AUTOBACKUP_FILE")
    if f:
        return os.path.expanduser(f)
    return os.path.join(HOME, "pipfound", "autobackup.json")


def backup_dir():
    """پوشهٔ نسخه‌های پشتیبان (جدا از بقیهٔ فایل‌های وضعیت تا prune امن باشد)."""
    d = os.environ.get("PIPFOUND_BACKUP_DIR")
    if d:
        return os.path.expanduser(d)
    return os.path.join(HOME, "pipfound", "backups")


def state_path():
    """مسیرِ فایلِ حالت (آخرین اجرا/خطا) — جدا از تنظیماتِ کاربر."""
    f = os.environ.get("PIPFOUND_AUTOBACKUP_STATE")
    if f:
        return os.path.expanduser(f)
    return os.path.join(HOME, "pipfound", "autobackup_state.json")


# ═══════════════════════════════════════════════════════════════════
#  ابزارِ خالص
# ═══════════════════════════════════════════════════════════════════
def _num(v):
    """عددِ متناهی از ورودی، وگرنه None (بولین عدد نیست، nan/inf هم رد است)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _cap(probs):
    if len(probs) > MAX_PROBLEMS:
        extra = len(probs) - MAX_PROBLEMS
        return probs[:MAX_PROBLEMS] + [f"…و {extra} خطای دیگر"]
    return probs


def validate_settings(d):
    """اعتبارسنجیِ تنظیماتِ ورودیِ API → فهرستِ خطاهای فارسی (خالی = سالم).

    فقط کلیدهای *حاضر* سنجیده می‌شوند (به‌روزرسانیِ جزئی مجاز است)، ولی مقدارِ
    حاضر باید در بازه باشد؛ در غیرِ آن `400` می‌گیرد و تنظیماتِ فعلی دست‌نخورده
    می‌مانَد (نه اینکه بی‌صدا به پیش‌فرض برگردد).
    """
    if not isinstance(d, dict):
        return ["تنظیماتِ پشتیبان باید یک شیءِ JSON باشد (بالاترین سطح)"]
    p = []
    if "enabled" in d and not isinstance(d["enabled"], bool):
        p.append("کلیدِ enabled باید بولین باشد (روشن/خاموش)")
    if "interval_h" in d:
        f = _num(d["interval_h"])
        if f is None:
            p.append("کلیدِ interval_h باید عدد باشد")
        elif not (MIN_INTERVAL_H <= f <= MAX_INTERVAL_H):
            p.append(f"کلیدِ interval_h باید بینِ {MIN_INTERVAL_H:g} و "
                     f"{MAX_INTERVAL_H:g} ساعت باشد")
    if "keep" in d:
        f = _num(d["keep"])
        if f is None:
            p.append("کلیدِ keep باید عدد باشد")
        elif f != int(f):
            p.append("کلیدِ keep باید عددِ صحیح باشد")
        elif not (MIN_KEEP <= int(f) <= MAX_KEEP):
            p.append(f"کلیدِ keep باید بینِ {MIN_KEEP} و {MAX_KEEP} نسخه باشد")
    return _cap(p)


def normalize(cfg):
    """تنظیماتِ ذخیره‌شده را امن می‌کند: کلیدِ غایب/خراب → پیش‌فرضِ سالم.

    تفاوت با `validate_settings`: این‌جا هیچ خطایی برگردانده نمی‌شود، چون
    خواندنِ یک فایلِ خراب روی دیسک نباید اپ را از کار بیندازد — فقط مقدارِ
    نامعتبر با پیش‌فرض جایگزین می‌شود.
    """
    out = dict(DEFAULTS)
    if isinstance(cfg, dict):
        if isinstance(cfg.get("enabled"), bool):
            out["enabled"] = cfg["enabled"]
        f = _num(cfg.get("interval_h"))
        if f is not None and MIN_INTERVAL_H <= f <= MAX_INTERVAL_H:
            out["interval_h"] = float(f)
        k = _num(cfg.get("keep"))
        if k is not None and MIN_KEEP <= k <= MAX_KEEP:
            out["keep"] = int(k)
    return out


def filename(now=None):
    """نامِ استانداردِ نسخه برای یک لحظه (تست‌پذیر با پاس‌دادنِ now)."""
    if now is None:
        t = datetime.datetime.now()
    elif isinstance(now, (int, float)):
        t = datetime.datetime.fromtimestamp(float(now))
    else:
        t = now
    return "pipfound-backup-%s.json" % t.strftime("%Y%m%d-%H%M%S")


def is_backup_name(name):
    """آیا این نام، نامِ یک نسخهٔ پشتیبانِ خودِ ماست؟ (کلیدِ ایمنیِ prune)

    سخت‌گیرانه است چون همین تابع تعیین می‌کند چه چیزی *قابلِ حذف* است: هر
    فایلِ ناشناخته در پوشه (یادداشت، دفتر، فایلِ موقت) باید دست‌نخورده بمانَد.
    """
    s = str(name or "")
    return bool(s) and NAME_RE.match(s) is not None


def plan_prune(names, keep):
    """تصمیمِ خالصِ نگه‌داشت → (نگه‌داشته‌شده‌ها، نامزدهای حذف).

    نام‌ها با تاریخِ صفرپُر مرتب‌شدنی‌اند، پس مرتب‌سازیِ نزولیِ رشته‌ای =
    «تازه‌ترین اول». فقط نام‌های معتبر واردِ محاسبه می‌شوند و کوچک‌ترین
    نگه‌داشت هم ۱ است — هیچ‌وقت «همه را حذف کن» اتفاق نمی‌افتد.
    """
    k = _num(keep)
    k = MIN_KEEP if k is None else max(MIN_KEEP, int(k))
    safe = sorted({str(n) for n in (names or []) if is_backup_name(n)}, reverse=True)
    return safe[:k], safe[k:]


def due(last_run_ts, now_ts, interval_h, enabled=True):
    """آیا وقتِ اسنپ‌شاتِ تازه است؟ (خالص و بدونِ خواندنِ ساعتِ سیستم)

    «هرگز پشتیبان نگرفته» (`last_run_ts` تهی) یعنی همین حالا — همان چیزی که
    کاری می‌کند یک نصبِ تازه هم از همان اولین اجرا پشتیبان داشته باشد.
    """
    if not enabled:
        return False
    iv = _num(interval_h)
    if iv is None or iv <= 0:
        iv = DEFAULTS["interval_h"]
    iv = min(max(iv, MIN_INTERVAL_H), MAX_INTERVAL_H)
    last = _num(last_run_ts)
    if last is None:
        return True
    now = _num(now_ts)
    if now is None:
        return False
    return (now - last) >= iv * 3600.0


def effective_last_run(state_ts, backups):
    """زمانِ مؤثرِ آخرین پشتیبان = بیشینهٔ (state، تازهٔ‌ترین فایلِ موجود).

    چرا: اگر state گم/خراب شود، ملاک‌گرفتنِ «صفر» باعث می‌شود هر ری‌استارتِ
    اپ یک نسخهٔ تازه بسازد و چند نسخهٔ سالمِ قبلی را با prune بیرون بیندازد.
    """
    vals = [_num(state_ts)]
    for b in (backups or []):
        if isinstance(b, dict):
            vals.append(_num(b.get("mtime")))
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


# ═══════════════════════════════════════════════════════════════════
#  I/O — همه اتمیک
# ═══════════════════════════════════════════════════════════════════
def _write_json(p, obj):
    """نوشتنِ اتمیکِ JSON (tmp + os.replace) — الگوی همهٔ فایل‌های وضعیتِ اپ."""
    d = os.path.dirname(p)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p


def load_settings(path=None):
    """تنظیماتِ ذخیره‌شده؛ فایلِ نبود/خراب → پیش‌فرض‌ها (بدونِ استثنا)."""
    p = path or settings_path()
    try:
        with open(p, encoding="utf-8") as f:
            return normalize(json.load(f))
    except Exception:
        return dict(DEFAULTS)


def save_settings(d, path=None):
    """ذخیرهٔ اتمیکِ تنظیمات + مهرِ زمان تا معلوم باشد کی عوض شده."""
    p = path or settings_path()
    data = normalize(d)
    data["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S")
    _write_json(p, data)
    return data


def load_state(path=None):
    """حالتِ زمان‌بند (آخرین اجرا/نامِ فایل/شمارش/خطا) — نبود = حالتِ نخستین."""
    out = {"last_run": None, "last_run_ts": None, "last_file": None,
           "last_bytes": 0, "runs": 0, "last_error": None}
    try:
        with open(path or state_path(), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k in list(out):
                if k in d:
                    out[k] = d[k]
    except Exception:
        pass
    return out


def save_state(st, path=None):
    """ذخیرهٔ اتمیکِ حالت (فقط کلیدهای شناخته‌شده)."""
    st = st if isinstance(st, dict) else {}
    data = {k: st.get(k) for k in ("last_run", "last_run_ts", "last_file",
                                   "last_bytes", "runs", "last_error")}
    _write_json(path or state_path(), data)
    return data


def list_backups(dir=None):
    """نسخه‌های موجود، تازه‌ترین اول؛ فایل‌های ناشناخته نادیده می‌مانند."""
    d = dir or backup_dir()
    out = []
    try:
        names = os.listdir(d)
    except Exception:
        return []
    for n in names:
        if not is_backup_name(n):
            continue
        try:
            stt = os.stat(os.path.join(d, n))
        except OSError:
            continue
        out.append({"name": n, "bytes": stt.st_size, "mtime": stt.st_mtime,
                    "at": _fmt(stt.st_mtime), "file": os.path.join(d, n)})
    return sorted(out, key=lambda x: x["name"], reverse=True)


def write_snapshot(bundle, dir=None, now=None):
    """یک نسخه می‌نویسد و مسیرش را برمی‌گرداند (هرگز روی نسخهٔ موجود نمی‌نویسد)."""
    d = dir or backup_dir()
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    base = filename(now)
    stem, ext = base[:-len(".json")], ".json"
    name, n = base, 2
    while os.path.exists(os.path.join(d, name)):
        name = "%s-%d%s" % (stem, n, ext)
        n += 1
    p = os.path.join(d, name)
    _write_json(p, bundle if isinstance(bundle, dict) else {})
    return p


def prune(dir=None, keep=None):
    """فقط نسخه‌های قدیمیِ *خودِ اپ* را می‌بُرد → (نگه‌داشته، حذف‌شده، آزادشده).

    کمربندِ ایمنی دو لایه است: `plan_prune` فقط نام‌های معتبر را نامزد می‌کند و
    این‌جا هم پیش از `os.remove` دوباره با `is_backup_name` سنجیده می‌شود.
    """
    d = dir or backup_dir()
    k = _num(keep)
    keep = DEFAULTS["keep"] if k is None else int(k)
    try:
        names = os.listdir(d)
    except Exception:
        return {"kept": [], "deleted": [], "freed": 0}
    kept, doomed = plan_prune(names, keep)
    deleted, freed = [], 0
    for n in doomed:
        if not is_backup_name(n):
            continue
        p = os.path.join(d, n)
        try:
            sz = os.path.getsize(p)
            os.remove(p)
        except OSError:
            continue
        deleted.append(n)
        freed += sz
    return {"kept": kept, "deleted": deleted, "freed": freed}


def snapshot(bundle, dir=None, keep=None, now=None):
    """نوشتن + هرس، در یک قدم (چیزی که زمان‌بند صدا می‌زند)."""
    p = write_snapshot(bundle, dir=dir, now=now)
    pr = prune(dir=dir, keep=keep)
    try:
        size = os.path.getsize(p)
    except OSError:
        size = 0
    return {"ok": True, "file": p, "name": os.path.basename(p), "bytes": size,
            "kept": len(pr["kept"]), "deleted": len(pr["deleted"]),
            "freed": pr["freed"], "deleted_names": pr["deleted"]}


# ═══════════════════════════════════════════════════════════════════
#  خودآزمونِ سبک (بدونِ دست‌زدن به دادهٔ واقعی)
# ═══════════════════════════════════════════════════════════════════
def main():
    import tempfile
    d = tempfile.mkdtemp(prefix="pf_ab_selftest_")
    try:
        fake = {"kind": "pipfound-backup", "version": 1}
        r1 = snapshot(fake, dir=d, keep=2, now=datetime.datetime(2026, 9, 20, 10, 0, 0))
        print("نوشتن:", r1["name"], r1["bytes"], "بایت")
        for h in range(11, 14):
            snapshot(fake, dir=d, keep=2, now=datetime.datetime(2026, 9, 20, h, 0, 0))
        left = list_backups(d)
        print("نگه‌داشته:", [b["name"] for b in left])
        assert len(left) == 2, "نگه‌داشتِ نسخه‌ها کار نکرد"
        with open(os.path.join(d, "یادداشت.txt"), "w") as f:
            f.write("x")
        prune(dir=d, keep=1)
        assert os.path.exists(os.path.join(d, "یادداشت.txt")), "فایلِ ناشناخته حذف شد!"
        print("✅ autobackup سالم است")
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
