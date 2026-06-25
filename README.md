# coloring-pages

Turn photos into printable coloring pages with a full-color reference in the corner.
Two ways to use it: a **website** (no install) or a **Python script** (batch a folder).

## Website (no install)

Open `docs/index.html` — drag in pictures, get coloring pages, download them.
It runs entirely in the browser (OpenCV.js); images never leave the device.

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
python3 coloringify.py --c 9             # fewer lines (less noise)
python3 coloringify.py --c 2             # more detail
python3 coloringify.py --in pics --out pages
```

- `threshold` (default): clean, bold coloring-book lines. Best for most photos.
- `edges`: thinner Canny outlines. Good for simple/high-contrast subjects.

Tip: if a page comes out too noisy/scribbly, raise `--c` (e.g. `--c 9`).
If it's too sparse, lower it (`--c 3`).
