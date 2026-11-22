#!/bin/sh
# نصب/حذفِ LaunchAgentِ pipfound تا سرور همیشه بالا بماند (شروع در لاگین + KeepAlive).
#   sh install.sh install     نصب و روشن‌کردن
#   sh install.sh uninstall   خاموش‌کردن و حذف
#   sh install.sh status      وضعیتِ فعلی
set -e
LABEL="com.pipfound.server"
SRC="$(cd "$(dirname "$0")" && pwd)/$LABEL.plist"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

case "${1:-status}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents"
    cp "$SRC" "$DST"
    plutil -lint "$DST" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$DST" 2>/dev/null || launchctl load -w "$DST"
    echo "✅ $LABEL نصب شد — سرور با لاگین بالا می‌آید و پس از هر کرش برمی‌گردد."
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
