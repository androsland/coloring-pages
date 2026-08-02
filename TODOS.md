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

- **The tuning sample is not reproducible from a clean checkout.** Both new
  controls were tuned against four images in `in/`, which is gitignored on
  purpose (don't commit copyrighted pictures). So the specific numbers quoted in
  the README and in the source comments cannot be re-derived by anyone else, and
  a future change to either heuristic has no fixture set to regress against.
  Worth adding two or three small, freely-licensed cartoon images as a tracked
  fixture directory (`fixtures/`, separate from `in/`) plus a script that prints
  the ink coverage per style, so these claims become checkable. (2026-08-02)

- **Cartoon's ink target quantises on images with large flat regions.** The
  cutoff is an integer V, so where many pixels share one brightness the achieved
  coverage jumps: `0007.png` cannot go below 3.08% (a big pure-black region) and
  jumps 6.07% → 11.55% between `--ink 6` and `--ink 8`. Harmless in practice —
  the slider still moves monotonically — but the number on the badge is a target,
  not a promise. (2026-08-02)

## Housekeeping

- **Dead assignment in `add_reference()`**: `x0, y0 = x1 - 0, y1 - 0` — `x0` is
  never read (pyflakes). Pre-existing and unrelated to the line-width/ink work,
  so it was left out of that diff rather than padding it. (2026-08-02)

## Completed

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
