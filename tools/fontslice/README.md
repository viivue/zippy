# FontSlice

Subset and convert variable/static fonts to optimized `woff2` files.

Processes `.ttf` files by default. Also discovers `.otf` and pre-compiled web
fonts (`.woff` / `.woff2` with no matching source) and prompts before including
them. Skips `icomoon*` and `fontawesome*` files. Reads weight ranges from
`$fonts` in `_config.scss` when available; when no `_config.scss` is found it
prompts to confirm or override the weight range for each font before building.

## Quick start

```sh
uv tool install ./tools/fontslice
cd path/to/your-theme
fontslice
```

Fonts and `_config.scss` are auto-discovered from the current folder. Answer
the prompts and it builds optimized `.woff2` files plus ready-to-paste
`@font-face` CSS. See [Usage](#usage) below for flags that skip the prompts.

## Requirements

Python 3.10+ and the following packages (installed automatically):

| Package | Purpose |
|---|---|
| `fonttools` | Font parsing, subsetting, instancing |
| `brotli` | woff2 compression |

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

### Step 3: install fontslice

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

`cd` into your theme project, fonts and `_config.scss` are auto-discovered:

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

### `--weights`: override font weights

Pin or range-limit weights instead of using the values from `_config.scss` or the
font's own axis. The flag is **repeatable** and can target a specific font with a
`FontName:` prefix.

| Example | Behaviour | Output |
|---|---|---|
| `--weights 400` | pin all fonts to 400 | `Font-400.woff2` |
| `--weights 400,700` | two static instances for all fonts | `Font-400.woff2`, `Font-700.woff2` |
| `--weights 400-700` | variable range 400-700 for all fonts | `Font.woff2` |
| `--weights NotoSansSC:400-700` | range for NotoSansSC only | `NotoSansSC.woff2` |
| `--weights NotoSansSC:400,700` | two pins for NotoSansSC only | `NotoSansSC-400.woff2`, `NotoSansSC-700.woff2` |

Multiple fonts in one command:

```sh
fontslice --weights NotoSansSC:400-700 --weights Inter:300,400,700
```

- **Range** (`400-700`): instances the variable axis to that range; the output is
  still a variable font within that span, just smaller. One output file.
- **Pins** (`400,700`): creates a separate static instance per weight. Multiple
  output files, one per pin.

Font name matching is case-insensitive and ignores spaces/dashes
(`NotoSansSC`, `Noto Sans SC`, and `noto-sans-sc` all match the same font).

### `--text-file`: subset to exact characters (recommended for CJK)

```sh
fontslice --subsets korean --text-file path/to/content.txt
```

Pass a plain-text file containing every character your site uses. fontTools will
keep only those glyphs, producing a much smaller file than a full-range subset.
This is the **recommended approach for Chinese, Korean, and Japanese** fonts, where
a full unicode-range subset can still be 2-10 MB.

When `--text-file` is provided it takes priority over `--subsets`.

### Available subsets

| Name | Coverage | Notes |
|---|---|---|
| `latin` | Basic Latin + common punctuation/symbols | Default |
| `latin-ext` | Extended Latin (Western/Central European) | |
| `vietnamese` | Vietnamese diacritics | |
| `cyrillic` | Core Cyrillic | |
| `cyrillic-ext` | Extended Cyrillic | |
| `greek` | Core Greek | |
| `greek-ext` | Extended Greek (polytonic) | |
| `chinese-simplified` | CJK Unified Ideographs + Simplified punctuation | Large output (2-8 MB), prefer `--text-file` |
| `chinese-traditional` | CJK Unified Ideographs + Traditional punctuation | Large output (2-8 MB), prefer `--text-file` |
| `korean` | Hangul syllables, Jamo, Hanja, punctuation | Large output (2-8 MB), prefer `--text-file` |
| `japanese` | Hiragana, Katakana, Kanji, punctuation | Large output (2-8 MB), prefer `--text-file` |

Combine subsets: `--subsets latin,latin-ext,vietnamese`

Use `--subsets all` to include every defined subset in one pass.

## What it does

1. **Discover**: scans for `.ttf`, `.otf`, `.woff`, and `.woff2` files (skipping `icomoon*` and `fontawesome*`). Resolves weight ranges from `_config.scss` (falls back to the font's own axis values).
2. **Filter**: only `.ttf` files are included by default. Prompts to also include `.otf` files and any pre-compiled web fonts (`.woff` / `.woff2` with no matching `.ttf` source).
3. **Report**: prints a table of selected fonts with family name, weight range, opsz default, and build status (`NEEDS_BUILD` / `UP_TO_DATE`). Fonts whose output is newer than the source are skipped.
4. **Weights** *(no config only)*: if no `_config.scss` and no `--weights` flag is given, prompts to confirm or override the auto-detected weight range per font.
5. **Ask**: prompts for character subsets (or uses `--subsets` / `--text-file`).
6. **Build**: for each font, instances variable axes to the resolved weight range/pins, then subsets and converts to `woff2` via `fontTools`.
7. **Metrics check**: fixes short ascent/descent metrics automatically. See [Ascent/descent metrics fix](#ascentdescent-metrics-fix) below.
8. **Summary**: prints a size comparison table and total bytes saved.
9. **CSS**: prints ready-to-paste `@font-face` rules using the font's actual family name and resolved weight.

## Ascent/descent metrics fix

| | |
|---|---|
| Issue | Fonts with short declared ascent clip tall glyph ink (e.g. Vietnamese `Ằ`, `Ẫ`, `Ổ`) in Chromium `<input>` fields, since it uses the font's own metrics and not CSS `line-height` there. |
| Fix | fontslice measures each build's actual glyph ink and widens `hhea`/`OS2` ascent and descent to fit, automatically. Metadata only, never shrinks. |
| Action needed | None, this is automatic. A patched font prints its old/new values during build. |

## Output

For each font:

- `FontName.woff2`: Brotli-compressed (range or default)
- `FontName-400.woff2`, `FontName-700.woff2`: one file per pin when `--weights` uses pins
- `FontName.opt.woff2`: output for `.woff` / `.woff2` source files (subset/optimized copy)
- `FontName_instanced.ttf`: intermediate file (variable fonts only); safe to delete

And a CSS block per output file:

```css
/* default (full axis range from font or _config.scss) */
@font-face {
  font-family: 'Inter';
  src: url('assets/fonts/Inter.woff2') format('woff2');
  font-weight: 100 900;
  font-style: normal;
  font-display: swap;
}

/* range (--weights 400-700) */
@font-face {
  font-family: 'Inter';
  src: url('assets/fonts/Inter.woff2') format('woff2');
  font-weight: 400 700;
  font-style: normal;
  font-display: swap;
}

/* pins (--weights 400,700) */
@font-face {
  font-family: 'Inter';
  src: url('assets/fonts/Inter-400.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
```

## Advanced: standalone scripts

The sub-modules can be run directly, useful for one-off scripting rather than
the interactive flow above:

```sh
# list fonts in a project
python -m fontslice.list_fonts --dir path/to/your-theme
python -m fontslice.list_fonts --fonts-dir path/to/fonts --config path/to/_config.scss

# subset a single font manually
python -m fontslice.subset_font path/to/Font.ttf -o output/Font --subsets latin --weight 100:900
python -m fontslice.subset_font path/to/Font.ttf -o output/Font --subsets latin --weight 100:900 --opsz 14

# CJK with text-based subsetting
python -m fontslice.subset_font path/to/NotoSansSC.ttf -o output/NotoSansSC --text-file content.txt --weight 400
```

## Development

```sh
cd tools/fontslice
uv venv && uv pip install -e .
fontslice --help
```

The `-e` flag installs in editable mode, so source changes take effect
immediately without reinstalling.

If you add or change dependencies in `pyproject.toml`, re-run:

```sh
uv pip install -e .
```
