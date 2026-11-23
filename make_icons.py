#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reuse the checked-in PWA icons; building/installing needs only stdlib.

The PNGs are source assets, not generated at runtime. This command validates
and optionally copies them. It needs neither Pillow nor a platform image tool.
Changing the artwork is a separate, optional design step.
"""
import argparse
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parent
ICONS = ((180, False), (192, False), (512, False), (192, True), (512, True))
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def icon_name(size, maskable=False):
    if (size, maskable) not in ICONS:
        raise ValueError("No checked-in icon for size/mask: %r" % ((size, maskable),))
    return "icon-%d%s.png" % (size, "-mask" if maskable else "")


def checked_png(path, size):
    """Validate dimensions, chunk bounds/CRCs and a complete PNG terminator."""
    path = Path(path)
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid PNG signature: %s" % path)
    offset, dimensions, saw_data, ended = 8, None, False, False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("Truncated PNG chunk: %s" % path)
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG payload: %s" % path)
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if (zlib.crc32(kind + payload) & 0xffffffff) != crc:
            raise ValueError("Invalid PNG CRC: %s" % path)
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise ValueError("Missing PNG IHDR: %s" % path)
            dimensions = struct.unpack_from(">II", payload)
        if kind == b"IDAT":
            saw_data = True
        if kind == b"IEND":
            ended = length == 0 and end == len(data)
            break
        offset = end
    if dimensions != (size, size) or not saw_data or not ended:
        raise ValueError("Incomplete PNG or wrong icon dimensions: %s" % path)
    return data


def copy_icons(output, source=ROOT, check_only=False):
    """Validate the full set before creating an output or replacing any asset."""
    source, output = Path(source).resolve(), Path(output).resolve()
    assets = [(icon_name(size, mask), checked_png(source / icon_name(size, mask), size))
              for size, mask in ICONS]
    if not check_only and output != source:
        output.mkdir(parents=True, exist_ok=True)
        for name, data in assets:
            (output / name).write_bytes(data)
    return [(name, len(data)) for name, data in assets]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT,
                        help="copy checked-in PNGs here (default: validate them in place)")
    parser.add_argument("--source", type=Path, default=ROOT,
                        help="directory containing the checked-in PNGs")
    parser.add_argument("--check", action="store_true", help="validate only; never write")
    args = parser.parse_args(argv)
    try:
        assets = copy_icons(args.output, args.source, args.check)
    except (OSError, ValueError) as exc:
        parser.exit(1, "Icon validation failed: %s\n" % exc)
    for name, length in assets:
        print("%s: %d bytes (checked-in asset)" % (name, length))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
