# Fixtures

Seven small images and a report that measures the pipeline against them.

## Why these exist

The tuning behind `Cartoon`'s ink cutoff and the `Line width` thinning was done
against real cartoon art in `in/`, which is gitignored on purpose — those are
copyrighted pictures and must not be committed. That left every number quoted in
`README.md` and in the source comments impossible to re-derive from a clean
checkout, and left both heuristics with nothing to regress against.

So the fixtures are **drawn by code** instead of collected. `make_fixtures.py`
produces every pixel, which means no licence question and no "trust me" — and
each image is built to exercise one specific claim the code makes.

## Running it

```bash
python3 fixtures/report.py                    # print the tables, check the claims
python3 fixtures/report.py --update-baseline  # accept the current numbers
python3 fixtures/make_fixtures.py             # redraw the PNGs (they are committed)
python3 fixtures/falsify.py                   # break the code on purpose, check a claim notices
python3 fixtures/parity.py                    # check the browser draws the same page
python3 fixtures/parity.py --falsify          # break the browser on purpose, check parity notices
```

`report.py` and `falsify.py` need nothing but `requirements.txt`. `parity.py`
also needs Playwright, a Chromium build and network access to the OpenCV CDN —
see "Checking the browser twin" below.

`report.py` exits non-zero if a claim fails or a number has moved since
`baseline.json`. When a change is meant to move the numbers, re-record the
baseline in the same commit and say why they moved.

All four gate, so all four run in CI, split by what makes them fail rather than
by how long they take. `.github/workflows/checks.yml` runs `report.py` and
`parity.py` on every push and pull request — those break when the pipeline
changes. `.github/workflows/mutations.yml` runs `falsify.py` and `parity.py
--falsify` weekly and on demand — those break when the *checking* changes, which
is rarer, and the second of them is ~19 minutes. Nothing runs in CI that cannot
fail; a green job that could never have been red is worse than no job, because
it reads as coverage.

Every render goes through `coloringify.convert()` — the same dispatch the CLI
uses — rather than calling the style functions directly. An earlier version did
its own branching here, which quietly turned one claim into a tautology: it
compared two outputs this file had already routed identically, so it was testing
itself. It also meant nothing exercised `convert()`, which is where a regression
in argument routing would actually live.

## Falsifying the claims

Each claim has been run against a build broken in the specific way that claim
exists to catch, and each one fails there. `falsify.py` is that check, committed
rather than described: it applies 27 deliberate defects one at a time in a
temporary copy of the tree and reports which claims fire. 26 are caught. Run it
and the table below re-derives itself; a table nobody can re-derive is the exact
thing this directory exists to stop.

It gates on that count rather than printing it, on the same rule as `--falsify`
below: the run fails when the set of defects it cannot catch differs from
`KNOWN_BLIND` in either direction. One entry is listed today, `despeckle ignores
its flag`, with the measurement that says why. Printing the misses and trusting
whoever is reading to check them against this file works only while someone is
reading, which is not the case on the schedule that now runs it.

| claim | broken build it was checked against |
|---|---|
| coloured outlines survive | the old fixed `V < 120 && S < 60` rule; a weakened `S < 180` variant |
| the cutoff is image-specific | `ink_cutoff` pinned to a constant 128 |
| `--ink` reaches the picture | `ink_cutoff` returning `min + 0.15*(max-min)`, discarding the requested percentage; a fixed cutoff for thin-histogram images, freezing the slider on three fixtures |
| `--ink` inks the percentage asked for | the percentile honoured at half, at double, and at 0.65x, 0.95x and 1.05x the requested rate |
| the exemption lists are earned | `INK_MAY_BE_FLAT` padded with three fixtures a broken cutoff had frozen; `STROKE_NAMES` widened to drop a fixture that really does have strokes; `DEEPEST_MAY_CONVERGE` padded with the five a depth-capped thinner had frozen |
| coloured outlines survive, by enough | a one-unit systematic undercount in `ink_cutoff`, which left 3.61% against a healthy 9.51% and cleared the old 2.0% floor |
| line width moves the ink, by enough | the thickening kernel weakened from a 3x3 ellipse to a 2x2 rect, halving the slider and clearing the old shared 2.0pp floor at 3.11pp |
| thinning erases only the 2x2 | plain erosion in place of Zhang-Suen; erosion bolted on after the first pass |
| line width moves the ink | a no-op `set_line_width`; magnitude-blind variants; the thinning loop depth-capped at 1 and at 2, and capped only on "busy" pages so it froze just two fixtures; `line_width` dropped in `convert()` |
| `--ink` affects Cartoon only | `--ink` leaked into the Bold path, and into the Thin path, inside `convert()` |

