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
the same maths; `fixtures/parity.py` is what holds the two together, driving the
real page over this same sweep and failing if a single pixel differs. It needs
Playwright and network access, which is why it is a separate script — this one
runs on nothing but requirements.txt.
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
    _thin_pass, convert, ink_cutoff, load_bgr, set_line_width,
)

FIX = Path(__file__).resolve().parent
NAMES = ["grey-ink", "saturated-ink", "pale-ink", "full-bleed", "flat-bands",
         "fine-detail", "ink-ramp"]

# Fixtures with actual strokes in them. ink-ramp is a smooth gradient with no
# edges, so adaptive threshold finds nothing to ink and it reads 0.00% at every
# line width — there is no stroke there to thin or thicken. Excluded from the
# line-width claims for that reason and no other; it still takes part in every
# claim about the ink cutoff, which is what it was drawn for.
STROKE_NAMES = [n for n in NAMES if n != "ink-ramp"]

BASELINE = FIX / "baseline.json"

# Sweep points. Defined once because measure(), the claims and the printed
# tables all have to agree: a claim that asserts over a different set than the
# one recorded is a claim about nothing.
WIDTHS = (-3, -2, -1, 0, 1, 2, 3)
INK_LEVELS = (1, 2, 4, 8, 16, 50, 100)

# Fixtures allowed not to respond to a slider, each for a stated reason. Named
# individually rather than counted, because a bare "at least N of them must
# respond" floor turned out to be trivially gameable: a cutoff that froze --ink
# on exactly three images scored 3/7 against a floor of 3 and passed, with the
# slider dead on four of seven pictures. Anything not listed here must respond on
# its own, so killing any single one of them fails loudly and names the fixture.
#
# fine-detail is pure black on pure white, so every level from 1% to 100%
# resolves to the same cutoff — correct for an image with no midtones.
INK_MAY_BE_FLAT = {"fine-detail"}
# flat-bands reaches a Zhang-Suen skeleton by -2, so -3 correctly does nothing.
DEEPEST_MAY_CONVERGE = {"flat-bands"}
# What actually earns a place in INK_MAY_BE_FLAT. Counting brightness levels was
# the wrong test: an image can have exactly two levels and still respond fine.
# Ink at V=50 on a V=250 background moves from 10% to 100% coverage as --ink
# rises, because the cutoff can be raised past 250. fine-detail cannot only
# because its light level is 255 and ink_cutoff caps there (coloringify.py:61),
# so no request can ever reach past the background. That cap is the invariant, so
# that is what gets checked: two levels, the upper one at the ceiling.
MAX_FLAT_LEVELS = 2
FLAT_REQUIRES_MAX_V = 255

# How far achieved ink coverage may stray from the percentage requested, in
# percentage points, on the one fixture where the question is meaningful.
#
# Absolute rather than a ratio. A ratio band has to be wide at the bottom of the
# range, where quantisation dominates — `--ink 1` lands at 1.25%, a ratio of 1.25
# that is arithmetic, not error — and that width then carries all the way up,
# where it means something entirely different: a 0.65 ratio at `--ink 100` is a
# 35-point shortfall, and a band loose enough to accept 1.25 at the bottom
# accepts that too. Measured in points the ramp behaves uniformly: the achievable
# coverages are multiples of one pixel column, 100/240 = 0.417 points, so every
# level should land within about one column of the request regardless of size.
# Healthy build's worst is 0.42; a 10% miscalibration misses by 10.4.
RAMP_TOLERANCE_PP = 0.7


def ink_pct(binary):
    return round(float((binary == 0).mean()) * 100, 2)


