# TODOS

## Line styles

- **`Thin` (Canny) draws a doubled outline on pictures that already have black
  ink.** Canny detects intensity *edges*, so an existing black stroke yields two
  parallel lines — one per side. This is inherent to the algorithm, not a tuning
  problem, and it makes `Thin` unsuitable for cartoons/clip art/Pokémon. The
  workaround now shipped is `Bold` + a thin Line width, which gives thin single
  strokes; `Thin` remains the right choice for photos, where there is no ink to
  double. A real fix would collapse the paired edges (morphological close, then
  thin) — prototyped 2026-08-02 and it does produce single lines, but it lumps
  up at junctions (teeth, small triangles) and looked worse than the workaround,
  so it was not shipped. Revisit only if `Thin` needs to work on inked art.
  (user report + prototype, 2026-08-02)

- **Cartoon's `Ink` target is coverage-based, so a large dark *fill* spends the
  budget that the outlines needed.** Keeping the darkest N% of the page works
  because outlines are usually the darkest thing in cartoon art — but a picture
  with a big dark region (Squirtle's brown shell above ~6%, Baby Shark's open
  mouth at 4%) inks the region solid and starves the linework. Lowering `Ink`
  recovers the outlines, so there is always a way out, but it is a real ceiling
  on how good the page can get for those images. A structural fix would reject
  *blobby* components and keep thin ones, since a fill is thick and a stroke is
  not — deliberately not attempted, because solid black areas are sometimes
  exactly what you want to keep (sunglasses, wing markings), and no cheap test
  distinguishes "fill" from "intentional black shape". (2026-08-02)

- **Cartoon measures the percentile over the whole image, background included.**
  Two crops of the same subject with different amounts of white space get
  different cutoffs. This is intentional — "how much toner hits the paper" is
  the thing a printed page actually cares about — but it means the control is
  not invariant to framing, and a picture with no white background behaves
  differently from one cut out on white. Every image it was tuned against was
  cut out on white; the `full-bleed` fixture now covers the other case and pins
  its cutoff so the behaviour cannot change silently, though the framing
  sensitivity itself is intended and stays. (2026-08-02, fixture added
  2026-08-03)

- **Cartoon's ink target quantises on images with large flat regions.** The
  cutoff is an integer V, so where many pixels share one brightness the achieved
  coverage jumps. Originally observed on `0007.png`, which is in the gitignored
  `in/` and so was not checkable by anyone else; the `flat-bands` fixture now
  demonstrates it from a clean checkout, holding 16.67% across `--ink 1` through
  `16` and then jumping to 50% at `--ink 50`. Harmless in practice — the slider
  still moves monotonically, and `claim_ink_level_moves_the_ink` enforces that —
  but the number on the badge is a target, not a promise. (2026-08-02, pinned to
  a committed fixture 2026-08-03)

## Robustness (pre-existing, surfaced by cross-model review 2026-08-02)

- **A big enough picture freezes the tab.** Intake only checks that the image
  has non-zero dimensions; `makeColoringPage` then allocates RGBA + gray + HSV +
  split-channel + output Mats and runs the whole pipeline synchronously on the
  UI thread, with no pixel-count cap and no worker. A phone photo at 48MP will
  lock the page for seconds; something larger can crash the tab. The `Line width`
  thinning pass adds a full-image `Uint8Array` and up to 6 more full-image scans
  on top, so this got slightly worse, but the exposure predates it. Fix is a
  pixel-count cap with a downscale-and-warn path, or moving the pipeline into a
  worker. (2026-08-02)

- **One unreadable image aborts the whole batch.** `handleFiles` guards each
  file while *decoding*, but `rerunAll` calls `makeColoringPage` for every image
  with no per-image `try/catch`. An OpenCV allocation or conversion failure
  midway leaves the status stuck on "Drawing…" and the grid never rebuilt — the
  page looks hung rather than reporting a bad file. Wrap the per-image call and
  render a placeholder card for failures. (2026-08-02)

