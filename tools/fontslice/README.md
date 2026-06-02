# FontSlice

Subset and convert variable/static fonts to optimized `woff2` + `woff` files.

Scans all `.ttf` / `.otf` files in a theme's `fonts/` folder, skips `icomoon*`
files, and reads weight ranges from `$fonts` in `_config.scss` when available.

## Requirements

Python 3.10+ and the following packages (installed automatically):

| Package | Purpose |
|---|---|
| `fonttools[woff]` | Font parsing, subsetting, instancing |
| `brotli` | woff2 compression |
| `zopfli` | woff compression |

## Install

### Step 1 - Python 3.10 or later

Check if Python is already installed:

```sh
python --version
```

If it is missing or older than 3.10, download it from
[python.org/downloads](https://www.python.org/downloads/).

> **Windows tip:** In the installer check "Add Python to PATH" before clicking
> Install Now.

### Step 2 - install uv or pipx

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

### Step 3 - install fontslice

From the repo root:

```sh
uv tool install ./tools/fontslice
# or
pipx install ./tools/fontslice
```

## Updating

Pull the latest code, then reinstall:

```sh
uv tool install --reinstall ./tools/fontslice
# or
pipx install --force ./tools/fontslice
```

## Usage

`cd` into your theme project — fonts and `_config.scss` are auto-discovered:

```sh
cd path/to/your-theme
fontslice
```

Or pass paths explicitly:

```sh
fontslice --fonts-dir path/to/assets/fonts --config path/to/_config.scss
fontslice --dir path/to/your-theme
fontslice --subsets latin,latin-ext,vietnamese   # skip the interactive prompt
```

### Available subsets

| Name | Coverage |
|---|---|
| `latin` | Basic Latin + common punctuation/symbols (default) |
| `latin-ext` | Extended Latin (Western/Central European accented characters) |
| `vietnamese` | Vietnamese diacritics |
| `cyrillic` | Core Cyrillic |
| `cyrillic-ext` | Extended Cyrillic |
| `greek` | Core Greek |
| `greek-ext` | Extended Greek (polytonic) |

Combine subsets: `--subsets latin,latin-ext,vietnamese`

## What it does

1. **Discover** — finds all `.ttf`/`.otf` files and resolves weight ranges from `_config.scss` (falls back to the font's own axis values).
2. **Report** — prints a table of found fonts with family name, weight range, opsz default, and build status (`NEEDS_BUILD` / `UP_TO_DATE`). Fonts whose `.woff2` output is newer than the source are skipped.
3. **Ask** — prompts for character subsets (or uses `--subsets`).
4. **Build** — for each font that needs building, instances variable axes then subsets and converts to `woff2`/`woff` via `fontTools`.
5. **Summary** — prints a size comparison table and total bytes saved.
6. **CSS** — prints ready-to-paste `@font-face` rules using the font's actual family name and resolved weight range.

## Output

For each font:

- `FontName.woff2` — primary format, Brotli-compressed
- `FontName.woff` — fallback format, Zopfli-compressed
- `FontName_instanced.ttf` — intermediate file (variable fonts only); safe to delete

And a CSS block:

```css
@font-face {
  font-family: 'Inter';
  src: url('assets/fonts/Inter.woff2') format('woff2'),
       url('assets/fonts/Inter.woff') format('woff');
  font-weight: 100 900;
  font-style: normal;
  font-display: swap;
}
```

## Helper scripts (standalone use)

The sub-modules can be run directly:

```sh
# list fonts in a project
python -m fontslice.list_fonts --dir path/to/your-theme
python -m fontslice.list_fonts --fonts-dir path/to/fonts --config path/to/_config.scss

# subset a single font manually
python -m fontslice.subset_font path/to/Font.ttf -o output/Font --subsets latin --weight 100:900
python -m fontslice.subset_font path/to/Font.ttf -o output/Font --subsets latin --weight 100:900 --opsz 14
```

## Development

```sh
cd tools/fontslice
uv venv && uv pip install -e .
fontslice --help
```
