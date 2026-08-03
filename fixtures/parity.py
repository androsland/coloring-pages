#!/usr/bin/env python3
"""Check that the browser build and the script still draw the same page.

`docs/index.html` re-implements `coloringify.py` in JavaScript — the same
histogram cutoff, the same Zhang-Suen thinning, the same OpenCV calls with the
same constants. Until now the two had only ever been reconciled by hand, which
is exactly the kind of agreement that rots without anyone noticing. A divergence
means the page you preview is not the page the batch script produces.

This drives the real page in real headless Chromium, over a real HTTP server,
with the real opencv.js, against the committed fixtures — and compares the
result to `coloringify.convert()` pixel for pixel. Not "close enough": equal.

    python3 fixtures/parity.py             # run both passes, non-zero on any diff
    python3 fixtures/parity.py --falsify   # break the browser on purpose, check it notices

`--falsify` is a gate too, not just a report: it fails if the set of defects
parity cannot see is anything other than the one written down in KNOWN_BLIND,
in either direction. A newly blind check cannot pass itself off as a known gap,
and a gap that has been closed cannot sit in the list overstating it.

Two passes, because they fail in different ways:

  maths  calls `makeColoringPage()` directly over the same sweep `report.py`
         pins, plus Detail and speck removal, which `report.py` does not cover.
         Catches drift in the duplicated arithmetic and in the hard-coded
         constants (block size, Canny thresholds, minimum speck area).

  wiring drives the actual controls with actual key presses and clicks, and
         reads back the canvas `Download` would hand you. Catches a control
         wired to the wrong field — an `Ink` slider writing `o.detail` renders
         perfectly and matches nothing the user asked for, and the maths pass
         cannot see it, because it never touches a control.

Needs Playwright and a Chromium build, which the script itself does not:

    pip install -r requirements-dev.txt && python3 -m playwright install chromium

and network access, because the page loads opencv.js from the OpenCV CDN. Both
are why this is separate from `report.py`, which stays runnable with nothing but
`requirements.txt`. A missing dependency exits 2 rather than 0 — "could not
check" must not read as "checked, fine".

What this does NOT cover is in fixtures/README.md, under the parity heading.
The short version: the colour-guide inset genuinely differs between the two and
is excluded, and agreement is not correctness — both sides can be wrong
together, and this pass would be silent.
"""

import argparse
import base64
import functools
import http.client
import http.server
import os
import posixpath
import re
import socketserver
import sys
import threading
import urllib.parse
from collections import namedtuple
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from report import (  # noqa: E402
    FIX, INK_LEVELS, NAMES, WIDTHS, page as py_page,
)

# The one fixture the wiring pass drives. It has real strokes, real midtones and
# a white background, so every control moves it: a fixture that ignored a slider
# would turn that step into a comparison of two unchanged pictures.
UI_FIXTURE = "grey-ink"

# Detail (the CLI's --c) at the ends of the slider's range and in the middle.
# report.py only ever renders c=5, so this dimension is checked here or nowhere.
DETAIL_LEVELS = (1, 5, 20)

# Served path for the deliberately-broken copy used by --falsify. It lives under
# the repository's URL space so `/fixtures/*.png` still resolves, but it is
# served from memory — nothing is written inside the repository, or anywhere
# else on disk.
MUTANT_PATH = "/__parity_mutant__.html"

HTML = ROOT / "docs" / "index.html"

# One record per comparison. Both sides are built from this, rather than each
# being given its own settings: a cell whose two halves are configured
# separately can compare the wrong two pictures and still report a pass.
Cell = namedtuple("Cell", "name style detail ink line_width despeckle")


def cell(name, style="threshold", detail=5, ink=4, line_width=0, despeckle=False):
    return Cell(name, style, detail, ink, line_width, despeckle)


def describe(c: Cell) -> str:
    bits = [c.style]
    if c.style == "threshold":
        bits.append(f"detail={c.detail}")
    if c.style == "lineart":
        bits.append(f"ink={c.ink}")
    if c.line_width:
        bits.append(f"width={c.line_width:+d}")
    if c.despeckle:
        bits.append("despeckle")
    return f"{c.name} [{' '.join(bits)}]"