- **An all-black picture produces an all-black page in Cartoon.** `ink_cutoff`
  returns 1, `v < 1` inks everything. Both implementations agree, and arguably
  an all-black input has no line art to find, but it wastes a whole cartridge if
  anyone actually prints it. Cheap guard: if coverage lands above ~60%, fall back
  to a blank page and say so in the status line. (2026-08-02)

## Accessibility

- **Arrow-keying a slider re-announces the whole control each press.** Every
  committed change rebuilds the card's DOM and refocuses the slider by matching
  `aria-label`, so a screen reader sees a brand-new element on each keystroke and
  reads the full name again ("Line width (thin to thick) for …, slider, Thinner")
  instead of just the new value. Not a WCAG 2.1 AA violation and the control stays
  fully operable, but it is noticeably chattier than a native slider. Fixing it
  means not rebuilding the DOM on every keystroke — debounce the commit, or
  re-render on rAF — which also helps the main-thread cost tracked above.
  (accessibility review, 2026-08-02)

- **Control labels are `aria-label` strings that duplicate the visible text.**
  Each slider row is a `<div>` holding two labelable controls (the range and the
  type-in box), so there is no single valid `<label>` target; each control names
  itself instead. That satisfies AA — the accessible name starts with the visible
  text, so Label in Name holds — but it is a convention with nothing enforcing it:
  edit the visible `<span>` and no test catches the drift, and you lose the free
  click-the-label-to-focus affordance. More robust would be `aria-labelledby`
  pointing at the shared visible span plus a per-control visually-hidden suffix.
  (accessibility review, 2026-08-02)

- **A clamped entry is corrected silently.** Type 500 into Ink (max 100) and it
  snaps to 100 with no announcement, so a screen-reader user only finds out by
  re-reading the field. Not an SC 3.3.1 failure (nothing is blocked, and the
  field does re-read correctly on refocus), but a short `aria-live="polite"`
  note — "snapped to 100" — would remove the ambiguity. (accessibility review,
  2026-08-02)

- **A deferred card swap repaints late while the tab is hidden.** Committing a
  typed value defers only the DOM swap to a `requestAnimationFrame`, and rAF is
  suspended (not cancelled) for a background tab. Background the tab inside that
  one-frame window and the card's thumbnail keeps showing the pre-edit picture
  until the tab is visible again. Nothing is lost or wrong meanwhile —
  `results[i]`, the field value and its `aria-valuetext` are all updated
  synchronously, so Print and Download are correct throughout — and it takes
  backgrounding within ~16ms of a commit to hit at all. The dangerous half of
  this (a stalled swap waking up and pasting its superseded card over a newer
  one) is fixed: `swap` now returns early unless `results[i]` still holds the
  canvas it was scheduled for. What remains is only the late repaint, which a
  `visibilitychange` backstop flushing pending swaps would close.
  (accessibility + security review, 2026-08-02)

- **`rerunAll` drops keyboard focus.** Adding another image rebuilds the whole
  grid with `grid.replaceChildren`, which has no focus capture or restore — so
  whatever card control had focus is discarded and the user lands on `<body>`.
  This predates the per-card controls (it is identical on `main`) and is the one
  remaining place that replaces a focused subtree without preserving focus; the
  card swap and the viewer panel both handle it now. Fix is the same aria-label
  capture/restore those two use. (accessibility review, 2026-08-02)

## Fixtures and regression checks

- **Nothing checks that `make_fixtures.py` still redraws the committed PNGs.**
  The whole premise of `fixtures/` is that the images are drawn by code rather
  than collected, which is what makes every number here re-derivable from a
  clean checkout. Nothing holds the generator to the artefacts, though: edit
  `make_fixtures.py` and the committed PNGs keep the old geometry, so the claims
  keep passing against images the generator would no longer produce and the
  "drawn by code" property quietly stops being true. Measured 2026-08-04: a
  regeneration into a scratch tree reproduces all seven byte-identically, so the
  gap is unguarded rather than already broken. Cheap to close — regenerate and
  `cmp` in the `report` job — and deliberately left out of the CI diff, which
  was scoped to running the checks that already existed. (2026-08-04)

