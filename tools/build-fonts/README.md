# build-fonts

Font build pipeline: subset, compile, and package webfonts.

## Install

```sh
uv tool install ./tools/build-fonts   # from repo root
# or
pipx install ./tools/build-fonts
```

## Usage

```
build-fonts --help
build-fonts --input fonts/MyFont.ttf --formats woff2,woff
```

## Development

```sh
cd tools/build-fonts
uv venv && uv pip install -e .
build-fonts --help
```

## Dependencies

Runtime dependencies go in `pyproject.toml → [project] dependencies`.
Planned: `fonttools`, `brotli`.
