#!/usr/bin/env python3
"""Turn photos into coloring pages.

Reads every image from ./in, converts each to black-outline-on-white line art,
and writes the result to ./out.

Usage:
    python3 coloringify.py                 # process all images in ./in
    python3 coloringify.py --style edges   # use Canny edge style instead
    python3 coloringify.py --in pics --out pages

Styles:
    threshold  (default) clean "coloring-book" lines via adaptive threshold
    edges      thinner, sketchier outlines via Canny edge detection
"""

import argparse
import sys
from pathlib import Path

import cv2

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


def add_reference(outline, color_img, scale: float, margin: int):
    """Paste a small full-color thumbnail in the top-right corner as a color guide."""
    # Outline is single-channel; promote to BGR so we can paint color onto it.
    canvas = cv2.cvtColor(outline, cv2.COLOR_GRAY2BGR)
    h, w = canvas.shape[:2]

    thumb_w = max(1, int(w * scale))
    thumb_h = max(1, int(thumb_w * color_img.shape[0] / color_img.shape[1]))
    # Don't let the thumbnail overflow a small/tall page.
    if thumb_h > h - 2 * margin:
        thumb_h = max(1, h - 2 * margin)
        thumb_w = max(1, int(thumb_h * color_img.shape[1] / color_img.shape[0]))
    thumb = cv2.resize(color_img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)

    x1, y1 = w - margin - thumb_w, margin
    x0, y0 = x1 - 0, y1 - 0  # top-left of thumb
    canvas[y0:y0 + thumb_h, x1:x1 + thumb_w] = thumb
    # Thin black frame so the guide reads as a separate inset.
    cv2.rectangle(canvas, (x1 - 1, y0 - 1), (x1 + thumb_w, y0 + thumb_h), (0, 0, 0), 2)
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
    else:
        outline = to_threshold(gray, args.block_size, args.c)
    if not args.no_reference:
        outline = add_reference(outline, img, args.ref_scale, args.ref_margin)
    return outline


def main() -> int:
    p = argparse.ArgumentParser(description="Turn photos into coloring pages.")
    p.add_argument("--in", dest="in_dir", default="in", help="input folder (default: in)")
    p.add_argument("--out", dest="out_dir", default="out", help="output folder (default: out)")
    p.add_argument("--style", choices=["threshold", "edges"], default="threshold",
                   help="line style (default: threshold)")
    # Tuning knobs (sensible defaults; expose for fiddling).
    p.add_argument("--block-size", type=int, default=9,
                   help="adaptive-threshold neighborhood, odd >=3 (default: 9)")
    p.add_argument("--c", type=int, default=5,
                   help="adaptive-threshold sensitivity; higher = fewer lines (default: 5)")
    p.add_argument("--canny-low", type=int, default=50, help="Canny low threshold (default: 50)")
    p.add_argument("--canny-high", type=int, default=150, help="Canny high threshold (default: 150)")
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
