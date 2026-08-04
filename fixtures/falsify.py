#!/usr/bin/env python3
"""Break the pipeline on purpose, and check that a claim notices.

`report.py` asserts the claims. This asserts the claims are worth asserting: it
copies the tree to a temporary directory, applies one deliberate defect at a
time, and records which claims fire. A check that has never failed has never
been tested, and on this file's history that is not a figure of speech — the
line-width claim shipped hollow four separate times, each version passing
against the exact build it was written to catch.

The table in README.md is generated from this. Re-derive it with:

    python3 fixtures/falsify.py

Every mutation asserts its target text exists before applying. That matters more
than it sounds: `str.replace` no-ops silently on a missed target, so a mutation
that quietly failed to apply looks identical to a claim that cannot be broken,
and it has already produced one false "unbreakable" reading here.

This gates rather than reports: it exits non-zero when the set of mutations it
cannot catch differs from `KNOWN_BLIND` in either direction. Printing the misses
and trusting the reader to check them against README.md works only while someone
is reading, which is not the case when this runs unattended.

Nothing is written inside the repository. The working tree is never touched.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CUTOFF_BODY = '''    below = np.cumsum(np.bincount(v.ravel(), minlength=256))  # below[i] = count(V <= i)
    want = v.size * pct / 100.0
    # Smallest t >= 1 with count(V < t) >= want; count(V < t) is below[t - 1].
    t = int(np.searchsorted(below, want, side="left")) + 1
    return min(max(t, 1), 255)'''
THIN_LOOP = '''    ink = (binary == 0).astype(np.uint8)
    for _ in range(-width):
        changed = _thin_pass(ink, 0)
        changed |= _thin_pass(ink, 1)
        if not changed:
            break                                    # already 1px everywhere'''

# (label, file, old, new)
MUTATIONS = [
    ("ink_cutoff pinned to constant 128", "c", CUTOFF_BODY, "    return 128"),
    ("ink_cutoff discards pct (min+0.15*range)", "c", CUTOFF_BODY,
     "    t = int(v.min() + 0.15 * (int(v.max()) - int(v.min())))\n    return min(max(t, 1), 255)"),
    ("cutoff at half the requested rate", "c", "    want = v.size * pct / 100.0",
     "    want = v.size * pct / 200.0"),
    ("cutoff at double the requested rate", "c", "    want = v.size * pct / 100.0",
     "    want = v.size * pct / 50.0"),
    ("cutoff scaled x0.95 (5% under)", "c", "def ink_cutoff(v, pct: float) -> int:",
     "def ink_cutoff(v, pct: float) -> int:\n    pct = pct * 0.95"),
    ("cutoff scaled x1.05 (5% over)", "c", "def ink_cutoff(v, pct: float) -> int:",
     "def ink_cutoff(v, pct: float) -> int:\n    pct = pct * 1.05"),
    ("one-V-unit systematic undercount", "c", "    return min(max(t, 1), 255)",
     "    t -= 1\n    return min(max(t, 1), 255)"),
    ("fixed cutoff for thin histograms (3 frozen)", "c", "    below = np.cumsum",
     "    if len(np.unique(v)) < 165:\n        return 90\n    below = np.cumsum"),
    ("fixed cutoff, 1 fixture frozen", "c", "    below = np.cumsum",
     "    if len(np.unique(v)) < 100:\n        return 90\n    below = np.cumsum"),
    ("old S<60 saturation rule reintroduced", "c",
     "    return np.where(v < ink_cutoff(v, ink_pct), 0, 255).astype(np.uint8)",
     "    _s = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]\n"
     "    return np.where((v < 120) & (_s < 60), 0, 255).astype(np.uint8)"),
    ("weakened saturation filter (S<180)", "c",
     "    return np.where(v < ink_cutoff(v, ink_pct), 0, 255).astype(np.uint8)",
     "    _s = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]\n"
     "    return np.where((v < ink_cutoff(v, ink_pct)) & (_s < 180), 0, 255).astype(np.uint8)"),
    ("thinning depth-capped at 1", "c", "    for _ in range(-width):",
     "    for _ in range(min(-width, 1)):"),
    ("thinning depth-capped at 2", "c", "    for _ in range(-width):",
     "    for _ in range(min(-width, 2)):"),
    ("depth cap on busy pages only (2 frozen)", "c", THIN_LOOP,
     '''    ink = (binary == 0).astype(np.uint8)
    _d = -width
    if ink.mean() > 0.08 and _d > 2:
        _d = 2
    for _ in range(_d):
        changed = _thin_pass(ink, 0)
        changed |= _thin_pass(ink, 1)
        if not changed:
            break'''),
    ("depth cap, 1 fixture frozen", "c", THIN_LOOP,
     '''    ink = (binary == 0).astype(np.uint8)
    _d = -width
    if ink.mean() > 0.11 and _d > 2:
        _d = 2
    for _ in range(_d):
        changed = _thin_pass(ink, 0)
        changed |= _thin_pass(ink, 1)
        if not changed:
            break'''),
    ("plain erosion replaces Zhang-Suen", "c",
     THIN_LOOP + "\n    return np.where(ink == 1, 0, 255).astype(np.uint8)",
     "    return cv2.dilate(binary, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), "
     "iterations=-width)"),
    ("erosion bolted on after the first pass", "c", THIN_LOOP,
     '''    ink = (binary == 0).astype(np.uint8)
    for _i in range(-width):
        changed = _thin_pass(ink, 0)
        changed |= _thin_pass(ink, 1)
        if _i > 0:
            ink = cv2.erode(ink, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
        if not changed:
            break'''),
    ("thickening magnitude-blind", "c",
     "        return cv2.erode(binary, k, iterations=width)",
     "        return cv2.erode(binary, k, iterations=1)"),
    ("thickening kernel weakened to RECT(2,2)", "c",
     "        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))",
     "        k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))"),
    ("no-op set_line_width", "c", "    if width == 0:\n        return binary",
     "    if True:\n        return binary"),
    ("line_width dropped inside convert()", "c",
     "    if args.line_width:\n        outline = set_line_width(outline, args.line_width)",
     "    if False and args.line_width:\n        outline = set_line_width(outline, args.line_width)"),
    ("--ink leaked into Bold", "c",
     "        outline = to_threshold(gray, args.block_size, args.c)",
     "        outline = to_threshold(gray, args.block_size, args.c + int(args.ink))"),
    ("--ink leaked into Thin", "c",
     "        outline = to_edges(gray, args.canny_low, args.canny_high)",
     "        outline = to_edges(gray, args.canny_low + int(args.ink), args.canny_high)"),
    ("despeckle ignores its flag", "c",
     "    if args.despeckle:\n        outline = despeckle(outline, args.min_area)",
     "    outline = despeckle(outline, args.min_area)"),
    # exemption-list abuse: mutate report.py itself
    ("pad INK_MAY_BE_FLAT to hide a frozen slider", "both",
     ("    below = np.cumsum", "    if len(np.unique(v)) < 165:\n        return 90\n    below = np.cumsum"),
     ('INK_MAY_BE_FLAT = {"fine-detail"}',
      'INK_MAY_BE_FLAT = {"fine-detail", "pale-ink", "full-bleed", "flat-bands"}')),
    ("pad DEEPEST_MAY_CONVERGE to hide a depth cap", "both",
     ("    for _ in range(-width):", "    for _ in range(min(-width, 2)):"),
     ('DEEPEST_MAY_CONVERGE = {"flat-bands"}',
      'DEEPEST_MAY_CONVERGE = {"flat-bands", "grey-ink", "saturated-ink", "pale-ink",'
      ' "full-bleed", "fine-detail"}')),
    ("widen STROKE_NAMES to drop a real stroke fixture", "r",
     'STROKE_NAMES = [n for n in NAMES if n != "ink-ramp"]',
     'STROKE_NAMES = [n for n in NAMES if n not in ("ink-ramp", "flat-bands")]'),
]

# The misses this battery is allowed to have, each with the measurement that
# says why. Same list and same reasoning as `parity.py`'s: printing "only
# acceptable if README.md lists it as an uncovered gap" trusts whoever is
# reading to go and look, which holds right up until a claim quietly goes blind
# and its miss reads as one of the known ones. Both directions matter — a gap
# that gets closed has to be deleted from here too, or the list starts
# overstating the blind spots instead of understating them.
KNOWN_BLIND = {
    "despeckle ignores its flag": (
        "`page()` always passes `despeckle=False`, so no claim ever reaches the "
        "flag's true branch and the mutation has nothing to change. Measured "
        "rather than asserted: this mutation makes despeckle unconditional in "
        "`convert()` and every claim still passes. Closing it needs a fixture "
        "with specks of known area and a claim that they go at `--min-area` and "
        "survive below it — a new fixture and a new baseline entry, not a wider "
        "sweep of the existing ones. `parity.py` does compare despeckle output "
        "between the browser and the script, so the two cannot drift apart "
        "here; what is missing is a claim about what either should produce."
    ),
}


def _reset(work):
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(REPO / "coloringify.py", work)
    shutil.copytree(REPO / "fixtures", work / "fixtures")


def _apply(work, target, old, new):
    path = work / ("coloringify.py" if target == "c" else "fixtures/report.py")
    text = path.read_text()
    if old not in text:
        raise AssertionError(
            f"mutation target is not present in {path.name}: {old[:70]!r}. "
            f"The code moved; fix the mutation rather than recording a pass."
        )
    path.write_text(text.replace(old, new, 1))


def _run(work):
    p = subprocess.run([sys.executable, "fixtures/report.py"], cwd=work,
                       capture_output=True, text=True)
    fails = [ln.strip()[7:].strip() for ln in p.stdout.splitlines()
             if ln.strip().startswith("[FAIL]")]
    return fails, p.returncode


def main():
    tmp = Path(tempfile.mkdtemp(prefix="coloringify-falsify-"))
    work = tmp / "tree"
    try:
        _reset(work)
        fails, rc = _run(work)
        if fails or rc != 0:
            print("The unmutated build does not pass. Fix that before reading "
                  f"anything below.\n  failing claims: {fails}\n  exit: {rc}")
            return 2
        print(f"healthy control: all claims pass, exit {rc}\n")

        caught = []
        hollow = []
        for entry in MUTATIONS:
            label, kind = entry[0], entry[1]
            _reset(work)
            if kind == "both":
                _apply(work, "c", *entry[2])
                _apply(work, "r", *entry[3])
            else:
                _apply(work, kind, entry[2], entry[3])
            fails, rc = _run(work)
            if fails:
                caught.append((label, fails))
                print(f"  caught  {label:<50} {len(fails)} claim(s)")
            else:
                hollow.append(label)
                print(f"  MISSED  {label:<50} every claim passed (exit {rc})")

        print(f"\n{len(caught)}/{len(MUTATIONS)} caught.")
        unexpected = [m for m in hollow if m not in KNOWN_BLIND]
        closed = [m for m in KNOWN_BLIND if m not in hollow]
        if hollow:
            print("\nNot caught:")
            for label in hollow:
                why = KNOWN_BLIND.get(label)
                print(f"  - {label}")
                if why:
                    print(f"      known: {why}")
        if unexpected:
            print("\n  [FAIL] the ones above without a reason are new blind spots. "
                  "Either fix the claim\n"
                  "         that should have caught them, or add them to "
                  "KNOWN_BLIND with the measurement\n"
                  "         that shows why they cannot be caught. Do not weaken "
                  "the mutation to get a\n"
                  "         clean score — that is the hollow claim this file "
                  "exists to prevent.")
        if closed:
            print("\n  [FAIL] these are listed in KNOWN_BLIND but were caught, so "
                  "the list now overstates\n"
                  "         the blind spots. Delete them:")
            for label in closed:
                print(f"           - {label}")
        return 1 if (unexpected or closed) else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