- **CI runs one Python version.** `checks.yml` pins `3.10` to match the machine
  the repo is developed on, so a red build means the code rather than the
  interpreter. Nothing therefore exercises 3.11+, where a deprecation or a
  changed stdlib default would land silently until someone upgrades. A matrix is
  the obvious fix and was skipped on purpose: it multiplies the runs and every
  extra failure mode needs triaging, which is a decision worth taking on its own
  rather than smuggling into the workflow that introduces CI. (2026-08-04)

- **The colour guide is the one thing the two twins genuinely draw
  differently.** `parity.py` renders with the guide off and says so, because
  with it on they disagree: measured at 4.91% of pixels on `grey-ink`, 5.81% on
  `saturated-ink` and 8.20% on `full-bleed`, every differing pixel inside the
  inset's bounding box and none outside it. Three causes, all in the geometry
  rather than the picture: the script's margin is a fixed 15px where the browser
  uses `round(W * 0.015) + 6` (10px at fixture width), the thumbnail size is
  truncated in Python and rounded in JS, and the frame is a `cv2.rectangle`
  offset by a pixel against a `strokeRect` centred on its path. Fixing it means picking
  which one is right, and they are not obviously commensurable — the browser's
  margin scales with the page and it also offers `Above image`, which the CLI
  has no flag for. Deliberately left alone; the point of recording it is that
  "parity passes" must not be read as "the guide matches". (2026-08-03)

- **Neither side pins OpenCV to an exact build — the majors now match, the
  minors still float.** Narrowed 2026-08-04: `requirements.txt` is
  `opencv-python>=4.8,<5`, and the page loads
  `https://docs.opencv.org/4.x/opencv.js`. Both sides are bounded to the 4
  major, so the cross-major skew that CI hit is closed. What remains is minor
  drift inside 4.x — `/4.x/` redirects to whatever the newest 4 release is
  (measured 2026-08-04: `4.x` -> `4.13.0`, 10.9 MB), so a CDN-side point release
  still moves the browser without a commit here. OpenCV's SIMD paths have
  differed numerically across builds before, so parity can still start failing
  for reasons that have nothing to do with this repository. `parity.py` prints
  both versions and warns when they differ, which is what made the original
  divergence triageable. Same root cause as the `baseline.json` item below,
  which is now the sharper of the two.

  Raising the ceiling to 5 is a decision with a measured price, taken and
  declined on 2026-08-04: `opencv.js` is **16.2 MB** on 5.0 against **10.9 MB**
  on 4.13.0, a 48% larger download on every cold load of the live page. All 15
  functions the page calls exist in the 5.0 JS build (probed in a real browser,
  so the upgrade is possible rather than blocked), and none of OpenCV 5's
  headline changes — C API removal, C++17, Python 2 drop, G-API and ML moved to
  contrib — touch a Python-plus-JS consumer of thirteen core imgproc calls. The
  one change that does land here is the revised `resize()` interpolation, and
  this pipeline's only `resize()` is the colour guide thumbnail at
  `coloringify.py:159` — which is the region no harness covers. Pay 5.2 MB for
  no new capability, with the one behavioural change aimed at the blind spot:
  no. Revisit when the guide is covered, or when 4.x stops receiving fixes.

  The supply-chain half is unchanged by the bound: fetching third-party
  JavaScript unpinned at the point release is something a runner now does
  unattended on every push and pull request. Not worse per event — the jobs hold
  `permissions: contents: read`, reference no secret, and use `pull_request`
  rather than `pull_request_target`, so a fork's run gets a read-only token and
  nothing to exfiltrate. An exact pin on both sides would close it, at the cost
  of a CDN path that can 404 and take the live page with it: `/4.13.0/` serves
  200 today but `/4.12.0/` is already 404, so the published set is curated
  rather than complete. (2026-08-03, amended supply-chain review 2026-08-04,
  narrowed 2026-08-04)

- **The transparency path is untested on both sides.** `load_bgr()` composites
  alpha over white and `makeColoringPage` does the same by drawing onto a
  white-filled canvas; every committed fixture is opaque, so neither the
  fixtures nor parity exercises either one. Both could be broken, or broken
  differently, and nothing here would notice. Needs a fixture with an alpha
  channel — which also means a baseline entry and a claim about what
  compositing should produce. (2026-08-03)

