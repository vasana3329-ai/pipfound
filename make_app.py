#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""می‌سازد: pipfound.app روی دسکتاپ + آیکونِ اختصاصی (.icns)."""
import os, sys, subprocess, shutil, math
from PIL import Image, ImageDraw, ImageFont

HOME = os.path.expanduser("~")
DESKTOP = os.path.join(HOME, "Desktop")
APP = os.path.join(DESKTOP, "pipfound.app")
SCRIPTS = os.path.join(HOME, ".hermes", "skills", "trading",
                       "smc-ict-analysis", "scripts")
VENV_PY = os.path.join(HOME, ".hermes", "hermes-agent", "venv", "bin", "python3")
PORT = 8787

# ---------- 1) آیکون ----------
def make_icon(png_path, size=1024):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # پس‌زمینه‌ی گرد با گرادیانِ عمودی (تیره -> آبیِ اسمارت‌مانی)
    top = (13, 20, 33)      # #0d1421
    bot = (20, 60, 110)     # آبی
    rad = int(size * 0.22)
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] + (bot[0]-top[0]) * t)
        g = int(top[1] + (bot[1]-top[1]) * t)
        b = int(top[2] + (bot[2]-top[2]) * t)
        grad.putpixel((0, y), (r, g, b))
    grad = grad.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, size-1, size-1], radius=rad, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # کندلِ صعودی + نزولی (سبک SMC)
    cx = size // 2
    # کندل سبز (صعودی)
    green = (34, 211, 165)
    red = (239, 68, 68)
    bw = int(size * 0.11)
    # کندل چپ (نزولی/قرمز)
    x1 = int(size*0.30)
    d.line([(x1, int(size*0.24)), (x1, int(size*0.72))], fill=red, width=int(size*0.020))
    d.rounded_rectangle([x1-bw//2, int(size*0.34), x1+bw//2, int(size*0.60)],
                        radius=int(bw*0.25), fill=red)
    # کندل راست (صعودی/سبز)
    x2 = int(size*0.62)
    d.line([(x2, int(size*0.20)), (x2, int(size*0.80))], fill=green, width=int(size*0.020))
    d.rounded_rectangle([x2-bw//2, int(size*0.36), x2+bw//2, int(size*0.66)],
                        radius=int(bw*0.25), fill=green)

    # خطِ روند صعودی (نمادِ pip/سود)
    d.line([(int(size*0.20), int(size*0.66)), (int(size*0.50), int(size*0.50)),
            (int(size*0.80), int(size*0.30))],
           fill=(255, 255, 255), width=int(size*0.018), joint="curve")
    # نوکِ فلش
    ax, ay = int(size*0.80), int(size*0.30)
    d.polygon([(ax, ay-int(size*0.02)), (ax+int(size*0.055), ay),
               (ax, ay+int(size*0.055))], fill=(255, 255, 255))

    # حروفِ pf پایین
    try:
        fnt = ImageFont.truetype("/System/Library/Fonts/SFNSRounded.ttf", int(size*0.16))
    except Exception:
        try:
            fnt = ImageFont.truetype("/Library/Fonts/Arial Bold.ttf", int(size*0.16))
        except Exception:
            fnt = ImageFont.load_default()
    txt = "pf"
    bbox = d.textbbox((0, 0), txt, font=fnt)
    tw = bbox[2]-bbox[0]
    d.text(((size-tw)//2, int(size*0.80)), txt, font=fnt, fill=(180, 200, 230))
    img.save(png_path)

def build_icns(work):
    png = os.path.join(work, "icon_1024.png")
    make_icon(png)
    iconset = os.path.join(work, "pipfound.iconset")
    os.makedirs(iconset, exist_ok=True)
    specs = [(16,1),(16,2),(32,1),(32,2),(128,1),(128,2),(256,1),(256,2),(512,1),(512,2)]
    for base, scale in specs:
        px = base*scale
        name = f"icon_{base}x{base}{'@2x' if scale==2 else ''}.png"
        subprocess.run(["sips", "-z", str(px), str(px), png,
                        "--out", os.path.join(iconset, name)],
                       check=True, capture_output=True)
    icns = os.path.join(work, "pipfound.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns],
                   check=True, capture_output=True)
    return icns

# ---------- 2) اسکریپتِ راه‌انداز ----------
LAUNCHER = f'''#!/bin/bash
# راه‌اندازِ pipfound — سرور را بالا می‌آورد و مرورگر را باز می‌کند
SCRIPTS="{SCRIPTS}"
VENV_PY="{VENV_PY}"
PORT={PORT}
URL="http://127.0.0.1:$PORT"

# اگر پایتونِ venv نبود، از پایتونِ سیستم استفاده کن
if [ ! -x "$VENV_PY" ]; then VENV_PY="$(command -v python3)"; fi

# اگر سرور از قبل بالا نیست، بالا بیاور
if ! curl -s "$URL/api/health" >/dev/null 2>&1; then
  cd "$SCRIPTS" || exit 1
  nohup "$VENV_PY" app.py --port $PORT >/tmp/pipfound.log 2>&1 &
  # صبر تا آماده شدن
  for i in $(seq 1 30); do
    if curl -s "$URL/api/health" >/dev/null 2>&1; then break; fi
    sleep 0.3
  done
fi

open "$URL"
'''

def build_app(icns):
    if os.path.exists(APP):
        shutil.rmtree(APP)
    macos = os.path.join(APP, "Contents", "MacOS")
    res = os.path.join(APP, "Contents", "Resources")
    os.makedirs(macos, exist_ok=True)
    os.makedirs(res, exist_ok=True)

    launcher = os.path.join(macos, "pipfound")
    with open(launcher, "w") as f:
        f.write(LAUNCHER)
    os.chmod(launcher, 0o755)

    shutil.copy(icns, os.path.join(res, "pipfound.icns"))

    plist = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>pipfound</string>
  <key>CFBundleDisplayName</key><string>pipfound</string>
  <key>CFBundleIdentifier</key><string>com.local.pipfound</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>pipfound</string>
  <key>CFBundleIconFile</key><string>pipfound.icns</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSUIElement</key><false/>
</dict>
</plist>
'''
    with open(os.path.join(APP, "Contents", "Info.plist"), "w") as f:
        f.write(plist)

def main():
    work = "/tmp/pipfound_build"
    os.makedirs(work, exist_ok=True)
    icns = build_icns(work)
    build_app(icns)
    # رفرشِ آیکون در Finder
    subprocess.run(["touch", APP], check=False)
    print(f"OK — ساخته شد: {APP}")
    print(f"icns: {icns}")

if __name__ == "__main__":
    main()
