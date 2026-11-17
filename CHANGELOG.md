# Changelog

All notable changes to the zippy workspace are documented here. Versions apply
to all four packages (`fontslice`, `imgopt`, `vidopt`, `zippy`), which move in
lockstep.

## [Unreleased]

### Fixed

- **imgopt:** author and copyright metadata (EXIF Artist/Copyright, XMP rights,
  PNG Copyright/Author/Disclaimer text) and non-sRGB colour profiles are now
  kept by default; other metadata is still stripped.
- **imgopt:** `--keep-exif` ("Keep all metadata" in the UI) now actually keeps
  EXIF, XMP, PNG text and the ICC profile; it previously kept nothing.
- **imgopt:** keep IPTC-IIM rights datasets (By-line, Credit, Source, Copyright
  Notice, Contact), PLUS and IPTC licensing XMP, the AI-generated marker
  (`DigitalSourceType`) and comments that read like a rights notice. IIM rights
  are copied into XMP when converting to WebP or PNG.
- **imgopt, vidopt:** detect C2PA Content Credentials, report that the
  re-encode invalidates them, and carry the AI-generated marker
  (`DigitalSourceType`) into the output's XMP. zippy shows the note under the
  file name in the results table.
- **imgopt:** private JPEG and GIF comments are now stripped by default; Pillow
  used to copy them through.
- **fontslice:** keep every `name` table record, so trademark, manufacturer,
  designer, license and license URL survive subsetting.
- **fontslice:** warn when a font's embedding permissions (`fsType`
  restricted, preview and print, no subsetting, bitmap only) or license (not
  OFL/Apache, or an OFL Reserved Font Name) may not allow web use, and write a
  `<Family>-LICENSE.txt` with the copyright and license records next to the
  outputs. zippy shows the warnings under each built font.
- **vidopt:** keep `copyright`, `artist`, `author`, `album_artist`, `composer`
  and `license` container tags while still stripping all other metadata.

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
