#!/usr/bin/env python3
"""Measure the pipeline against the fixtures, and check the claims the code makes.

Two jobs:

1. Print ink coverage per fixture per style, so a change's effect is visible as
   numbers rather than as "looks about the same to me".
2. Assert the specific claims made in README.md and in the source comments. Those
   claims were written from images that cannot be committed (`in/` is gitignored),
   so until now nothing could re-derive them. A claim nobody can check is a claim
   that quietly stops being true.

    python3 fixtures/report.py                    # print + check, non-zero on drift
    python3 fixtures/report.py --update-baseline  # accept current numbers

Covers coloringify.py only. The browser build in docs/index.html re-implements
the same maths and is verified against this one by hand; there is no in-repo
check that the two still agree. See TODOS.md.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coloringify import (  # noqa: E402
    ink_cutoff, load_bgr, set_line_width, to_edges, to_lineart, to_threshold,
)

FIX = Path(__file__).resolve().parent
NAMES = ["grey-ink", "saturated-ink", "pale-ink", "full-bleed", "flat-bands",
         "fine-detail"]
BASELINE = FIX / "baseline.json"


def ink_pct(binary):
    return round(float((binary == 0).mean()) * 100, 2)


def page(img, gray, style, ink=4.0, line_width=0):
    if style == "edges":
        out = to_edges(gray, 50, 150)
    elif style == "lineart":
        out = to_lineart(img, ink)
    else:
        out = to_threshold(gray, 9, 5)
    if line_width:
        out = set_line_width(out, line_width)
    return out


def measure():
    """Every number the report asserts on, keyed for a stable diff."""
    data = {}
    for name in NAMES:
        img = load_bgr(FIX / f"{name}.png")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2]
        entry = {
            "ink_cutoff_at_4pct": int(ink_cutoff(v, 4.0)),
            "styles": {s: ink_pct(page(img, gray, s)) for s in ("threshold", "edges", "lineart")},
            "line_width": {
                str(w): ink_pct(page(img, gray, "threshold", line_width=w))
                for w in (-3, -2, -1, 0, 1, 2, 3)
            },
            "ink_levels": {
                str(p): ink_pct(page(img, gray, "lineart", ink=p))
                for p in (1, 2, 4, 8, 16, 50, 100)
            },
        }
        data[name] = entry
    return data


# ---- the claims ---------------------------------------------------------

def claim_saturated_ink_survives(data):
    """README: the old `V < 120 && S < 60` rule 'produced a near-blank page on
    art whose outlines were dark but *coloured*'."""
    img = load_bgr(FIX / "saturated-ink.png")
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    old_rule = float(((v < 120) & (s < 60)).mean()) * 100
    now = data["saturated-ink"]["styles"]["lineart"]
    return (old_rule < 0.5 and now > 2.0,
            f"old rule keeps {old_rule:.2f}% (near-blank), current keeps {now:.2f}%")


def claim_cutoff_adapts(data):
    """README: 'the same `--ink 4` resolved to cutoffs anywhere from 21 to 229'
    — the number is image-specific, which is the whole reason it is measured."""
    cuts = {n: data[n]["ink_cutoff_at_4pct"] for n in NAMES}
    lo, hi = min(cuts.values()), max(cuts.values())
    return (hi - lo >= 40,
            f"cutoff at --ink 4 spans {lo}..{hi} across fixtures ({cuts})")


def claim_only_2x2_vanishes(_data):
    """README and set_line_width's docstring: thinning 'will not break a line,
    pull its ends back, or erase a lone pixel', except 'an isolated 2x2 block of
    ink is erased outright'. Shapes are at the coordinates make_fixtures.py drew."""
    img = load_bgr(FIX / "fine-detail.png")
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2]
    mask = np.where(v < 128, 0, 255).astype(np.uint8)
    thin = set_line_width(mask, -1)
    regions = {                    # (label, y0,y1, x0,x1, must_survive)
        "lone pixel": (94, 99, 28, 33, True),
        "2x2 block": (94, 100, 58, 64, False),
        "3x3 block": (94, 101, 88, 95, True),
        "4x4 block": (94, 102, 118, 126, True),
        "2x8 bar": (94, 100, 148, 160, True),
        "1px line": (74, 79, 20, 221, True),
    }
    notes, ok = [], True
    for label, (y0, y1, x0, x1, must) in regions.items():
        left = int((thin[y0:y1, x0:x1] == 0).sum())
        good = (left > 0) == must
        ok &= good
        notes.append(f"{label}={left}px{'' if good else ' UNEXPECTED'}")
    return ok, "; ".join(notes)


