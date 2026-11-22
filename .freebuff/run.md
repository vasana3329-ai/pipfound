# run.md — pipfound (سشنِ مستقل)

این پوشه خودش یک پروژهٔ کاملِ pipfound است: اسکیل + همهٔ اسکریپت‌ها + محیطِ پایتونِ
اختصاصی. هیچ مسیری از آن به `~/.hermes` نمی‌رود.

## اجرا
```bash
cd scripts
../.venv/bin/python3 selfcheck.py --guard        # نگهبانِ سلامت
../.venv/bin/python3 -u app.py --port 8787 --no-autorestart
# یا صرفاً دوبار کلیک روی ~/Desktop/pipfound.app
```
راستی‌آزمایی: `curl -s http://127.0.0.1:8787/api/health` → `{"ok": true}`

## همیشه‌روشن (launchd)
```bash
sh scripts/launchagent/install.sh install    # نصب/به‌روزرسانی (مسیرها را خودش می‌سازد)
sh scripts/launchagent/install.sh status
sh scripts/launchagent/install.sh uninstall
```
`scripts/launchagent/com.pipfound.server.plist` یک قالب با `__ROOT__` است؛ نسخهٔ نصب‌شده در
`~/Library/LaunchAgents/com.pipfound.server.plist` قرار می‌گیرد. لاگ: `/tmp/pipfound.log`

## محیطِ پایتون
`.venv/` (Python 3.14 + pillow + certifi) و در گیت نیست. اگر نبود:
```bash
python3 -m venv .venv && ./.venv/bin/python3 -m pip install pillow certifi
```

## دادهٔ شخصی
در `~/pipfound/` زندگی می‌کند (`journal.csv`, `alarms.json`, `good/`, `selfcheck.log` …)،
نه داخلِ ریپو. `data/` داخلِ ریپو فقط کپیِ کهنه است و در گیت نمی‌رود.

## ساختِ اپ دسکتاپ
```bash
./.venv/bin/python3 scripts/make_app.py      # ~/Desktop/pipfound.app را بازمی‌سازد
```

## گیت
شاخهٔ سشن: `session/full-1` (روی گیت‌هاب هم هست). تغییراتِ پایدار روی همین شاخه، نه `main`.