Most of these were added *because* an earlier version passed against a broken
build. The line-width claim alone has shipped hollow four times: ordering only
(a dead slider is flat, and flat is non-decreasing); ordering plus a combined
end-to-end spread (the working half carried the broken half); per-direction
floors (a magnitude-blind slider cleared one fixture by 0.05pp on luck of its
geometry); and per-side distinct-value counting (satisfied by `-1` differing
from `-2`, while `-3` silently stopped doing anything).

The two claims added to close those gaps then shipped hollow themselves, in the
same shape: both accepted "enough fixtures responded" rather than naming which,
and the calibration band was wide enough to pass a systematic 35% under-inking.
Naming the exemptions then moved the weak point onto the lists themselves, one of
which went a full round unguarded while this file said otherwise. Every fix so
far has relocated the problem before it removed it, which is the argument for
attacking each round's *new* code rather than re-checking the old.

The pattern behind all of them is worth naming: each verified the property it set
out to test and assumed the one immediately adjacent. If you add a claim, break
the code on purpose and watch it fail before you trust it — a check that has
never failed has never been tested. Verify the mutation actually applied, too; a
find-and-replace that misses its target passes silently and looks exactly like a
claim that cannot be broken.

## What each fixture is for

| fixture | the claim it holds the code to |
|---|---|
| `grey-ink` | the ordinary case — dark desaturated outlines on white — still works |
| `saturated-ink` | dark *coloured* outlines (navy, teal, brown) survive. The old `V < 120 && S < 60` rule scores **0.00%** here: a blank page |
| `pale-ink` | the cutoff reaches high values too. Its darkest 4% sits at V≈237, so a fixed cutoff of 120 would return nothing |
| `full-bleed` | a picture with no white background. The percentile is measured over the whole image, so framing changes the answer — a documented blind spot, pinned here so it cannot change silently |
| `flat-bands` | large uniform regions, where an integer cutoff makes achieved coverage jump rather than glide |
| `fine-detail` | thinning keeps a lone pixel, 1px lines, 3x3, 4x4 and a 2x8 bar, and erases exactly one shape: the isolated 2x2 block |
| `ink-ramp` | a linear brightness gradient, the only fixture where `--ink N` can be checked against N. One pixel column per brightness step puts the p-th percentile at p%, so achieved coverage is comparable to the request. Every other image has a lumpy histogram on purpose |

Together they put the cutoff for `--ink 4` anywhere from **10 to 237**, which is
the point of measuring it per image rather than fixing it.

## Checking the browser twin

`docs/index.html` is not a different tool that happens to behave similarly — it
is this pipeline written a second time, in JavaScript against opencv.js. Same
histogram cutoff, same Zhang-Suen thinning, same OpenCV calls with the same
constants. Two implementations that must agree but cannot share a line of code
will drift, and until `parity.py` the only thing holding them together was a
hand reconciliation — most recently 54/54 byte-identical cells, a result nobody
else could re-derive and nobody would notice going stale.

```bash
pip install -r requirements-dev.txt
python3 -m playwright install chromium
python3 fixtures/parity.py
```

It serves the repository over a loopback HTTP server, opens the real page in
headless Chromium with the real opencv.js from the CDN, renders these fixtures
through it, and compares the result to `coloringify.convert()` **pixel for
pixel**. Not a tolerance, not a percentage: equal, or it fails and names the
cell. Two passes, because they fail in different ways.

The server answers for `/docs/` and `/fixtures/` and 404s everything else, so
`in/` — your own pictures, gitignored on purpose — along with `.git/` and
`.gstack/` are never on that port. No directories either, at any depth. The
allowlist is checked at startup rather than trusted: `check_server_scope()` sends
the running server twenty request targets it must refuse and two it must serve,
down a raw socket so a client library cannot tidy them up on the way out, and
refuses to run if any answers wrong.

It compares the reason phrase, not just the status code. `404 Not served` is this
gate refusing; the stdlib's `404 File not found` is the allowlist having let the
request through and the filesystem happening to have nothing there — which is a
property of how the repo is laid out today, not a control. Two of the bypasses
below scored 404 on the broken build precisely that way.

Four of the twenty are there because an obvious version of the guard lets them
through, and every one of them did:

