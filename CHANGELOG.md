# Changelog

All notable changes to the zippy workspace are documented here. Versions apply
to all five packages (`fontslice`, `imgopt`, `imgresize`, `vidopt`, `zippy`),
which move in lockstep.

## [Unreleased]

### Added

- **imgresize:** new tool to resize or crop images to target dimensions, in
  `fit` mode (scale to a box, keep ratio) or `cover` mode (fill a box, keep
  ratio, crop the overflow), with imgopt-style `--quality` and `--webp`/`--jpg`
  options. Also available as a **Resize** tab in the `zippy` UI.

## [0.1.1] - 2026-09-03

### Added

- uv workspace at the repo root so `zippy` and every tool run from a single
  `uv sync`.
- Root `CONTRIBUTING.md` covering how to add a new tool.

### Fixed

- **imgopt:** never emit an output image larger than the source; the original is
  kept when optimization would inflate the file.
- **fontslice:** auto-widen ascent/descent so they always cover the glyph ink,
  preventing clipped rendering.

## [0.1.0]

- Initial release: `fontslice`, `imgopt`, `vidopt` CLIs and the `zippy` local web
  UI wrapping all three.

[0.1.1]: https://github.com/viivue/zippy/releases/tag/v0.1.1
