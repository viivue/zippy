# devkit

A monorepo of standalone Python command-line tools for internal team use.
Each tool is a fully independent package with no shared code or cross-dependencies.

## Tools

| Tool | Command | Description |
|------|---------|-------------|
| [vidopt](tools/vidopt/) | `vidopt` | Re-encode MP4/MOV videos to streaming-ready H.264/H.265 MP4 |
| [fontslice](tools/fontslice/) | `fontslice` | Subset variable/static fonts and export optimized woff2 files |
| [imgopt](tools/imgopt/) | `imgopt` | Compress JPEG/PNG/WebP images, resize, and convert to WebP or JPEG |

---

## vidopt

Encodes MP4/MOV source files to web-ready H.264 (or H.265) MP4 using ffmpeg.
Source files are never modified. Outputs land in an `optimized/` subfolder by default.

**Key options**

| Flag | Default | Description |
|------|---------|-------------|
| `--quality 1-5` | `4` | Output quality — 1 = smallest file, 5 = best quality |
| `--speed fast\|balanced\|slow\|thorough` | `slow` | Encoding speed — slower = better compression |
| `--h265` | off | Encode with H.265/HEVC (smaller files, modern browsers only) |
| `--max-width PX` | — | Scale down if wider than PX, preserving aspect ratio |
| `--recursive` / `-r` | off | Include subfolders when input is a directory |
| `--overwrite` | off | Replace existing output files |
| `--dry-run` | off | Print ffmpeg commands without running them |

**Examples**

```sh
vidopt video.mp4
vidopt clip.mov --output ./exports
vidopt ./raw-footage --recursive
vidopt video.mp4 --quality 5           # best quality
vidopt video.mp4 --quality 2           # smallest file
vidopt video.mp4 --h265 --quality 4
vidopt video.mp4 --speed thorough      # best compression, slower encode
vidopt video.mp4 --max-width 1280
vidopt ./raw-footage --dry-run
vidopt ./raw-footage --recursive --overwrite
```

---

## fontslice

Subsets `.ttf`, `.otf`, and `.woff2` font files and exports optimized `.woff2` files.
Reads weight ranges from `$fonts` in `_config.scss` when available; falls back to
font file axes. Skips icomoon and Font Awesome fonts automatically.

**Key options**

| Flag | Description |
|------|-------------|
| `--dir PATH` | Project root to scan for `fonts/` and `_config.scss` |
| `--fonts-dir PATH` | Path to fonts folder (auto-detected if omitted) |
| `--config PATH` | Path to `_config.scss` (auto-detected if omitted) |
| `--subsets` | Comma-separated subset names — skips the interactive prompt |

Valid subsets: `latin`, `latin-ext`, `vietnamese`, `cyrillic`, `cyrillic-ext`, `greek`, `greek-ext`

**Examples**

```sh
fontslice
fontslice --dir ./my-theme
fontslice --subsets latin,latin-ext
```

---

## imgopt

Compresses JPEG, PNG, WebP, GIF, BMP, and TIFF images using Pillow.
Source files are never modified. Outputs land in an `optimized/` subfolder by default.
EXIF metadata is stripped by default.

**Key options**

| Flag | Default | Description |
|------|---------|-------------|
| `--quality 1-5` | `4` | Output quality — 1 = smallest file, 5 = best quality |
| `--webp` | off | Convert all outputs to WebP |
| `--jpg` | off | Convert all outputs to JPEG (lossy, drops transparency) |
| `--max-width PX` | — | Scale down if wider than PX, preserving aspect ratio |
| `--max-height PX` | — | Scale down if taller than PX, preserving aspect ratio |
| `--keep-exif` | off | Preserve EXIF metadata instead of stripping it |
| `--recursive` / `-r` | off | Include subfolders when input is a directory |
| `--overwrite` | off | Replace existing output files |
| `--dry-run` | off | Print what would be done without writing files |

**Examples**

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

---

## Installing a tool

### Step 1 — Python 3.10 or later

```sh
python --version
```

If missing or older than 3.10, install from [python.org/downloads](https://www.python.org/downloads/).

> **Windows tip:** Check "Add Python to PATH" in the installer before clicking Install Now.

### Step 2 — install uv or pipx

Both runners install each CLI into its own isolated environment. Pick one.

#### uv (recommended)

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```sh
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify: `uv --version`

#### pipx (alternative)

```sh
pip install --user pipx
pipx ensurepath
```

Verify: `pipx --version`

### Step 3 — install

From the repo root:

```sh
# uv
uv tool install ./tools/vidopt
uv tool install ./tools/fontslice
uv tool install ./tools/imgopt

# pipx
pipx install ./tools/vidopt
pipx install ./tools/fontslice
pipx install ./tools/imgopt
```

Run `<command> --help` to verify.

## Updating a tool

Pull the latest code, then reinstall:

```sh
# uv
uv tool install --reinstall ./tools/vidopt
uv tool install --reinstall ./tools/fontslice
uv tool install --reinstall ./tools/imgopt

# pipx
pipx install --force ./tools/vidopt
pipx install --force ./tools/fontslice
pipx install --force ./tools/imgopt
```

## Adding a new tool

1. Copy an existing tool folder as a template:
   ```sh
   cp -r tools/imgopt tools/my-tool
   ```
2. Rename `src/imgopt` to match your package name (underscores, e.g. `src/my_tool`).
3. Edit `tools/my-tool/pyproject.toml`: update `name`, `version`, `description`,
   the `[project.scripts]` entry, and the `[tool.hatch.build]` source path.
4. Write your CLI logic in `src/my_tool/cli.py`.
5. Add a row to the Tools table and a section above.
6. Install and verify: `uv tool install ./tools/my-tool && my-tool --help`
