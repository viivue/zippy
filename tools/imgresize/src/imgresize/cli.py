"""
imgresize — resize and crop images to target dimensions for teams.

Two modes:
  fit    scale the whole image to fit inside a target box, keeping aspect
         ratio (no cropping). This is the default.
  cover  scale to fill the target box keeping aspect ratio, then crop the
         overflow at a chosen anchor. Output is exactly the target size.

Handles JPEG, PNG, WebP, GIF, BMP, and TIFF using Pillow. Source files are
never modified. Outputs land in a 'resized/' subfolder unless --output is
given. EXIF metadata is stripped by default.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# ── Format support ────────────────────────────────────────────────────────────
INPUT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
OUTPUT_SUBFOLDER = "resized"

# ── Quality scale (--quality 1-5, higher = better) ───────────────────────────
# Maps to JPEG/WebP save quality (0-95).
QUALITY_MAP: dict[int, int] = {5: 92, 4: 82, 3: 72, 2: 60, 1: 45}
DEFAULT_QUALITY = 4

# PNG compression: 0 (none) - 9 (max). Higher = smaller but slower.
PNG_COMPRESS_MAP: dict[int, int] = {5: 6, 4: 7, 3: 8, 2: 9, 1: 9}

# oxipng effort: 1 (fast) - 6 (exhaustive). Pillow is a PNG *writer*, not an
# optimiser, so re-encoded PNGs are often bigger than a source that a real
# optimiser already touched. Running oxipng on our output recovers that.
OXIPNG_LEVEL_MAP: dict[int, int] = {5: 2, 4: 3, 3: 4, 2: 6, 1: 6}

# Extension -> the format we'd write when no conversion is requested. Used to
# label a "larger than source" output as a same-format re-encode.
SAME_FORMAT: dict[str, str] = {
    ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".gif": "GIF",
}

# Crop anchor -> Pillow ImageOps.fit centering tuple (x, y), 0.0 = start edge.
POSITION_CENTERING: dict[str, tuple[float, float]] = {
    "center": (0.5, 0.5),
    "top": (0.5, 0.0),
    "bottom": (0.5, 1.0),
    "left": (0.0, 0.5),
    "right": (1.0, 0.5),
    "top-left": (0.0, 0.0),
    "top-right": (1.0, 0.0),
    "bottom-left": (0.0, 1.0),
    "bottom-right": (1.0, 1.0),
}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class FileResult:
    source: Path
    output: Path | None
    input_size: int
    output_size: int
    status: str   # OK | LARGER | SKIPPED | FAILED | DRY-RUN
    resolution: str = ""
    error: str = ""


# ── Sizing maths ──────────────────────────────────────────────────────────────

def parse_aspect_ratio(text: str) -> float:
    """Parse '16:9', '16/9', or a bare float like '1.777' to a width/height ratio.

    Raises ValueError on anything unparseable or non-positive.
    """
    raw = text.strip().replace("/", ":")
    try:
        if ":" in raw:
            w_str, h_str = raw.split(":", 1)
            w, h = float(w_str), float(h_str)
            ratio = w / h
        else:
            ratio = float(raw)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(
            f"'{text}' is not a valid aspect ratio (try 16:9, 4:3, or 1.5)."
        ) from exc
    if ratio <= 0:
        raise ValueError(f"aspect ratio must be positive, got '{text}'.")
    return ratio


def compute_target(
    src_w: int,
    src_h: int,
    mode: str,
    width: int | None,
    height: int | None,
    aspect: float | None,
    allow_upscale: bool,
) -> tuple[int, int, bool]:
    """Return the output (width, height) plus a flag for whether the box was
    clamped down to avoid upscaling.

    Raises ValueError when the given options do not describe a target for the
    chosen mode.
    """
    if mode == "fit":
        if not width and not height:
            raise ValueError("fit mode needs --width or --height (or both).")
        scale_w = width / src_w if width else float("inf")
        scale_h = height / src_h if height else float("inf")
        scale = min(scale_w, scale_h)
        if not allow_upscale:
            scale = min(scale, 1.0)
        return max(1, round(src_w * scale)), max(1, round(src_h * scale)), False

    # mode == "cover": resolve the target box.
    if width and height:
        box_w, box_h = width, height
    elif aspect and width:
        box_w, box_h = width, max(1, round(width / aspect))
    elif aspect and height:
        box_w, box_h = max(1, round(height * aspect)), height
    elif aspect:
        # Largest box of this ratio that fits inside the source: a pure crop.
        if src_w / src_h > aspect:
            box_w, box_h = max(1, round(src_h * aspect)), src_h
        else:
            box_w, box_h = src_w, max(1, round(src_w / aspect))
    else:
        raise ValueError(
            "cover mode needs both --width and --height, or --aspect-ratio."
        )

    clamped = False
    if not allow_upscale:
        need = max(box_w / src_w, box_h / src_h)
        if need > 1:
            box_w = max(1, round(box_w / need))
            box_h = max(1, round(box_h / need))
            clamped = True
    return box_w, box_h, clamped


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

def resize_file(
    source: Path,
    output_dir: Path,
    *,
    mode: str,
    width: int | None,
    height: int | None,
    aspect: float | None,
    position: str,
    allow_upscale: bool,
    quality: int,
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
        out_name, out_fmt = source.stem + ".webp", "WEBP"
    elif to_jpg:
        out_name, out_fmt = source.stem + ".jpg", "JPEG"
    elif ext in (".jpg", ".jpeg"):
        out_name, out_fmt = source.stem + ".jpg", "JPEG"
    elif ext == ".png":
        out_name, out_fmt = source.stem + ".png", "PNG"
    elif ext == ".webp":
        out_name, out_fmt = source.stem + ".webp", "WEBP"
    elif ext == ".gif":
        out_name, out_fmt = source.stem + ".gif", "GIF"
    else:  # bmp / tiff / tif
        out_name, out_fmt = source.stem + ".png", "PNG"

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / out_name

    if output_path.exists() and not overwrite:
        print(f"  SKIP: {source.name} — output exists (--overwrite to replace)")
        return FileResult(
            source=source, output=output_path,
            input_size=input_size, output_size=output_path.stat().st_size,
            status="SKIPPED",
        )

    try:
        img = Image.open(source)

        # Correct EXIF orientation before measuring so the crop lines up.
        img = ImageOps.exif_transpose(img)
        src_w, src_h = img.size

        out_w, out_h, clamped = compute_target(
            src_w, src_h, mode, width, height, aspect, allow_upscale
        )
        resolution = f"{src_w}x{src_h} -> {out_w}x{out_h}"

        if clamped:
            print(
                f"  NOTE: {source.name} target is larger than the source; "
                f"clamped to {out_w}x{out_h} (--allow-upscale to enlarge)"
            )

        if dry_run:
            fmt_note = out_fmt if out_fmt != "PNG" else f"PNG compress={PNG_COMPRESS_MAP[quality]}"
            print(
                f"  DRY-RUN: {source.name} -> {mode} {resolution} "
                f"-> {fmt_note} -> {output_path}"
            )
            return FileResult(
                source=source, output=output_path,
                input_size=input_size, output_size=0,
                status="DRY-RUN", resolution=resolution,
            )

        if mode == "cover":
            img = ImageOps.fit(
                img, (out_w, out_h),
                method=Image.LANCZOS,
                centering=POSITION_CENTERING[position],
            )
        elif (out_w, out_h) != (src_w, src_h):
            img = img.resize((out_w, out_h), Image.LANCZOS)

        # Build save kwargs (mirrors imgopt).
        save_kwargs: dict = {}

        if out_fmt == "JPEG":
            if img.mode in ("RGBA", "P", "LA") or "transparency" in img.info:
                if ext == ".png":
                    print(
                        f"  WARN: {source.name} is a PNG with transparency or a "
                        f"palette — as JPEG it loses the alpha channel. Try "
                        f"--webp instead."
                    )
                img = img.convert("RGB")
            save_kwargs["quality"] = QUALITY_MAP[quality]
            save_kwargs["optimize"] = True
            save_kwargs["progressive"] = True
            if strip_exif:
                save_kwargs["exif"] = b""

        elif out_fmt == "PNG":
            save_kwargs["compress_level"] = PNG_COMPRESS_MAP[quality]
            save_kwargs["optimize"] = True

        elif out_fmt == "WEBP":
            # Graphics (PNG/GIF/BMP sources, or anything with an alpha channel)
            # encode badly as lossy WebP. Use lossless WebP for those and keep
            # lossy WebP for photographic (JPEG/opaque) input.
            is_graphic = (
                ext in (".png", ".gif", ".bmp")
                or img.mode in ("P", "LA", "RGBA")
                or "transparency" in img.info
            )
            if is_graphic:
                save_kwargs["lossless"] = True
                save_kwargs["quality"] = 100  # for lossless: effort, not fidelity
            else:
                save_kwargs["quality"] = QUALITY_MAP[quality]
            save_kwargs["method"] = 6
            if strip_exif:
                save_kwargs["exif"] = b""

        elif out_fmt == "GIF":
            pass  # Pillow re-saves GIFs; no meaningful quality knob

        img.save(output_path, format=out_fmt, **save_kwargs)

        if out_fmt == "PNG":
            _run_oxipng(output_path, quality)

    except ValueError:
        # A bad size/mode combination is a user error, not a per-file failure;
        # let it propagate so main() can report it and stop.
        raise
    except Exception as exc:
        return FileResult(
            source=source, output=None,
            input_size=input_size, output_size=0,
            status="FAILED", error=str(exc),
        )

    output_size = output_path.stat().st_size
    is_larger = output_size > input_size
    if is_larger:
        print(
            f"  NOTE: {source.name} output is larger "
            f"({_fmt_bytes(output_size)} > {_fmt_bytes(input_size)})"
        )
    return FileResult(
        source=source, output=output_path,
        input_size=input_size, output_size=output_size,
        status="LARGER" if is_larger else "OK", resolution=resolution,
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

    NM, ND, NO, NN = 24, 26, 10, 10

    print(
        f"{'File':<{NM}}"
        f"{'Resize':<{ND}}"
        f"{'Original':>{NO}}"
        f"{'Output':>{NN}}"
        "  Status"
    )
    print("-" * W)

    net_saved = 0
    failures: list[FileResult] = []

    for r in results:
        name = r.source.name
        if len(name) > NM - 1:
            name = name[: NM - 4] + "..."

        res = r.resolution or "-"
        if len(res) > ND - 1:
            res = res[: ND - 4] + "..."

        orig = _fmt_bytes(r.input_size)

        if r.status in ("FAILED", "DRY-RUN"):
            new_s = "-"
        elif r.status == "SKIPPED":
            new_s = _fmt_bytes(r.output_size)
        else:
            new_s = _fmt_bytes(r.output_size)
            net_saved += r.input_size - r.output_size

        flag = "  <<<" if r.status in ("FAILED", "LARGER") else ""
        print(
            f"{name:<{NM}}"
            f"{res:<{ND}}"
            f"{orig:>{NO}}"
            f"{new_s:>{NN}}"
            f"  {r.status}{flag}"
        )
        if r.status == "FAILED":
            failures.append(r)

    print("-" * W)
    if net_saved:
        sign = "" if net_saved >= 0 else "-"
        mb = abs(net_saved) / (1024 * 1024)
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
        prog="imgresize",
        description=(
            "Resize and crop images to target dimensions using Pillow.\n"
            "Source files are never modified or deleted."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  imgresize photo.jpg --width 1200                   # fit: width 1200, keep ratio
  imgresize photo.jpg --width 1200 --height 1200     # fit inside a 1200 square
  imgresize photo.jpg --mode cover --width 1200 --height 630
  imgresize photo.jpg --mode cover --aspect-ratio 16:9
  imgresize photo.jpg --mode cover --aspect-ratio 1:1 --position top
  imgresize icon.png --mode cover --width 512 --height 512 --allow-upscale
  imgresize photo.jpg --width 1600 --webp
  imgresize ./raw-images --recursive --width 1600
  imgresize ./raw-images --recursive --width 1600 --dry-run
        """.strip(),
    )

    parser.add_argument("input",
                        help="Source image file or folder")
    parser.add_argument("--output", metavar="DIR",
                        help="Destination folder (default: <input>/resized)")
    parser.add_argument("--mode", choices=("fit", "cover"), default="fit",
                        help="fit: scale to fit the box, keep ratio (default). "
                             "cover: fill the box, keep ratio, crop the overflow")
    parser.add_argument("--width", type=int, metavar="PX",
                        help="Target width")
    parser.add_argument("--height", type=int, metavar="PX",
                        help="Target height")
    parser.add_argument("--aspect-ratio", metavar="RATIO",
                        help="Target ratio for cover mode, e.g. 16:9 or 1:1")
    parser.add_argument("--position", choices=tuple(POSITION_CENTERING), default="center",
                        metavar="ANCHOR",
                        help="Crop anchor for cover mode: center (default), top, "
                             "bottom, left, right, top-left, top-right, "
                             "bottom-left, bottom-right")
    parser.add_argument("--allow-upscale", action="store_true",
                        help="Permit enlarging an image past its source size")
    parser.add_argument("--quality", type=int, choices=range(1, 6), default=DEFAULT_QUALITY,
                        metavar="1-5",
                        help=f"Output quality: 1=smallest .. 5=best (default: {DEFAULT_QUALITY})")
    parser.add_argument("--webp", action="store_true",
                        help="Convert all outputs to WebP")
    parser.add_argument("--jpg", action="store_true",
                        help="Convert all outputs to JPEG (lossy, drops transparency)")
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

    aspect: float | None = None
    if args.aspect_ratio:
        try:
            aspect = parse_aspect_ratio(args.aspect_ratio)
        except ValueError as exc:
            sys.exit(f"ERROR: {exc}")

    if args.mode == "fit" and not args.width and not args.height:
        sys.exit("ERROR: fit mode needs --width or --height (or both).")
    if args.mode == "cover" and not ((args.width and args.height) or aspect):
        sys.exit(
            "ERROR: cover mode needs both --width and --height, or --aspect-ratio."
        )

    input_path = Path(args.input)
    try:
        files = gather_inputs(input_path, recursive=args.recursive)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    if not files:
        print("No supported image files found.")
        sys.exit(0)

    print(f"imgresize: {len(files)} file(s) to process\n")

    if args.output:
        output_root = Path(args.output)
    else:
        base = input_path if input_path.is_dir() else input_path.parent
        output_root = base / OUTPUT_SUBFOLDER

    results: list[FileResult] = []

    for source_file in files:
        if input_path.is_dir() and args.recursive:
            rel = source_file.parent.relative_to(input_path)
            output_dir = output_root / rel
        else:
            output_dir = output_root

        try:
            result = resize_file(
                source_file,
                output_dir,
                mode=args.mode,
                width=args.width,
                height=args.height,
                aspect=aspect,
                position=args.position,
                allow_upscale=args.allow_upscale,
                quality=args.quality,
                to_webp=args.webp,
                to_jpg=args.jpg,
                strip_exif=not args.keep_exif,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
        except ValueError as exc:
            sys.exit(f"ERROR: {exc}")
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