def matrix():
    """Every cell the maths pass compares, in a stable order.

    The three sweeps mirror `report.py` exactly — same fixtures, same widths,
    same ink levels — so parity covers the space the baseline pins rather than
    some adjacent space of its own. Detail and speck removal are added because
    both are duplicated in the browser and neither appears in `report.py`.
    """
    cells = []
    for n in NAMES:
        for s in ("threshold", "edges", "lineart"):
            cells.append(cell(n, s))
        for w in WIDTHS:
            cells.append(cell(n, "threshold", line_width=w))
        for p in INK_LEVELS:
            cells.append(cell(n, "lineart", ink=p))
        for d in DETAIL_LEVELS:
            cells.append(cell(n, "threshold", detail=d))
        cells.append(cell(n, "threshold", despeckle=True))
        cells.append(cell(n, "edges", despeckle=True))
        # Speck removal runs before the line-width pass in both, so the minimum
        # area sees the specks at the size the style drew them. Only a *positive*
        # width can tell the two orderings apart, and the reason is worth stating
        # because the obvious probe is the wrong one: thickening grows a blob that
        # was under the minimum up past it, so speck-removal-after keeps what
        # speck-removal-before deleted. Thinning only ever shrinks, so a blob
        # already doomed stays doomed and both orders agree. This started as a
        # -2 cell asserting it caught an ordering swap; --falsify showed it caught
        # nothing, and on the fixtures only fine-detail at +1 and +2 moves at all
        # (12px and 24px). Both signs are here now: the negative one earns no
        # ordering claim, but it costs one render and would notice a thinning pass
        # that started deleting whole components.
        cells.append(cell(n, "threshold", despeckle=True, line_width=2))
        cells.append(cell(n, "threshold", despeckle=True, line_width=-2))
    seen, out = set(), []
    for c in cells:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ---- the local server ----------------------------------------------------

