#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""نگهبانِ بازگشتِ خودکار — آخرین خطِ دفاعِ سلامتِ کد.

اگر `selfcheck` چند بارِ پشت‌سرهم رد شد، main به **آخرین کامیتِ سبزِ CI** برمی‌گردد —
از راهِ شاخه → PR → چکِ سبز → ادغام، چون ruleset پوشِ مستقیم به main را می‌بندد.

چرخه‌ی هر دور:
  ۱) `python3 selfcheck.py --json` روی همین ریپو اجرا می‌شود.
  ۲) سالم ← شمارنده‌ی شکستِ پیاپی صفر می‌شود. خراب ← +۱ و ثبتِ جزئیات.
  ۳) رسیدن به آستانه (پیش‌فرض ۳ بار) و برقرار بودنِ **همه‌ی** شروط:
       · worktree تمیز              (هیچ کارِ ذخیره‌نشده‌ای قربانی نشود)
       · fetch از origin ممکن       (بدونِ شبکه، تصمیمِ برگشت نمی‌گیریم)
       · HEAD روی main است          (نه شاخه‌ی دیگر، نه detached)
       · HEAD ≠ آخرینِ سبز          (اگر main خودش سبز است، شکست «محیطی» است نه کدی)
       · سبزِ آخر، پدرِ HEAD است     (merge-base؛ تاریخچه‌ی عوض‌شده برگشت نمی‌خورد)
       · فاصله ≤ MAX_COMMITS        (پیش‌فرض ۱۰؛ بیشتر یعنی تصمیمِ انسانی لازم است)
       · PRِ برگشتِ بازی از قبل باز نیست (ضدِ تکرار)
     آنگاه در یک **git-worktreeِ جدا** (فایل‌های زنده‌ی سرور اصلاً دست نمی‌خورند):
       `git revert --no-commit <سبز>..HEAD` → یک کامیت → push شاخه → PR
  ۴) با auto-merge: `gh pr merge --squash --auto` — گیتهاب بعد از سبز شدنِ چکِ همان
     PR (که کدِ برگشتیِ سالم است، پس سبز می‌شود) خودش ادغام می‌کند؛ نگهبان تا
     MERGED منتظر می‌ماند و در پایان `git pull --ff-only` می‌کند — سرورِ محلی هم
     با ری‌استارتِ خودکارِ خودش (app.py) روی کدِ سالم می‌رود. حلقه بسته می‌شود.

اجرا:
  python3 selfcheck_watcher.py              # یک دور
  python3 selfcheck_watcher.py --loop 300   # دیمان (برای launchd)
  python3 selfcheck_watcher.py --status     # وضعیتِ شمارنده و آخرین اقدام
  python3 selfcheck_watcher.py --reset      # صفر کردنِ شمارنده
  فلگ‌ها: --dry-run (فقط نقشه، بدونِ هیچ نوشتنی در گیت) · --no-pr (فقط تا کامیتِ محلیِ برگشت — برای تست)

نصبِ دوره‌ای (launchd):
  launchctl submit -l pipfound-selfcheck-watcher -- /bin/sh -c \
    'exec python3 -u <scripts>/selfcheck_watcher.py --loop 300 >> <log> 2>&1'

هوک‌های تست/محیط:
  PIPFOUND_WATCH_THRESHOLD (۳) · PIPFOUND_WATCH_MAX_COMMITS (۱۰) ·
  PIPFOUND_WATCH_AUTO_MERGE (۱) · PIPFOUND_WATCH_MERGE_TIMEOUT (۶۰۰ ثانیه) ·
  PIPFOUND_WATCH_GREEN_SHA (به‌جای gh — برای تست) · PIPFOUND_WATCH_STATE (مسیرِ فایلِ وضعیت)
فقط stdlib؛ خروجی: ۰ سالم، ۱ خطایِ غیرمنتظره.
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback

ROOT_DEFAULT = os.path.dirname(os.path.abspath(__file__))
HOME_DIR = os.path.join(os.path.expanduser("~"), "pipfound")
BRANCH_PREFIX = "revert/selfcheck-"
WORKFLOW = "selfcheck.yml"
MARKER = "<!-- pipfound-selfcheck-watcher -->"


