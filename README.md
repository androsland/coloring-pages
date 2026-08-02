# coloring-pages

Turn photos into printable coloring pages with a full-color reference in the corner.
Two ways to use it: a **website** (no install) or a **Python script** (batch a folder).

## Website (no install)

Open `docs/index.html` — drag in pictures, get coloring pages, download them.
It runs entirely in the browser (OpenCV.js); images never leave the device.

There are no global controls: **every setting lives on the page it affects** —
style, Remove specks, Detail (Bold pages only), Ink (Cartoon pages only), Line
width, and color guide + size. Every page starts on **Bold** (the robust default
that works for photos and cartoons alike); switch a page to **Cartoon** when it
already has outlines you want to keep (Pokémon, clip art) and use its **Ink**
slider to set how much of the picture survives, or **Thin** for a sketchier look.
Tweak any card and only that page re-renders. Click any page to view it at
**actual size** and check the line detail. Paper size and scaling are left to
your browser's print preview when you hit Print.

**Style picks *which* lines get drawn; Line width picks *how heavy* they are.**
They are independent, so `Bold` + a thin Line width gives thin outlines that are
still single strokes — which is what you want for a picture that already has
black outlines. Thinning uses Zhang-Suen skeletonisation rather than erosion, so
it will not open a gap in a line or pull its ends back. The one thing it does
delete is an isolated 2x2 block of ink, which the algorithm removes outright; at
print resolution that is a speck, but it is a deletion rather than a thinning.
Thickening (good for younger kids, or for pages that print faint) grows the ink
a pixel per step.

Try it locally:

```bash
python3 -m http.server 8000 --directory docs
# then open http://localhost:8000
```

### Host it on GitHub Pages (free)

1. Push this repo to GitHub.
2. Repo **Settings → Pages**.
3. Source: **Deploy from a branch**, branch **main**, folder **/docs**. Save.
4. Wait ~1 min — your site is live at `https://<you>.github.io/<repo>/`.

## Python script (batch a folder)

Drop images in `in/`, run the script, get line art in `out/`.

## Setup

```bash
pip install -r requirements.txt
```

## Use

```bash
# 1. put some photos in ./in
# 2. run:
python3 coloringify.py

# results land in ./out as PNGs
```

### Options

```bash
python3 coloringify.py --style edges     # thinner, sketchier lines
python3 coloringify.py --style lineart   # for cartoons / clip art
python3 coloringify.py --c 9             # fewer lines (less noise)
python3 coloringify.py --c 2             # more detail
python3 coloringify.py --line-width -2   # same lines, drawn thinner
python3 coloringify.py --line-width 2    # same lines, drawn thicker
python3 coloringify.py --despeckle       # drop tiny black specks
python3 coloringify.py --in pics --out pages
```

- `threshold` (default): clean, bold coloring-book lines. Best for most photos.
- `edges`: thinner Canny outlines. Good for simple/high-contrast subjects.
- `lineart`: keeps the darkest few percent of the picture as ink and whitens the
  colored fills. Best for images that *already* have outlines — cartoons, clip
  art, Pokémon — where `threshold` would turn the fills into speckle. For photos,
  stick with `threshold`.

Lineart tuning:

- `--ink` (default 4): what percentage of the picture to keep as ink. Raise it
  to pull in lighter lines, lower it if fills are turning solid black.

The brightness cutoff behind that percentage is measured from each image, not
fixed — on the four cartoon images this was tuned against, the same `--ink 4`
resolved to cutoffs anywhere from 21 to 229. That is the whole point: "dark
enough to be an outline" is not a constant, and the previous fixed pair of
thresholds produced a near-blank page on art whose outlines were dark but
*coloured*. Saturation is deliberately not part of the test; filtering on it is
what dropped navy, dark-teal and brown outlines. (Those test images aren't in
the repo — `in/` is gitignored so nobody commits copyrighted pictures — so the
numbers above are a record of the tuning, not something a clean checkout can
reproduce.)

Line width (works with any style, `0` = leave the style's own stroke alone):

- `--line-width -3 … 3`: how heavy the finished outline is. Negative peels
  layers off every stroke (Zhang-Suen thinning: it will not break a line, pull
  its ends back, or erase a lone pixel — but see the 2x2 caveat above); positive
  grows the ink by a pixel per step.
- This is orthogonal to `--style`. If a picture already has black outlines and
  `--style edges` gives you a *doubled* line, that is Canny finding both sides
  of each existing stroke — use `--style threshold --line-width -2` instead to
  get thin, single outlines.

Despeckle (works with any style, off by default):

- `--despeckle`: remove small black blobs left over after thresholding.
- `--min-area` (default 12): smallest blob, in pixels, to keep when
  `--despeckle` is on. Raise it to remove larger specks.

Tip: if a page comes out too noisy/scribbly, raise `--c` (e.g. `--c 9`).
If it's too sparse, lower it (`--c 3`).
