# Contributing

## Contributing a new tool

1. Copy an existing tool folder as a template:
   ```sh
   cp -r tools/imgopt tools/my-tool
   ```
2. Rename `src/imgopt` to match your package name (underscores, e.g. `src/my_tool`).
3. Edit `tools/my-tool/pyproject.toml`: update `name`, `version`, `description`,
   the `[project.scripts]` entry, and the `[tool.hatch.build]` source path.
4. Write your CLI logic in `src/my_tool/cli.py`.
5. Add a row to the [Tools](README.md#tools) table, and a full README in the new
   tool's folder covering install/usage (see the other tools for the format).
6. Install and verify: `uv tool install ./tools/my-tool && my-tool --help`
7. If the tool should be usable from the UI, wire it into `tools/zippy` as a
   local path dependency (see `tools/zippy/pyproject.toml` for the pattern).
