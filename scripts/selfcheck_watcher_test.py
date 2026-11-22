#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ سرتاسریِ نگهبانِ بازگشتِ خودکار (selfcheck_watcher.py).

این تستِ دروازه‌ای است: نگهبان روی کامیتِ خرابِ main باید main را به آخرین سبزِ CI برگرداند —
ولی **فقط** وقتی شروطِ امنیت برقرارند. اگر روزی کسی شرطی را شُل کند، همین‌جا گرفته می‌شود.

چرا «سندباکس» و نه ریپوی واقعی: برگشت‌دادنِ main واقعی را نمی‌شود در تست تمرین کرد.
پس هر سناریو یک ریپوی تازه در دایرکتوریِ موقت می‌سازد با:
  · یک `origin` بَرِ محلی (بدونِ شبکه)
  · `selfcheck.py` جعلی که با یک فایلِ کنارش روشن/خراب می‌شود
  · `gh` جعلی روی PATH که مثلِ گیت‌هاب رفتار می‌کند (PR می‌سازد، `--auto` را
    واقعاً ادغام می‌کند و شاخه را پاک می‌کند) و هر فراخوانی را لاگ می‌کند
  · `HOME` خالی تا هوکِ هویتِ گیت (نبودِ user.email) هم واقعاً آزموده شود

سناریوها:
  A) زیرِ آستانه فقط می‌شمارد و برنمی‌گرداند؛ سالم شدن دوباره شمارنده را صفر می‌کند.
  B) آستانه پر + تغییرِ ذخیره‌نشده‌ی **ردیابی‌شده** → مسدود (کارِ کسی قربانی نمی‌شود).
  C) آستانه پر + همه‌ی شروط برقرار → شاخه‌ی برگشت، PR، ادغامِ خودکار و pull تا main
     (درختِ برگشتی بایت‌به‌بایت = درختِ آخرین سبز؛ حلقه بسته می‌شود).
  D) HEAD خودش همان سبزِ آخر است → مسدود (شکست محیطی است، نه کدی).
  E) سبزِ آخر پدرِ HEAD نیست (تاریخچه بازنویسی شده) → مسدود.
  F) فاصله بیشتر از حدِّ مجاز → مسدود.
  G) PRِ برگشتِ بازِ قبلی → مسدود (ضدِ تکرار).
  H) `--no-pr` → فقط کامیتِ محلی؛ هیچ پوش/PRی نمی‌سازد.
  I) `--dry-run` → هیچ شاخه‌ای ساخته نمی‌شود.
  J) فایلِ untracked (مثلِ لاگ) کار را نمی‌بندد — `git revert` اصلاً به آن دست نمی‌زند.
  K) کرشِ `selfcheck` بدونِ JSON هم یک شکست شمرده می‌شود (نه استثنا).

اجرا:  python3 selfcheck_watcher_test.py     (خروجی: ۰ سالم، ۱ خراب)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHER = os.path.join(HERE, "selfcheck_watcher.py")
TMPDIRS = []
problems = []
notes = []

SELFCHECK_STUB = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selfcheck جعلیِ سندباکس: رفتارش را از فایلِ .selfcheck_mode می‌خواند."""
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
try:
    mode = open(os.path.join(here, ".selfcheck_mode"), encoding="utf-8").read().strip()
except Exception:
    mode = "ok"
if mode == "ok":
    print(json.dumps({"ok": True, "problems": []}))
    sys.exit(0)
if mode == "crash":
    sys.stderr.write("stub: بدونِ JSON مرد\\n")
    sys.exit(3)
print(json.dumps({"ok": False, "problems": ["کلیدِ عمداً شکسته: #sbBtn گم شده"]}))
sys.exit(2)
'''

GH_STUB = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gh جعلی: فقط همان زیرفرمان‌هایی که نگهبان صدا می‌زند."""
import json, os, subprocess, sys

ORIGIN = os.environ.get("PF_TEST_ORIGIN", "")
LOG = os.environ.get("PF_TEST_GH_LOG", "")
args = sys.argv[1:]


def log(line):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\\n")


log(" | ".join(args))

if args[:2] == ["pr", "list"]:
    print(os.environ.get("PF_TEST_OPEN_PRS", "[]"))
    sys.exit(0)

