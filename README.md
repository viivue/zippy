# devkit

A monorepo of standalone Python command-line tools for internal team use.
Each tool is a fully independent package with no shared code or cross-dependencies.

## Tools

| Tool | Command | Description |
|------|---------|-------------|
| [vidopt](tools/vidopt/) | `vidopt` | Video optimisation helper (re-encode, resize, batch-process) |
| [fontslice](tools/fontslice/) | `fontslice` | Subset and convert variable/static fonts to optimized woff2/woff |

## Installing a tool

### Step 1 - Python 3.10 or later

Check if Python is already installed:

```sh
python --version
```

If it is missing or older than 3.10, download and install it from
[python.org/downloads](https://www.python.org/downloads/).

> **Windows tip:** In the installer check "Add Python to PATH" before clicking
> Install Now.

### Step 2 - install uv or pipx

Both are tool-runners that install each CLI into its own isolated environment.
Pick one.

#### uv (recommended)

##### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After the script completes, close and reopen your terminal so the `uv` command
is recognised.

##### macOS / Linux

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify: `uv --version`

#### pipx (alternative)

```sh
pip install --user pipx
pipx ensurepath
```

Close and reopen your terminal after `ensurepath`, then verify with
`pipx --version`.

### Step 3 - install the tool

From the repo root:

```sh
# uv
uv tool install ./tools/vidopt
uv tool install ./tools/fontslice

# pipx
pipx install ./tools/vidopt
pipx install ./tools/fontslice
```

After installation the commands `vidopt` and `fontslice` are available
system-wide. Run `<command> --help` to see usage.

## Updating a tool

Pull the latest code, then reinstall:

```sh
# uv
uv tool install --reinstall ./tools/vidopt
uv tool install --reinstall ./tools/fontslice

# pipx
pipx install --force ./tools/vidopt
pipx install --force ./tools/fontslice
```

## Adding a new tool

1. Copy an existing tool folder as a template:
   ```sh
   cp -r tools/vidopt tools/my-tool
   ```
2. Rename the inner `src/vidopt` directory to match your package name (use
   underscores, e.g. `src/my_tool`).
3. Edit `tools/my-tool/pyproject.toml`: update `name`, `version`, `description`,
   the `[project.scripts]` entry point, and the `[tool.hatch.build]` source path.
4. Write your CLI logic in `src/my_tool/cli.py`.
5. Add a row to the table above.
6. Install and verify: `uv tool install ./tools/my-tool && my-tool --help`
