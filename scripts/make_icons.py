#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ساختِ آیکون‌های PWA (شمعِ اسمارت‌مانی) — یک‌بار اجرا می‌شود، سپس می‌شود پاکش کرد."""
from PIL import Image, ImageDraw
import os

OUT = os.path.dirname(os.path.abspath(__file__))
GREEN = (34, 211, 165, 255)
RED = (239, 68, 68, 255)


def make_icon(size, maskable=False):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, size, size], fill=(16, 34, 59, 255))
    else:
        pad = int(size * 0.06)
        rad = int(size * 0.22)
        d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=rad,
                            fill=(20, 26, 38, 255), outline=(40, 50, 74, 255),
                            width=max(2, size // 128))
    cx = size / 2
    W = size * 0.62
    x0 = cx - W / 2
    n = 5
    slot = W / n
    body_w = slot * 0.42
    cy = size / 2
    specs = [
        (0.60, 0.42, RED),
        (0.50, 0.30, GREEN),
        (0.66, 0.34, GREEN),
        (0.44, 0.26, RED),
        (0.72, 0.30, GREEN),
    ]
    for i, (h_frac, body_frac, c) in enumerate(specs):
        xc = x0 + slot * i + slot / 2
        total_h = size * h_frac
        top = cy - total_h / 2
        bot = cy + total_h / 2
        d.line([(xc, top), (xc, bot)], fill=c, width=max(2, size // 96))
        body_h = total_h * body_frac
        shift = size * 0.04 if c == GREEN else -size * 0.04
        bt = cy - body_h / 2 - shift
        bb = bt + body_h
        d.rounded_rectangle([xc - body_w / 2, bt, xc + body_w / 2, bb],
                            radius=max(2, size // 64), fill=c)
    name = f"icon-{size}{'-mask' if maskable else ''}.png"
    img.save(os.path.join(OUT, name))
    return name


if __name__ == "__main__":
    files = []
    for s in (192, 512):
        files.append(make_icon(s, maskable=False))
        files.append(make_icon(s, maskable=True))
    files.append(make_icon(180, maskable=False))
    for f in files:
        p = os.path.join(OUT, f)
        print(f, os.path.getsize(p), "bytes")