if args[:2] == ["pr", "create"]:
    print("https://example.invalid/pull/9001")
    sys.exit(0)

if args[:2] == ["pr", "merge"]:
    branch = args[2] if len(args) > 2 else ""
    sha = subprocess.run(["git", "-C", ORIGIN, "rev-parse", "refs/heads/" + branch],
                         capture_output=True, text=True).stdout.strip()
    log("merged_ref %s %s" % (branch, sha))
    if sha:
        # مثلِ گیت‌هاب پس از سبز شدنِ چک: main جلو می‌رود و شاخه پاک می‌شود
        subprocess.run(["git", "-C", ORIGIN, "update-ref", "refs/heads/main", sha])
        subprocess.run(["git", "-C", ORIGIN, "update-ref", "-d", "refs/heads/" + branch])
    sys.exit(0)

if args[:2] == ["pr", "view"]:
    print(json.dumps({"state": os.environ.get("PF_TEST_PR_STATE", "MERGED"),
                      "url": "https://example.invalid/pull/9001"}))
    sys.exit(0)

if args[:2] == ["run", "list"]:
    print("[]")
    sys.exit(0)

sys.exit(0)
'''


def check(ok, msg):
    if ok:
        notes.append("✓ " + msg)
    else:
        problems.append(msg)
    return ok


def _run(args, cwd, env, timeout=180, check_rc=False):
    p = subprocess.run(args, cwd=cwd, env=env, timeout=timeout,
                       capture_output=True, text=True)
    if check_rc and p.returncode != 0:
        problems.append("دستور شکست خورد: %s\n%s\n%s" % (" ".join(args), p.stdout, p.stderr))
    return p


class Sandbox(object):
    """یک ریپوی آزمایشیِ کامل با origin و ghِ جعلی."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="pf_watch_")
        TMPDIRS.append(self.tmp)
        self.origin = os.path.join(self.tmp, "origin.git")
        self.repo = os.path.join(self.tmp, "repo")
        self.bindir = os.path.join(self.tmp, "bin")
        self.home = os.path.join(self.tmp, "home")
        self.state = os.path.join(self.tmp, "state.json")
        self.ghlog = os.path.join(self.tmp, "gh.log")
        self.green = ""
        self.env = self._env()

    # ── زیرساخت ───────────────────────────────────────────────────────────
    def _env(self):
        env = dict(os.environ)
        env["PATH"] = self.bindir + os.pathsep + env.get("PATH", "")
        env["HOME"] = self.home
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        # عمداً هیچ هویتِ گیتی نمی‌گذاریم: باید هوکِ fallback در نگهبان کار کند
        env["GIT_CONFIG_GLOBAL"] = os.path.join(self.home, "empty.gitconfig")
        env["PF_TEST_ORIGIN"] = self.origin
        env["PF_TEST_GH_LOG"] = self.ghlog
        env["PIPFOUND_WATCH_STATE"] = self.state
        env["PIPFOUND_WATCH_GREEN_SHA"] = self.green
        env["PIPFOUND_WATCH_THRESHOLD"] = "3"
        env["PIPFOUND_WATCH_MERGE_TIMEOUT"] = "20"
        env.pop("PIPFOUND_WATCH_MAX_COMMITS", None)
        env.pop("PIPFOUND_WATCH_AUTO_MERGE", None)
        return env

    def setup(self):
        for d in (self.bindir, self.home):
            os.makedirs(d, exist_ok=True)
        open(os.path.join(self.home, "empty.gitconfig"), "w").close()

        with open(os.path.join(self.bindir, "gh"), "w", encoding="utf-8") as f:
            f.write(GH_STUB)
        os.chmod(os.path.join(self.bindir, "gh"), 0o755)

        _run(["git", "init", "--bare", "--initial-branch=main", self.origin],
             self.tmp, self.env, check_rc=True)
        _run(["git", "clone", "--quiet", self.origin, self.repo],
             self.tmp, self.env, check_rc=True)

        # این‌ها باید در ریپو باشند ولی هرگز ردیابی نشوند (وگرنه روشن/خاموش‌کردنشان
        # خودش worktree را کثیف می‌کرد)
        with open(os.path.join(self.repo, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("selfcheck.py\n.selfcheck_mode\n")
        with open(os.path.join(self.repo, "selfcheck.py"), "w", encoding="utf-8") as f:
            f.write(SELFCHECK_STUB)

        self.set_mode("ok")
        self.write("app.py", "V1 = 1\n")
        self.commit("c0: سبزِ آخر (نقطه‌ی بازگشت)")
        self.green = self.rev("HEAD")
        self.env["PIPFOUND_WATCH_GREEN_SHA"] = self.green
        self.push_main()
        return self

    # ── کمک‌کارها ─────────────────────────────────────────────────────────
    def write(self, rel, text):
        with open(os.path.join(self.repo, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def set_mode(self, mode):
        self.write(".selfcheck_mode", mode + "\n")

    def commit(self, msg):
        _run(["git", "add", "-A"], self.repo, self.env, check_rc=True)
        _run(["git", "-c", "user.name=stub", "-c", "user.email=stub@example.invalid",
              "commit", "-q", "-m", msg], self.repo, self.env, check_rc=True)

    def push_main(self):
        _run(["git", "-c", "user.name=stub", "-c", "user.email=stub@example.invalid",
              "push", "--quiet", "-u", "origin", "main"], self.repo, self.env, check_rc=True)

    def rev(self, ref):
        return _run(["git", "rev-parse", ref], self.repo, self.env).stdout.strip()

    def origin_main(self):
        return _run(["git", "-C", self.origin, "rev-parse", "refs/heads/main"],
                    self.tmp, self.env).stdout.strip()

    def origin_refs(self, pattern):
        out = _run(["git", "-C", self.origin, "for-each-ref", "--format=%(refname)",
                    pattern], self.tmp, self.env).stdout
        return [ln.strip() for ln in out.splitlines() if ln.strip()]

    def local_branches(self, pattern):
        out = _run(["git", "branch", "--list", pattern], self.repo, self.env).stdout
        return [ln.strip().lstrip("* ") for ln in out.splitlines() if ln.strip()]

    def gh_calls(self):
        """هر خط = یک فراخوانیِ gh با آرگومان‌های چسبیده با ` | `."""
        if not os.path.exists(self.ghlog):
            return []
        with open(self.ghlog, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]

    def gh_pr_create(self):
        return [c for c in self.gh_calls() if c.startswith("pr | create")]

    def gh_pr_merge(self):
        return [c for c in self.gh_calls() if c.startswith("pr | merge")]

    def state_json(self):
        if not os.path.exists(self.state):
            return {}
        with open(self.state, encoding="utf-8") as f:
            return json.load(f)

    def blocked_guard(self):
        hist = [h for h in self.state_json().get("history", []) if h.get("result") == "blocked"]
        return hist[-1].get("guard", "") if hist else ""

    def run_watcher(self, *args, **envs):
        env = dict(self.env)
        env.update({k: str(v) for k, v in envs.items()})
        return _run([sys.executable, "-u", WATCHER, "--root", self.repo] + list(args),
                    self.tmp, env, timeout=180)

    def fail_times(self, n):
        """n بار شکستِ پیاپی (تا آستانه)؛ خروجیِ آخرین دور برگردانده می‌شود."""
        self.set_mode("fail")
        out = ""
        for _ in range(n):
            out = self.run_watcher().stdout
        return out

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ────────────────────────────── سناریوها ──────────────────────────────

def case_below_threshold():
    """A) زیرِ آستانه فقط می‌شمارد؛ سالم شدن، شمارنده را صفر می‌کند."""
    sb = Sandbox().setup()
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: کامیتِ خراب")
    sb.push_main()
    head0 = sb.rev("HEAD")

    sb.fail_times(2)
    check(sb.state_json().get("consecutive_failures") == 2,
          "A: زیرِ آستانه دو بار شمرده شد (%s)" % sb.state_json().get("consecutive_failures"))
    check(sb.rev("HEAD") == head0, "A: زیرِ آستانه HEAD دست‌نخورده ماند")
    check(sb.origin_refs("refs/heads/revert/*") == [],
          "A: زیرِ آستانه هیچ شاخه‌ی برگشتی ساخته نشد")

    sb.set_mode("ok")
    p = sb.run_watcher()
    check("سالم" in p.stdout, "A: پیامِ سالم‌بودن آمد")
    check(sb.state_json().get("consecutive_failures") == 0, "A: سالم شدن، شمارنده را صفر کرد")
    sb.cleanup()


def case_tracked_dirty_blocks():
    """B) تغییرِ ذخیره‌نشده روی فایلِ ردیابی‌شده → برگشت نمی‌کنیم."""
    sb = Sandbox().setup()
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: کامیتِ خراب")
    sb.push_main()
    head0 = sb.rev("HEAD")
    sb.fail_times(2)

    # کارِ ذخیره‌نشده‌ی کاربر روی یک فایلِ ردیابی‌شده
    sb.write("app.py", "V1 = 99  # کارِ نیمه‌کاره‌ی کاربر\n")
    p = sb.run_watcher()          # سومین شکست = پر شدنِ آستانه

    check("worktree تمیز" in p.stdout and "✗" in p.stdout,
          "B: شرطِ «worktree تمیز» شکست و گزارش شد")
    check("برگشت انجام نمی‌شود" in p.stdout, "B: صریحاً گفت که برنمی‌گرداند")
    check(sb.rev("HEAD") == head0, "B: HEAD دست‌نخورده ماند")
    check(sb.origin_refs("refs/heads/revert/*") == [], "B: شاخه‌ای به origin پوش نشد")
    check(sb.local_branches("revert/*") == [], "B: حتی شاخه‌ی محلی هم ساخته نشد")
    check(sb.state_json().get("last_action") is None, "B: هیچ اقدامی ثبت نشد (فقط blocked)")
    check(sb.blocked_guard() == "worktree تمیز", "B: علت ثبت‌شده درست است")
    sb.cleanup()


def case_head_is_green():
    """D) HEAD خودش سبزِ آخر است → شکست محیطی است، نه کدی؛ برنمی‌گردیم."""
    sb = Sandbox().setup()
    sb.fail_times(3)
    check(sb.blocked_guard() == "HEAD ≠ سبزِ آخر",
          "D: گاردِ درست گرفت (%s)" % sb.blocked_guard())
    check(sb.origin_refs("refs/heads/revert/*") == [], "D: شاخه‌ای ساخته نشد")
    check(not sb.gh_pr_create(), "D: PRی ساخته نشد")
    sb.cleanup()


def case_not_ancestor():
    """E) سبزِ آخر پدرِ HEAD نیست (تاریخچه بازنویسی شده) → مسدود."""
    sb = Sandbox().setup()
    green = sb.green
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: خراب")
    sb.push_main()

    _run(["git", "checkout", "--orphan", "rewritten"], sb.repo, sb.env, check_rc=True)
    sb.commit("c1': تاریخچه‌ی بازنویسی‌شده")
    _run(["git", "branch", "-M", "rewritten", "main"], sb.repo, sb.env, check_rc=True)
    sb.fail_times(3)

    check("پدر" in sb.blocked_guard(), "E: گاردِ «سبزِ آخر پدرِ HEAD نیست» گرفت (%s)"
          % sb.blocked_guard())
    check(sb.origin_refs("refs/heads/revert/*") == [], "E: شاخه‌ای پوش نشد")
    check(sb.rev("HEAD") != green, "E: وضعیتِ آزمایشی درست بود (HEAD ≠ سبز)")
    sb.cleanup()


def case_gap_too_large():
    """F) فاصله‌ی سبز تا HEAD بیشتر از حدِ مجاز → تصمیمِ انسانی لازم است."""
    sb = Sandbox().setup()
    for i in range(1, 4):
        sb.write("app.py", "V1 = %d  # خراب\n" % (10 + i))
        sb.commit("c%d: خراب" % i)
    sb.push_main()
    sb.fail_times(2)
    p = sb.run_watcher(PIPFOUND_WATCH_MAX_COMMITS=2)
    check("فاصله ≤ 2 کامیت" in p.stdout and "✗" in p.stdout, "F: گاردِ فاصله فعال شد")
    check("فاصله" in sb.blocked_guard(), "F: علت ثبت شد (%s)" % sb.blocked_guard())
    check(sb.origin_refs("refs/heads/revert/*") == [], "F: شاخه‌ای پوش نشد")
    sb.cleanup()


def case_open_revert_pr_blocks():
    """G) PRِ برگشتِ بازِ قبلی → دوباره برنمی‌گردانیم (ضدِ تکرار)."""
    sb = Sandbox().setup()
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: خراب")
    sb.push_main()
    sb.fail_times(2)
    open_prs = json.dumps([{"number": 9001,
                            "headRefName": "revert/selfcheck-20260101-000000"}])
    p = sb.run_watcher(PF_TEST_OPEN_PRS=open_prs)
    check("PRِ برگشتِ بازی باز نیست" in p.stdout and "✗" in p.stdout,
          "G: گاردِ ضدِ تکرار فعال شد")
    check(sb.origin_refs("refs/heads/revert/*") == [], "G: شاخه‌ی تازه‌ای پوش نشد")
    check(not sb.gh_pr_create(), "G: PRِ تازه‌ای ساخته نشد")
    sb.cleanup()


def case_no_pr_local_only():
    """H) --no-pr: تا کامیتِ محلیِ برگشت، بدونِ پوش/PR."""
    sb = Sandbox().setup()
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: خراب")
    sb.push_main()
    sb.fail_times(2)
    p = sb.run_watcher("--no-pr")
    check("no-pr" in p.stdout, "H: حالتِ no-pr گزارش شد")
    check(sb.gh_calls() == [], "H: gh اصلاً صدا زده نشد (نه PR، نه ادغام)")
    check(sb.origin_refs("refs/heads/revert/*") == [], "H: به origin پوش نشد")
    brs = sb.local_branches("revert/*")
    check(bool(brs), "H: کامیتِ برگشت به‌صورتِ شاخه‌ی محلی ساخته شد (%s)"
          % (brs[0] if brs else "—"))
    sb.cleanup()


def case_dry_run():
    """I) --dry-run: هیچ شاخه/پوش/PRی — فقط نقشه."""
    sb = Sandbox().setup()
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: خراب")
    sb.push_main()
    head0 = sb.rev("HEAD")
    sb.fail_times(2)
    p = sb.run_watcher("--dry-run")
    check("dry-run" in p.stdout, "I: حالتِ dry-run گزارش شد")
    # فقط خواندن مجاز است (gh pr list برای گاردِ ضدِ تکرار)؛ نوشتن ممنوع
    writes = sb.gh_pr_create() + sb.gh_pr_merge()
    check(writes == [], "I: هیچ PRی ساخته/ادغام نشد (%s)" % (writes or "—"))
    check(sb.origin_refs("refs/heads/revert/*") == [], "I: شاخه‌ای ساخته نشد")
    check(sb.local_branches("revert/*") == [], "I: شاخه‌ی محلی هم ساخته نشد")
    check(sb.rev("HEAD") == head0, "I: HEAD دست‌نخورده ماند")
    check("نقشه" in p.stdout, "I: نقشه‌ی برگشت چاپ شد")
    sb.cleanup()


def case_untracked_does_not_block():
    """J) فایلِ untracked (لاگ/کش) کار را نمی‌بندد."""
    sb = Sandbox().setup()
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: خراب")
    sb.push_main()
    sb.write("watch.log", "یک لاگِ بی‌ربط\n")      # untracked و بدونِ gitignore
    check(_run(["git", "status", "--porcelain"], sb.repo, sb.env).stdout.strip()
          == "?? watch.log", "J: وضعیتِ آزمایشی درست است (فایلِ untracked)")
    sb.fail_times(3)
    check(bool(sb.gh_pr_create()), "J: فایلِ untracked مانعِ برگشت نشد (PR ساخته شد)")
    sb.cleanup()


def case_crash_without_json():
    """K) کرشِ selfcheck بدونِ JSON هم یک شکست شمرده می‌شود (نه استثنا)."""
    sb = Sandbox().setup()
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: خراب")
    sb.push_main()
    sb.set_mode("crash")
    p = sb.run_watcher()
    check("کرشِ کامل، بدونِ JSON" in p.stdout, "K: کرشِ بدونِ JSON تشخیص داده شد")
    check(sb.state_json().get("consecutive_failures") == 1, "K: دقیقاً یک شکست شمرده شد")
    sb.cleanup()


def case_full_revert_and_merge():
    """C) همه‌ی شروط برقرار → برگشت، PR، ادغامِ خودکار، pull — حلقه بسته می‌شود."""
    sb = Sandbox().setup()
    green = sb.green
    sb.write("app.py", "V1 = 2  # خراب\n")
    sb.commit("c1: خراب‌کاریِ اول")
    sb.write("app.py", "V1 = 3  # خراب‌تر\n")
    sb.commit("c2: خراب‌کاریِ دوم")
    sb.push_main()

    out = sb.fail_times(3)
    check("🚨 آستانه پر شد" in out, "C: آستانه تشخیص داده شد")
    check("♻️ ساختِ برگشت" in out, "C: برگشت ساخته شد")
    check("درخت = درختِ سبز" in out, "C: تأییدِ درون‌برنامه‌ایِ برابریِ درخت آمد")
    check("ادغام شد" in out, "C: PR خودکار ادغام شد")
    check("main به‌روز شد" in out, "C: پس از ادغام، main محلی به‌روز شد")

    calls = sb.gh_calls()
    create_calls = sb.gh_pr_create()
    merge_calls = sb.gh_pr_merge()
    check(len(create_calls) == 1, "C: gh pr create دقیقاً یک بار صدا زده شد")
    check(bool(merge_calls), "C: gh pr merge صدا زده شد")
    check(all("--squash" in c and "--auto" in c for c in merge_calls),
          "C: auto-merge با squash تنظیم شد (نه ادغامِ فوری و مستقیم)")
    check(all("--delete-branch" in c for c in merge_calls), "C: شاخه پس از ادغام پاک می‌شود")
    if create_calls:
        check("--base | main" in create_calls[0], "C: PR روی main باز شد")

    merged = [c for c in calls if c.startswith("merged_ref ")]
    check(bool(merged), "C: شاخه‌ی برگشت روی origin وجود داشت و ادغام شد")
    if merged:
        parts = merged[-1].split()
        branch, sha = parts[1], parts[2]
        check(branch.startswith("revert/selfcheck-"), "C: نامِ شاخه استاندارد بود (%s)" % branch)
        if sha:
            check(_run(["git", "-C", sb.origin, "diff", "--quiet", green, sha],
                       sb.tmp, sb.env).returncode == 0,
                  "C: درختِ ادغام‌شده بایت‌به‌بایت = درختِ آخرین سبزِ CI")
            check(_run(["git", "-C", sb.origin, "merge-base", "--is-ancestor", green, sha],
                       sb.tmp, sb.env).returncode == 0,
                  "C: کامیتِ سبز جدِ کامیتِ ادغام‌شده است (پس main فقط برگشت خورد)")

    check(sb.origin_main() == sb.rev("HEAD"), "C: mainِ محلی و origin یکی شدند (pull کار کرد)")
    check(sb.origin_refs("refs/heads/revert/*") == [],
          "C: شاخه‌ی برگشت روی origin پاک شد")
    check(sb.state_json().get("consecutive_failures") == 0,
          "C: بعد از برگشتِ موفق، شمارنده صفر شد")
    check(sb.state_json().get("last_action", {}).get("kind") == "merged",
          "C: اقدامِ نهایی به‌عنوانِ merged ثبت شد")
    sb.cleanup()


def main():
    cases = [
        case_below_threshold,
        case_tracked_dirty_blocks,
        case_head_is_green,
        case_not_ancestor,
        case_gap_too_large,
        case_open_revert_pr_blocks,
        case_no_pr_local_only,
        case_dry_run,
        case_untracked_does_not_block,
        case_crash_without_json,
        case_full_revert_and_merge,
    ]
    try:
        for fn in cases:
            try:
                fn()
            except Exception as e:
                import traceback
                problems.append("سناریو %s استثنا داد: %s\n%s"
                                % (fn.__name__, e, traceback.format_exc()))
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

    for n in notes:
        print(n)
    if problems:
        print("\n❌ تستِ نگهبانِ برگشت رد شد — %d مشکل:" % len(problems))
        for p in problems:
            print("  · %s" % p)
        return 1
    print("\n✅ تستِ نگهبانِ برگشت سالم — %d بررسی" % len(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
