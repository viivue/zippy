# zippy

A local web UI that wraps `vidopt`, `imgopt`, and `fontslice` behind a single
tabbed page. Runs entirely on your machine, the server only binds to
`127.0.0.1`, and every job works with file/folder *paths* you browse to, not
uploads. Source files are never modified, same as the CLIs.

## Requirements

- Python 3.10 or later
- `uv` (see the root [README](../../README.md#installing-a-tool) for install steps)
- ffmpeg on PATH or auto-downloadable (only needed for the Video tab, same
  requirement as `vidopt`)
- A desktop session for the native folder/file picker (uses `tkinter`, bundled
  with standard Python installs). If `tkinter` isn't available, the UI falls
  back to a plain text prompt for paths.

## Install

zippy depends on `vidopt`, `imgopt`, and `fontslice` as local path
dependencies (declared under `[tool.uv.sources]` in `pyproject.toml`), so it
is **uv-first**: `uv tool install` resolves those paths automatically. `pipx`
does not understand intra-repo path dependencies the same way, so it isn't
supported for this tool specifically (the other three tools install fine with
either).

From the repo root:

```sh
uv tool install ./tools/zippy
```

To pick up code changes to zippy *or* to vidopt/imgopt/fontslice, reinstall:

```sh
uv tool install --reinstall ./tools/zippy
```

Optional: install the `[window]` extra for the native desktop window (Phase 2):

```sh
uv tool install ./tools/zippy --with pywebview
```

Run `zippy --help` to verify.

## Usage

```sh
zippy                  # start the server and open a browser tab
zippy --no-open        # start the server without opening a browser
zippy --port 9000      # bind to a different port
zippy --window         # open in a native desktop window instead of a browser
```

Open the three tabs (**Images**, **Videos**, **Fonts**), browse to an input
file or folder, set options (same defaults as each CLI), and click
**Optimize**. Progress streams live; results land in an `optimized/`
subfolder next to your input, same as running the CLI directly, unless you
set an output folder override.

**Fonts tab**: browse to a project folder to scan it for a `fonts/` directory
and `_config.scss` (same auto-detection `fontslice` uses), review the
detected fonts and their weight ranges, edit per-font weight overrides,
choose subsets (or a text file for exact CJK subsetting), and build. The
generated `@font-face` CSS is shown in a copyable block afterward.

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--port PORT` | `8765` | Port to bind to |
| `--no-open` | off | Don't automatically open a browser tab on start |
| `--window` | off | Open in a native pywebview window instead of the browser (requires the `[window]` extra; falls back to browser mode with a hint if not installed) |

## Notes on design deviations from the CLIs

- The Video tab only accepts `.mp4`/`.mov` and the Images tab only accepts
  the formats Pillow can read (`.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`,
  `.bmp`, `.tiff`/`.tif`), matching `vidopt`/`imgopt` exactly.
- The Fonts tab adds an explicit **Include** checkbox per detected font
  (checked by default only for `.ttf` sources), replacing the CLI's
  interactive `[y/N]` prompts for `.otf` and pre-compiled web fonts.
- Real (non-dry-run) video encodes stream ffmpeg's `-progress pipe:1` output
  for live percent complete; dry-run and image/font jobs report per-file
  progress instead.

## Screenshots

_(placeholder, add screenshots of the Images, Videos, and Fonts tabs here)_
