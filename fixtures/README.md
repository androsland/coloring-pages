# Fixtures

Six small images and a report that measures the pipeline against them.

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

## What each fixture is for

| fixture | the claim it holds the code to |
|---|---|
| `grey-ink` | the ordinary case — dark desaturated outlines on white — still works |
| `saturated-ink` | dark *coloured* outlines (navy, teal, brown) survive. The old `V < 120 && S < 60` rule scores **0.00%** here: a blank page |
| `pale-ink` | the cutoff reaches high values too. Its darkest 4% sits at V≈237, so a fixed cutoff of 120 would return nothing |
| `full-bleed` | a picture with no white background. The percentile is measured over the whole image, so framing changes the answer — a documented blind spot, pinned here so it cannot change silently |
| `flat-bands` | large uniform regions, where an integer cutoff makes achieved coverage jump rather than glide |
| `fine-detail` | thinning keeps a lone pixel, 1px lines, 3x3, 4x4 and a 2x8 bar, and erases exactly one shape: the isolated 2x2 block |

Together they put the cutoff for `--ink 4` anywhere from **21 to 237**, which is
the point of measuring it per image rather than fixing it.

## What this does NOT cover

Stated plainly, because an unlisted limit reads as coverage.

- **These are not real photographs or real art.** No JPEG artefacts, no
  photographic gradients, no scanner noise, only light anti-aliasing. A change
  could pass all six fixtures and still ruin a phone photo or an anime
  screenshot. The fixtures protect the *documented claims*; they do not tell you
  the tool still looks good.
- **`coloringify.py` only.** `docs/index.html` re-implements the same maths for
  the browser, and nothing here checks the two still agree — that has only ever
  been verified by hand. This is the largest remaining gap; see `TODOS.md`.
- **Small (240x180).** Nothing here exercises memory, the synchronous
  main-thread cost, or the pixel-count behaviour that a 48MP photo would.
- **Nothing about `Thin`.** Canny's doubled outline on already-inked art is a
  known, documented limitation that is not being fixed, so there is no claim to
  hold it to.

## Adding one

Say in its docstring which claim it exists for. A fixture whose purpose nobody
can state is one nobody will maintain, and it will be deleted the first time it
becomes inconvenient.
