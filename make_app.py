#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a relocatable pipfound.app using only Python's standard library.

The app embeds the project sources and checked-in PNG assets. Python 3.11+ is
an explicit external runtime prerequisite; it is not bundled. The launcher
uses --python/PIPFOUND_PYTHON when available, then discovers a supported Python.
Only launching on macOS needs its native bash/curl/open tools. Building needs
neither Pillow, sips, iconutil, Hermes paths nor a running server/browser.

For an isolated smoke build, pass --output /path/to/scratch/pipfound.app.
Existing bundles are never replaced without --replace. The generated launcher
supports --check (stdlib-only preflight; no server, browser or notifications).
"""
import argparse
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile

from make_icons import checked_png

ROOT = Path(__file__).resolve().parent
PORT = 8787
SKIP_NAMES = {".git", "__pycache__", "node_modules", ".DS_Store", ".ff_cache.json",
              ".te_actuals.json", "fundamental_report.md", ".pytest_cache"}

LAUNCHER = r'''#!/bin/bash
set -u
# Resources/app is relative to this executable: moving the .app keeps it usable.
SCRIPTS="$(cd "$(dirname "$0")/../Resources/app" && pwd -P)" || exit 1
PREFERRED_PY=@@PYTHON@@
PORT="${PIPFOUND_PORT:-@@PORT@@}"
CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then CHECK_ONLY=1; fi

report() {
  printf '%s\n' "$1" >&2
  # Preflight/tests never open an app or show a desktop dialog.
  if [ "$CHECK_ONLY" = 0 ] && [ "${PIPFOUND_NOTIFY:-1}" != 0 ] && command -v osascript >/dev/null 2>&1; then
    osascript -e 'display dialog "pipfound نتوانست اجرا شود. گزارش در لاگِ pipfound است." buttons {"باشه"} default button 1 with icon caution with title "pipfound"' >/dev/null 2>&1 || true
  fi
  exit 1
}
python_ok() {
  [ -n "$1" ] && "$1" -S -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}
PY=""
if [ -n "${PIPFOUND_PYTHON:-}" ]; then
  if python_ok "$PIPFOUND_PYTHON"; then PY="$PIPFOUND_PYTHON";
  else report "PIPFOUND_PYTHON must be an executable Python 3.11+."; fi
else
  for candidate in "$PREFERRED_PY" python3 python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if python_ok "$candidate"; then PY="$candidate"; break; fi
  done
fi
[ -n "$PY" ] || report "pipfound needs Python 3.11+ (not bundled); set PIPFOUND_PYTHON to its executable."
case "$PORT" in ''|*[!0-9]*) report "PIPFOUND_PORT must be between 1 and 65535.";; esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then report "PIPFOUND_PORT must be between 1 and 65535."; fi
if [ "$CHECK_ONLY" = 1 ]; then
  exec "$PY" -S "$SCRIPTS/selfcheck.py"
fi

LOG_DIR="${PIPFOUND_LOG_DIR:-${XDG_STATE_HOME:-$HOME/Library/Logs}/pipfound}"
mkdir -p "$LOG_DIR" || report "Cannot create pipfound log directory: $LOG_DIR"
GUARD_LOG="$LOG_DIR/selfcheck.log"
SERVER_LOG="$LOG_DIR/server.log"
if ! "$PY" "$SCRIPTS/selfcheck.py" --guard >"$GUARD_LOG" 2>&1; then
  report "pipfound preflight failed: $GUARD_LOG"
fi
command -v curl >/dev/null 2>&1 || report "Launching pipfound on macOS needs its native curl."
URL="http://127.0.0.1:$PORT"
healthy() {
  curl -fsS --max-time 2 "$URL/api/health" 2>/dev/null | "$PY" -S -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("ok") is True else 1)' >/dev/null 2>&1
}
if ! healthy; then
  cd "$SCRIPTS" || report "Missing bundled sources: $SCRIPTS"
  nohup "$PY" -u app.py --host 127.0.0.1 --port "$PORT" >"$SERVER_LOG" 2>&1 &
  for ((i=0; i<40; i++)); do
    if healthy; then break; fi
    sleep 0.3
  done
fi
healthy || report "pipfound server did not become healthy: $SERVER_LOG"
if [ "${PIPFOUND_OPEN_BROWSER:-1}" != 0 ]; then
  command -v open >/dev/null 2>&1 || report "Opening pipfound needs macOS open (or PIPFOUND_OPEN_BROWSER=0)."
  open "$URL"
fi
'''


def build_icns(work, source=ROOT):
    """Modern macOS ICNS accepts a PNG-backed 512px (ic09) icon element."""
    png = checked_png(Path(source) / "icon-512.png", 512)
    element = b"ic09" + struct.pack(">I", len(png) + 8) + png
    content = b"icns" + struct.pack(">I", len(element) + 8) + element
    target = Path(work) / "pipfound.icns"
    target.write_bytes(content)
    return target


def supported_python(executable):
    executable = str(executable or sys.executable)
    resolved = shutil.which(executable)
    if not resolved:
        raise ValueError("Python executable not found: %s" % executable)
    result = subprocess.run(
        [resolved, "-S", "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"],
        capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError("Python 3.11+ is required: %s" % executable)
    return str(Path(resolved).resolve())


def ignore_sources(directory, names):
    return [name for name in names if name in SKIP_NAMES or name.endswith(".log")
            or Path(directory, name).is_symlink()]


def build_app(output, scripts=ROOT, python=None, port=PORT, replace=False):
    scripts = Path(scripts).resolve(strict=True)
    output = Path(output).expanduser().absolute()
    if output.is_symlink() or output.suffix.lower() != ".app":
        raise ValueError("Output must be a non-symlink .app path")
    if output.resolve().is_relative_to(scripts):
        raise ValueError("Output must be outside the source tree")
    if output.exists() and (not replace or not output.is_dir()):
        raise ValueError("Output exists; use --replace explicitly: %s" % output)
    if isinstance(port, bool) or not 1 <= int(port) <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    for name in ("app.py", "selfcheck.py", "selfcheck-baseline.json", "sw.js", "manifest.webmanifest"):
        if not (scripts / name).is_file():
            raise ValueError("Missing project source: %s" % (scripts / name))
    preferred = supported_python(python)
    # Validate all source assets before making or replacing an output bundle.
    from make_icons import copy_icons
    copy_icons(scripts, scripts, check_only=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pipfound-build-", dir=output.parent) as work:
        staged = Path(work) / output.name
        contents = staged / "Contents"
        macos, resources = contents / "MacOS", contents / "Resources"
        macos.mkdir(parents=True)
        resources.mkdir()
        shutil.copytree(scripts, resources / "app", ignore=ignore_sources)
        icon = build_icns(resources, scripts)
        launcher = macos / "pipfound"
        launcher.write_text(LAUNCHER.replace("@@PYTHON@@", shlex.quote(preferred))
                            .replace("@@PORT@@", str(int(port))), encoding="utf-8")
        launcher.chmod(0o755)
        plist = {"CFBundleName": "pipfound", "CFBundleDisplayName": "pipfound",
                 "CFBundleIdentifier": "com.local.pipfound", "CFBundleVersion": "1.0",
                 "CFBundleShortVersionString": "1.0", "CFBundlePackageType": "APPL",
                 "CFBundleExecutable": "pipfound", "CFBundleIconFile": icon.name,
                 "LSMinimumSystemVersion": "10.13", "NSHighResolutionCapable": True,
                 "LSUIElement": False}
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump(plist, stream)
        previous = Path(work) / "previous.app"
        if output.exists():
            output.rename(previous)
        try:
            staged.rename(output)
        except OSError:
            if previous.exists():
                previous.rename(output)
            raise
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path.home() / "Desktop" / "pipfound.app")
    parser.add_argument("--scripts", type=Path, default=ROOT, help="project sources to embed")
    parser.add_argument("--python", help="external Python 3.11+ executable (default: this interpreter)")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--replace", action="store_true", help="explicitly replace an existing bundle")
    args = parser.parse_args(argv)
    try:
        output = build_app(args.output, args.scripts, args.python, args.port, args.replace)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, "Build failed: %s\n" % exc)
    print("Built: %s" % output)
    print("Requires external Python 3.11+; sources/icons are embedded; no Pillow required.")
    print("Preflight without launching: %s --check" % shlex.quote(str(output / "Contents/MacOS/pipfound")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
