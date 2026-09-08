# imgresize

Command-line tool for resizing and cropping images to target dimensions.
Handles JPEG, PNG, WebP, GIF, BMP, and TIFF files using Pillow.
Source files are never modified or deleted. EXIF metadata is stripped by default.

Use `imgopt` when the goal is to *compress* images at their current size; use
`imgresize` when the goal is a specific *size* (a thumbnail, a social card, a
hero at exactly 1600px wide).

## Quick start

```sh
uv tool install ./tools/imgresize
imgresize photo.jpg --width 1200
```

That scales `photo.jpg` down to 1200px wide, keeping its aspect ratio, and
writes the result to `resized/`. See below for install details if you don't
have `uv` yet, or [Usage](#usage) for more examples.

## Requirements

Python 3.10+ and the following packages (installed automatically):

| Package | Purpose |
|---------|---------|
| `Pillow` | Image decoding, resizing, cropping, and encoding |
| `pyoxipng` | Lossless PNG post-compression |

## Install

### Step 1: Python 3.10 or later

Check if Python is already installed:

```sh
python --version
```

If it is missing or older than 3.10, download it from
[python.org/downloads](https://www.python.org/downloads/).

> **Windows tip:** In the installer check "Add Python to PATH" before clicking
> Install Now.

### Step 2: install uv or pipx

#### uv (recommended)

##### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After the script completes, close and reopen your terminal.

##### macOS / Linux

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### pipx (alternative)

```sh
pip install --user pipx
pipx ensurepath
```

Close and reopen your terminal after `ensurepath`.

### Step 3: install imgresize

From the repo root:

```sh
uv tool install ./tools/imgresize
# or
pipx install ./tools/imgresize
```

## Updating

Pull the latest code, then reinstall:

```sh
uv tool install --reinstall ./tools/imgresize
# or
pipx install --force ./tools/imgresize
```

## Usage

```sh
imgresize photo.jpg --width 1200                   # fit: width 1200, keep ratio
imgresize photo.jpg --width 1200 --height 1200     # fit inside a 1200 square
imgresize photo.jpg --mode cover --width 1200 --height 630
imgresize photo.jpg --mode cover --aspect-ratio 16:9
imgresize photo.jpg --mode cover --aspect-ratio 1:1 --position top
imgresize icon.png --mode cover --width 512 --height 512 --allow-upscale
imgresize photo.jpg --width 1600 --webp
imgresize ./raw-images --recursive --width 1600
imgresize ./raw-images --recursive --width 1600 --dry-run
```

## Modes (`--mode`)

### `fit` (default)

Scales the whole image so it fits inside the target box, keeping the aspect
ratio. Nothing is cropped and nothing is padded, so the output dimensions
depend on the image: a landscape photo constrained to `--width 1200 --height
1200` comes out `1200x800`, a portrait comes out `800x1200`.

- Give `--width`, `--height`, or both.
- By default the image is only ever scaled **down**. Pass `--allow-upscale` to
  let a smaller image be enlarged to reach the target.

### `cover`

Scales the image to completely fill the target box, keeping the aspect ratio,
then crops the overflow. The output is exactly the target size. This is the
mode for uniform thumbnails and social cards.

- Give both `--width` and `--height`, or an `--aspect-ratio` (e.g. `16:9`,
  `4:3`, `1:1`, or a bare number like `1.5`).
- `--aspect-ratio` on its own crops the source to that ratio at the largest
  size that fits, without scaling.
- `--position` sets which part of the image survives the crop: `center`
  (default), `top`, `bottom`, `left`, `right`, `top-left`, `top-right`,
  `bottom-left`, `bottom-right`.
- Targets larger than the source are clamped down unless `--allow-upscale` is
  given.

## All flags

| Flag | Default | Description |
|------|---------|-------------|
| `--output DIR` | `<input>/resized` | Destination folder |
| `--mode {fit,cover}` | `fit` | Resize strategy (see above) |
| `--width PX` | off | Target width |
| `--height PX` | off | Target height |
| `--aspect-ratio RATIO` | off | Target ratio for cover mode, e.g. `16:9` |
| `--position ANCHOR` | `center` | Crop anchor for cover mode |
| `--allow-upscale` | off | Permit enlarging past the source size |
| `--quality 1-5` | `4` | Output quality (see below) |
| `--webp` | off | Convert all outputs to WebP |
| `--jpg` | off | Convert all outputs to JPEG (lossy, drops transparency) |
| `--keep-exif` | off | Preserve EXIF metadata instead of stripping it |
| `--recursive` / `-r` | off | Include subfolders |
| `--overwrite` | off | Replace existing outputs |
| `--dry-run` | off | Print what would be done, do not write files |

## Quality (`--quality`)

| Value | JPEG / WebP quality | PNG compression |
|-------|---------------------|-----------------|
| `5` | 92 | 6 |
| `4` | **82 (default)** | **7 (default)** |
| `3` | 72 | 8 |
| `2` | 60 | 9 |
| `1` | 45 | 9 |

JPEG and WebP quality is lossy (higher = better). PNG compression is lossless,
only file size changes; after Pillow writes a PNG,
[oxipng](https://github.com/oxipng/oxipng) re-compresses it losslessly.

## Format conversion (`--webp` / `--jpg`)

By default each file keeps its original format (except BMP and TIFF, which are
written as PNG). Use `--webp` or `--jpg` to convert everything to one format;
the two flags are mutually exclusive. Graphics and images with transparency are
written as lossless WebP; photographic input stays lossy at the `--quality`
setting. `--jpg` drops any alpha channel.

## Supported formats

| Input | Output (default) | `--jpg` | `--webp` |
|-------|-----------------|---------|----------|
| `.jpg` / `.jpeg` | `.jpg` | `.jpg` | `.webp` |
| `.png` | `.png` | `.jpg` | `.webp` |
| `.webp` | `.webp` | `.jpg` | `.webp` |
| `.gif` | `.gif` | `.jpg` | `.webp` |
| `.bmp` | `.png` | `.jpg` | `.webp` |
| `.tiff` / `.tif` | `.png` | `.jpg` | `.webp` |

## End-of-run report

```
================================================================================
SUMMARY
================================================================================
File                      Resize                 Original    Output  Status
--------------------------------------------------------------------------------
hero.jpg                  4000x2667 -> 1600x1067    2.4 MB  381.2 KB  OK
avatar.png                512x512 -> 256x256      118.0 KB   41.6 KB  OK
card.jpg                  3000x2000 -> 1200x630     1.8 MB  132.9 KB  OK
--------------------------------------------------------------------------------
Net saved: 4.35 MB
```

Files marked `LARGER` re-encoded bigger than the source (rare, usually a poor
format conversion) and are kept but flagged. Files marked `SKIPPED` already
have an output in place; pass `--overwrite` to re-process them.

## Development

```sh
cd tools/imgresize
uv venv && uv pip install -e .
imgresize --help
```

The `-e` flag installs in editable mode, so source changes take effect
immediately without reinstalling.

If you add or change dependencies in `pyproject.toml`, re-run:

```sh
uv pip install -e .
```
