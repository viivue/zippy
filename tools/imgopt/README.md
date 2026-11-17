# imgopt

Command-line tool for optimizing images for web delivery.
Compresses JPEG, PNG, WebP, GIF, BMP, and TIFF files using Pillow.
Source files are never modified or deleted. Private metadata is stripped by
default, but copyright and author fields are always kept, see
[Metadata](#metadata).

## Quick start

```sh
uv tool install ./tools/imgopt
imgopt photo.jpg
```

That compresses `photo.jpg` and writes the result to `optimized/`. See below
for install details if you don't have `uv` yet, or [Usage](#usage) for more
examples.

## Requirements

Python 3.10+ and the following package (installed automatically):

| Package | Purpose |
|---------|---------|
| `Pillow` | Image decoding, resizing, and encoding |

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

### Step 3: install imgopt

From the repo root:

```sh
uv tool install ./tools/imgopt
# or
pipx install ./tools/imgopt
```

## Updating

Pull the latest code, then reinstall:

```sh
uv tool install --reinstall ./tools/imgopt
# or
pipx install --force ./tools/imgopt
```

## Usage

```sh
imgopt photo.jpg
imgopt banner.png --output ./exports
imgopt ./raw-images --recursive
imgopt photo.jpg --quality 5           # best quality
imgopt photo.jpg --quality 2           # smallest file
imgopt photo.jpg --webp                # convert to WebP
imgopt photo.png --jpg                 # convert to JPEG
imgopt photo.jpg --max-width 1920
imgopt photo.jpg --max-width 1920 --max-height 1080
imgopt ./raw-images --dry-run
imgopt ./raw-images --recursive --overwrite
```

## All flags

| Flag | Default | Description |
|------|---------|-------------|
| `--output DIR` | `<input>/optimized` | Destination folder |
| `--quality 1-5` | `4` | Output quality (see below) |
| `--webp` | off | Convert all outputs to WebP |
| `--jpg` | off | Convert all outputs to JPEG (lossy, drops transparency) |
| `--max-width PX` | off | Scale down if wider than PX |
| `--max-height PX` | off | Scale down if taller than PX |
| `--keep-exif` | off | Preserve all metadata (EXIF, XMP, PNG text, ICC profile) instead of stripping it |
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

JPEG and WebP quality is lossy (higher = better).
PNG compression is lossless, only file size changes, not visual quality. After
Pillow writes a PNG, [oxipng](https://github.com/oxipng/oxipng) re-compresses it
losslessly; the `--quality` value picks the oxipng effort level (higher quality =
faster/lighter, lower quality = exhaustive).

## Format conversion (`--webp` / `--jpg`)

By default each file is saved in its original format (except BMP and TIFF, which
are converted to PNG). Use `--webp` or `--jpg` to convert everything to a single
format. The two flags are mutually exclusive.

**`--webp`**: WebP typically produces smaller files than JPEG or PNG at equivalent
visual quality and is supported by all modern browsers. Graphics (PNG/GIF/BMP
sources, or any image with transparency) are written as **lossless** WebP so hard
edges stay crisp; photographic input stays lossy at the `--quality` setting.

**`--jpg`**: converts to JPEG. Images with transparency (e.g. PNG with alpha) have
their transparent areas dropped (filled with black) because JPEG does not support
an alpha channel.

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
File                                   Original     Output   Saved  Status
--------------------------------------------------------------------------------
hero.jpg                                 2.4 MB    480.1 KB  80.6%  OK
banner.png                             512.0 KB    198.3 KB  61.3%  OK
grid-bg.png                            217.6 KB    217.6 KB    kept  COPIED
icon.gif                                12.0 KB     14.2 KB  -18.3%  LARGER  <<<
--------------------------------------------------------------------------------
Net saved: 2.23 MB
```

Files marked `COPIED` re-encoded larger than the source in the same format, so
the original was copied through unchanged. This happens when the source is
already optimally compressed (many design-tool PNG exports already are).

Files marked `LARGER` are kept but flagged. Since same-format regressions are
copied through, this now only shows up on format conversions (`--jpg` / `--webp`)
where the target format is a poor fit for the image, e.g. converting a flat,
few-colour graphic to JPEG.

Files marked `SKIPPED` already have an output in place, pass `--overwrite` to
re-process them.

## Metadata

| Kept by default | Removed by default |
|-----------------|--------------------|
| EXIF Artist and Copyright | Camera make/model, lens and exposure settings |
| IPTC-IIM By-line, By-line Title, Credit, Source, Copyright Notice, Contact | GPS location, XMP location fields |
| XMP rights: `dc:rights`, `dc:creator`, `xmpRights:*`, `plus:*` (PLUS license IDs, licensor), `photoshop:Credit`/`Source`, `Iptc4xmpCore:CreatorContactInfo` | Dates, thumbnails, software tags |
| AI-generated marker: `Iptc4xmpExt:DigitalSourceType` | IPTC keywords, captions, places |
| PNG `Copyright`, `Author`, `Disclaimer` text | Comments that are not a rights notice |
| JPEG/GIF comments and PNG `Comment`/`Description` that read like a copyright or license notice | All other EXIF/IPTC/XMP/PNG text |
| Non-sRGB colour profiles (Display P3, Adobe RGB) | Plain sRGB colour profiles (browsers assume sRGB) |

Content Credentials (C2PA) cannot survive a re-encode, because their
signature covers the original pixels. imgopt prints a note for such files and
copies the AI-generated marker (`DigitalSourceType`) from the manifest into the
output's XMP. When the original is kept (`COPIED`), its credentials stay intact.

IPTC-IIM can only be written to JPEG. When converting to WebP or PNG, its
rights fields are copied into XMP instead, which keeps non-ASCII names and the
`©` sign intact.

`--keep-exif` keeps everything, including GPS and camera details. Keeping the
rights fields adds about 0.5 to 1 KB per image, and nothing for images without
rights metadata.

## Development

```sh
cd tools/imgopt
uv venv && uv pip install -e .
imgopt --help
```

The `-e` flag installs in editable mode, so source changes take effect
immediately without reinstalling.

If you add or change dependencies in `pyproject.toml`, re-run:

```sh
uv pip install -e .
```
