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
  cut out on white, so the full-bleed case is untested. (2026-08-02)

- **Nothing checks that the browser and the script still agree.** `fixtures/`
  now regresses `coloringify.py`, but `docs/index.html` re-implements the same
  histogram cutoff and the same Zhang-Suen thinning in JavaScript, and the two
  have only ever been reconciled by hand — most recently at 54/54 byte-identical
  cells, which is exactly the kind of result that rots silently. This is the
  largest remaining verification gap, and it is bigger than the one the fixtures
  just closed: a divergence means the page you preview is not the page the batch
  script produces. Closing it needs the browser driven headlessly against the
  same fixtures (Playwright is not currently a repo dependency), or the shared
  maths extracted to one file both sides load. (2026-08-03)

- **Cartoon's ink target quantises on images with large flat regions.** The
  cutoff is an integer V, so where many pixels share one brightness the achieved
  coverage jumps: `0007.png` cannot go below 3.08% (a big pure-black region) and
  jumps 6.07% → 11.55% between `--ink 6` and `--ink 8`. Harmless in practice —
  the slider still moves monotonically — but the number on the badge is a target,
  not a promise. (2026-08-02)

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

- **Nothing runs `fixtures/report.py` automatically.** There is no CI in this
  repo at all, so the whole regression net only fires when someone remembers to
  run it by hand. Every claim in `fixtures/` is worth exactly as much as that
  habit. A single workflow running `python3 fixtures/report.py` on push would
  close it. (security review, 2026-08-03)

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
  `--min-area` and survive below it. (2026-08-03)

## Housekeeping

- **Dead assignment in `add_reference()`**: `x0, y0 = x1 - 0, y1 - 0` — `x0` is
  never read (pyflakes). Pre-existing and unrelated to the line-width/ink work,
  so it was left out of that diff rather than padding it. (2026-08-02)

## Completed

- **The tuning claims could not be re-derived by anyone else.** Both heuristics
  were tuned against copyrighted art in the gitignored `in/`, so every number in
  the README and the source comments was unverifiable from a clean checkout, and
  neither had anything to regress against. Added `fixtures/`: seven images drawn
  by code (no licence question), each built to exercise one documented claim,
  plus `report.py`, which prints coverage per style and fails if a claim breaks
  or a number drifts from `baseline.json`. All seven claims were checked against
  builds broken in the specific way each exists to catch — thirteen mutations in
  total, twelve caught, the thirteenth (`--despeckle`) recorded above as an
  uncovered gap rather than left implied. Blind spots are written into
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
