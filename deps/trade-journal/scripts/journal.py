#!/usr/bin/env python3
"""
Trade Journal — standard SMC/ICT trade logging + auto stats.
Pure stdlib. Stores trades as CSV.

Default journal file: ~/Desktop/trading-journal/journal.csv  (override with --file)

Commands:
  add     -> append a trade
  list    -> show trades (optionally filter by symbol/result)
  stats   -> win-rate, avg RR, expectancy, best/worst, mistakes breakdown
  close   -> set result/exit on an open trade by id

Examples:
  python3 journal.py add --symbol XAUUSD --direction long --session "NY AM" \
      --htf-bias up --entry 4390 --sl 4374 --tp 4432 --rr 2.5 \
      --setup "H4 discount + M15 CHoCH" --poi "M15 OB 4390" \
      --reason "sweep EQL 4391 then bullish CHoCH" --risk-pct 1 --status open

  python3 journal.py close --id 3 --result win --exit 4432 --realized-r 2.5 --lesson "waited for pullback, worked"
  python3 journal.py list
  python3 journal.py list --symbol XAUUSD --result win
  python3 journal.py stats
"""
import argparse, csv, os, sys, datetime, json

DEFAULT_FILE = os.path.expanduser("~/Desktop/trading-journal/journal.csv")  # مسیرِ قدیمی (سازگاری)


def app_file():
    """فایلِ دفترِ همان‌جایی که اپِ pipfound می‌نویسد (بیرونِ Desktop/Documents)."""
    return os.path.expanduser("~/pipfound/journal.csv")


def default_file():
    """ترتیبِ انتخابِ فایلِ دفتر: env → فایلِ اپ (اگر هست) → مسیرِ قدیمیِ Desktop.

    env: `PIPFOUND_JOURNAL_CSV` (فایلِ دقیق) یا `PIPFOUND_JOURNAL_DIR` (پوشه).
    دلیلِ ترجیحِ فایلِ اپ: جاب‌های launchd اجازه‌ی نوشتن در Desktop/Documents را ندارند.
    """
    f = os.environ.get("PIPFOUND_JOURNAL_CSV")
    if f:
        return os.path.expanduser(f)
    d = os.environ.get("PIPFOUND_JOURNAL_DIR")
    if d:
        return os.path.join(os.path.expanduser(d), "journal.csv")
    return app_file() if os.path.exists(app_file()) else DEFAULT_FILE

FIELDS = ["id","datetime","symbol","direction","session","tf","htf_bias",
          "entry","sl","tp","rr","risk_pct","setup","poi","reason",
          "status","result","exit","realized_r","mistake","lesson","notes"]

def ensure(path):
    d=os.path.dirname(path)
    if d and not os.path.exists(d): os.makedirs(d, exist_ok=True)
    if not os.path.exists(path):
        with open(path,"w",newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def read_all(path):
    ensure(path)
    with open(path,newline="") as f:
        return list(csv.DictReader(f))

def write_all(path, rows):
    with open(path,"w",newline="") as f:
        w=csv.DictWriter(f, fieldnames=FIELDS); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in FIELDS})

def next_id(rows):
    ids=[int(r["id"]) for r in rows if r.get("id","").isdigit()]
    return str(max(ids)+1) if ids else "1"

def cmd_add(a):
    rows=read_all(a.file)
    row={k:"" for k in FIELDS}
    row.update({
        "id":next_id(rows),
        "datetime":a.datetime or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "symbol":a.symbol.upper(),"direction":a.direction,"session":a.session or "",
        "tf":a.tf or "","htf_bias":a.htf_bias or "",
        "entry":a.entry or "","sl":a.sl or "","tp":a.tp or "","rr":a.rr or "",
        "risk_pct":a.risk_pct or "","setup":a.setup or "","poi":a.poi or "",
        "reason":a.reason or "","status":a.status or "open",
        "result":a.result or "","exit":a.exit or "","realized_r":a.realized_r or "",
        "mistake":a.mistake or "","lesson":a.lesson or "","notes":a.notes or "",
    })
    rows.append(row); write_all(a.file, rows)
    print(json.dumps({"added":row["id"],"symbol":row["symbol"],"file":a.file},ensure_ascii=False))

def cmd_close(a):
    rows=read_all(a.file); found=None
    for r in rows:
        if r["id"]==str(a.id):
            r["status"]="closed"
            if a.result: r["result"]=a.result
            if a.exit is not None: r["exit"]=str(a.exit)
            if a.realized_r is not None: r["realized_r"]=str(a.realized_r)
            if a.mistake: r["mistake"]=a.mistake
            if a.lesson: r["lesson"]=a.lesson
            found=r; break
    if not found: print(json.dumps({"error":f"id {a.id} not found"})); return
    write_all(a.file, rows)
    print(json.dumps({"closed":a.id,"result":found["result"],"realized_r":found["realized_r"]},ensure_ascii=False))

