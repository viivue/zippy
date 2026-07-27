<div align="center">

# zippy

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)
![Package manager: uv](https://img.shields.io/badge/package%20manager-uv-de5fe9?style=flat-square)
![Platform](https://img.shields.io/badge/platform-windows%20%7C%20macos%20%7C%20linux-lightgrey?style=flat-square)
![Maintained by ViiVue](https://img.shields.io/badge/maintained%20by-ViiVue-f1c400?style=flat-square)

A local web UI for optimizing images, videos, and fonts, no command line
required.

</div>

## Quick start

```sh
uv tool install ./tools/zippy
zippy
```

A browser tab opens at `http://127.0.0.1:8765` with tabs for Images, Videos,
and Fonts. Pick a file or folder, click optimize, done. Nothing you select is
ever modified in place, outputs land in a new `optimized/` folder next to
the source.

Don't have `uv` yet? See [Step 1](#step-1-python-310-or-later) below.

## Installing

### Step 1: Python 3.10 or later

```sh
python --version
```

If missing or older than 3.10, install from [python.org/downloads](https://www.python.org/downloads/).

> **Windows tip:** Check "Add Python to PATH" in the installer before clicking Install Now.

### Step 2: install uv

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```sh
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify: `uv --version`

### Step 3: install zippy

```sh
uv tool install ./tools/zippy
```

This bundles `vidopt`, `imgopt`, and `fontslice` automatically, no need to
install them separately. Run `zippy --help` to verify the install worked.

### Updating

Pull the latest code, then reinstall:

```sh
uv tool install --reinstall ./tools/zippy
```

---

## Tools

`zippy` is the recommended way to use everything in this repo. Each tool
also ships as its own standalone CLI for scripting or terminal use, follow a
link below for that tool's install and usage instructions.

| Tool | Command | Description |
|------|---------|-------------|
| [zippy](tools/zippy/) | `zippy` | Local web UI wrapping vidopt, imgopt, and fontslice in one tabbed page |
| [vidopt](tools/vidopt/) | `vidopt` | Re-encode MP4/MOV videos to streaming-ready H.264/H.265 MP4 |
| [fontslice](tools/fontslice/) | `fontslice` | Subset variable/static fonts and export optimized woff2 files |
| [imgopt](tools/imgopt/) | `imgopt` | Compress JPEG/PNG/WebP images, resize, and convert to WebP or JPEG |

Each tool is a fully independent package with no shared code or
cross-dependencies.

---

## Contributing a new tool

1. Copy an existing tool folder as a template:
   ```sh
   cp -r tools/imgopt tools/my-tool
   ```
2. Rename `src/imgopt` to match your package name (underscores, e.g. `src/my_tool`).
3. Edit `tools/my-tool/pyproject.toml`: update `name`, `version`, `description`,
   the `[project.scripts]` entry, and the `[tool.hatch.build]` source path.
4. Write your CLI logic in `src/my_tool/cli.py`.
5. Add a row to the [Tools](#tools) table, and a full README in the new
   tool's folder covering install/usage (see the other tools for the format).
6. Install and verify: `uv tool install ./tools/my-tool && my-tool --help`
7. If the tool should be usable from the UI, wire it into `tools/zippy` as a
   local path dependency (see `tools/zippy/pyproject.toml` for the pattern).
