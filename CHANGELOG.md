# Changelog

All notable changes to the zippy workspace are documented here. Versions apply
to all four packages (`fontslice`, `imgopt`, `vidopt`, `zippy`), which move in
lockstep.

## [0.2.0] - 2026-11-17

Optimized files now keep copyright, license and provenance metadata while
still stripping private data. See "Metadata and copyright" in the README for
what each tool keeps and removes.

### Added

- **imgopt, vidopt:** detect C2PA Content Credentials, report that the
  re-encode invalidates them, and carry the AI-generated marker
  (`DigitalSourceType`) into the output's XMP.
- **fontslice:** warn when a font's embedding permissions (`fsType`
  restricted, preview and print, no subsetting, bitmap only) or license (not
  OFL/Apache, or an OFL Reserved Font Name) may not allow web use.
- **fontslice:** write a `<Family>-LICENSE.txt` with the copyright and license
  records next to the outputs.
- **vidopt:** carry XMP rights fields (`dc:rights`, `dc:creator`,
  `xmpRights:*`, PLUS license IDs, `photoshop:Credit`/`Source`) from the
  source's XMP `uuid` box or QuickTime `moov/udta/XMP_` into an XMP box
  appended to the output; ffmpeg drops XMP entirely.
- **zippy:** results tables show per-file notes (C2PA, font license warnings)
  under the file name.
- README "Metadata and copyright" section and a Metadata section in each tool
  README.

### Changed

- **imgopt:** author, copyright and license metadata is kept by default: EXIF
  Artist/Copyright; IPTC-IIM By-line, Credit, Source, Copyright Notice and
  Contact; XMP rights, PLUS and IPTC licensing fields; PNG
  Copyright/Author/Disclaimer text; comments that read like a rights notice.
  IIM rights are copied into XMP when converting to WebP or PNG. Camera
  details, GPS, dates and other metadata are still stripped.
- **imgopt:** non-sRGB colour profiles (Display P3, Adobe RGB) are kept so
  colours don't shift; plain sRGB profiles are still dropped.
- **imgopt:** private JPEG and GIF comments are now stripped by default.
- **imgopt:** requires Pillow 11.0 or newer (was 10.0), needed to write XMP
  into JPEG.
- **fontslice:** keep every `name` table record, so trademark, manufacturer,
  designer, license and license URL survive subsetting.
- **vidopt:** keep `copyright`, `artist`, `author`, `album_artist`, `composer`
  and `license` container tags while still stripping all other metadata.
- **zippy:** the "Keep EXIF metadata" option is now "Keep all metadata".

### Fixed

- **imgopt:** `--keep-exif` now actually keeps EXIF, XMP, IPTC, PNG text and
  the ICC profile; it previously kept nothing.
- **imgopt:** oxipng no longer strips the PNG text and EXIF chunks imgopt
  wrote on purpose.
- `__version__` in `fontslice` and `vidopt` was stuck at 0.1.0.

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

[0.2.0]: https://github.com/viivue/zippy/releases/tag/v0.2.0
[0.1.1]: https://github.com/viivue/zippy/releases/tag/v0.1.1