# The only two prefixes the page or the harness ever asks for. An allowlist
# rather than a denylist: the repository root also holds `in/` (the user's own
# source pictures, gitignored precisely because they are personal or
# copyrighted), `.git/`, and `.gstack/`, which contains a live local agent
# token. A denylist has to name all of those and stay right as the repo grows;
# this cannot be wrong about a directory nobody has created yet.
SERVED_PREFIXES = ("/docs/", "/fixtures/")


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves docs/ and fixtures/ only, plus one in-memory page for --falsify."""

    mutant_html = None

    def _resolved_path(self) -> str:
        """The path this request will actually reach, with `..` collapsed.

        Testing `self.path` as it arrives is not enough. SimpleHTTPRequestHandler
        runs posixpath.normpath *before* it drops `..` components, so
        `/docs/../.git/config` resolves to `<root>/.git/config` on the filesystem
        while still passing a startswith("/docs/") test on the raw string. Collapse
        it here so the allowlist sees the same path the filesystem will.
        """
        raw = urllib.parse.urlsplit(self.path).path
        return posixpath.normpath(urllib.parse.unquote(raw))

    def send_head(self):
        # The one choke point both do_GET and do_HEAD funnel through, so the
        # allowlist cannot be walked around with a different method.
        path = self._resolved_path()
        # A null byte survives normpath and the prefix test — /docs/index.html%00.git
        # is still under /docs/ — and then reaches the stdlib's open(), which raises
        # ValueError and takes the handler thread down with it. Nothing leaks, but
        # an unhandled crash in the one function that exists to be trustworthy is
        # not a good look. Refuse it here.
        if "\x00" in path or not path.startswith(SERVED_PREFIXES):
            self.send_error(404, "Not served")
            return None
        # No directory listings, ever. normpath strips the trailing slash, so "/"
        # and "/docs/" already fail the prefix test — but a directory *inside* an
        # allowed prefix does not, and fixtures/__pycache__/ was listing 631 bytes
        # of build artefacts. The harness only ever asks for files.
        if os.path.isdir(self.translate_path(self.path)):
            self.send_error(404, "Not served")
            return None
        return super().send_head()

    def do_GET(self):
        if self._resolved_path() == MUTANT_PATH:
            body = (_Handler.mutant_html or "").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # Every mutation reuses this one URL, and the response carries no
            # Last-Modified or ETag for the browser to revalidate against — so
            # without this a heuristically cached copy hands the next mutation
            # the previous one's page, and the run records a defect it never
            # actually loaded. no-store, not no-cache: nothing about this
            # response is worth keeping.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


def serve(root: Path):
    """Loopback-only, on an ephemeral port, for the length of the run.

    Rooted at the repository because the page lives at /docs/index.html and the
    fixtures at /fixtures/, but SERVED_PREFIXES is what decides: everything else
    under the root is 404, so `in/`, `.git/` and `.gstack/` are never reachable.
    An earlier version served the whole tree and said so in a comment, on the
    reasoning that loopback and a few seconds is a small window. It is a window
    that costs nothing to close — the harness never requests anything outside
    those two prefixes — and `.gstack/` holds a live local agent token, which the
    comment did not account for. check_server_scope() proves the allowlist holds
    rather than trusting this docstring.
    """
    handler = functools.partial(_Handler, directory=str(root))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


# Paths that must never be served, and the two that must. Sent verbatim over
# http.client rather than urllib, which would helpfully collapse the traversal
# cases client-side and turn them into a test of nothing.
#
# `/in/` and `/.gstack/browse.json` only exist on a machine that has used either,
# so on a fresh clone they would 404 whatever the allowlist did. They are here
# because they name the actual stakes, not because they carry the check —
# `/.git/config`, `/coloringify.py` and both traversal forms exist in every
# checkout, so this cannot pass vacuously.
MUST_404 = ("/", "/docs/", "/fixtures/", "/.git/config", "/.gstack/browse.json",
            "/in/", "/requirements.txt", "/coloringify.py",
            "/docs/../.git/config", "/fixtures/../.gstack/browse.json",
            "/docs/%2e%2e/.git/config", "//.git/config",
            # Null byte: passes the prefix test and used to crash the handler
            # thread inside the stdlib's open(). status() reports a dropped
            # connection as a leak, so a regression here fails loudly.
            "/docs/index.html%00.git", "/fixtures/grey-ink.png%00x",
            # A directory inside an allowed prefix. __pycache__ is the only one
            # that reliably exists, because importing report.py writes it — so
            # under PYTHONDONTWRITEBYTECODE this single entry passes vacuously
            # while every other one still carries the check.
            "/fixtures/__pycache__/", "/fixtures/__pycache__")
MUST_200 = ("/docs/index.html", "/fixtures/grey-ink.png")


def check_server_scope(port: int):
    """Ask the running server for the things it must refuse. Returns what leaked.

    A guard nobody has watched fail is a guard nobody has tested, and the
    traversal cases are the reason this is a request rather than an assertion
    about a string: `/docs/../.git/config` walks straight through a naive
    startswith() on the raw path, and it is the shape a reviewer would use.
    """
    bad = []

    def status(path):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            r.read()
            return r.status
        finally:
            conn.close()

    for p in MUST_404:
        try:
            code = status(p)
        except Exception as e:
            bad.append(f"{p} raised {type(e).__name__}")
            continue
        if code != 404:
            bad.append(f"{p} answered {code}, expected 404")
    for p in MUST_200:
        try:
            code = status(p)
        except Exception as e:
            bad.append(f"{p} raised {type(e).__name__}")
            continue
        if code != 200:
            bad.append(f"{p} answered {code}, expected 200")
    return bad


# ---- talking to the page -------------------------------------------------

# Decode every fixture once per page load. makeColoringPage() takes an
# HTMLImageElement, the same thing an upload produces, so the browser's own PNG
# decode is inside the comparison rather than bypassed by handing it pixels.
LOAD_FIXTURES = """
async (names) => {
  window.__fx = {};
  for (const n of names) {
    const img = new Image();
    img.src = '/fixtures/' + n + '.png';
    await img.decode();
    window.__fx[n] = img;
  }
  return Object.keys(window.__fx).length;
}
"""

# thumb:false because the colour guide is the one part the two do not share —
# see fixtures/README.md. Everything else is the settings the cell asks for.
RENDER_CELL = """
([name, style, detail, ink, lineWidth, despeckle]) => {
  const canvas = makeColoringPage({
    name, img: window.__fx[name], style, detail, ink, lineWidth, despeckle,
    thumb: false, thumbScale: 25, thumbAbove: false,
  });
  return canvas.toDataURL('image/png');
}
"""

# What Download and Print hand the user for card 0. Reading `results` rather
# than the canvas in the DOM is deliberate: the card's swap can be held back a
# frame on purpose, and this is the buffer both buttons actually read.
READ_CARD = "() => results[0].canvas.toDataURL('image/png')"

SETTLE = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"


def to_gray(data_url: str):
    """Decode a canvas PNG back to the single-channel image Python produced.

    cv.imshow() writes a CV_8UC1 Mat out as opaque RGBA with R=G=B, and PNG is
    lossless, so one channel is the original byte.
    """
    raw = base64.b64decode(data_url.split(",", 1)[1])
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    return img[:, :, 0] if img.ndim == 3 else img


def compare(c: Cell, data_url: str):
    """None if the two agree, otherwise what disagrees."""
    js = to_gray(data_url)
    if js is None:
        return "browser returned something that is not an image"
    py = py_page(c.name, c.style, ink=c.ink, line_width=c.line_width,
                 detail=c.detail, despeckle=c.despeckle)
    if js.shape != py.shape:
        return f"size {js.shape} vs {py.shape}"
    wrong = int((js != py).sum())
    if wrong:
        return f"{wrong} of {py.size} px differ ({100.0 * wrong / py.size:.2f}%)"
    return None


def open_page(context, url, errors, timeout=180_000):
    """A page in the *shared* context, deliberately — a fresh context per page
    means a fresh HTTP cache, and opencv.js is a ~10MB file from the CDN.

    Measured, because the obvious version of this claim is wrong: the request is
    made either way (Chromium serves it from cache rather than skipping it, and
    the /4.x/ redirect means two requests per load regardless). What changes is
    the time — about 2.2s per page load in a shared context against 3.0s in a
    fresh one, so roughly 25 seconds over a --falsify battery. Worth having, not
    worth overstating.

    The mutated page itself is sent no-store, so sharing the cache cannot leak
    one mutation's HTML into the next."""
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(url)
        page.wait_for_function(
            "() => typeof cvReady !== 'undefined' && cvReady === true", timeout=timeout)
        page.evaluate(LOAD_FIXTURES, NAMES)
    except Exception:
        page.close()
        raise
    return page