def page(name, style, ink=4.0, line_width=0, detail=5, despeckle=False):
    """Render a fixture through the CLI's own dispatch, with one deviation.

    Goes through `convert()` rather than calling to_threshold / to_edges /
    to_lineart directly. An earlier version reimplemented that branching here,
    which made one claim a tautology — it compared two outputs this file had
    already routed identically, so it was testing the test. Worse, nothing then
    exercised `convert()`'s own dispatch, where a regression that leaked --ink
    into Bold would actually live.

    The deviation: `no_reference=True`, where the CLI defaults to False and does
    paste the colour thumbnail. That keeps the ink percentages measuring the
    outline instead of the thumbnail's pixels, but it means `add_reference()` is
    never exercised here and no claim would notice it breaking. Every other field
    matches main()'s real defaults.

    `detail` (the CLI's `--c`) and `despeckle` default to the CLI's own defaults,
    so every claim in this file renders exactly what it did before they became
    parameters. They exist for parity.py, which sweeps both against the browser
    and needs one place where the Namespace is built — a second copy of these
    defaults is a second thing to drift.
    """
    args = argparse.Namespace(
        block_size=9, c=detail, canny_low=50, canny_high=150,
        ink=ink, line_width=line_width,
        despeckle=despeckle, min_area=12,
        no_reference=True, ref_scale=0.25, ref_margin=15,
    )
    return convert(FIX / f"{name}.png", style, args)


