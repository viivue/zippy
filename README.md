# devkit

A monorepo of standalone Python command-line tools for internal team use.
Each tool is a fully independent package with no shared code or cross-dependencies.

## Tools

| Tool | Command | Description |
|------|---------|-------------|
| [vidopt](tools/vidopt/) | `vidopt` | Video optimisation helper (re-encode, resize, batch-process) |
| [fontslice](tools/fontslice/) | `fontslice` | Subset and convert variable/static fonts to optimized woff2/woff |

## Installing a tool

### uv (recommended)

```sh
uv tool install ./tools/vidopt
uv tool install ./tools/fontslice
```

### pipx

```sh
pipx install ./tools/vidopt
pipx install ./tools/fontslice
```

After installation the commands `vidopt` and `fontslice` are available system-wide.
Run `<command> --help` to see usage.

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