- `/docs/../.git/config` — `SimpleHTTPRequestHandler` collapses `..` *before* it
  filters components, so a `startswith("/docs/")` test on the requested path
  passes and then hands over `.git/config`. The check runs on the resolved path
  for exactly this reason.
- `/docs/index.html%00.git` — a null byte survives both normpath and the prefix
  test, then reaches the stdlib's `open()`, which raises `ValueError` and takes
  the handler thread with it. Nothing leaked, but an unhandled crash in the one
  function whose job is to be trustworthy is worth closing.
- `/fixtures/__pycache__/` — a directory *inside* an allowed prefix still listed,
  631 bytes of build artefacts. The prefix rule only kills `/` and `/docs/`,
  because normpath strips their trailing slash.
- `http://a%00b/docs/x` — the interesting one, and the reason the guard is shaped
  the way it is. An absolute-form request target is legal HTTP and one line of
  socket code to send. `urlsplit()` throws `http://a%00b` away as the authority,
  so the gate reads `/docs/x` and approves it, while `translate_path()` reads the
  *raw* string and resolves something else — carrying the very null byte the gate
  was looking for into `open()`. The bug was never the null check or the prefix
  check: it was that two parsers each decided what the path was and only one of
  them was consulted. Refusing anything but origin-form is what makes them agree.
  (The scheme is the load-bearing half. A bare `//evil/docs/x` never reaches the
  handler intact — `BaseHTTPRequestHandler.parse_request` collapses repeated
  leading slashes first, so the prefix rule catches it. `/////docs/index.html`
  arrives as `/docs/index.html` and is served, correctly.)

A known limit of that model: a symlink placed inside `docs/` or `fixtures/`
pointing at a file outside the repo would be served, because it resolves to a
file rather than a directory. None exist today, and nothing in the harness
creates one.

**maths** — 147 cells: every fixture through all three styles, all seven line
widths, all seven ink levels, three Detail settings, and speck removal alone and
combined with a line width in each direction. The first three sweeps mirror
`report.py` exactly, so parity covers the space the baseline pins rather than an
adjacent space of its own. Detail and speck removal are additions, because the
browser duplicates both and `report.py` exercises neither.

**wiring** — 15 steps that drive the real controls with real key presses, clicks
and typed values, then read the canvas `Download` would hand you. A slider wired
to the wrong field renders perfectly and matches nothing the user asked for, and
the maths pass cannot see it because it never touches a control. The type-in box
is driven separately from the slider: it is a second commit path, with its own
clamping and its own deferred DOM swap. The fullscreen viewer builds its panel
from the same `buildControls()` the grid card uses, so the control-to-state half
of its wiring is shared code and covered here; its own commit path,
`commitFromLightbox`, is not driven by any step.

### Falsifying it

Same rule as `falsify.py`: a check that has never failed has never been tested.

```bash
python3 fixtures/parity.py --falsify
```

applies deliberate defects to `docs/index.html` one at a time — served from
memory, never written to disk, working tree untouched — and reports which ones
parity notices. They cover the duplicated arithmetic (a pinned cutoff, an
off-by-one threshold, capped thinning depth, a paper border that becomes ink,
both Zhang-Suen sub-passes clearing the same corners), the hard-coded constants
(block size, median and Gaussian blur, Canny thresholds, minimum speck area,
speck connectivity), and the controls (a dead slider, a slider writing another
slider's field, a dropdown that swallows a style, a typed value committed one
too high).

32 of the 33 are caught. The one that is not is Canny's *low* threshold, and the
reason is a property of the fixtures rather than of parity. Its *high* threshold
is mutated too, and caught — so the gap is exactly one parameter wide, and the
battery shows that rather than a comment claiming it. It is in `KNOWN_BLIND`
with the measurement, and listed below.

Three things this had to get right:

- **Every mutation asserts its target text is present before applying**, the
  same guard `falsify.py` carries and for the same reason: a find-and-replace
  that misses looks exactly like an unbreakable check, and has produced that
  false reading here before.
- **Every mutant is stamped with an id the harness reads back out of the loaded
  page**, and the served response is `no-store`. Applying a defect to a string
  is only half the job — it still has to reach the browser, and a cached copy of
  the previous mutation is the same false reading one step further along the
  pipe. The exposure is real rather than theoretical: every mutant reuses one URL
  which carries no `Last-Modified` or `ETag`, and the browser context is shared
  across the battery so Chromium's cache is warm for opencv.js.
