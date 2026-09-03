"""
imgopt — web-optimised image compression for teams.

Compresses JPEG, PNG, WebP, GIF, BMP, and TIFF images using Pillow.
Source files are never modified. Outputs land in an 'optimized/' subfolder
unless --output is given. EXIF metadata is stripped by default.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# ── Format support ────────────────────────────────────────────────────────────
INPUT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
OUTPUT_SUBFOLDER = "optimized"

# ── Quality scale (--quality 1-5, higher = better) ───────────────────────────
# Maps to JPEG/WebP save quality (0–95).
QUALITY_MAP: dict[int, int] = {5: 92, 4: 82, 3: 72, 2: 60, 1: 45}
DEFAULT_QUALITY = 4

# PNG compression: 0 (none) – 9 (max). Higher = smaller but slower.
PNG_COMPRESS_MAP: dict[int, int] = {5: 6, 4: 7, 3: 8, 2: 9, 1: 9}

# oxipng effort: 1 (fast) – 6 (exhaustive). Pillow is a PNG *writer*, not an
# optimiser, so re-encoded PNGs are often bigger than a source that a real
# optimiser already touched. Running oxipng on our output recovers that.
OXIPNG_LEVEL_MAP: dict[int, int] = {5: 2, 4: 3, 3: 4, 2: 6, 1: 6}

# Extension -> the format we'd write when no conversion is requested. Used to
# decide whether a "larger than source" result is a same-format regression
# (which we undo) or an intentional format change (which we keep).
SAME_FORMAT: dict[str, str] = {
    ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".gif": "GIF",
}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class FileResult:
    source: Path
    output: Path | None
    input_size: int
    output_size: int
    status: str   # OK | LARGER | COPIED | SKIPPED | FAILED | DRY-RUN
    error: str = ""


# ── PNG post-processing ───────────────────────────────────────────────────────

def _run_oxipng(path: Path, quality: int) -> None:
    """Losslessly shrink a PNG in place with oxipng, if it is installed.

    A no-op when the file is already optimal or oxipng is missing; never raises.
    """
    try:
        import oxipng  # type: ignore[import]
    except ImportError:
        return
    try:
        oxipng.optimize(
            str(path),
            level=OXIPNG_LEVEL_MAP.get(quality, 3),
            strip=oxipng.StripChunks.safe(),
        )
    except Exception:
        pass


# ── Core processing ───────────────────────────────────────────────────────────

def optimize_file(
    source: Path,
    output_dir: Path,
    quality: int,
    max_width: int | None,
    max_height: int | None,
    to_webp: bool,
    to_jpg: bool,
    strip_exif: bool,
    overwrite: bool,
    dry_run: bool,
) -> FileResult:
    try:
        from PIL import Image, ImageOps  # type: ignore[import]
    except ImportError:
        sys.exit("ERROR: Pillow is not installed. Run: pip install Pillow")

    input_size = source.stat().st_size
    ext = source.suffix.lower()

    if to_webp:
        out_name = source.stem + ".webp"
        out_fmt = "WEBP"
    elif to_jpg:
        out_name = source.stem + ".jpg"
        out_fmt = "JPEG"
    elif ext in (".jpg", ".jpeg"):
        out_name = source.stem + ".jpg"
        out_fmt = "JPEG"
    elif ext == ".png":
        out_name = source.stem + ".png"
        out_fmt = "PNG"
    elif ext == ".webp":
        out_name = source.stem + ".webp"
        out_fmt = "WEBP"
    elif ext == ".gif":
        out_name = source.stem + ".gif"
        out_fmt = "GIF"
    elif ext in (".bmp",):
        out_name = source.stem + ".png"
        out_fmt = "PNG"
    else:  # tiff/tif
        out_name = source.stem + ".png"
        out_fmt = "PNG"

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / out_name

    if output_path.exists() and not overwrite:
        print(f"  SKIP: {source.name} — output exists (--overwrite to replace)")
        return FileResult(
            source=source, output=output_path,
            input_size=input_size, output_size=output_path.stat().st_size,
            status="SKIPPED",
        )

    if dry_run:
        q = QUALITY_MAP[quality]
        action = f"{out_fmt} quality={q}" if out_fmt != "PNG" else f"PNG compress={PNG_COMPRESS_MAP[quality]}"
        resize = ""
        if max_width or max_height:
            resize = f" max={max_width or '?'}x{max_height or '?'}"
        print(f"  DRY-RUN: {source.name} -> {action}{resize} -> {output_path}")
        return FileResult(
            source=source, output=output_path,
            input_size=input_size, output_size=0,
            status="DRY-RUN",
        )

    try:
        img = Image.open(source)

        # Correct EXIF orientation before any resize so thumbnails face the right way.
        img = ImageOps.exif_transpose(img)

        # Resize if needed (preserve aspect ratio).
        w, h = img.size
        new_w, new_h = w, h
        if max_width and w > max_width:
            new_h = round(h * max_width / w)
            new_w = max_width
        if max_height and new_h > max_height:
            new_w = round(new_w * max_height / new_h)
            new_h = max_height
        resized = (new_w, new_h) != (w, h)
        if resized:
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # Build save kwargs.
        save_kwargs: dict = {}

        if out_fmt == "JPEG":
            if img.mode in ("RGBA", "P", "LA") or "transparency" in img.info:
                if ext == ".png":
                    print(
                        f"  WARN: {source.name} is a PNG with transparency or a "
                        f"palette — as JPEG it usually grows a lot and loses the "
                        f"alpha channel. Try --webp instead."
                    )
                img = img.convert("RGB")
            save_kwargs["quality"]   = QUALITY_MAP[quality]
            save_kwargs["optimize"]  = True
            save_kwargs["progressive"] = True
            if strip_exif:
                save_kwargs["exif"] = b""

        elif out_fmt == "PNG":
            save_kwargs["compress_level"] = PNG_COMPRESS_MAP[quality]
            save_kwargs["optimize"]       = True

        elif out_fmt == "WEBP":
            # Graphics (PNG/GIF/BMP sources, or anything with an alpha channel)
            # are full of hard edges that lossy WebP encodes very badly — often
            # many times the size of the source. Use lossless WebP for those and
            # keep lossy WebP for photographic (JPEG/opaque) input.
            is_graphic = (
                ext in (".png", ".gif", ".bmp")
                or img.mode in ("P", "LA", "RGBA")
                or "transparency" in img.info
            )
            if is_graphic:
                save_kwargs["lossless"] = True
                save_kwargs["quality"]  = 100  # for lossless: effort, not fidelity
            else:
                save_kwargs["quality"] = QUALITY_MAP[quality]
            save_kwargs["method"] = 6  # best compression ratio
            if strip_exif:
                save_kwargs["exif"] = b""

        elif out_fmt == "GIF":
            pass  # Pillow re-saves GIFs; no meaningful quality knob

        img.save(output_path, format=out_fmt, **save_kwargs)

        if out_fmt == "PNG":
            _run_oxipng(output_path, quality)

    except Exception as exc:
        return FileResult(
            source=source, output=None,
            input_size=input_size, output_size=0,
            status="FAILED", error=str(exc),
        )

    output_size = output_path.stat().st_size

    # A re-encode that ended up larger, in the same format and at the same
    # dimensions, is a regression — the source was already well optimised.
    # Keep the smaller original rather than shipping a worse file.
    same_format = SAME_FORMAT.get(ext) == out_fmt
    if output_size >= input_size and same_format and not resized:
        shutil.copyfile(source, output_path)
        return FileResult(
            source=source, output=output_path,
            input_size=input_size, output_size=input_size,
            status="COPIED",
        )

    is_larger = output_size > input_size
    if is_larger:
        print(
            f"  NOTE: {source.name} output is larger "
            f"({_fmt_bytes(output_size)} > {_fmt_bytes(input_size)})"
        )
    return FileResult(
        source=source, output=output_path,
        input_size=input_size, output_size=output_size,
        status="LARGER" if is_larger else "OK",
    )


# ── Input gathering ───────────────────────────────────────────────────────────

def gather_inputs(input_path: Path, recursive: bool) -> list[Path]:
    """Resolve an input path to a list of image files.

    Raises FileNotFoundError if the path does not exist, or ValueError if a
    single file has an unsupported extension.
    """
    if input_path.is_file():
        if input_path.suffix.lower() not in INPUT_EXTENSIONS:
            raise ValueError(
                f"'{input_path.name}' is not a supported image file "
                f"({', '.join(sorted(INPUT_EXTENSIONS))})."
            )
        return [input_path]

    if input_path.is_dir():
        globber = input_path.rglob if recursive else input_path.glob
        files: list[Path] = []
        for ext in INPUT_EXTENSIONS:
            files.extend(globber("*" + ext))
            files.extend(globber("*" + ext.upper()))
        return sorted(set(files))

    raise FileNotFoundError(f"'{input_path}' does not exist.")


# ── Summary report ────────────────────────────────────────────────────────────

def print_report(results: list[FileResult]) -> int:
    W = 80
    print()
    print("=" * W)
    print("SUMMARY")
    print("=" * W)

    NM, NO, NN, NS = 34, 11, 11, 8

    print(
        f"{'File':<{NM}}"
        f"{'Original':>{NO}}"
        f"{'Output':>{NN}}"
        f"{'Saved':>{NS}}"
        "  Status"
    )
    print("-" * W)

    net_saved = 0
    failures: list[FileResult] = []

    for r in results:
        name = r.source.name
        if len(name) > NM - 1:
            name = name[: NM - 4] + "..."

        orig = _fmt_bytes(r.input_size)

        if r.status in ("FAILED", "DRY-RUN"):
            new_s, saved_s = "-", "-"
        elif r.status == "SKIPPED":
            new_s, saved_s = _fmt_bytes(r.output_size), "-"
        elif r.status == "COPIED":
            new_s, saved_s = _fmt_bytes(r.output_size), "kept"
        else:
            new_s  = _fmt_bytes(r.output_size)
            saved  = r.input_size - r.output_size
            net_saved += saved
            pct    = saved * 100 / r.input_size if r.input_size else 0.0
            saved_s = f"{pct:+.1f}%" if r.status == "LARGER" else f"{pct:.1f}%"

        flag = "  <<<" if r.status in ("FAILED", "LARGER") else ""
        print(
            f"{name:<{NM}}"
            f"{orig:>{NO}}"
            f"{new_s:>{NN}}"
            f"{saved_s:>{NS}}"
            f"  {r.status}{flag}"
        )
        if r.status == "FAILED":
            failures.append(r)

    print("-" * W)
    if net_saved:
        sign = "" if net_saved >= 0 else "-"
        mb   = abs(net_saved) / (1024 * 1024)
        print(f"Net saved: {sign}{mb:.2f} MB")

    if failures:
        print(f"\nFailed ({len(failures)}):")
        for f in failures:
            print(f"  {f.source.name}: {f.error}")
        return 1

    return 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024**2:.1f} MB"


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="imgopt",
        description=(
            "Optimise JPEG/PNG/WebP images for web delivery using Pillow.\n"
            "Source files are never modified or deleted."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  imgopt photo.jpg
  imgopt banner.png --output ./exports
  imgopt ./raw-images --recursive
  imgopt photo.jpg --quality 5          # best quality
  imgopt photo.jpg --quality 2          # smallest file
  imgopt photo.jpg --webp               # convert to WebP
  imgopt photo.png --jpg                # convert to JPEG
  imgopt photo.jpg --max-width 1920
  imgopt photo.jpg --max-width 1920 --max-height 1080
  imgopt ./raw-images --dry-run
  imgopt ./raw-images --recursive --overwrite
        """.strip(),
    )

    parser.add_argument("input",
                        help="Source image file or folder")
    parser.add_argument("--output", metavar="DIR",
                        help="Destination folder (default: <input>/optimized)")
    parser.add_argument("--quality", type=int, choices=range(1, 6), default=DEFAULT_QUALITY,
                        metavar="1-5",
                        help=f"Output quality: 1=smallest .. 5=best (default: {DEFAULT_QUALITY})")
    parser.add_argument("--webp", action="store_true",
                        help="Convert all outputs to WebP (smaller, modern browsers)")
    parser.add_argument("--jpg", action="store_true",
                        help="Convert all outputs to JPEG (note: lossy, drops transparency)")
    parser.add_argument("--max-width", type=int, metavar="PX",
                        help="Scale down if image is wider than PX (preserves aspect ratio)")
    parser.add_argument("--max-height", type=int, metavar="PX",
                        help="Scale down if image is taller than PX (preserves aspect ratio)")
    parser.add_argument("--keep-exif", action="store_true",
                        help="Preserve EXIF metadata (stripped by default)")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Include subfolders when input is a directory")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing output files")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be done without writing files")

    args = parser.parse_args()

    if args.webp and args.jpg:
        sys.exit("ERROR: --webp and --jpg are mutually exclusive.")

    input_path = Path(args.input)
    try:
        files = gather_inputs(input_path, recursive=args.recursive)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    if not files:
        print("No supported image files found.")
        sys.exit(0)

    print(f"imgopt: {len(files)} file(s) to process\n")

    if args.output:
        output_root = Path(args.output)
    else:
        base = input_path if input_path.is_dir() else input_path.parent
        output_root = base / OUTPUT_SUBFOLDER

    results: list[FileResult] = []

    for source_file in files:
        if input_path.is_dir() and args.recursive:
            rel        = source_file.parent.relative_to(input_path)
            output_dir = output_root / rel
        else:
            output_dir = output_root

        try:
            result = optimize_file(
                source=source_file,
                output_dir=output_dir,
                quality=args.quality,
                max_width=args.max_width,
                max_height=args.max_height,
                to_webp=args.webp,
                to_jpg=args.jpg,
                strip_exif=not args.keep_exif,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            result = FileResult(
                source=source_file,
                output=None,
                input_size=source_file.stat().st_size if source_file.exists() else 0,
                output_size=0,
                status="FAILED",
                error=str(exc),
            )

        results.append(result)

    sys.exit(print_report(results))


if __name__ == "__main__":
    main()