def cmd_list(a):
    rows=read_all(a.file)
    if a.symbol: rows=[r for r in rows if r["symbol"]==a.symbol.upper()]
    if a.result: rows=[r for r in rows if r["result"]==a.result]
    if a.status: rows=[r for r in rows if r["status"]==a.status]
    if not rows: print("(دفتر خالی است یا فیلتری مطابقت نداشت)"); return
    for r in rows:
        res=r["result"] or r["status"]
        rr=r["realized_r"] or r["rr"]
        print(f"#{r['id']:>3} {r['datetime']:16} {r['symbol']:8} {r['direction']:5} "
              f"{res:7} R={rr:>5} | {r['setup'][:40]}")

def _f(x):
    try: return float(x)
    except: return None

def cmd_stats(a):
    rows=[r for r in read_all(a.file) if r["status"]=="closed" and r["result"]]
    if not rows:
        print(json.dumps({"note":"هیچ معامله‌ی بسته‌شده‌ای برای آمار نیست"},ensure_ascii=False)); return
    n=len(rows)
    wins=[r for r in rows if r["result"]=="win"]
    losses=[r for r in rows if r["result"]=="loss"]
    be=[r for r in rows if r["result"] in ("be","breakeven")]
    wr=len(wins)/n*100
    rs=[_f(r["realized_r"]) for r in rows if _f(r["realized_r"]) is not None]
    avg_r=sum(rs)/len(rs) if rs else 0
    win_r=[_f(r["realized_r"]) for r in wins if _f(r["realized_r"]) is not None]
    loss_r=[_f(r["realized_r"]) for r in losses if _f(r["realized_r"]) is not None]
    avg_win=sum(win_r)/len(win_r) if win_r else 0
    avg_loss=sum(loss_r)/len(loss_r) if loss_r else 0
    # expectancy per trade in R
    p=len(wins)/n; q=len(losses)/n
    expectancy=(p*avg_win)+(q*avg_loss) if rs else 0
    total_r=sum(rs)
    # mistakes breakdown
    mistakes={}
    for r in rows:
        m=r.get("mistake","").strip()
        if m: mistakes[m]=mistakes.get(m,0)+1
    # per symbol
    bysym={}
    for r in rows:
        s=r["symbol"]; bysym.setdefault(s,{"n":0,"w":0})
        bysym[s]["n"]+=1
        if r["result"]=="win": bysym[s]["w"]+=1
    out={
        "trades_closed":n,"wins":len(wins),"losses":len(losses),"breakeven":len(be),
        "win_rate_pct":round(wr,1),
        "avg_R":round(avg_r,2),"avg_win_R":round(avg_win,2),"avg_loss_R":round(avg_loss,2),
        "expectancy_R_per_trade":round(expectancy,3),
        "total_R":round(total_r,2),
        "per_symbol":{s:{**v,"wr%":round(v["w"]/v["n"]*100,1)} for s,v in bysym.items()},
        "top_mistakes":dict(sorted(mistakes.items(), key=lambda x:-x[1])),
    }
    # verdict
    if expectancy>0.3: verdict="edge مثبت قوی — سیستم را ادامه بده و سایز را ثابت نگه دار."
    elif expectancy>0: verdict="edge مثبت خفیف — کار می‌کند اما اجرای انضباط را سفت کن."
    else: verdict="edge منفی — قبل از ادامه، الگوی اشتباهات بالا را برطرف کن."
    out["verdict"]=verdict
    print(json.dumps(out,indent=2,ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--file",default=None)
    sub=ap.add_subparsers(dest="cmd",required=True)

    p=sub.add_parser("add")
    for opt in ["symbol","direction","session","tf","htf-bias","entry","sl","tp","rr",
                "risk-pct","setup","poi","reason","status","result","exit","realized-r",
                "mistake","lesson","notes","datetime"]:
        p.add_argument("--"+opt, dest=opt.replace("-","_"), default=None)
    p.set_defaults(func=cmd_add)

    p=sub.add_parser("close")
    p.add_argument("--id",required=True)
    p.add_argument("--result",default=None,help="win|loss|be")
    p.add_argument("--exit",default=None)
    p.add_argument("--realized-r",dest="realized_r",default=None)
    p.add_argument("--mistake",default=None)
    p.add_argument("--lesson",default=None)
    p.set_defaults(func=cmd_close)

    p=sub.add_parser("list")
    p.add_argument("--symbol",default=None); p.add_argument("--result",default=None)
    p.add_argument("--status",default=None)
    p.set_defaults(func=cmd_list)

    p=sub.add_parser("stats"); p.set_defaults(func=cmd_stats)

    a=ap.parse_args()
    a.file=os.path.expanduser(a.file) if a.file else default_file()
    a.func(a)

if __name__=="__main__":
    main()