- **`baseline.json` is exact-equality against an unpinned OpenCV.**
  `requirements.txt` pins `opencv-python>=4.8` with no ceiling and no lockfile,
  and the drift check compares floats for exact equality. OpenCV's SIMD/IPP
  paths through `adaptiveThreshold`/`Canny` have differed numerically across
  builds before, so a legitimate version bump can present as drift that looks
  identical to a real regression — which trains whoever hits it to reflexively
  `--update-baseline` without reading why, disabling the net for the next real
  one. Fix is either recording the OpenCV version alongside the numbers so drift
  can be triaged, or giving the comparison an explicit small tolerance.
  (security review, 2026-08-03)

- **A corrupt fixture PNG crashes with a raw traceback.** `report.py`'s
  pre-flight only checks `.exists()`, not readability, so a truncated or
  garbled PNG reaches `cv2` and produces an unhandled `cv2.error` instead of
  the friendly "run make_fixtures.py" message that already exists three lines
  above. It does fail loudly rather than skipping silently, so this is polish,
  not a hole. (security review, 2026-08-03)

- **`--despeckle` has no claim behind it.** `page()` always passes
  `despeckle=False`, so `despeckle()` could stop honouring its flag and every
  claim would still pass — verified by making it unconditional in `convert()`.
  Needs a fixture with specks of known area and a claim that they go at
  `--min-area` and survive below it. Since 2026-08-04 it is the single entry in
  `falsify.py`'s `KNOWN_BLIND`, so the gap is held open by a check that fails
  rather than by this bullet: closing it means deleting the entry in the same
  commit, or `falsify.py` fails for overstating what it cannot see.
  (2026-08-03, gated 2026-08-04)

## Housekeeping

- **If the CLI is ever frozen into a distributable binary, move to
  `opencv-python-headless` first.** The wheel's own METADATA says "All wheels
  ship with FFmpeg licensed under the LGPLv2.1" and "Non-headless Linux wheels
  ship with Qt 5 licensed under the LGPLv3" — verified against the installed
  4.13.0.92 wheel rather than taken from the review that raised it. LGPL's
  relink-ability obligations bite on closed-source frozen binaries, and nothing
  here is one: this is a source-distributed CLI (`pip install -r
  requirements.txt`) plus a static Pages site, so the condition is currently
  absent and no action is due. Recorded as a conditional rather than a task, so
  that PyInstaller-ing this later is a decision rather than a surprise. Headless
  drops the Qt5/LGPLv3 bundle; FFmpeg's LGPLv2.1 ships in every variant and
  would still need handling. Unaffected by declaring this project MIT — that
  governs the code in this repository, not the binaries its dependency vendors.
  (supply-chain review 2026-08-04, narrowed 2026-08-04)

## Completed

