#!/usr/bin/env python3
"""Derive the transparent NCE nav logos from the source banner (Refs #121).

The source `assets/nce.png` is a dark banner whose top half holds the white NCE
emblem + wordmark. The emblem is monochrome white; the background is dark navy
and the rest of the banner (border, "SYSTEM ACCESS REQUEST") is yellow. White is
the only colour with a high *minimum* RGB channel — navy is dark and yellow has a
low blue channel — so a min-channel mask isolates the emblem cleanly. We emit two
colour variants sharing one alpha mask, swapped by theme in NavBar.vue:

    nce-logo-white.png  — white emblem, for the dark UI
    nce-logo-navy.png   — navy emblem, for the light UI

Run from the repo root (needs Pillow): python scripts/extract_nce_logo.py
"""
from PIL import Image, ImageChops

SRC = "assets/nce.png"
OUT_DIR = "frontend/src/assets"
LO, HI = 80, 205          # min-channel ramp: <=LO transparent, >=HI opaque
BOTTOM_KEEP = 0.62        # drop everything below this fraction of height

im = Image.open(SRC).convert("RGB")
W, H = im.size

r, g, b = im.split()
mn = ImageChops.darker(ImageChops.darker(r, g), b)          # per-pixel min(R,G,B)
alpha = mn.point(lambda v: 0 if v <= LO else (255 if v >= HI else int((v - LO) * 255 / (HI - LO))))

# Guard against stray specks in the lower (yellow) banner zone.
px = alpha.load()
for y in range(int(H * BOTTOM_KEEP), H):
    for x in range(W):
        px[x, y] = 0

alpha = alpha.crop(alpha.getbbox())                          # tight-crop to the emblem

for name, rgb in (("white", (255, 255, 255)), ("navy", (20, 31, 56))):
    img = Image.new("RGBA", alpha.size, rgb + (0,))
    img.putalpha(alpha)
    img.save(f"{OUT_DIR}/nce-logo-{name}.png")

print(f"Wrote nce-logo-white.png / nce-logo-navy.png ({alpha.size[0]}x{alpha.size[1]})")
