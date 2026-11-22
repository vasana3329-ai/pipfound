#!/bin/sh
# نصب/حذفِ LaunchAgentِ pipfound تا سرور همیشه بالا بماند (شروع در لاگین + KeepAlive).
# مسیرها از محلِ همین پوشهٔ pipfound ساخته می‌شوند؛ هیچ ارجاعی به ~/.hermes لازم نیست.
#   sh install.sh install     نصب و روشن‌کردن
#   sh install.sh uninstall   خاموش‌کردن و حذف
#   sh install.sh status      وضعیتِ فعلی
set -e
LABEL="com.pipfound.server"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/$LABEL.plist"
ROOT="$(cd "$HERE/../.." && pwd)"          # پوشهٔ اصلیِ pipfound
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

case "${1:-status}" in
  install)
    if [ ! -x "$ROOT/.venv/bin/python3" ]; then
      echo "❌ محیطِ پایتونِ اختصاصی پیدا نشد: $ROOT/.venv" >&2
      echo "   اول این را اجرا کن:  python3 -m venv \"$ROOT/.venv\" && \"$ROOT/.venv/bin/python3\" -m pip install pillow certifi" >&2
      exit 1
    fi
    mkdir -p "$HOME/Library/LaunchAgents"
    sed "s|__ROOT__|$ROOT|g" "$SRC" > "$DST"
    plutil -lint "$DST" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$DST" 2>/dev/null || launchctl load -w "$DST"
    echo "✅ $LABEL نصب شد — سرور با لاگین بالا می‌آید و پس از هر کرش برمی‌گردد."
    echo "   root: $ROOT"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || launchctl unload -w "$DST" 2>/dev/null || true
    rm -f "$DST"
    echo "🗑 $LABEL حذف شد."
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state = |pid = |runs = " | head -3 || echo "نصب نیست."
    ;;
  *)
    echo "استفاده: sh install.sh [install|uninstall|status]" >&2; exit 2 ;;
esac