- **`--ref-margin` and `--ref-scale` reached `add_reference()` straight from
  argparse, and a negative margin was a crash.** `main()` already validated
  `--block-size` and `--ink`; the two guide flags were the pair nothing checked.
  Measured on a 240x180 fixture before fixing, because the review that raised it
  had the failing and silent cases the wrong way round: `--ref-margin -1` (a
  plausible typo, not an absurd value) raised a bare
  `ValueError: could not broadcast input array`, while *every* other input —
  margins up to 300 on a 240px page, `--ref-scale` at 0.0, 1.5 and 3.0 — produced
  a finished page and exit 0, with the guide silently misplaced by numpy's
  negative-index wraparound once `x1` went below zero.

  Closed in two halves, because the two failures have different homes. `main()`
  now rejects `--ref-margin < 0` and `--ref-scale` outside `(0, 1]` in the style
  of the existing block. `add_reference()` clamps the margin per image, since the
  flag is validated once but a batch holds images of any size and only that
  function knows the one in front of it; when the requested margin does not fit
  it says so on stderr rather than quietly substituting. The vertical bound is
  half the slack rather than all of it, so the pre-existing overflow guard cannot
  then fire and shrink the thumbnail to a single pixel — on-canvas and
  deterministic, but as silently wrong as the wraparound it replaced.

  One thing the fix deliberately did not do is remove the overflow guard that
  follows the clamp. Review argued it had become unreachable now that `scale` is
  pinned to `(0, 1]`, with a trace over 11,280 calls showing zero executions.
  That was wrong, and checking it was worth the minute: `thumb_h` derives from
  the *source image's* aspect ratio, not the canvas's, so a tall source
  overflows a short page at any scale — the trace had swept canvas shapes
  without varying the source's. It fires on a 50x400 page with an ordinary
  240x180 source at the default 0.25. The guard is load-bearing and now carries
  a comment saying so, since a reader who reasons only about the canvas will
  reach the same wrong conclusion.

  `scale` is guarded too, but by a raise rather than a clamp, and the asymmetry
  is deliberate: a margin that does not fit a particular page is a runtime
  condition worth adapting to, whereas a scale outside `(0, 1]` is a request
  with no sensible rendering. The review of the first fix caught that
  `add_reference()` defended itself on `margin` and not on `scale` while being
  importable — `fixtures/report.py` calls it without going through `main()`.
  Measured rather than accepted as described, which turned up one case the
  review had missed: `scale=1.1` on a 35x10 page raised a bare numpy
  `could not broadcast`, NaN raised `ValueError` on every canvas tried, and
  **infinity raised `OverflowError`** from `int()`. All three named the symptom
  rather than the input. The function now rejects any non-finite or
  out-of-range scale up front, quoting the value.

  Verified against the gap that made this necessary in the first place: no
  harness covers `add_reference()`, so all 7 fixtures were rendered at four
  scale/margin combinations before and after and confirmed byte-identical; the
  previously-broken margins re-measured to show the guide keeps its full size
  on-canvas in every case; and the scale guard swept over 7 canvas shapes
  (including 1x1, 2x2, 10x10000 and 10000x10) against 8 bad values each, all
  rejected with a named error, with valid scales from 1e-6 to 1.0 still
  rendering on every shape. Not a parity change — the browser has no equivalent
  exposure, computing its margin as `round(W*0.015)+6` and bounding its
  guide-size slider to 10-40% (`docs/index.html:1020`), so none of these inputs
  is reachable there. (security review 2026-08-04, fixed 2026-08-04)

- **The repository had no `LICENSE` file, so its own terms were undeclared.**
  A public repo with no licence is all-rights-reserved by default: readable, but
  not legally reusable, which was an oversight rather than a decision. Now MIT.
  Surfaced by the supply-chain review of PR #6 while it was checking the
  dependency's licence, which is how a question about OpenCV's Apache 2.0 core
  turned into a question about this project's own terms. (2026-08-04)

- **Dead assignment in `add_reference()`.** `x0, y0 = x1 - 0, y1 - 0` left `x0`
  unread (pyflakes), and both `- 0` terms were no-ops, so `y0` was an alias for
  `y1`. Collapsed to `x1, y1` throughout. Behaviour-preserving, and proved
  rather than assumed: neither harness covers this function — `report.py` renders
  with `no_reference=True` and `parity.py`'s `RENDER_CELL` passes `thumb: false`
  — so it was checked by rendering all 7 fixtures at four scale/margin
  combinations (including the `margin=0` and `margin=40` edges) before and after,
  and confirming all 28 outputs byte-identical. That the check had to be built
  by hand is the argument for the colour guide coverage item above.
  (2026-08-02, fixed 2026-08-04)

