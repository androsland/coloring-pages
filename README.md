# coloring-pages

Turn photos into printable coloring pages with a full-color reference in the corner.
Two ways to use it: a **website** (no install) or a **Python script** (batch a folder).

## Website (no install)

Open `docs/index.html` — drag in pictures, get coloring pages, download them.
It runs entirely in the browser (OpenCV.js); images never leave the device.

There are no global controls: **every setting lives on the page it affects** —
style, Remove specks, Detail (Bold pages only), and color guide + size. Every
page starts on **Bold** (the robust default that works for photos and cartoons
alike); switch a page to **Cartoon** when it already has black outlines you want
to keep (Pokémon, clip art), or **Thin** for a sketchier look. Tweak any card and
only that page re-renders. Click any page to view it at **actual size** and check
the line detail. Paper size and scaling are left to your browser's print preview
when you hit Print.

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
python3 coloringify.py --despeckle       # drop tiny black specks
python3 coloringify.py --in pics --out pages
```

- `threshold` (default): clean, bold coloring-book lines. Best for most photos.
- `edges`: thinner Canny outlines. Good for simple/high-contrast subjects.
- `lineart`: keeps existing ink (dark, low-saturation pixels) and whitens the
  colored fills. Best for images that *already* have outlines — cartoons, clip
  art, Pokémon — where `threshold` would turn the fills into speckle. For photos,
  stick with `threshold`.

Lineart tuning (HSV scale: H 0–179, S/V 0–255):

- `--v-max` (default 120): max brightness for a pixel to count as ink. Raise it
  to keep lighter lines; lower it to keep only the darkest.
- `--s-max` (default 60): max saturation for ink. Raise it if colored outlines
  are being dropped; lower it to ignore more color.

Despeckle (works with any style, off by default):

- `--despeckle`: remove small black blobs left over after thresholding.
- `--min-area` (default 12): smallest blob, in pixels, to keep when
  `--despeckle` is on. Raise it to remove larger specks.

Tip: if a page comes out too noisy/scribbly, raise `--c` (e.g. `--c 9`).
If it's too sparse, lower it (`--c 3`).