- **`--falsify` fails when the set of misses is not exactly `KNOWN_BLIND`**, in
  either direction. `falsify.py` prints "only acceptable if README.md lists it as
  an uncovered gap" and trusts the reader to go and look; that holds until a
  check quietly goes blind and its miss passes for one of the known ones. A gap
  that gets closed has to be deleted from the list too, or the list starts
  overstating the blind spots rather than understating them.

Two of the first run's three misses were weak probes rather than real limits,
and both are fixed rather than excused:

- The cell asserting that speck removal still runs *before* the line-width pass
  used `--line-width -2`, and caught nothing. Only a *positive* width can tell
  the orderings apart: thickening grows a blob from under the minimum area to
  over it, so removal-after keeps what removal-before deleted, while thinning
  only ever shrinks and a doomed blob stays doomed. On these fixtures the
  difference appears on `fine-detail` alone, at 12px for `+1` and 24px for `+2`.
- The typed-value steps entered 37 and 500 into `Ink` on `grey-ink`, where the
  page is ~90% white paper and only 7 of the 100 ink levels render differently
  from the level above. Both sat in flat stretches, so a mutation committing
  every typed value one too high changed nothing visible. `Detail` moves at every
  one of its 20 steps, so it now carries the clamp check, and the `Ink` step
  types 29.

## What this does NOT cover

Stated plainly, because an unlisted limit reads as coverage.

- **These are not real photographs or real art.** No JPEG artefacts, no
  photographic gradients, no scanner noise, only light anti-aliasing. A change
  could pass all seven fixtures and still ruin a phone photo or an anime
  screenshot. The fixtures protect the *documented claims*; they do not tell you
  the tool still looks good.
- **`report.py` measures `coloringify.py` only.** `docs/index.html` re-implements
  the same maths for the browser; `parity.py` is what holds the two together, and
  it has its own limits, listed at the end of this section.
- **Small (240x180).** Nothing here exercises memory, the synchronous
  main-thread cost, or the pixel-count behaviour that a 48MP photo would. That
  goes double for `parity.py`, which runs the whole browser pipeline on the same
  small images and so says nothing about the tab-freezing behaviour in
  `TODOS.md`.
- **The colour-reference thumbnail is never drawn.** `page()` passes
  `no_reference=True` so the ink percentages measure the outline rather than the
  thumbnail's pixels. `add_reference()` is therefore untested — it could break
  and every claim here would still pass. `parity.py` renders with the guide off
  for the same reason, and in its case there is a second one: the two
  implementations genuinely place the inset differently.
- **Nothing composites transparency.** Every fixture is opaque, so neither
  `load_bgr()`'s alpha-over-white path nor the browser's white-filled canvas is
  exercised — by any claim here, or by parity. They could be broken, or broken
  differently from each other, and nothing would notice.
- **Nothing here is spatial.** Every claim except the 2x2 one measures a
  percentage of inked pixels, never *which* pixels. A `set_line_width` that hit
  the right coverage by flipping pixels unrelated to any stroke would pass
  cleanly, and no threshold can catch that — it needs a claim that checks the
  changed pixels sit adjacent to existing ink. `claim_only_2x2_vanishes` is the
  single exception, and it only inspects six known coordinates.
- **Nothing about `Thin`.** Canny's doubled outline on already-inked art is a
  known, documented limitation that is not being fixed, so there is no claim to
  hold it to.
- **`--despeckle` is never exercised.** `page()` always passes `despeckle=False`,
  so `despeckle()` could stop honouring its flag — or stop working entirely — and
  every claim here would still pass. Verified: making despeckle unconditional in
  `convert()` breaks no claim. That is the one entry in `falsify.py`'s
  `KNOWN_BLIND`, so the gap is held open by a failing run rather than by this
  sentence — close it and the list has to lose the entry, or `falsify.py` fails
  for overstating what it cannot see.
- **`ink-ramp` takes no part in the line-width claims.** A smooth gradient has no
  edges for adaptive threshold to find, so it reads 0.00% ink at every width and
  there is no stroke to thin. It is the only fixture excluded from anything, and
  the exclusion is checked rather than asserted in a comment: anything left out
  of `STROKE_NAMES` must really read 0.00% at every width, so a fixture cannot be
  added to that filter to dodge a failure.