def claim_line_width_monotonic(data):
    """The slider has to actually mean something: more negative is never more ink."""
    bad = []
    for name in NAMES:
        seq = [data[name]["line_width"][str(w)] for w in (-3, -2, -1, 0, 1, 2, 3)]
        if any(b < a for a, b in zip(seq, seq[1:])):
            bad.append(f"{name}:{seq}")
    return not bad, "non-decreasing everywhere" if not bad else f"not monotonic: {bad}"


def claim_ink_only_touches_cartoon(_data):
    """`--ink` is documented as a lineart knob. Bold and Thin must ignore it."""
    bad = []
    for name in NAMES:
        img = load_bgr(FIX / f"{name}.png")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for style in ("threshold", "edges"):
            a = ink_pct(page(img, gray, style, ink=1))
            b = ink_pct(page(img, gray, style, ink=90))
            if a != b:
                bad.append(f"{name}/{style} {a}!={b}")
    return not bad, "Bold and Thin unchanged by --ink" if not bad else str(bad)


CLAIMS = [
    ("coloured outlines survive the current ink rule", claim_saturated_ink_survives),
    ("the ink cutoff is image-specific, not a constant", claim_cutoff_adapts),
    ("thinning erases the 2x2 block and nothing else", claim_only_2x2_vanishes),
    ("line width is monotonic in every style", claim_line_width_monotonic),
    ("--ink affects Cartoon only", claim_ink_only_touches_cartoon),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update-baseline", action="store_true",
                    help="rewrite baseline.json from the current numbers")
    args = ap.parse_args()

    missing = [n for n in NAMES if not (FIX / f"{n}.png").exists()]
    if missing:
        print(f"Missing fixtures: {', '.join(missing)}. Run fixtures/make_fixtures.py.",
              file=sys.stderr)
        return 2

    data = measure()

    print("Ink coverage per style (% of the page)\n")
    print(f"  {'fixture':<16}{'Bold':>8}{'Thin':>8}{'Cartoon':>9}{'cutoff@4%':>11}")
    for n in NAMES:
        s, c = data[n]["styles"], data[n]["ink_cutoff_at_4pct"]
        print(f"  {n:<16}{s['threshold']:>8}{s['edges']:>8}{s['lineart']:>9}{c:>11}")

    print("\nBold at each line width\n")
    widths = (-3, -2, -1, 0, 1, 2, 3)
    print(f"  {'fixture':<16}" + "".join(f"{w:>+8}" for w in widths))
    for n in NAMES:
        print(f"  {n:<16}" + "".join(f"{data[n]['line_width'][str(w)]:>8}" for w in widths))

    print("\nCartoon at each ink level\n")
    levels = (1, 2, 4, 8, 16, 50, 100)
    print(f"  {'fixture':<16}" + "".join(f"{p:>7}%" for p in levels))
    for n in NAMES:
        print(f"  {n:<16}" + "".join(f"{data[n]['ink_levels'][str(p)]:>8}" for p in levels))

    print("\nClaims\n")
    failures = 0
    for label, fn in CLAIMS:
        ok, note = fn(data)
        failures += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}\n         {note}")

    if args.update_baseline:
        BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        print(f"\nBaseline written to {BASELINE.relative_to(ROOT)}")
        return 1 if failures else 0

    if not BASELINE.exists():
        print("\nNo baseline yet — run with --update-baseline to record one.")
        return 1 if failures else 0

    old = json.loads(BASELINE.read_text())
    drift = []
    for name in NAMES:
        for section in ("styles", "line_width", "ink_levels"):
            for key, now in data[name][section].items():
                was = old.get(name, {}).get(section, {}).get(key)
                if was != now:
                    drift.append(f"{name}/{section}/{key}: {was} -> {now}")
        was_cut = old.get(name, {}).get("ink_cutoff_at_4pct")
        if was_cut != data[name]["ink_cutoff_at_4pct"]:
            drift.append(f"{name}/cutoff: {was_cut} -> {data[name]['ink_cutoff_at_4pct']}")

    print("\nBaseline\n")
    if drift:
        print(f"  {len(drift)} value(s) moved since the baseline was recorded:")
        for d in drift:
            print(f"    {d}")
        print("\n  If the change was intended, re-record with --update-baseline")
        print("  and say in the commit why the numbers moved.")
    else:
        print("  no drift")

    return 1 if (failures or drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