def browser_opencv_version(page) -> str:
    try:
        info = page.evaluate(
            "() => cv.getBuildInformation ? cv.getBuildInformation().slice(0, 600) : ''")
    except Exception:
        return "unknown"
    m = re.search(r"OpenCV\s+([0-9][0-9.]*)", info or "")
    return m.group(1) if m else "unknown"


# ---- the two passes ------------------------------------------------------

def run_maths(page, cells):
    bad = []
    for c in cells:
        url = page.evaluate(RENDER_CELL,
                            [c.name, c.style, c.detail, c.ink, c.line_width, c.despeckle])
        why = compare(c, url)
        if why:
            bad.append(f"{describe(c)}: {why}")
    return bad


INK_LABEL = "Ink coverage (less to more of the picture kept)"
DETAIL_LABEL = "Detail (fewer to more lines)"
WIDTH_LABEL = "Line width (thin to thick)"


def _aria(label, suffix=""):
    return f'[aria-label="{label} for {UI_FIXTURE}{suffix}"]'


def _press(page, label, key):
    """Focus a range and send a real key. `input` moves the state, `change`
    commits — the same two events a mouse drag and release produce."""
    page.locator(f'input[type=range]{_aria(label)}').press(key)


def _type(page, label, text, unit_word=""):
    """Type into the exact-value box, the slider's other commit path. It clamps
    its own input and defers the card's DOM swap by a frame; the range never
    goes near either.

    The values typed below are picked so the step can actually fail. On grey-ink
    only 7 of the 100 ink levels render differently from the level above them —
    the picture is ~90% white paper, so most of the range resolves to the same
    cutoff — and a first version of these steps typed 37 and 500 into Ink, both
    inside a flat stretch. --falsify caught it: a mutation that commits every
    typed value one too high went unnoticed. Detail moves at every one of its 20
    steps, so it carries the clamp check.
    """
    suffix = ", exact value" + (f" in {unit_word}" if unit_word else "")
    box = page.locator(f'input[type=number]{_aria(label, suffix)}')
    box.fill(text)
    box.press("Enter")


UI_STEPS = [
    # (what the step does, how, the settings the page should now be rendering)
    ("turn the colour guide off",
     lambda p: p.uncheck(f'input[type=checkbox]{_aria("Show color guide")}'),
     cell(UI_FIXTURE)),
    ("Detail slider to its minimum",
     lambda p: _press(p, DETAIL_LABEL, "Home"),
     cell(UI_FIXTURE, detail=1)),
    ("Detail slider to its maximum",
     lambda p: _press(p, DETAIL_LABEL, "End"),
     cell(UI_FIXTURE, detail=20)),
    ("Detail typed in as an exact value",
     lambda p: _type(p, DETAIL_LABEL, "7"),
     cell(UI_FIXTURE, detail=7)),
    ("Detail typed far over its maximum, which should clamp to 20",
     lambda p: _type(p, DETAIL_LABEL, "500"),
     cell(UI_FIXTURE, detail=20)),
    ("Remove specks on",
     lambda p: p.check(f'input[type=checkbox]{_aria("Remove specks")}'),
     cell(UI_FIXTURE, detail=20, despeckle=True)),
    ("Remove specks off again",
     lambda p: p.uncheck(f'input[type=checkbox]{_aria("Remove specks")}'),
     cell(UI_FIXTURE, detail=20)),
    ("Line width to Thinnest",
     lambda p: _press(p, WIDTH_LABEL, "Home"),
     cell(UI_FIXTURE, detail=20, line_width=-3)),
    ("Line width to Thickest",
     lambda p: _press(p, WIDTH_LABEL, "End"),
     cell(UI_FIXTURE, detail=20, line_width=3)),
    ("style to Thin",
     lambda p: p.select_option(f'select{_aria("Style")}', "edges"),
     cell(UI_FIXTURE, style="edges", detail=20, line_width=3)),
    ("style to Cartoon",
     lambda p: p.select_option(f'select{_aria("Style")}', "lineart"),
     cell(UI_FIXTURE, style="lineart", detail=20, line_width=3)),
    ("Ink slider to its minimum",
     lambda p: _press(p, INK_LABEL, "Home"),
     cell(UI_FIXTURE, style="lineart", detail=20, ink=1, line_width=3)),
    ("Ink slider to its maximum",
     lambda p: _press(p, INK_LABEL, "End"),
     cell(UI_FIXTURE, style="lineart", detail=20, ink=100, line_width=3)),
    # 29, not a round number: it is one of only seven ink levels on this fixture
    # whose page differs from the level above it, so a value committed one too
    # high has somewhere to show up. See _type().
    ("Ink typed in as an exact value",
     lambda p: _type(p, INK_LABEL, "29", "percent"),
     cell(UI_FIXTURE, style="lineart", detail=20, ink=29, line_width=3)),
    ("style back to Bold",
     lambda p: p.select_option(f'select{_aria("Style")}', "threshold"),
     cell(UI_FIXTURE, detail=20, line_width=3)),
]