def measure():
    """Every number the report asserts on, keyed for a stable diff."""
    data = {}
    for name in NAMES:
        v = cv2.cvtColor(load_bgr(FIX / f"{name}.png"), cv2.COLOR_BGR2HSV)[:, :, 2]
        entry = {
            "ink_cutoff_at_4pct": int(ink_cutoff(v, 4.0)),
            # How many brightness levels the image actually contains. Half of
            # what earns a place in INK_MAY_BE_FLAT — on its own it proves
            # nothing, since a two-level image responds perfectly well when the
            # cutoff can be raised past its lighter level. See max_v.
            "distinct_v": int((np.bincount(v.ravel(), minlength=256) > 0).sum()),
            # The brightest level present. Paired with distinct_v it is what
            # earns an INK_MAY_BE_FLAT place: ink_cutoff caps at 255, so a
            # two-level image can only be immovable if its light level is 255.
            "max_v": int(v.max()),
            "styles": {s: ink_pct(page(name, s)) for s in ("threshold", "edges", "lineart")},
            "line_width": {
                str(w): ink_pct(page(name, "threshold", line_width=w))
                for w in WIDTHS
            },
            "ink_levels": {
                str(p): ink_pct(page(name, "lineart", ink=p))
                for p in INK_LEVELS
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
    return (old_rule < 0.5 and now > MIN_SATURATED_PCT,
            f"old rule keeps {old_rule:.2f}% (near-blank), current keeps {now:.2f}% "
            f"(floor {MIN_SATURATED_PCT}%)")


def claim_cutoff_adapts(data):
    """README: the same `--ink 4` resolves to a wide span of cutoffs — the
    number is image-specific, which is the whole reason it is measured rather
    than fixed. (The pre-fixture README quoted 21 to 229 from the private art in
    `in/`; the committed set spans 10 to 237.)

    Spread only. This says the cutoff *varies by image*; it does not say the
    cutoff is *right*. Any per-image brightness statistic — min, mean, median,
    a fixed fraction of the range — varies across differently-lit fixtures and
    clears this bar. claim_ink_level_moves_the_ink and
    claim_ink_percentage_is_calibrated are what hold the cutoff to the
    percentage actually asked for; the three are only meaningful together.
    """
    cuts = {n: data[n]["ink_cutoff_at_4pct"] for n in NAMES}
    lo, hi = min(cuts.values()), max(cuts.values())
    return (hi - lo >= 40,
            f"cutoff at --ink 4 spans {lo}..{hi} across fixtures ({cuts})")


def claim_ink_level_moves_the_ink(data):
    """`--ink N` is documented as "keep the darkest N% as ink". So raising it
    must never remove ink, and must actually reach different pictures.

    The companion to claim_cutoff_adapts, and the reason that one is not enough
    on its own. Replacing the percentile search with `min + 0.15*(max-min)`
    throws the requested percentage away entirely — `--ink 1` and `--ink 100`
    then render identically — yet the cutoffs still span 53..212 across these
    fixtures, so the spread claim passes and the slider is dead.

    Ordering alone does not catch that either: a dead slider is flat, and flat
    is non-decreasing. Hence the second half, requiring each fixture outside
    INK_MAY_BE_FLAT to respond on its own.

    Per fixture, not counted across them. A "at least 3 of 7 must respond" floor
    stood here first and was worth very little: a cutoff that returned a fixed 90
    for any image with a thin histogram froze --ink on pale-ink, full-bleed and
    flat-bands, scored exactly 3/7, and passed with the slider dead on four of
    the seven pictures. Naming the one fixture that may legitimately be flat
    costs nothing and removes the whole class.
    """
    bad, responding = [], []
    for name in NAMES:
        seq = [data[name]["ink_levels"][str(p)] for p in INK_LEVELS]
        if any(b < a for a, b in zip(seq, seq[1:])):
            bad.append(f"{name}: more ink asked for, less delivered {seq}")
        if len(set(seq)) >= 2:
            responding.append(name)
        elif name not in INK_MAY_BE_FLAT:
            bad.append(f"{name}: --ink changes nothing across {INK_LEVELS} "
                       f"(all {seq[0]}%); the cutoff is ignoring the percentage "
                       f"it was handed")
    # The exemption list has to keep earning itself, exactly as STROKE_NAMES
    # does. Otherwise the cheapest way past this claim is to add a name to it:
    # padding INK_MAY_BE_FLAT with the three fixtures a broken cutoff had frozen
    # made the report read "3/7 respond, every one outside [...]" and pass. A
    # fixture may only be listed if its histogram genuinely leaves the cutoff
    # nowhere to go.
    for name in sorted(INK_MAY_BE_FLAT):
        levels, top = data[name]["distinct_v"], data[name]["max_v"]
        if levels > MAX_FLAT_LEVELS or top != FLAT_REQUIRES_MAX_V:
            bad.append(f"{name} is exempted from responding to --ink on the "
                       f"grounds that no cutoff can move it, but it has {levels} "
                       f"brightness levels topping out at V={top} (needs "
                       f"<={MAX_FLAT_LEVELS} levels with the highest at "
                       f"{FLAT_REQUIRES_MAX_V}) — the exemption is not earned")
    return not bad, (f"never decreasing; {len(responding)}/{len(NAMES)} fixtures "
                     f"respond, every one outside {sorted(INK_MAY_BE_FLAT)}"
                     if not bad else "; ".join(bad))


def claim_ink_percentage_is_calibrated(data):
    """`--ink N` is documented as keeping 'the darkest N%' — so the number has to
    mean the percentage, not merely a direction.

    Responsiveness and ordering both miss this. A cutoff that honours the request
    at half the rate asked for still varies per image, still never loses ink as
    the slider rises, and still moves at every level; it just quietly inks half
    of what was asked. Every other claim here passes it.

    Only ink-ramp can answer the question. A linear left-to-right gradient has one
    pixel column per brightness step, so the p-th percentile lands at p% by
    construction and achieved coverage is comparable to the request. The other
    fixtures have lumpy histograms on purpose — flat-bands overshoots --ink 4 by
    four times, which is a documented property of the cutoff being an integer V,
    not a defect — so measuring calibration on them would assert the noise.

    Measured in percentage points, not as a ratio. A ratio band wide enough for
    the bottom of the range, where one pixel column is a quarter of the request,
    is far too wide at the top, where the same ratio is a 35-point hole: scaling
    every request by 0.65 held the ratio inside 0.6-1.5 at every level and passed
    this claim while under-inking by a third. Points do not have that problem.
    """
    bad, devs = [], {}
    for p in INK_LEVELS:
        got = data["ink-ramp"]["ink_levels"][str(p)]
        dev = got - p
        devs[p] = round(dev, 2)
        if abs(dev) > RAMP_TOLERANCE_PP:
            bad.append(f"--ink {p} inked {got}% ({dev:+.2f}pp, "
                       f"tolerance {RAMP_TOLERANCE_PP}pp)")
    return not bad, (f"ink-ramp lands within {RAMP_TOLERANCE_PP}pp of the request "
                     f"at every level, deviations {devs}"
                     if not bad else "; ".join(bad))


def claim_only_2x2_vanishes(_data):
    """README and set_line_width's docstring: thinning 'will not break a line,
    pull its ends back, or erase a lone pixel', except 'an isolated 2x2 block of
    ink is erased outright'. Shapes are at the coordinates make_fixtures.py drew.

    Checked at every depth the CLI offers, not just -1. An earlier version only
    ever called set_line_width(mask, -1), which left the guarantee unverified at
    exactly the settings that stress it hardest: bolting a plain 3x3 erosion onto
    every pass after the first leaves -1 untouched and passes this claim, while
    -3 erases the drawing down to a blank page. Erosion doing precisely that is
    why Zhang-Suen was chosen over it, so the one claim guarding that choice has
    to look past the first iteration.

    This is a survival check, not a pixel count: 4x4 legitimately drops from 3px
    to 1px between -1 and -2 as it converges to its skeleton. What must never
    happen is a shape reaching zero.
    """
    img = load_bgr(FIX / "fine-detail.png")
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2]
    mask = np.where(v < 128, 0, 255).astype(np.uint8)
    regions = {                    # (label, y0,y1, x0,x1, must_survive)
        "lone pixel": (94, 99, 28, 33, True),
        "2x2 block": (94, 100, 58, 64, False),
        "3x3 block": (94, 101, 88, 95, True),
        "4x4 block": (94, 102, 118, 126, True),
        "2x8 bar": (94, 100, 148, 160, True),
        "1px line": (74, 79, 20, 221, True),
    }
    depths = [w for w in WIDTHS if w < 0]
    notes, ok = [], True
    for depth in depths:
        thin = set_line_width(mask, depth)
        left_at = []
        for label, (y0, y1, x0, x1, must) in regions.items():
            left = int((thin[y0:y1, x0:x1] == 0).sum())
            good = (left > 0) == must
            ok &= good
            left_at.append(f"{label}={left}px{'' if good else ' UNEXPECTED'}")
        notes.append(f"at {depth:+d}: " + ", ".join(left_at))
    return ok, "; ".join(notes)


# Minimum movement either side of Normal, per direction. Observed minima across
# the fixtures are 4.13 thinning and 6.03 thickening, so these sit roughly a
# quarter below what a healthy build delivers rather than at a token distance
# from zero. One shared floor of 2.0 stood here first and was far too generous:
# swapping the thickening kernel from a 3x3 ellipse to a 2x2 rect halves the
# slider's effect, dropping the smallest thickening to 3.11pp, and passed.
MIN_THIN_PP = 3.0
MIN_THICK_PP = 4.5

# Coverage the current ink rule must keep on saturated-ink, where the old
# `V < 120 && S < 60` rule kept nothing. Healthy reads 9.51%. A floor of 2.0
# stood here first, which a one-unit systematic undercount in ink_cutoff cleared
# at 3.61% — a 62% loss of the drawing that every claim called fine.
MIN_SATURATED_PCT = 7.0


def claim_line_width_moves_the_ink(data):
    """The slider has to actually mean something in *both* directions: never less
    ink as it rises, and a real change either side of Normal.

    Three hollow versions of this claim have already shipped, each defeated by
    the thing it did not measure. Ordering alone passed against a no-op slider,
    since a flat sequence is trivially non-decreasing. Ordering plus a combined
    end-to-end spread then passed against a slider that thickened but never
    thinned — the working half carried the broken half over the bar. So each
    direction is now bounded on its own. Thinning is the half that matters most:
    it is the Zhang-Suen path the 2x2 claim depends on.

    The fourth was subtler and is why the deepest step is counted separately
    below. Per-side distinct-value counting asks only for two distinct readings
    somewhere on a side, which capping the thinning loop at two iterations
    satisfies: -1 still differs from -2, so the pair is found, while -3 silently
    stops doing anything at all. Comparing -1 against -2 does not catch it
    either — that pair is exactly the one such a cap keeps working. Only the
    deepest step tells them apart."""
    zero = WIDTHS.index(0)
    bad, thins, thicks, deep_moves = [], [], [], 0
    for name in STROKE_NAMES:
        seq = [data[name]["line_width"][str(w)] for w in WIDTHS]
        if seq[0] != seq[1]:
            deep_moves += 1
        normal = seq[zero]
        thin_delta, thick_delta = normal - seq[0], seq[-1] - normal
        thins.append(thin_delta)
        thicks.append(thick_delta)
        if any(b < a for a, b in zip(seq, seq[1:])):
            bad.append(f"{name}: not monotonic {seq}")
        elif thin_delta < MIN_THIN_PP:
            bad.append(f"{name}: thinning barely moves, {normal} -> {seq[0]} "
                       f"({thin_delta:.2f}pp, floor {MIN_THIN_PP})")
        elif thick_delta < MIN_THICK_PP:
            bad.append(f"{name}: thickening barely moves, {normal} -> {seq[-1]} "
                       f"({thick_delta:.2f}pp, floor {MIN_THICK_PP})")
        # Magnitude has to matter, not just direction. A set_line_width that
        # collapses every negative width to -1 and every positive to +1 clears
        # both deltas above — on one fixture by 0.05pp, i.e. by luck of that
        # image's geometry rather than by the check working. Counting distinct
        # settings per side catches it without depending on any threshold.
        # Not "strictly increasing at every step": thinning legitimately
        # converges (flat-bands reads 2.74 at both -3 and -2, because Zhang-Suen
        # reaches a skeleton and further rounds correctly do nothing), so that
        # stricter form would fail the healthy build.
        elif len(set(seq[:zero])) < 2:
            bad.append(f"{name}: thinning ignores magnitude, {seq[:zero]}")
        elif len(set(seq[zero + 1:])) < 2:
            bad.append(f"{name}: thickening ignores magnitude, {seq[zero + 1:]}")
    # The deepest step, demanded of every fixture outside DEEPEST_MAY_CONVERGE.
    # flat-bands legitimately reads the same at -3 and -2 (Zhang-Suen has reached
    # a skeleton and further rounds correctly do nothing), so it is named. A
    # count instead of names was worth little: a thinner that capped depth at 2
    # for "busy" pages only froze saturated-ink and full-bleed, scored exactly
    # 3/6 against a floor of 3, and passed.
    for name in STROKE_NAMES:
        seq = [data[name]["line_width"][str(w)] for w in WIDTHS]
        if seq[0] == seq[1] and name not in DEEPEST_MAY_CONVERGE:
            bad.append(f"{name}: -3 is indistinguishable from -2 "
                       f"(both {seq[0]}%); the deepest thinning setting is not "
                       f"reaching the image")

    # Both exclusions above have to keep earning themselves, or the cheapest way
    # past this claim is to widen a list. Padding DEEPEST_MAY_CONVERGE with the
    # five fixtures a depth-capped thinner had frozen turned a 5/6 failure into a
    # clean pass; nothing checked that list at all while the other two were
    # guarded, and the README claimed all of them were.

    # STROKE_NAMES drops ink-ramp because a smooth gradient gives adaptive
    # threshold no edges, so there is no stroke to thin. Measured on raw pixel
    # counts rather than the table's 2-decimal percentages, which would round a
    # couple of stray pixels to 0.0 and call the exclusion earned.
    for name in NAMES:
        if name in STROKE_NAMES:
            continue
        inked = {w: int((page(name, "threshold", line_width=w) == 0).sum())
                 for w in WIDTHS}
        if any(inked.values()):
            bad.append(f"{name} is excluded from the line-width claims on the "
                       f"grounds that it has no strokes, but it inks {inked} "
                       f"pixels across the widths — either include it or change "
                       f"the reason it is excluded")

    # DEEPEST_MAY_CONVERGE exempts a fixture from moving at -3, on the grounds
    # that Zhang-Suen has already reached a skeleton by -2 and further rounds
    # correctly do nothing. Asked of the algorithm directly rather than inferred
    # from the -3 reading, which would be circular: a depth cap makes -3 equal
    # -2 for reasons that have nothing to do with convergence, and any check
    # built on that equality would bless it. _thin_pass reports whether it can
    # still delete anything, so it separates "converged" from "stopped early".
    for name in sorted(DEEPEST_MAY_CONVERGE):
        ink = (page(name, "threshold", line_width=-2) == 0).astype(np.uint8)
        if _thin_pass(ink.copy(), 0) or _thin_pass(ink.copy(), 1):
            bad.append(f"{name} is exempted from moving at -3 on the grounds "
                       f"that it has converged by -2, but Zhang-Suen can still "
                       f"remove pixels from it — the exemption is not earned")
    return not bad, (f"monotonic everywhere; smallest thinning {min(thins):.2f}pp "
                     f"(floor {MIN_THIN_PP}), smallest thickening {min(thicks):.2f}pp "
                     f"(floor {MIN_THICK_PP}); magnitude distinguishable both sides; "
                     f"{deep_moves}/{len(STROKE_NAMES)} still move at -3, every "
                     f"one outside {sorted(DEEPEST_MAY_CONVERGE)}, which is a "
                     f"converged skeleton at -2"
                     if not bad else "; ".join(bad))


def claim_ink_only_touches_cartoon(_data):
    """`--ink` is documented as a lineart knob. Bold and Thin must ignore it.

    Only meaningful because page() dispatches through convert(): this is a test
    of convert()'s routing, which is where a leak would actually happen. When
    this file did its own branching the comparison could not fail."""
    bad = []
    for name in NAMES:
        for style in ("threshold", "edges"):
            a = ink_pct(page(name, style, ink=1))
            b = ink_pct(page(name, style, ink=90))
            if a != b:
                bad.append(f"{name}/{style} {a}!={b}")
    return not bad, "Bold and Thin unchanged by --ink (through convert)" if not bad else str(bad)


CLAIMS = [
    ("coloured outlines survive the current ink rule", claim_saturated_ink_survives),
    ("the ink cutoff is image-specific, not a constant", claim_cutoff_adapts),
    ("--ink reaches the picture at every level", claim_ink_level_moves_the_ink),
    ("--ink inks the percentage it was asked for", claim_ink_percentage_is_calibrated),
    ("thinning erases the 2x2 block and nothing else, at every depth",
     claim_only_2x2_vanishes),
    ("line width both orders and actually moves the ink", claim_line_width_moves_the_ink),
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
    print(f"  {'fixture':<16}" + "".join(f"{w:>+8}" for w in WIDTHS))
    for n in NAMES:
        print(f"  {n:<16}" + "".join(f"{data[n]['line_width'][str(w)]:>8}" for w in WIDTHS))

    print("\nCartoon at each ink level\n")
    print(f"  {'fixture':<16}" + "".join(f"{p:>7}%" for p in INK_LEVELS))
    for n in NAMES:
        print(f"  {n:<16}" + "".join(f"{data[n]['ink_levels'][str(p)]:>8}" for p in INK_LEVELS))

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
        for scalar in ("ink_cutoff_at_4pct", "distinct_v", "max_v"):
            was_s = old.get(name, {}).get(scalar)
            if was_s != data[name][scalar]:
                drift.append(f"{name}/{scalar}: {was_s} -> {data[name][scalar]}")

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
