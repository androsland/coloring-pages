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
```

`report.py` exits non-zero if a claim fails or a number has moved since
`baseline.json`. When a change is meant to move the numbers, re-record the
baseline in the same commit and say why they moved.

Every render goes through `coloringify.convert()` — the same dispatch the CLI
uses — rather than calling the style functions directly. An earlier version did
its own branching here, which quietly turned one claim into a tautology: it
compared two outputs this file had already routed identically, so it was testing
itself. It also meant nothing exercised `convert()`, which is where a regression
in argument routing would actually live.

## Falsifying the claims

Each claim has been run against a build broken in the specific way that claim
exists to catch, and each one fails there:

| claim | broken build it was checked against |
|---|---|
| coloured outlines survive | the old fixed `V < 120 && S < 60` rule; a weakened `S < 180` variant |
| the cutoff is image-specific | `ink_cutoff` pinned to a constant 128 |
| `--ink` reaches the picture | `ink_cutoff` returning `min + 0.15*(max-min)`, discarding the requested percentage |
| `--ink` inks the percentage asked for | the percentile honoured at half, and at double, the requested rate |
| thinning erases only the 2x2 | plain erosion in place of Zhang-Suen; erosion bolted on after the first pass |
| line width moves the ink | a no-op `set_line_width`; magnitude-blind variants; the thinning loop depth-capped at 1 and at 2; `line_width` dropped in `convert()` |
| `--ink` affects Cartoon only | `--ink` leaked into the Bold path, and into the Thin path, inside `convert()` |

Most of these were added *because* an earlier version passed against a broken
build. The line-width claim alone has shipped hollow four times: ordering only
(a dead slider is flat, and flat is non-decreasing); ordering plus a combined
end-to-end spread (the working half carried the broken half); per-direction
floors (a magnitude-blind slider cleared one fixture by 0.05pp on luck of its
geometry); and per-side distinct-value counting (satisfied by `-1` differing
from `-2`, while `-3` silently stopped doing anything).

The pattern behind all four is worth naming: each verified the property it set
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

## What this does NOT cover

Stated plainly, because an unlisted limit reads as coverage.

- **These are not real photographs or real art.** No JPEG artefacts, no
  photographic gradients, no scanner noise, only light anti-aliasing. A change
  could pass all seven fixtures and still ruin a phone photo or an anime
  screenshot. The fixtures protect the *documented claims*; they do not tell you
  the tool still looks good.
- **`coloringify.py` only.** `docs/index.html` re-implements the same maths for
  the browser, and nothing here checks the two still agree — that has only ever
  been verified by hand. This is the largest remaining gap; see `TODOS.md`.
- **Small (240x180).** Nothing here exercises memory, the synchronous
  main-thread cost, or the pixel-count behaviour that a 48MP photo would.
- **The colour-reference thumbnail is never drawn.** `page()` passes
  `no_reference=True` so the ink percentages measure the outline rather than the
  thumbnail's pixels. `add_reference()` is therefore untested — it could break
  and every claim here would still pass.
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
  `convert()` breaks no claim.
- **`ink-ramp` takes no part in the line-width claims.** A smooth gradient has no
  edges for adaptive threshold to find, so it reads 0.00% ink at every width and
  there is no stroke to thin. The exclusion is explicit in `STROKE_NAMES`, and it
  is the only fixture excluded from anything.
- **The slider floors are aggregate, not per-fixture.** `--ink` and the deepest
  thinning step are each required to move on at least 3 fixtures, not all of
  them, because convergence and flat histograms make some legitimately stop
  responding. A regression that killed the slider on exactly the fixtures below
  that margin would pass. The healthy build scores 6/7 and 5/6 against a floor of
  3, so the margin is two fixtures wide in both directions.
- **Coverage ratios, not pixel positions, on the ramp.** `--ink` calibration is
  checked as a ratio of achieved to requested coverage within 0.6–1.5. A cutoff
  off by less than that band, or one inking the *wrong* pixels at the right
  count, passes.

## Adding one

Say in its docstring which claim it exists for. A fixture whose purpose nobody
can state is one nobody will maintain, and it will be deleted the first time it
becomes inconvenient.