- **Three lists narrow what these claims cover, and each one has to earn itself
  against the data.** `STROKE_NAMES` drops `ink-ramp` from the line-width claims,
  `INK_MAY_BE_FLAT` excuses `fine-detail` from responding to `--ink`, and
  `DEEPEST_MAY_CONVERGE` excuses `flat-bands` from moving at `-3`. Every other
  fixture must respond individually. An earlier version counted instead ("at
  least 3 of 7"), which a cutoff that froze `--ink` on exactly three images
  walked straight through, scoring 3/7 with the slider dead on four of seven.
  Each list is checked:
  - out of `STROKE_NAMES` requires a genuine zero ink pixels at every width,
    counted raw rather than from the table's rounded percentages
  - in `INK_MAY_BE_FLAT` requires 2 brightness levels *with the lighter at 255*.
    The level count alone is not the invariant and briefly stood here as though
    it were: ink at V=50 on a V=250 background also has two levels and moves from
    10% to 100% as `--ink` rises. `fine-detail` is immovable only because
    `ink_cutoff` caps at 255 and its background sits exactly there.
  - in `DEEPEST_MAY_CONVERGE` requires that Zhang-Suen genuinely cannot remove
    another pixel at `-2`, asked of `_thin_pass` directly. Inferring it from the
    `-3` reading would be circular — a depth cap makes `-3` equal `-2` for
    reasons that have nothing to do with convergence, and a check built on that
    equality would bless the cap.

  This list was the last one added, and until it was, padding
  `DEEPEST_MAY_CONVERGE` with the five fixtures a depth-capped thinner had frozen
  turned a 5/6 failure into a clean 7/7 pass — while this file already claimed
  every exemption was earned.
- **Coverage in percentage points, not pixel positions, on the ramp.** `--ink`
  calibration allows 0.7 points of deviation, one pixel column plus a little.
  A ratio band stood here first and was much weaker: wide enough for the bottom
  of the range, where one column is a quarter of `--ink 1`, it also accepted a
  35-point hole at `--ink 100`. Still nothing checks *which* pixels get inked —
  a cutoff hitting the right count on the wrong pixels passes. `parity.py` is the
  exception and only on its own axis: it compares positions, but only between the
  two implementations, so it catches a browser that moved pixels the script did
  not — never a script that moved the wrong ones.

### And what `parity.py` in particular does not cover

- **Agreement is not correctness.** Every cell can pass while both sides are
  wrong in the same way, and a change applied identically to both is invisible
  here by construction. `report.py` is what holds the Python side to the claims;
  parity is what carries those claims across to the browser. Neither is
  load-bearing on its own, and "parity passes" is not a release gate.
- **One fixture drives the wiring pass.** All 15 steps use `grey-ink`, chosen
  because every control visibly moves it. A control that works there and breaks
  on a picture with a different histogram passes. The maths pass covers all seven
  fixtures; the control wiring does not.
- **It reads `results[i]`, not the canvas in the grid.** Deliberate: that is the
  buffer Print and Download read, and the card's DOM swap is held back a frame on
  purpose. But it means a broken swap — the wrong picture on screen while the
  right one downloads — is not something parity can see.
- **Only the file input is exercised.** Drag-and-drop, the paste-a-URL loader,
  Print, Download, Download all, the lightbox's own rebuild, `Guide size`,
  `Above image` and multi-image batches are never driven.
- **Canny's low threshold is unfalsifiable against these fixtures.** They are
  drawn with hard edges, so hysteresis never has a weak edge to reject: no
  fixture's `Thin` output moves for any low threshold from 10 to 80, and only
  `pale-ink` (at 120) and `full-bleed` (at 149) move anywhere below the high
  threshold of 150. The high threshold *is* covered: mutating it from 150 to 100
  fails 5 cells. This is recorded in `KNOWN_BLIND`, and `--falsify` fails if the
  set of things it cannot catch stops matching that list in either direction.
- **Neither side's OpenCV is pinned.** The page loads
  `https://docs.opencv.org/4.x/opencv.js`, which redirects to whatever the latest
  release is; `requirements.txt` says `opencv-python>=4.8`. They matched at
  4.13.0 on 2026-08-03 by luck, not by design, and can drift apart with no commit
  on either side. `parity.py` prints both and warns when they differ so a failure
  can be triaged, but nothing holds them together. See `TODOS.md`.

## Adding one

Say in its docstring which claim it exists for. A fixture whose purpose nobody
can state is one nobody will maintain, and it will be deleted the first time it
becomes inconvenient.
