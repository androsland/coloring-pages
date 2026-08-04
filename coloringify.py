#!/usr/bin/env python3
"""Turn photos into coloring pages.

Reads every image from ./in, converts each to black-outline-on-white line art,
and writes the result to ./out.

Usage:
    python3 coloringify.py                    # process all images in ./in
    python3 coloringify.py --style edges      # use Canny edge style instead
    python3 coloringify.py --line-width -2    # same lines, drawn thinner
    python3 coloringify.py --in pics --out pages

Styles:
    threshold  (default) clean "coloring-book" lines via adaptive threshold
    edges      thinner, sketchier outlines via Canny edge detection
    lineart    keep the darkest --ink percent of the picture — cartoons/clip art

--line-width is separate from the style: it re-weights whatever the style drew,
so `--style threshold --line-width -2` gives thin *single* outlines.
"""

import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np

# Image extensions OpenCV can reliably read.
EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def to_threshold(gray, block_size: int, c: int):
    """Adaptive-threshold style: clean, bold coloring-book lines."""
    blur = cv2.medianBlur(gray, 5)
    return cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY,
        blockSize=block_size, C=c,
    )


def to_edges(gray, low: int, high: int):
    """Canny style: thinner, sketchier outlines (black on white)."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, low, high)
    return cv2.bitwise_not(edges)  # invert so lines are black on white


def ink_cutoff(v, pct: float) -> int:
    """Brightness cutoff that inks roughly `pct`% of the picture: the smallest
    V at which at least that share of pixels is darker.

    Returns 1..255 — never 0, or a picture containing a pure-black region would
    come back completely blank. Mirrors inkCutoff() in docs/index.html; the two
    must agree bin for bin, which `python3 fixtures/parity.py` checks by running
    both against the committed fixtures and comparing every pixel.
    """
    below = np.cumsum(np.bincount(v.ravel(), minlength=256))  # below[i] = count(V <= i)
    want = v.size * pct / 100.0
    # Smallest t >= 1 with count(V < t) >= want; count(V < t) is below[t - 1].
    t = int(np.searchsorted(below, want, side="left")) + 1
    return min(max(t, 1), 255)


def to_lineart(img, ink_pct: float):
    """For images that already have outlines: keep the darkest `ink_pct`% of
    the picture as ink and whiten everything else.

    The cutoff is measured from this image rather than fixed, because "dark
    enough to be an outline" varies hugely between pictures — across the
    committed fixtures the same 4% target resolves to cutoffs from 10 to 237.
    Run `python3 fixtures/report.py` to re-derive that; it also fails if the
    number moves.

    Deliberately not filtered on saturation. The old rule also required S < 60,
    on the theory that ink is grey and fills are colourful — but cartoon
    outlines are very often dark *and* saturated (navy, dark teal, brown), and
    that test threw them away, taking most of the drawing with them.

    Uses V (the HSV value: max of R/G/B) rather than luma, so a saturated colour
    is judged by how light it is, not by how bright it looks to the eye.
    """
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2]
    return np.where(v < ink_cutoff(v, ink_pct), 0, 255).astype(np.uint8)


def _thin_pass(ink, step: int) -> bool:
    """One Zhang-Suen sub-pass over `ink` (1=ink), in place. True if it changed."""
    p = np.pad(ink, 1)
    # Neighbours clockwise from north, in Zhang-Suen's P2..P9 order.
    n = [p[0:-2, 1:-1], p[0:-2, 2:], p[1:-1, 2:], p[2:, 2:],
         p[2:, 1:-1], p[2:, 0:-2], p[1:-1, 0:-2], p[0:-2, 0:-2]]
    n2, n3, n4, n5, n6, n7, n8, n9 = n
    b = sum(n)                                       # ink neighbour count
    a = sum(((n[i] == 0) & (n[(i + 1) % 8] == 1)).astype(np.uint8)  # 0->1 steps
            for i in range(8))
    corners = (((n2 * n4 * n6 == 0) & (n4 * n6 * n8 == 0)) if step == 0
               else ((n2 * n4 * n8 == 0) & (n2 * n6 * n8 == 0)))
    doomed = (ink == 1) & (b >= 2) & (b <= 6) & (a == 1) & corners
    if not doomed.any():
        return False
    ink[doomed] = 0
    return True


def set_line_width(binary, width: int):
    """Redraw every stroke at the requested weight. binary: 0=ink, 255=paper.

    Negative widths peel layers off each stroke with Zhang-Suen thinning, which
    (unlike erosion) refuses to remove a pixel if that would disconnect the
    stroke — so lines get thinner without gaps appearing or ends retreating.

    One documented exception, inherent to the algorithm: an isolated 2x2 block
    of ink is erased outright, because all four of its pixels satisfy the delete
    test in the same sub-pass. No other shape vanishes — a lone pixel, a 1x2
    pair and every larger blob all keep at least one pixel. At print resolution
    a 2x2 blob is a speck, so losing it is no worse than --despeckle, but it is
    a real deletion rather than a thinning.

    Positive widths grow the ink; since ink is 0, that is an erode of the image.
    """
    if width == 0:
        return binary
    if width > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        return cv2.erode(binary, k, iterations=width)
    ink = (binary == 0).astype(np.uint8)
    for _ in range(-width):
        changed = _thin_pass(ink, 0)
        changed |= _thin_pass(ink, 1)
        if not changed:
            break                                    # already 1px everywhere
    return np.where(ink == 1, 0, 255).astype(np.uint8)


def despeckle(binary, min_area=12):
    """Remove black blobs smaller than min_area px. binary: 0=ink,255=paper."""
    ink = (binary == 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    out = np.full_like(binary, 255)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[labels == i] = 0
    return out


def add_reference(outline, color_img, scale: float, margin: int):
    """Paste a small full-color thumbnail in the top-right corner as a color guide."""
    # main() already restricts --ref-scale to (0, 1], but this function is
    # importable and reachable without it, and an out-of-range scale surfaces
    # far from its cause: 1.1 on a wide, short page raises a bare numpy
    # "could not broadcast" from the paste below, and a non-finite one raises
    # OverflowError from int(). Both name the symptom rather than the input, so
    # fail here instead, where the offending value can be quoted. Unlike the
    # margin clamp further down this is a raise, not a clamp — a margin that
    # does not fit a particular page is a runtime condition worth adapting to,
    # whereas a scale outside (0, 1] is the caller asking for something with no
    # sensible rendering.
    if not (math.isfinite(scale) and 0 < scale <= 1):
        raise ValueError(f"scale must be a finite number in (0, 1]; got {scale!r}")

    # Outline is single-channel; promote to BGR so we can paint color onto it.
    canvas = cv2.cvtColor(outline, cv2.COLOR_GRAY2BGR)
    h, w = canvas.shape[:2]

    thumb_w = max(1, int(w * scale))
    thumb_h = max(1, int(thumb_w * color_img.shape[0] / color_img.shape[1]))
    # A margin the canvas cannot accommodate used to drive x1 negative, which
    # numpy reads as a wraparound index rather than an error: the guide landed
    # somewhere else entirely and the run still exited 0. Clamp here rather than
    # in main(), because the flag is validated once but the batch can hold
    # images of any size, and only this function knows the one in front of it.
    #
    # The vertical bound is half the slack, not all of it, so that the overflow
    # guard below cannot then fire and shrink the thumbnail to a single pixel —
    # which is on-canvas and deterministic but just as silently wrong as the
    # wraparound it replaced.
    fitted = max(0, min(margin, w - thumb_w, (h - thumb_h) // 2))
    if fitted != margin:
        print(f"  warn  --ref-margin {margin} does not fit a {w}x{h} page; "
              f"using {fitted}.", file=sys.stderr)
    margin = fitted
    # Don't let the thumbnail overflow a small/tall page. This looks unreachable
    # now that scale is pinned to (0, 1] — a review argued exactly that, having
    # swept canvas shapes without varying the source's — but thumb_h comes from
    # the *source* image's aspect ratio, not the canvas's, so a tall source
    # overflows a short page at any scale. It fires on a 50x400 page with an
    # ordinary 240x180 source at the default 0.25. Load-bearing; do not delete.
    if thumb_h > h - 2 * margin:
        thumb_h = max(1, h - 2 * margin)
        thumb_w = max(1, int(thumb_h * color_img.shape[1] / color_img.shape[0]))
    thumb = cv2.resize(color_img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)

    x1, y1 = w - margin - thumb_w, margin  # top-left of thumb
    canvas[y1:y1 + thumb_h, x1:x1 + thumb_w] = thumb
    # Thin black frame so the guide reads as a separate inset.
    cv2.rectangle(canvas, (x1 - 1, y1 - 1), (x1 + thumb_w, y1 + thumb_h), (0, 0, 0), 2)
    return canvas


def load_bgr(path: Path):
    """Read an image as 3-channel BGR, flattening any transparency onto white.

    Without this, transparent PNG pixels come in as black and show up as a
    black background in both the outline and the color thumbnail.
    """
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:  # grayscale
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:  # has alpha — composite over white
        bgr = img[:, :, :3].astype(float)
        alpha = (img[:, :, 3:4].astype(float)) / 255.0
        white = (1.0 - alpha) * 255.0
        return (bgr * alpha + white).astype("uint8")
    return img


def convert(path: Path, style: str, args) -> "cv2.typing.MatLike | None":
    img = load_bgr(path)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if style == "edges":
        outline = to_edges(gray, args.canny_low, args.canny_high)
    elif style == "lineart":
        outline = to_lineart(img, args.ink)
    else:
        outline = to_threshold(gray, args.block_size, args.c)
    # Despeckle the single-channel outline before add_reference promotes to BGR.
    # It runs before the line-width pass so --min-area sees the specks at the
    # size the style actually drew them.
    if args.despeckle:
        outline = despeckle(outline, args.min_area)
    if args.line_width:
        outline = set_line_width(outline, args.line_width)
    if not args.no_reference:
        outline = add_reference(outline, img, args.ref_scale, args.ref_margin)
    return outline


def main() -> int:
    p = argparse.ArgumentParser(description="Turn photos into coloring pages.")
    p.add_argument("--in", dest="in_dir", default="in", help="input folder (default: in)")
    p.add_argument("--out", dest="out_dir", default="out", help="output folder (default: out)")
    p.add_argument("--style", choices=["threshold", "edges", "lineart"], default="threshold",
                   help="line style (default: threshold)")
    # Tuning knobs (sensible defaults; expose for fiddling).
    p.add_argument("--block-size", type=int, default=9,
                   help="adaptive-threshold neighborhood, odd >=3 (default: 9)")
    p.add_argument("--c", type=int, default=5,
                   help="adaptive-threshold sensitivity; higher = fewer lines (default: 5)")
    p.add_argument("--canny-low", type=int, default=50, help="Canny low threshold (default: 50)")
    p.add_argument("--canny-high", type=int, default=150, help="Canny high threshold (default: 150)")
    # lineart style: keep the darkest --ink percent of the picture. The
    # brightness cutoff that achieves it is measured per image.
    p.add_argument("--ink", type=float, default=4.0,
                   help="lineart: %% of the picture to keep as ink (default: 4)")
    # Outline weight (works with any style). 0 leaves the style's own stroke.
    p.add_argument("--line-width", type=int, default=0, choices=range(-3, 4),
                   metavar="{-3..3}",
                   help="outline weight: negative thins, positive thickens (default: 0)")
    # Optional despeckle post-process (works with any style; off by default).
    p.add_argument("--despeckle", action="store_true",
                   help="remove tiny black specks from the outline")
    p.add_argument("--min-area", type=int, default=12,
                   help="smallest black blob to keep in px when --despeckle is on (default: 12)")
    # Color-reference thumbnail in the top-right corner.
    p.add_argument("--no-reference", action="store_true",
                   help="don't add the full-color reference thumbnail")
    p.add_argument("--ref-scale", type=float, default=0.25,
                   help="reference thumbnail width as fraction of page (default: 0.25)")
    p.add_argument("--ref-margin", type=int, default=15,
                   help="reference thumbnail margin from the edge in px (default: 15)")
    args = p.parse_args()

    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    if not in_dir.is_dir():
        print(f"Input folder '{in_dir}' does not exist.", file=sys.stderr)
        return 1
    if args.block_size < 3 or args.block_size % 2 == 0:
        print("--block-size must be an odd number >= 3.", file=sys.stderr)
        return 1
    if not 0 < args.ink <= 100:
        print("--ink must be greater than 0 and at most 100.", file=sys.stderr)
        return 1
    # The two colour-guide flags reach add_reference() straight from argparse.
    # A negative margin was the one input that crashed outright, and it crashed
    # at -1: `canvas[y1:y1 + thumb_h, ...]` with a negative y1 produces a slice
    # that cannot take the thumbnail, and numpy raises a bare broadcast error.
    if args.ref_margin < 0:
        print("--ref-margin must be 0 or greater.", file=sys.stderr)
        return 1
    # Above 1 asks for a thumbnail wider than the page it sits on; at or below 0
    # the guide degenerates to a single pixel. Both used to be accepted silently.
    if not 0 < args.ref_scale <= 1:
        print("--ref-scale must be greater than 0 and at most 1.", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(f for f in in_dir.iterdir() if f.suffix.lower() in EXTS)
    if not images:
        print(f"No images found in '{in_dir}'. Drop some pictures in there and rerun.")
        return 0

    ok = failed = 0
    for src in images:
        result = convert(src, args.style, args)
        if result is None:
            print(f"  skip  {src.name}  (couldn't read)")
            failed += 1
            continue
        dst = out_dir / f"{src.stem}.png"
        cv2.imwrite(str(dst), result)
        print(f"  done  {src.name}  ->  {dst}")
        ok += 1

    print(f"\nConverted {ok} image(s) to '{out_dir}'." + (f" {failed} skipped." if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
