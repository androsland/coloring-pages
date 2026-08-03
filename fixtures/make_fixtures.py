#!/usr/bin/env python3
"""Draw the fixture images.

The PNGs are committed, so a clean checkout can run the report without this
script. It exists so the fixtures are auditable and reproducible: every pixel
here comes from code you can read, rather than from art someone has to trust the
licence of. `in/` is gitignored precisely because real source pictures cannot be
committed, which is what left the tuning claims unverifiable in the first place.

Each fixture targets a specific claim the pipeline makes. If you add one, say in
its comment which claim it is for — an image nobody can explain is an image
nobody will maintain.

Usage:
    python3 fixtures/make_fixtures.py
"""

import cv2
import numpy as np
from pathlib import Path

OUT = Path(__file__).parent
W, H = 240, 180

# Ink colours in BGR. The saturated ones are the point: each has V < 120 (dark)
# but S > 60 (colourful), which is exactly the combination the old lineart rule
# `V < 120 && S < 60` threw away, taking most of the drawing with it.
NAVY = (107, 42, 27)      # V=107 S=191
TEAL = (77, 61, 11)       # V=77  S=218
BROWN = (23, 44, 74)      # V=74  S=176
NEAR_BLACK = (28, 28, 30)  # V=30  S=17  — the easy case, grey ink

CREAM = (150, 220, 250)
SKY = (230, 200, 140)
ROSE = (200, 180, 240)


def blank(colour=(255, 255, 255)):
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = colour
    return img


def creature(img, ink, aa=True):
    """A blobby outlined figure: filled shapes with a heavier outline on top,
    which is the shape of most cartoon art the tool is pointed at."""
    line = cv2.LINE_AA if aa else cv2.LINE_8
    cv2.ellipse(img, (120, 105), (62, 48), 0, 0, 360, CREAM, -1, line)
    cv2.ellipse(img, (120, 105), (62, 48), 0, 0, 360, ink, 3, line)
    cv2.circle(img, (120, 58), 34, SKY, -1, line)
    cv2.circle(img, (120, 58), 34, ink, 3, line)
    cv2.circle(img, (108, 52), 6, ink, -1, line)      # eyes, solid ink
    cv2.circle(img, (133, 52), 6, ink, -1, line)
    cv2.ellipse(img, (120, 70), (14, 8), 0, 0, 180, ink, 2, line)   # mouth
    for x in (74, 166):                                # limbs
        cv2.line(img, (x, 110), (x - 30 if x < 120 else x + 30, 138), ink, 3, line)
    return img


def f_grey_ink():
    """Claim: the ordinary case — dark, desaturated outlines on white — still
    works. This is what the original fixed threshold was tuned for."""
    return creature(blank(), NEAR_BLACK)


def f_saturated_ink():
    """Claim: 'cartoon outlines are very often dark *and* saturated (navy, dark
    teal, brown), and that test threw them away'. Under `S < 60` this image
    comes out nearly blank; under the current rule it produces a usable page.
    The report shows both numbers so the difference is visible, not asserted."""
    img = blank()
    creature(img, NAVY)
    cv2.rectangle(img, (14, 22), (58, 66), ROSE, -1, cv2.LINE_AA)
    cv2.rectangle(img, (14, 22), (58, 66), TEAL, 3, cv2.LINE_AA)
    cv2.circle(img, (200, 40), 22, CREAM, -1, cv2.LINE_AA)
    cv2.circle(img, (200, 40), 22, BROWN, 3, cv2.LINE_AA)
    return img


def f_full_bleed():
    """Claim (a documented blind spot): 'Cartoon measures the percentile over
    the whole image, background included... a picture with no white background
    behaves differently from one cut out on white.' Nothing here is white, so
    the darkest N% lands somewhere quite different."""
    img = blank(SKY)
    cv2.rectangle(img, (0, 118), (W, H), (120, 160, 90), -1)       # ground
    creature(img, BROWN)
    return img


def f_pale_ink():
    """Claim: the ink cutoff reaches high values, not just low ones. A picture
    that is mostly white with sparse, light strokes puts its darkest 4% up around
    V=200 — which is why a fixed cutoff of 120 produced a blank page on art like
    this, and why the README quotes a range rather than a number. Without this
    fixture the set only demonstrates the low end."""
    img = blank()
    pale_blue = (235, 205, 170)
    pale_grey = (205, 200, 195)
    cv2.ellipse(img, (120, 100), (70, 52), 0, 0, 360, pale_blue, 2, cv2.LINE_AA)
    cv2.circle(img, (120, 56), 30, pale_blue, 2, cv2.LINE_AA)
    cv2.circle(img, (110, 50), 4, pale_grey, -1, cv2.LINE_AA)
    cv2.circle(img, (131, 50), 4, pale_grey, -1, cv2.LINE_AA)
    cv2.ellipse(img, (120, 66), (12, 7), 0, 0, 180, pale_blue, 2, cv2.LINE_AA)
    for x in (66, 174):
        cv2.line(img, (x, 104), (x - 26 if x < 120 else x + 26, 132), pale_grey, 2, cv2.LINE_AA)
    return img


def f_flat_bands():
    """Claim (a documented blind spot): 'the cutoff is an integer V, so where
    many pixels share one brightness the achieved coverage jumps'. Six large
    uniform bands give the histogram very few distinct values to land between."""
    img = blank()
    for n, v in enumerate((20, 60, 100, 140, 190, 240)):
        img[n * H // 6:(n + 1) * H // 6, :] = (v, v, v)
    return img


def f_fine_detail():
    """Claim: thinning 'will not break a line, pull its ends back, or erase a
    lone pixel' — with one exception, 'an isolated 2x2 block of ink is erased
    outright'. Contains each shape that claim names, at known sizes."""
    img = blank()
    for x in range(20, 221, 40):                       # 1px verticals
        cv2.line(img, (x, 16), (x, 60), NEAR_BLACK, 1, cv2.LINE_8)
    cv2.line(img, (20, 76), (220, 76), NEAR_BLACK, 1, cv2.LINE_8)   # 1px horizontal
    img[96, 30] = NEAR_BLACK                           # lone pixel
    img[96:98, 60:62] = NEAR_BLACK                     # 2x2 — the one that vanishes
    img[96:99, 90:93] = NEAR_BLACK                     # 3x3
    img[96:100, 120:124] = NEAR_BLACK                  # 4x4
    img[96:98, 150:158] = NEAR_BLACK                   # 2x8 bar
    cv2.rectangle(img, (30, 126), (210, 166), NEAR_BLACK, 6)        # thick stroke
    return img


FIXTURES = {
    "grey-ink": f_grey_ink,
    "saturated-ink": f_saturated_ink,
    "pale-ink": f_pale_ink,
    "full-bleed": f_full_bleed,
    "flat-bands": f_flat_bands,
    "fine-detail": f_fine_detail,
}


def main():
    for name, fn in FIXTURES.items():
        path = OUT / f"{name}.png"
        cv2.imwrite(str(path), fn())
        print(f"  wrote {path.relative_to(OUT.parent)}")
    print(f"\n{len(FIXTURES)} fixtures written to {OUT.relative_to(OUT.parent)}/")


if __name__ == "__main__":
    main()