def _env(name, default):
    try:
        v = os.environ.get(name, "").strip()
        return v if v else default
    except Exception:
        return default


def _now_iso():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _out(msg):
    print(msg, flush=True)


# ─────────────────────────── وضعیت (state) ───────────────────────────

def _state_path():
    return _env("PIPFOUND_WATCH_STATE", os.path.join(HOME_DIR, "selfcheck_watcher.json"))


def _state_read():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"consecutive_failures": 0, "history": []}


def _state_write(st):
    fp = _state_path()
    try:
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        tmp = fp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, fp)
    except Exception as e:
        _out("⚠️ ثبتِ وضعیتِ نگهبان ناموفق: %s" % e)


def _hist_add(st, entry, cap=20):
    st.setdefault("history", []).append(entry)
    st["history"] = st["history"][-cap:]


# ─────────────────────────── ابزارِ اجرا ───────────────────────────

def sh(args, cwd, timeout=120, extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        p = subprocess.run(args, cwd=cwd, env=env, timeout=timeout,
                           capture_output=True, text=True)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except Exception as e:
        return 127, "", str(e)


def _git_identity_env(root):
    """اگر هویتِ گیت تنظیم نیست (مثلاً رانرِ CI)، هویتِ خودِ نگهبان را بگذار."""
    rc, out, _ = sh(["git", "config", "user.email"], cwd=root)
    if rc == 0 and out.strip():
        return None
    return {
        "GIT_AUTHOR_NAME": "pipfound-watcher",
        "GIT_AUTHOR_EMAIL": "pipfound-watcher@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "pipfound-watcher",
        "GIT_COMMITTER_EMAIL": "pipfound-watcher@users.noreply.github.com",
    }


# ─────────────────────────── سلف‌چک ───────────────────────────

def selfcheck_once(root):
    """selfcheck را اجرا می‌کند؛ خروجیِ ساختاریافته برمی‌گرداند (هرگز exception نمی‌دهد)."""
    rc, out, err = sh([sys.executable, "-u", "selfcheck.py", "--json"],
                      cwd=root, timeout=300)
    rep = None
    try:
        rep = json.loads(out)
    except Exception:
        i = out.rfind("\n{")
        if i >= 0:
            try:
                rep = json.loads(out[i + 1:])
            except Exception:
                rep = None
    ok = (rc == 0 and isinstance(rep, dict) and rep.get("ok") is True)
    problems = (rep or {}).get("problems") or []
    return {"ok": ok, "rc": rc, "problems": [str(p) for p in problems][:8],
            "crash": not isinstance(rep, dict), "err": (err or "")[-400:]}


# ─────────────────────────── آخرینِ سبز ───────────────────────────

def green_sha(root):
    """آخرین کامیتِ سبزِ CI روی main — یا از env (تست) یا از gh."""
    explicit = _env("PIPFOUND_WATCH_GREEN_SHA", "")
    if explicit:
        return explicit, "env"
    rc, out, err = sh(["gh", "run", "list", "--workflow", WORKFLOW,
                       "--branch", "main", "--status", "success",
                       "--limit", "5", "--json", "headSha,createdAt"],
                      cwd=root, timeout=60)
    if rc != 0 or not out.strip():
        return None, "gh ناموفق: %s" % ((err or out).strip()[:200] or "بدونِ خروجی")
    try:
        runs = json.loads(out)
    except Exception:
        return None, "خروجیِ gh قابلِ تجزیه نبود"
    runs.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
    if not runs:
        return None, "هیچ اجرای سبزی روی main ثبت نشده"
    return runs[0].get("headSha"), "gh"


# ─────────────────────────── شروطِ برگشت ───────────────────────────

def collect_guards(root, no_pr):
    """فهرستِ شروط؛ هرکدام (نام، برقرار؟، توضیح). فقط اولینِ برقرارنشده گزارشِ قطعی است."""
    g = []

    # فقط تغییرِ فایل‌های ردیابیشده مسدود می‌کند؛ untracked (مثل لاگ/کش) به revert
    # ربطی ندارد چون git revert اصلاً دستش را به untracked نمی‌زند.
    rc, out, _ = sh(["git", "status", "--porcelain"], cwd=root)
    tracked_dirty = rc != 0 or any(not ln.startswith("??") for ln in out.splitlines())
    g.append(("worktree تمیز", not tracked_dirty,
              "تغییرِ ذخیره‌نشده روی فایل‌های ردیابیشده هست — revert نمی‌کنم (کارِ کسی از بین نمی‌رود)"))

    rc, out, err = sh(["git", "fetch", "origin", "main", "--quiet"], cwd=root, timeout=90)
    g.append(("دسترسی به origin", rc == 0,
              "fetch ناموفق: %s — بدونِ شبکه تصمیمِ برگشت نمی‌گیرم" % (err or "").strip()[:150]))

    rc, out, _ = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    branch = out.strip() if rc == 0 else "?"
    g.append(("HEAD روی main", branch == "main",
              "HEAD روی %s است — فقط از main برگشت معنا دارد" % branch))

    green, src = green_sha(root)
    g.append(("آخرینِ سبز پیدا شد", bool(green),
              "آخرین اجرای سبزِ CI پیدا نشد (%s)" % src))
    if not green:
        return g, None, None

    rc, head, _ = sh(["git", "rev-parse", "HEAD"], cwd=root)
    head = head.strip() if rc == 0 else "?"
    g.append(("HEAD ≠ سبزِ آخر", head != green,
              "HEAD خودش همان آخرینِ سبز (%s) است — شکست، محیطی/محلی است نه کدی؛ revert نمی‌کنم"
              % green[:8]))

    if head != green and head != "?":
        rc, _, _ = sh(["git", "merge-base", "--is-ancestor", green, head], cwd=root)
        g.append(("سبزِ آخر پدرِ HEAD است", rc == 0,
                  "سبزِ آخر (%s) پدرِ HEAD نیست — تاریخچه عوض شده؛ تصمیمِ انسانی لازم است" % green[:8]))
        rc, out, _ = sh(["git", "rev-list", "--count", "%s..%s" % (green, head)], cwd=root)
        try:
            n = int(out.strip())
        except Exception:
            n = -1
        maxn = int(_env("PIPFOUND_WATCH_MAX_COMMITS", "10"))
        g.append(("فاصله ≤ %d کامیت" % maxn, 0 <= n <= maxn,
                  "فاصله‌ی سبز تا HEAD برابر %s کامیت است — بیشتر از حدِ مجاز؛ دستی بررسی کن" % (n if n >= 0 else "؟")))

    if not no_pr:
        rc, out, err = sh(["gh", "pr", "list", "--state", "open",
                           "--json", "number,headRefName"], cwd=root, timeout=60)
        if rc == 0:
            try:
                opens = json.loads(out)
                dup = [p for p in opens
                       if str(p.get("headRefName", "")).startswith(BRANCH_PREFIX)]
                g.append(("PRِ برگشتِ بازی باز نیست", not dup,
                          "PRِ بازِ قبلی: #%s روی %s — منتظرِ همان می‌مانم"
                          % (", #".join(str(p["number"]) for p in dup),
                             ", ".join(p.get("headRefName", "") for p in dup))))
            except Exception:
                pass
    return g, green, head


# ─────────────────────────── عملِ برگشت ───────────────────────────

def _wt_cleanup(root, wt):
    sh(["git", "worktree", "remove", "--force", wt], cwd=root, timeout=60)


def build_revert(root, green, head, n_commits, problems, push=True):
    """در worktreeِ جدا برگشت می‌سازد (و اگر push=True، پوش می‌کند).

    خروجی: (نامِ شاخه، خطا|None). فایل‌های زنده‌ی سرور هیچ‌وقت دست نمی‌خورند:
    همه‌چیز در git-worktreeِ موقت اتفاق می‌افتد.
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = BRANCH_PREFIX + stamp
    wt = tempfile.mkdtemp(prefix="pf_revert_")
    ident = _git_identity_env(root)

    rc, out, err = sh(["git", "worktree", "prune"], cwd=root, timeout=60)
    rc, out, err = sh(["git", "worktree", "add", "-b", branch, wt, head],
                      cwd=root, timeout=120)
    if rc != 0:
        _wt_cleanup(root, wt)
        return None, "worktree ساخته نشد: %s" % (err or out).strip()[:200]

    rc, out, err = sh(["git", "revert", "--no-commit", "%s..%s" % (green, head)],
                      cwd=wt, timeout=120)
    if rc != 0:
        sh(["git", "revert", "--abort"], cwd=wt)
        _wt_cleanup(root, wt)
        return None, "revert تضاد داشت: %s" % (err or out).strip()[:200]

    rc, out, err = sh(["git", "commit", "-m", _revert_msg(green, head, n_commits, problems)],
                      cwd=wt, extra_env=ident, timeout=60)
    if rc != 0:
        _wt_cleanup(root, wt)
        return None, "کامیتِ برگشت ناموفق: %s" % (err or out).strip()[:200]

    # اثباتِ درستی: درختِ برگشتی باید دقیقاً = درختِ آخرینِ سبز باشد
    rc, out, _ = sh(["git", "diff", "--quiet", green, "HEAD"], cwd=wt, timeout=60)
    if rc != 0:
        _wt_cleanup(root, wt)
        return None, "درختِ برگشتی با درختِ سبز یکی نشد — بی‌خیالِ پوش"

    if push:
        rc, out, err = sh(["git", "push", "-u", "origin", branch], cwd=wt, timeout=180)
        if rc != 0:
            _wt_cleanup(root, wt)
            return None, "پوشِ شاخه‌ی برگشت ناموفق: %s" % (err or out).strip()[:200]

    _wt_cleanup(root, wt)
    return branch, None


def _revert_msg(green, head, n_commits, problems):
    probs = " · ".join(problems[:4])[:500] if problems else "—"
    return (
        "♻️ revert: بازگشتِ خودکار به آخرین کامیتِ سبزِ CI (%s)\n\n"
        "selfcheck چند بارِ پشت‌سرهم رد شد؛ main به آخرین وضعیتِ سبز برمی‌گردد.\n"
        "بازه‌ی برگشتی: %s..%s (%d کامیت)\n"
        "مشکلاتِ گزارش‌شده: %s\n"
        "ساخته‌شده توسطِ selfcheck_watcher.py در %s\n%s"
        % (green[:8], green[:8], head[:8], n_commits, probs, _now_iso(), MARKER)
    )


def create_pr(root, branch, green, head, n_commits, problems):
    title = ("♻️ revertِ خودکار: بازگشتِ main به سبزِ آخر (%s) — selfcheck پیاپی رد شد"
             % green[:8])
    probs = "\n".join("- %s" % p for p in problems[:8]) if problems else "- —"
    body = (
        "%s\n**نگهبانِ خودکار** — selfcheck چند بارِ پشت‌سرهم رد شد و همه‌ی شروطِ امنیت\n"
        "(worktree تمیز، سبزِ آخر پدرِ HEAD، فاصله‌ی مجاز) برقرار بود.\n\n"
        "- بازگشت به: `%s`\n- بازه: `%s..%s` (%d کامیت)\n- درختِ برگشتی = درختِ سبز (تأییدشده با diff)\n\n"
        "**مشکلاتِ selfcheck:**\n%s\n\n"
        "این PR با `--auto` تنظیم شده: بعد از سبز شدنِ چک، خودکار ادغام می‌شود.\n%s"
        % (MARKER, green[:8], green[:8], head[:8], n_commits, probs, MARKER)
    )
    rc, out, err = sh(["gh", "pr", "create", "--base", "main", "--head", branch,
                       "--title", title, "--body", body], cwd=root, timeout=120)
    if rc != 0:
        return None, "ساختِ PR ناموفق: %s" % (err or out).strip()[:300]
    url = out.strip().splitlines()[-1].strip() if out.strip() else ""
    return url, None


def wait_merge(root, branch, timeout_s):
    """تا ادغامِ خودکار منتظر می‌ماند. خروجی: (merged؟، url، پیام)."""
    deadline = time.time() + timeout_s
    url = ""
    while time.time() < deadline:
        rc, out, err = sh(["gh", "pr", "view", branch, "--json", "state,url"],
                          cwd=root, timeout=60)
        if rc == 0:
            try:
                j = json.loads(out)
                url = j.get("url") or url
                st = (j.get("state") or "").upper()
                if st == "MERGED":
                    return True, url, "ادغام شد"
                if st == "CLOSED":
                    return False, url, "PR بسته شد (بدونِ ادغام) — دستی بررسی کن"
            except Exception:
                pass
        time.sleep(15)
    return False, url, "مهلتِ انتظار تمام شد — auto-merge روی گیتهاب فعال ماند؛ دورِ بعدِ نگهبان پیگیری می‌کند"


# ─────────────────────────── یک دورِ کامل ───────────────────────────

def pass_once(root, dry=False, no_pr=False):
    st = _state_read()
    thr = int(_env("PIPFOUND_WATCH_THRESHOLD", "3"))

    rep = selfcheck_once(root)
    if rep["ok"]:
        st["consecutive_failures"] = 0
        st["last_ok_at"] = _now_iso()
        st["last_problems"] = []
        _hist_add(st, {"at": _now_iso(), "result": "ok"})
        _state_write(st)
        _out("✅ [%s] selfcheck سالم — شمارنده‌ی شکست صفر شد" % _now_iso())
        return 0

    n = int(st.get("consecutive_failures", 0)) + 1
    st["consecutive_failures"] = n
    st["last_failure_at"] = _now_iso()
    st["last_problems"] = rep["problems"]
    _hist_add(st, {"at": _now_iso(), "result": "fail", "n": n,
                   "crash": rep["crash"],
                   "problems": rep["problems"][:4]})
    _state_write(st)

    _out("❌ [%s] selfcheck رد شد (بارِ پیاپی: %d/%d)%s"
         % (_now_iso(), n, thr, " — کرشِ کامل، بدونِ JSON" if rep["crash"] else ""))
    for p in rep["problems"]:
        _out("   · %s" % p)
    if rep["crash"] and rep["err"]:
        _out("   · stderr: %s" % rep["err"][:200])
    if n < thr:
        _out("   تا آستانه‌ی %d، فقط شمرده می‌شود." % thr)
        return 0

    # آستانه پر شد → شروطِ امنیت
    _out("🚨 آستانه پر شد — بررسیِ شروطِ برگشت:")
    guards, green, head = collect_guards(root, no_pr)
    blocked = None
    for name, okv, why in guards:
        if okv:
            _out("   ✓ %s" % name)
        else:
            blocked = (name, why)
            _out("   ✗ %s — %s" % (name, why))
            break
    if blocked:
        _out("↩️ برگشت انجام نمی‌شود: %s" % blocked[1])
        _hist_add(st, {"at": _now_iso(), "result": "blocked", "guard": blocked[0]})
        _state_write(st)
        return 0

    if dry:
        _out("🏜 dry-run — نقشه: برگشتِ %s..%s در شاخه‌ی %s* + PR + auto-merge (هیچ‌چیز اجرا نشد)"
             % (green[:8], head[:8], BRANCH_PREFIX))
        return 0

    rc, out, _ = sh(["git", "rev-list", "--count", "%s..%s" % (green, head)], cwd=root)
    try:
        n_commits = int(out.strip())
    except Exception:
        n_commits = 0

    _out("♻️ ساختِ برگشت: %s..%s (%d کامیت) …" % (green[:8], head[:8], n_commits))
    branch, err = build_revert(root, green, head, n_commits, rep["problems"],
                               push=not no_pr)
    if err:
        _out("⚠️ %s — دستی بررسی کن." % err)
        _hist_add(st, {"at": _now_iso(), "result": "error", "detail": err[:200]})
        _state_write(st)
        return 1
    _out("   شاخه‌ی %s ساخته شد (درخت = درختِ سبز، تأییدشده)" % branch)

    if no_pr:
        st["last_action"] = {"at": _now_iso(), "kind": "local-revert",
                             "branch": branch, "green": green[:8], "head": head[:8]}
        _hist_add(st, {"at": _now_iso(), "result": "local-revert", "branch": branch})
        _state_write(st)
        _out("🏜 no-pr — تا کامیتِ محلیِ برگشت پیش رفتیم؛ پوش/PR انجام نشد.")
        return 0

    url, err = create_pr(root, branch, green, head, n_commits, rep["problems"])
    if err:
        _out("⚠️ %s — شاخه‌ی %s پوش شده؛ PR را دستی باز کن." % (err, branch))
        _hist_add(st, {"at": _now_iso(), "result": "error", "detail": err[:200],
                       "branch": branch})
        _state_write(st)
        return 1
    _out("   PR: %s" % url)

    auto = _env("PIPFOUND_WATCH_AUTO_MERGE", "1") not in ("0", "false", "no", "off")
    if not auto:
        st["last_action"] = {"at": _now_iso(), "kind": "pr-open", "url": url,
                             "branch": branch}
        _hist_add(st, {"at": _now_iso(), "result": "pr-open", "url": url})
        _state_write(st)
        _out("   auto-merge خاموش است — بعد از سبز شدنِ چک، دستی ادغام کن.")
        return 0

    rc, out, err = sh(["gh", "pr", "merge", branch, "--squash", "--auto", "--delete-branch"],
                      cwd=root, timeout=120)
    if rc != 0:
        _out("⚠️ تنظیمِ auto-merge ناموفق: %s — PR باز است؛ دستی ادغام کن."
             % (err or out).strip()[:200])

    merged, url2, msg = wait_merge(root, branch, int(_env("PIPFOUND_WATCH_MERGE_TIMEOUT", "600")))
    _out("   %s" % msg)
    if merged:
        rc, out, err = sh(["git", "pull", "--ff-only"], cwd=root, timeout=120)
        if rc == 0:
            _out("✅ main به‌روز شد (%s) — سرور با ری‌استارتِ خودکارِ خودش روی کدِ سالم می‌رود."
                 % out.strip().splitlines()[-1] if out.strip() else "✅ main به‌روز شد.")
        else:
            _out("⚠️ pull ناموفق: %s — دستی `git pull` کن." % (err or out).strip()[:200])
        sh(["git", "branch", "-D", branch], cwd=root)
        st["consecutive_failures"] = 0
    st["last_action"] = {"at": _now_iso(), "kind": "merged" if merged else "pr-pending",
                         "url": url2 or url, "branch": branch}
    _hist_add(st, {"at": _now_iso(), "result": "merged" if merged else "pr-pending",
                   "url": url2 or url})
    _state_write(st)
    return 0


# ─────────────────────────── CLI ───────────────────────────

def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="نگهبانِ بازگشتِ خودکارِ pipfound")
    ap.add_argument("--root", default=ROOT_DEFAULT)
    ap.add_argument("--loop", nargs="?", const="300", default=None, metavar="SEC",
                    help="دیمان: هر SEC ثانیه یک دور (پیش‌فرض ۳۰۰)")
    ap.add_argument("--once", action="store_true", help="فقط یک دور (پیش‌فرض)")
    ap.add_argument("--dry-run", action="store_true", help="هیچ تغییری در گیت نزن؛ فقط نقشه")
    ap.add_argument("--no-pr", action="store_true", help="تا کامیتِ محلیِ برگشت، بدونِ پوش/PR (تست)")
    ap.add_argument("--status", action="store_true", help="نمایشِ وضعیت")
    ap.add_argument("--reset", action="store_true", help="صفر کردنِ شمارنده")
    a = ap.parse_args()
    root = os.path.abspath(a.root)

    if a.status:
        st = _state_read()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    if a.reset:
        st = _state_read()
        st["consecutive_failures"] = 0
        st["reset_at"] = _now_iso()
        _state_write(st)
        _out("↺ شمارنده صفر شد.")
        return 0

    # قفلِ باینری: دو نمونه‌ی همزمان نباید با هم بجنگند
    lock_fp = _state_path() + ".lock"
    os.makedirs(os.path.dirname(lock_fp), exist_ok=True)
    lock = open(lock_fp, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _out("⏳ نگهبانِ دیگری همین حالا در جریان است — خروج.")
        return 0

    interval = None
    if a.loop is not None:
        try:
            interval = max(30, int(a.loop))
        except Exception:
            interval = 300
        _out("👁 نگهبانِ بازگشتِ خودکار: دیمان با دوره‌ی %d ثانیه (ریپو: %s)" % (interval, root))

    while True:
        try:
            pass_once(root, dry=a.dry_run, no_pr=a.no_pr)
        except Exception:
            traceback.print_exc()
            return 1
        if interval is None:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