- **Nothing ran the regression net automatically.** There was no CI in this
  repository at all — the only workflow on the remote was GitHub's own
  `pages-build-deployment` — so every claim in `fixtures/` was worth exactly as
  much as somebody's habit of running it, and `parity.py` was worth less than
  that, being the one check with dependencies to install. Added two workflows,
  split by what makes each check fail rather than by how long it takes.
  `checks.yml` runs `report.py` (0.45s, `requirements.txt` only) and `parity.py`
  (6.7s of checking behind a ~1 minute Chromium install) on every push and pull
  request, because those break when the pipeline changes. `mutations.yml` runs
  `falsify.py` (20s) and `parity.py --falsify` (~19 minutes) weekly and on
  demand, because those break when the *checking* changes, which is rarer.
  `falsify.py` had to be made to gate first: it printed its misses and exited 0
  regardless, so as a CI job it could never have gone red, and a green job that
  could not have failed reads as coverage without being any. It now carries a
  `KNOWN_BLIND` dict mirroring `parity.py`'s — one entry today, `despeckle
  ignores its flag`, with the measurement — and fails when the miss set differs
  in either direction. Both directions were checked by breaking the list on
  purpose: emptying it fails with "new blind spots", adding a mutation that is
  caught fails with "the list now overstates". Read-only `permissions`, no
  secrets referenced, `actions/*` on major tags. (2026-08-04)

- **Nothing checked that the browser and the script still agree.** `docs/index.html`
  re-implements the histogram cutoff and the Zhang-Suen thinning in JavaScript,
  and the two had only ever been reconciled by hand — most recently at 54/54
  byte-identical cells, which is exactly the kind of result that rots silently.
  Added `fixtures/parity.py`: it serves the repo over loopback, opens the real
  page in headless Chromium with the real opencv.js, renders the committed
  fixtures through it and compares them to `coloringify.convert()` pixel for
  pixel — 147 cells across every style, line width, ink level, Detail setting and
  speck-removal combination, plus 15 steps that drive the actual controls with
  real key presses, clicks and typed values, because a slider wired to the wrong
  field renders perfectly and the maths pass cannot see it. All 162 agree exactly
  today. `--falsify` applies 33 deliberate defects to a copy of the page held in
  memory and checks parity notices; it also gates its own coverage, failing if
  the set of defects it cannot see differs from `KNOWN_BLIND` in either
  direction. The first battery found three misses: two were weak probes and were
  fixed (the speck-ordering cell used a negative line width, where the two
  orderings genuinely agree; the typed-value steps used `Ink` values sitting in a
  flat stretch of `grey-ink`'s histogram), and one is a real limit of the fixture
  set, recorded above and in `fixtures/README.md`. The colour-guide inset is
  excluded, and measurably differs — see the open item above. (2026-08-03)

- **The tuning claims could not be re-derived by anyone else.** Both heuristics
  were tuned against copyrighted art in the gitignored `in/`, so every number in
  the README and the source comments was unverifiable from a clean checkout, and
  neither had anything to regress against. Added `fixtures/`: seven images drawn
  by code (no licence question), each built to exercise one documented claim,
  plus `report.py`, which prints coverage per style and fails if a claim breaks
  or a number drifts from `baseline.json`. All seven claims were checked against
  builds broken in the specific way each exists to catch, and that check is itself
  committed: `fixtures/falsify.py` applies 27 deliberate defects one at a time in
  a temporary copy and reports which claims fire. 26 are caught; the exception is
  `--despeckle`, recorded above as an uncovered gap rather than left implied.
  Six adversarial review rounds ran against this, and every one found a real
  defect — four hollow claims about the pipeline, then two rounds of defects in
  the test logic added to fix the round before. Blind spots are written into
  `fixtures/README.md`. (2026-08-03)

- **`Cartoon` was dead weight: fixed HSV thresholds (`V < 120 && S < 60`) that
  suited almost nothing.** The saturation test assumed ink is grey and fills are
  colourful, but cartoon outlines are routinely dark *and* saturated (navy, dark
  teal, brown) — it produced a 0.22%-ink blank page on `baby-shark`, and faint
  broken outlines on two others. Replaced both thresholds with a single `Ink`
  slider (`--ink` in the script): keep the darkest N% of the picture, with the
  brightness cutoff measured per image. The same 4% default resolves to cutoffs
  of 21–229 across the sample in `in/` and gives a usable page on all four.
  (2026-08-02)

- **No way to control outline thickness.** `Detail` changed how *many* lines Bold
  drew, never how heavy they were, so a page that was otherwise right could not
  be made lighter for print. Added a per-page `Line width` control (and
  `--line-width` in the script) covering all three styles. (2026-08-02)