def run_wiring(page):
    bad = []
    page.set_input_files("#file", str(FIX / f"{UI_FIXTURE}.png"))
    page.wait_for_function("() => results.length === 1", timeout=60_000)
    for label, act, expected in UI_STEPS:
        act(page)
        page.evaluate(SETTLE)
        why = compare(expected, page.evaluate(READ_CARD))
        if why:
            bad.append(f"after {label} -> {describe(expected)}: {why}")
    return bad


def check(page, cells, verbose=True):
    """Both passes against whatever page is loaded. Returns the failures."""
    bad = run_maths(page, cells)
    if verbose:
        print(f"  maths   {len(cells) - len(bad)}/{len(cells)} cells identical")
    ui = run_wiring(page)
    if verbose:
        print(f"  wiring  {len(UI_STEPS) - len(ui)}/{len(UI_STEPS)} steps identical")
    return bad + ui


# ---- breaking it on purpose ----------------------------------------------

DESPECKLE_BLOCK = """  if (despeckle) {
    const cleaned = despeckleMat(out, DESPECKLE_MIN_AREA);
    out.delete();
    out = cleaned;
  }"""
LINE_WIDTH_BLOCK = """  // Restroke at the chosen weight — applies to every style.
  if (o.lineWidth) {
    const reweighted = setLineWidth(out, o.lineWidth);
    out.delete();
    out = reweighted;
  }"""
ZHANG_SUEN_CORNERS = """          const ok = step === 0
            ? n2 * n4 * n6 === 0 && n4 * n6 * n8 === 0
            : n2 * n4 * n8 === 0 && n2 * n6 * n8 === 0;"""

