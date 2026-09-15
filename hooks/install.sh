#!/bin/bash
# نصبِ هوک‌های گیتِ pipfound
# هوک‌ها در .git/hooks نسخه‌بندی نمی‌شوند، پس همین‌جا در hooks/ نگه داشته می‌شوند
# و این اسکریپت آن‌ها را سرِ جای درست کپی می‌کند.
#   اجرا:  ./hooks/install.sh
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/hooks"
DST="$(git -C "$REPO" rev-parse --git-path hooks)"

if [ ! -d "$DST" ]; then
  echo "✗ پوشه‌ی هوک‌ها پیدا نشد: $DST" >&2
  exit 1
fi

installed=0
for f in "$SRC"/*; do
  name="$(basename "$f")"
  case "$name" in
    install.sh|README*|*.md) continue ;;
  esac
  cp "$f" "$DST/$name"
  chmod +x "$DST/$name"
  echo "✅ نصب شد: $DST/$name"
  installed=$((installed + 1))
done

if [ "$installed" -eq 0 ]; then
  echo "⚠️  هیچ هوکی برای نصب پیدا نشد در $SRC" >&2
  exit 1
fi

echo "🩺 نگهبانِ سلامت حالا قبل از هر کامیت اجرا می‌شود."
echo "   (عبورِ اضطراری: PIPFOUND_SKIP_SELFCHECK=1 git commit ...)"
