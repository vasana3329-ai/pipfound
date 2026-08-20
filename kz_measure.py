#!/usr/bin/env python3
"""اندازه‌گیریِ فعالیتِ کیل‌زونِ نیویورک روی دیتای ۱ دقیقه.

ادعای کاربر: ساعتِ ۹–۱۰ نیویورک بزرگ‌ترین سفارش‌ها/حرکت‌ها را دارد.
می‌سنجیم: به‌ازای هر ساعتِ ET، میانگینِ رِنجِ کندلِ ۱m، میانگینِ بدنه،
و اینکه های/لوِ روز چند بار در آن ساعت شکل می‌گیرد. داده، نه حدس.
"""
import sys, datetime, collections
sys.path.insert(0, "/Users/valiazadi/.hermes/skills/trading/smc-ict-analysis/scripts")
import smc_engine as E

SYM = sys.argv[1] if len(sys.argv) > 1 else "PAXGUSDT"
src, sym, disp, bars = E.fetch(SYM, "1m", 8000)

def et(ts):
    dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    off = 4 if E._is_us_dst(dt) else 5
    return dt - datetime.timedelta(hours=off)

# گروه‌بندیِ کندل‌ها بر اساسِ ساعتِ ET و بر اساسِ روزِ ET
by_hour = collections.defaultdict(lambda: {"n": 0, "range": 0.0, "body": 0.0})
by_day = collections.defaultdict(list)  # روزِ ET -> [(hour, high, low, bar)]
for b in bars:
    e = et(b["t"])
    h = e.hour
    rng = b["h"] - b["l"]
    body = abs(b["c"] - b["o"])
    by_hour[h]["n"] += 1
    by_hour[h]["range"] += rng
    by_hour[h]["body"] += body
    by_day[e.date()].append((h, b["h"], b["l"], b))

price = bars[-1]["c"]
def pct(x):
    return round(x / price * 100, 4)

print(f"نماد: {disp}  ({src})  |  {len(bars)} کندلِ ۱m  |  قیمتِ مرجع: {round(price,2)}")
print(f"بازه: {et(bars[0]['t']).date()} تا {et(bars[-1]['t']).date()}")
print("=" * 68)
print("ساعتِ ET | #کندل | میانگینِ رِنج٪ | میانگینِ بدنه٪ | نسبت به میانگینِ کل")
print("-" * 68)
# میانگینِ کلیِ رِنج برای نرمال‌سازی
tot_n = sum(v["n"] for v in by_hour.values())
tot_range = sum(v["range"] for v in by_hour.values())
avg_all = tot_range / tot_n if tot_n else 0
rows = []
for h in range(24):
    v = by_hour.get(h)
    if not v or v["n"] == 0:
        continue
    ar = v["range"] / v["n"]
    ab = v["body"] / v["n"]
    ratio = ar / avg_all if avg_all else 0
    rows.append((h, v["n"], ar, ab, ratio))
for h, n, ar, ab, ratio in rows:
    star = " ◀◀◀" if ratio >= 1.25 else (" ◀" if ratio >= 1.10 else "")
    print(f"  {h:02d}:00  | {n:5d} | {pct(ar):>10} | {pct(ab):>11} | {ratio:.2f}×{star}")

# کدام ساعت بیشترین رِنج را دارد؟
rows_sorted = sorted(rows, key=lambda r: r[4], reverse=True)
print("=" * 68)
print("پرتحرک‌ترین ساعت‌های ET (بر اساسِ میانگینِ رِنجِ کندل):")
for h, n, ar, ab, ratio in rows_sorted[:5]:
    print(f"  {h:02d}:00 ET  →  {ratio:.2f}× میانگین  ({pct(ar)}٪ رِنج)")

# های/لوِ روز در کدام ساعتِ ET شکل می‌گیرد؟ (لیکوئیدیتیِ روز کجا ساخته/زده می‌شود)
hod_hour = collections.Counter()  # ساعتِ high-of-day
lod_hour = collections.Counter()  # ساعتِ low-of-day
for day, items in by_day.items():
    if len(items) < 60:   # روزِ ناقص رد شود
        continue
    hi_item = max(items, key=lambda x: x[1])
    lo_item = min(items, key=lambda x: x[2])
    hod_hour[hi_item[0]] += 1
    lod_hour[lo_item[0]] += 1
ndays = sum(1 for d, it in by_day.items() if len(it) >= 60)
print("=" * 68)
print(f"در {ndays} روزِ کامل — های/لوِ روز در کدام ساعتِ ET بیشتر شکل می‌گیرد:")
print("  (این یعنی لیکوئیدیتیِ روز کجا ساخته یا زده می‌شود)")
print("  --- سقفِ روز (buyside) ---")
for h, c in sorted(hod_hour.items(), key=lambda x: -x[1])[:6]:
    print(f"    {h:02d}:00 ET → {c} بار ({round(c/ndays*100)}٪ روزها)")
print("  --- کفِ روز (sellside) ---")
for h, c in sorted(lod_hour.items(), key=lambda x: -x[1])[:6]:
    print(f"    {h:02d}:00 ET → {c} بار ({round(c/ndays*100)}٪ روزها)")