# (label, old, new). Every one is a way the browser has drifted from the script
# before, could drift, or would drift under an innocent-looking edit.
MUTATIONS = [
    # the histogram cutoff
    ("inkCutoff pinned to a constant 128",
     "  const hist = new Uint32Array(256);",
     "  return 128;\n  const hist = new Uint32Array(256);"),
    ("cutoff at half the requested rate",
     "  const want = n * pct / 100;", "  const want = n * pct / 200;"),
    ("cutoff one V unit low",
     "    if (below >= want) return t;",
     "    if (below >= want) return Math.max(1, t - 1);"),
    ("the cutoff loop skips the darkest bin",
     "  for (let t = 1; t < 256; t++) {", "  for (let t = 2; t < 256; t++) {"),
    ("THRESH_BINARY off by one, so the cutoff pixel inks",
     "cv.threshold(v, out, inkCutoff(v, o.ink) - 1, 255, cv.THRESH_BINARY);",
     "cv.threshold(v, out, inkCutoff(v, o.ink), 255, cv.THRESH_BINARY);"),
    ("Cartoon judges brightness by luma instead of V",
     "    const v = channels.get(2);", "    const v = gray.clone();"),
    # the thinning
    ("thinning depth-capped at 1",
     "  for (let r = 0; r < rounds; r++) {",
     "  for (let r = 0; r < Math.min(rounds, 1); r++) {"),
    ("thinning depth-capped at 2",
     "  for (let r = 0; r < rounds; r++) {",
     "  for (let r = 0; r < Math.min(rounds, 2); r++) {"),
    ("the paper border round the ink buffer becomes ink",
     "  const ink = new Uint8Array(pw * (h + 2));     // zero-filled = paper border",
     "  const ink = new Uint8Array(pw * (h + 2)).fill(1);  // ink border"),
    ("Zhang-Suen neighbour range widened to 7",
     "          if (b < 2 || b > 6) continue;   // endpoint (keep) or interior (keep)",
     "          if (b < 2 || b > 7) continue;"),
    ("the connectivity test accepts 2 transitions",
     "          if (a !== 1) continue;          // >1 means deleting would disconnect",
     "          if (a > 2) continue;"),
    ("both sub-passes clear the same corners",
     ZHANG_SUEN_CORNERS,
     """          const ok = n2 * n4 * n6 === 0 && n4 * n6 * n8 === 0;"""),
    ("sub-passes batch-delete per round instead of per pass",
     "      if (doomed.length) {\n        changed = true;\n        for (const p of doomed) ink[p] = 0;\n      }",
     "      if (doomed.length) { changed = true; }\n"
     "      if (step === 1) { for (const p of doomed) ink[p] = 0; }"),
    # the thickening
    ("thickening kernel weakened to a 2x2 rectangle",
     "  const k = cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(3, 3));",
     "  const k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(2, 2));"),
    ("thickening magnitude-blind",
     "  cv.erode(bin, out, k, new cv.Point(-1, -1), rounds,",
     "  cv.erode(bin, out, k, new cv.Point(-1, -1), 1,"),
    ("setLineWidth a no-op",
     "  if (w < 0) return thinMat(bin, -w);\n  if (w > 0) return fattenMat(bin, w);",
     "  if (false) return bin;"),
    ("the line-width range loses its deepest step",
     "const LINE_WIDTH_MIN = -3;", "const LINE_WIDTH_MIN = -2;"),
    # the style constants
    ("adaptive threshold block size 9 -> 11",
     "cv.adaptiveThreshold(blur, out, 255, cv.ADAPTIVE_THRESH_MEAN_C, cv.THRESH_BINARY, 9, C);",
     "cv.adaptiveThreshold(blur, out, 255, cv.ADAPTIVE_THRESH_MEAN_C, cv.THRESH_BINARY, 11, C);"),
    ("Detail off by one on the way into adaptiveThreshold",
     "    const C = detail;                         // higher = fewer lines",
     "    const C = detail + 1;"),
    ("median blur 5 -> 3 before the adaptive threshold",
     "    cv.medianBlur(gray, blur, 5);", "    cv.medianBlur(gray, blur, 3);"),
    # Both halves of Canny, deliberately. The low one is the single defect parity
    # cannot see on these fixtures, and pairing it with the high one keeps that
    # from reading as "Canny is a blind spot": the high threshold is caught, so
    # the gap is exactly one parameter wide and the harness demonstrates it
    # rather than a comment asserting it.
    ("Canny low threshold 50 -> 60",
     "    cv.Canny(blur, out, 50, 150);", "    cv.Canny(blur, out, 60, 150);"),
    ("Canny high threshold 150 -> 100",
     "    cv.Canny(blur, out, 50, 150);", "    cv.Canny(blur, out, 50, 100);"),
    ("Gaussian blur 5x5 -> 3x3 before Canny",
     "    cv.GaussianBlur(gray, blur, new cv.Size(5, 5), 0);",
     "    cv.GaussianBlur(gray, blur, new cv.Size(3, 3), 0);"),
    # speck removal
    ("minimum speck area 12 -> 20",
     "const DESPECKLE_MIN_AREA = 12;", "const DESPECKLE_MIN_AREA = 20;"),
    ("speck area boundary excludes blobs of exactly min-area",
     "    keep[i] = stats.intAt(i, cv.CC_STAT_AREA) >= minArea ? 1 : 0;",
     "    keep[i] = stats.intAt(i, cv.CC_STAT_AREA) > minArea ? 1 : 0;"),
    ("speck detection drops to 4-connectivity",
     "cv.connectedComponentsWithStats(inkMask, labels, stats, centroids, 8, cv.CV_32S);",
     "cv.connectedComponentsWithStats(inkMask, labels, stats, centroids, 4, cv.CV_32S);"),
    ("speck removal runs after the line-width pass instead of before",
     DESPECKLE_BLOCK + "\n\n" + LINE_WIDTH_BLOCK,
     LINE_WIDTH_BLOCK + "\n\n" + DESPECKLE_BLOCK),
    # the controls — invisible to the maths pass, which never touches one
    ("the Ink slider writes o.detail",
     "      (v) => { o.ink = v; }, commit, { unit: '%' }));",
     "      (v) => { o.detail = v; }, commit, { unit: '%' }));"),
    ("the Line width slider is dead",
     "    (v) => { o.lineWidth = v; }, commit, { labels: LINE_WIDTH_LABELS }));",
     "    (v) => { }, commit, { labels: LINE_WIDTH_LABELS }));"),
    ("the Detail slider is dead",
     "      (v) => { o.detail = v; }, commit));", "      (v) => { }, commit));"),
    ("Remove specks never turns on",
     "    (c) => { o.despeckle = c; commit(); }));",
     "    (c) => { o.despeckle = false; commit(); }));"),
    ("the style dropdown sends Cartoon to Bold",
     "    'Style for ' + o.name, (v) => { o.style = v; commit(); }));",
     "    'Style for ' + o.name, (v) => { o.style = v === 'lineart' ? 'threshold' : v; commit(); }));"),
    ("a typed value commits one too high",
     "      const v = Number.isFinite(typed) ? Math.max(min, Math.min(max, typed))\n"
     "                                       : parseInt(range.value, 10);",
     "      const v = Number.isFinite(typed) ? Math.max(min, Math.min(max, typed)) + 1\n"
     "                                       : parseInt(range.value, 10);"),
]


# Mutations parity is known not to catch, each with the reason it cannot.
# Checked rather than merely recorded: --falsify fails if the set of misses is
# not exactly this one. `falsify.py` prints "only acceptable if README.md lists
# it as an uncovered gap" and then trusts whoever is reading to go and look —
# which works right up until a claim quietly goes blind and its miss reads as
# one of the known ones. Both directions matter: a gap that gets closed has to
# be deleted from here too, or this list starts overstating the blind spots
# instead of understating them.
KNOWN_BLIND = {
    "Canny low threshold 50 -> 60": (
        "Every fixture is drawn by code with hard edges, so Canny's hysteresis "
        "never has a weak edge to reject. Measured on the Python side: no "
        "fixture's Thin output moves for any low threshold from 10 to 80, and "
        "only pale-ink (at 120) and full-bleed (at 149) move anywhere below the "
        "high threshold of 150. The high threshold is covered, and the mutation "
        "above it demonstrates that rather than this sentence asserting it: "
        "150 -> 100 fails 5 cells. So the gap is exactly one parameter wide. "
        "Closing it needs a fixture with soft, low-contrast edges — a new "
        "fixture and a new baseline, not a wider sweep."
    ),
}


def mutate(html: str, label: str, old: str, new: str) -> str:
    """Apply one defect, refusing to pretend a missed target is an unbreakable
    claim. A silent no-op replace looks exactly like a check that cannot be
    fooled, and that reading has been produced for real on this repository."""
    if old not in html:
        raise AssertionError(
            f"mutation target is not present in docs/index.html: {label}\n"
            f"  looked for: {old[:90]!r}\n"
            "  The page moved. Fix the mutation rather than recording a pass.")
    return html.replace(old, new, 1)


def falsify(context, port, cells):
    healthy = HTML.read_text()
    caught, missed = [], []
    for i, (label, old, new) in enumerate(MUTATIONS):
        # Stamp each mutant so the page can be asked which one it is. Applying a
        # defect to a string is only half the job: it still has to reach the
        # browser, and a stale cached copy of the previous mutation would look
        # exactly like a defect nothing can catch — the delivery-side version of
        # the silent no-op replace that mutate() guards against.
        _Handler.mutant_html = (mutate(healthy, label, old, new)
                                + f"\n<script>window.__mutant = {i};</script>\n")
        errors, bad, page = [], None, None
        # A mutant that throws, hangs the render or never reaches cvReady is
        # caught just as surely as one that draws the wrong pixels — the page is
        # visibly broken. Recorded in its own words so it is not read as a
        # pixel-level catch. The stale-page assertion below is deliberately NOT
        # swallowed here: it means the run itself is unsound, not that a defect
        # was found, and burying it as a catch is the failure it exists to stop.
        try:
            page = open_page(context, f"http://127.0.0.1:{port}{MUTANT_PATH}",
                             errors, timeout=60_000)
        except Exception as e:
            bad = [f"the page never became ready: {type(e).__name__}"]
        if page is not None:
            try:
                served = page.evaluate("() => window.__mutant")
                if served != i:
                    raise AssertionError(
                        f"the browser loaded mutant {served}, not {i} ({label}). "
                        "A stale page makes every result in this run meaningless.")
                try:
                    bad = check(page, cells, verbose=False)
                except Exception as e:
                    bad = [f"the page broke: "
                           f"{type(e).__name__}: {str(e).splitlines()[0][:110]}"]
            finally:
                page.close()
        if errors:
            bad = bad + [f"{len(errors)} script error(s): {errors[0][:120]}"]
        # Flushed: a full battery is a browser launch per mutation and takes
        # minutes, so a redirected run that shows nothing until the end is
        # indistinguishable from one that has hung.
        if bad:
            caught.append((label, len(bad)))
            print(f"  caught  {label:<58} {len(bad)} cell(s)", flush=True)
        else:
            missed.append(label)
            print(f"  MISSED  {label:<58} every cell matched", flush=True)
    print(f"\n{len(caught)}/{len(MUTATIONS)} caught.")
    unexpected = [m for m in missed if m not in KNOWN_BLIND]
    closed = [m for m in KNOWN_BLIND if m not in missed]
    if missed:
        print("\nNot caught:")
        for label in missed:
            why = KNOWN_BLIND.get(label)
            print(f"  - {label}")
            if why:
                print(f"      known: {why}")
    if unexpected:
        print("\n  [FAIL] the ones above without a reason are new blind spots. "
              "Either fix the cell\n"
              "         that should have caught them, or add them to KNOWN_BLIND "
              "with the measurement\n"
              "         that shows why they cannot be caught. Do not weaken the "
              "mutation to get a\n"
              "         clean score — that is the hollow claim this file exists "
              "to prevent.")
    if closed:
        print("\n  [FAIL] these are listed in KNOWN_BLIND but were caught, so the "
              "list now overstates\n"
              "         the blind spots. Delete them:")
        for label in closed:
            print(f"           - {label}")
    return 1 if (unexpected or closed) else 0


# ---- entry point ---------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--falsify", action="store_true",
                    help="break docs/index.html on purpose and check parity notices")
    args = ap.parse_args()

    missing = [n for n in NAMES if not (FIX / f"{n}.png").exists()]
    if missing:
        print(f"Missing fixtures: {', '.join(missing)}. Run fixtures/make_fixtures.py.",
              file=sys.stderr)
        return 2
    if not HTML.exists():
        print(f"Missing {HTML.relative_to(ROOT)} — nothing to compare against.",
              file=sys.stderr)
        return 2
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError:
        print("Playwright is not installed, so the browser half of this cannot run.\n"
              "  pip install -r requirements-dev.txt\n"
              "  python3 -m playwright install chromium\n"
              "Exiting 2: 'could not check' is not 'checked, fine'.", file=sys.stderr)
        return 2

    cells = matrix()
    httpd, port = serve(ROOT)
    errors = []
    try:
        leaked = check_server_scope(port)
        if leaked:
            print("The harness server is serving more than docs/ and fixtures/, "
                  "which puts `in/`,\n.git/ and .gstack/ on a local port. Refusing "
                  "to run:", file=sys.stderr)
            for line in leaked:
                print(f"  {line}", file=sys.stderr)
            return 2
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except PlaywrightError as e:
                print(f"Could not launch Chromium: {e}\n"
                      "  python3 -m playwright install chromium", file=sys.stderr)
                return 2
            context = browser.new_context()
            try:
                page = open_page(context, f"http://127.0.0.1:{port}/docs/index.html",
                                 errors)
                js_cv, py_cv = browser_opencv_version(page), cv2.__version__
                print(f"OpenCV: browser {js_cv} (from the CDN, whatever /4.x/ points at "
                      f"today) vs python {py_cv}")
                if js_cv != py_cv:
                    print("  WARN  the two are not the same build. Any failure below "
                          "may be OpenCV's own\n"
                          "        numerical drift rather than this repository's — "
                          "triage it before assuming a regression.")
                print(f"\n{len(cells)} maths cells, {len(UI_STEPS)} wiring steps, "
                      f"{len(NAMES)} fixtures\n")
                bad = check(page, cells)
                page.close()

                if bad:
                    print(f"\n  [FAIL] the browser and the script disagree "
                          f"({len(bad)} cell(s))")
                    for line in bad:
                        print(f"         {line}")
                    if args.falsify:
                        print("\nNot running --falsify: the healthy build already "
                              "fails, so nothing below would mean anything.")
                    return 1
                print("\n  [PASS] docs/index.html and coloringify.py draw the same "
                      "page, pixel for pixel")
                if errors:
                    print(f"  [FAIL] the page logged {len(errors)} script error(s): "
                          f"{errors[:3]}")
                    return 1

                if args.falsify:
                    print("\nBreaking the browser on purpose\n", flush=True)
                    return falsify(context, port, cells)
            finally:
                browser.close()
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
