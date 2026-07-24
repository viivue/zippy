"""
vidopt — web-optimised video encoding for teams.

Encodes MP4/MOV source files to streaming-ready H.264 (or H.265) MP4 using
ffmpeg. Source files are never modified. Outputs land in an 'optimized/'
subfolder unless --output is given.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ── Encoding defaults ─────────────────────────────────────────────────────────
DEFAULT_VIDEO_CODEC   = "libx264"
DEFAULT_AUDIO_BITRATE = "160k"
DEFAULT_PIXEL_FORMAT  = "yuv420p"  # broadest browser/device support

H265_VIDEO_CODEC = "libx265"
H265_TAG         = "hvc1"  # Apple/Safari require this tag for HEVC in MP4

# ── Quality scale (--quality 1-5, higher = better) ───────────────────────────
QUALITY_CRF_H264: dict[int, int] = {5: 18, 4: 21, 3: 23, 2: 25, 1: 28}
QUALITY_CRF_H265: dict[int, int] = {5: 21, 4: 24, 3: 26, 2: 28, 1: 31}
DEFAULT_QUALITY = 4

# ── Speed scale ───────────────────────────────────────────────────────────────
SPEED_PRESET: dict[str, str] = {
    "fast":     "faster",
    "balanced": "medium",
    "slow":     "slow",
    "thorough": "veryslow",
}
DEFAULT_SPEED = "slow"

INPUT_EXTENSIONS = {".mp4", ".mov"}
OUTPUT_EXTENSION = ".mp4"
OUTPUT_SUBFOLDER = "optimized"

# ── ffmpeg auto-download (Windows only) ──────────────────────────────────────
FFMPEG_DOWNLOAD_URL = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)
# Store downloaded binaries in the user's home directory so they survive
# package upgrades and work regardless of where the package is installed.
BIN_DIR     = Path.home() / ".vidopt" / "bin"
_ON_WINDOWS = sys.platform == "win32"
_EXE        = ".exe" if _ON_WINDOWS else ""

# ── Optional tqdm ─────────────────────────────────────────────────────────────
try:
    from tqdm import tqdm as _tqdm  # type: ignore[import]
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class VideoInfo:
    """Probe metadata for one source file."""
    path: Path
    duration: float
    width: int
    height: int
    video_codec: str
    has_audio: bool
    has_attached_pic: bool = False


@dataclass
class FileResult:
    """Outcome of processing one file."""
    source: Path
    output: Path | None
    input_size: int
    output_size: int
    resolution: str
    status: str  # OK | LARGER | SKIPPED | FAILED | DRY-RUN
    error: str = ""


# ── ffmpeg resolution ─────────────────────────────────────────────────────────

def _ffmpeg_not_found_message() -> str:
    if sys.platform == "darwin":
        hint = "  brew install ffmpeg"
    elif sys.platform.startswith("linux"):
        hint = (
            "  sudo apt install ffmpeg   # Debian / Ubuntu\n"
            "  sudo dnf install ffmpeg   # Fedora / RHEL"
        )
    else:
        hint = f"  Download from: {FFMPEG_DOWNLOAD_URL}"
    return f"ffmpeg not found. Install it and ensure it is on your PATH:\n{hint}"


def resolve_ffmpeg(skip_download: bool = False) -> tuple[str, str]:
    """Locate ffmpeg and ffprobe binaries.

    Search order: ~/.vidopt/bin/ → system PATH → auto-download (Windows only).
    Returns (ffmpeg_path, ffprobe_path). Raises RuntimeError if ffmpeg cannot
    be found or auto-downloaded.
    """
    ff_name  = f"ffmpeg{_EXE}"
    ffp_name = f"ffprobe{_EXE}"

    ff_bin  = BIN_DIR / ff_name
    ffp_bin = BIN_DIR / ffp_name
    if ff_bin.is_file() and ffp_bin.is_file():
        return str(ff_bin), str(ffp_bin)

    ff_sys  = shutil.which("ffmpeg")
    ffp_sys = shutil.which("ffprobe")
    if ff_sys and ffp_sys:
        return ff_sys, ffp_sys

    if not _ON_WINDOWS or skip_download:
        raise RuntimeError(_ffmpeg_not_found_message())

    download_ffmpeg()

    if ff_bin.is_file() and ffp_bin.is_file():
        return str(ff_bin), str(ffp_bin)

    raise RuntimeError("Download appeared to succeed but binaries are missing from ~/.vidopt/bin/.")


def download_ffmpeg() -> None:
    """Download the static Windows ffmpeg build and install binaries into ~/.vidopt/bin/."""
    ff_name  = f"ffmpeg{_EXE}"
    ffp_name = f"ffprobe{_EXE}"

    print(f"ffmpeg not found — downloading once from:\n  {FFMPEG_DOWNLOAD_URL}")
    print(f"(Place {ff_name} + {ffp_name} in {BIN_DIR} to skip this step in future.)\n")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="vidopt_ffmpeg_"))

    try:
        zip_path = tmp_dir / "ffmpeg.zip"

        def _reporthook(blocks: int, block_size: int, total: int) -> None:
            if total > 0:
                pct = min(100, blocks * block_size * 100 // total)
                print(f"\r  Downloading... {pct}%", end="", flush=True)

        urllib.request.urlretrieve(FFMPEG_DOWNLOAD_URL, zip_path, reporthook=_reporthook)
        print()

        print("  Extracting...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                base = Path(name).name
                if base in (ff_name, ffp_name):
                    dest = BIN_DIR / base
                    dest.write_bytes(zf.read(name))
                    print(f"  Installed: {dest}")

        if not (BIN_DIR / ff_name).is_file():
            raise FileNotFoundError(f"{ff_name} not found inside the zip archive.")
        if not (BIN_DIR / ffp_name).is_file():
            raise FileNotFoundError(f"{ffp_name} not found inside the zip archive.")

        print("Done. ffmpeg is ready.\n")

    except Exception as exc:
        raise RuntimeError(
            f"Could not auto-download ffmpeg: {exc}\n\n"
            "Please download it manually:\n"
            f"  {FFMPEG_DOWNLOAD_URL}\n"
            f"Extract the zip and copy {ff_name} + {ffp_name} into {BIN_DIR}"
        ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Video probing ─────────────────────────────────────────────────────────────

def probe_video(ffprobe: str, path: Path) -> VideoInfo:
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")

    data: dict[str, Any] = json.loads(result.stdout)
    streams = data.get("streams", [])
    fmt     = data.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        raise RuntimeError("No video stream found.")

    duration = float(fmt.get("duration", video.get("duration", 0.0)))

    attached_pic = any(
        s.get("disposition", {}).get("attached_pic") == 1
        for s in streams
        if s.get("codec_type") == "video"
    )

    return VideoInfo(
        path=path,
        duration=duration,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        video_codec=video.get("codec_name", "unknown"),
        has_audio=audio is not None,
        has_attached_pic=attached_pic,
    )


# ── Command builder ───────────────────────────────────────────────────────────

def build_ffmpeg_command(
    ffmpeg: str,
    source: Path,
    output: Path,
    info: VideoInfo,
    crf: int,
    preset: str,
    use_h265: bool,
    max_width: int | None,
) -> list[str]:
    """Return the ffmpeg argument list for encoding one file.

    No side effects — suitable for dry-run and unit tests.
    """
    codec = H265_VIDEO_CODEC if use_h265 else DEFAULT_VIDEO_CODEC

    cmd: list[str] = [ffmpeg, "-y", "-i", str(source)]

    filters: list[str] = []
    if max_width is not None and info.width > max_width:
        # Scale to max_width preserving aspect; -2 rounds height to even (required by yuv420p).
        # Commas inside if()/gt() are escaped so ffmpeg's filtergraph parser
        # does not treat them as chain separators.
        filters.append(f"scale=if(gt(iw\\,{max_width})\\,{max_width}\\,iw):-2")

    if filters:
        cmd += ["-vf", ",".join(filters)]

    cmd += [
        "-c:v", codec,
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", DEFAULT_PIXEL_FORMAT,
    ]

    if use_h265:
        cmd += ["-tag:v", H265_TAG]

    # Move moov atom to front for HTTP progressive streaming.
    cmd += ["-movflags", "+faststart"]

    # Strip container-level metadata (creation date, GPS, author, etc.).
    # Rotation is baked in by ffmpeg's default -autorotate behaviour.
    cmd += ["-map_metadata", "-1"]

    if info.has_audio:
        cmd += ["-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE]
    else:
        cmd += ["-an"]

    cmd.append(str(output))
    return cmd


# ── Per-file processing ───────────────────────────────────────────────────────

def optimize_file(
    ffmpeg: str,
    ffprobe: str,
    source: Path,
    output_dir: Path,
    crf: int,
    preset: str,
    use_h265: bool,
    max_width: int | None,
    overwrite: bool,
    dry_run: bool,
) -> FileResult:
    input_size = source.stat().st_size

    try:
        info = probe_video(ffprobe, source)
    except Exception as exc:
        return FileResult(
            source=source, output=None,
            input_size=input_size, output_size=0,
            resolution="?", status="FAILED",
            error=f"probe: {exc}",
        )

    resolution = f"{info.width}x{info.height}"
    print(f"  [{resolution}] {source.name}  ({info.duration:.1f}s, {info.video_codec})")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (source.stem + OUTPUT_EXTENSION)

    if output_path.exists() and not overwrite:
        print("  SKIP: output already exists — pass --overwrite to replace it")
        return FileResult(
            source=source, output=output_path,
            input_size=input_size, output_size=output_path.stat().st_size,
            resolution=resolution, status="SKIPPED",
        )

    cmd = build_ffmpeg_command(
        ffmpeg, source, output_path, info, crf, preset, use_h265, max_width
    )

    if dry_run:
        print(f"  DRY-RUN: {' '.join(cmd)}")
        return FileResult(
            source=source, output=output_path,
            input_size=input_size, output_size=0,
            resolution=resolution, status="DRY-RUN",
        )

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        excerpt = (result.stderr or "")[-600:].strip()
        return FileResult(
            source=source, output=None,
            input_size=input_size, output_size=0,
            resolution=resolution, status="FAILED",
            error=excerpt or "non-zero exit from ffmpeg",
        )

    output_size = output_path.stat().st_size
    is_larger   = output_size > input_size
    if is_larger:
        print(
            f"  NOTE: output is larger than source "
            f"({_fmt_bytes(output_size)} > {_fmt_bytes(input_size)})"
        )

    return FileResult(
        source=source, output=output_path,
        input_size=input_size, output_size=output_size,
        resolution=resolution,
        status="LARGER" if is_larger else "OK",
    )


# ── Input gathering ───────────────────────────────────────────────────────────

def gather_inputs(input_path: Path, recursive: bool) -> list[Path]:
    """Resolve an input path to a list of video files.

    Raises FileNotFoundError if the path does not exist, or ValueError if a
    single file has an unsupported extension.
    """
    if input_path.is_file():
        if input_path.suffix.lower() not in INPUT_EXTENSIONS:
            raise ValueError(
                f"'{input_path.name}' is not a supported video file "
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

    NM, NO, NN, NS, NR = 32, 11, 11, 8, 12

    print(
        f"{'File':<{NM}}"
        f"{'Original':>{NO}}"
        f"{'Output':>{NN}}"
        f"{'Saved':>{NS}}"
        f"{'Resolution':>{NR}}"
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
            f"{r.resolution:>{NR}}"
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
        prog="vidopt",
        description=(
            "Optimise MP4/MOV videos for web delivery using ffmpeg.\n"
            "Source files are never modified or deleted."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  vidopt video.mp4
  vidopt clip.mov --output ./exports
  vidopt ./raw-footage --recursive
  vidopt video.mp4 --quality 5          # best quality
  vidopt video.mp4 --quality 2          # smallest file
  vidopt video.mp4 --h265 --quality 4
  vidopt video.mp4 --speed thorough     # best compression, slower encode
  vidopt video.mp4 --max-width 1280
  vidopt ./raw-footage --dry-run
  vidopt ./raw-footage --recursive --overwrite
        """.strip(),
    )

    parser.add_argument("input",
                        help="Source video file or folder")
    parser.add_argument("--output", metavar="DIR",
                        help="Destination folder (default: <input>/optimized)")
    parser.add_argument("--quality", type=int, choices=range(1, 6), default=None,
                        metavar="1-5",
                        help=f"Output quality: 1=smallest … 5=best "
                             f"(default: {DEFAULT_QUALITY})")
    parser.add_argument("--speed", choices=list(SPEED_PRESET), default=None,
                        help=f"Encoding speed: fast|balanced|slow|thorough "
                             f"(default: {DEFAULT_SPEED}). Slower = better compression.")
    # Deprecated aliases kept for backwards compatibility
    parser.add_argument("--crf", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--preset", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--max-width", type=int, metavar="PX",
                        help="Scale down if source is wider than PX (preserves aspect ratio)")
    parser.add_argument("--h265", action="store_true",
                        help="Encode with H.265/HEVC — smaller files, modern browsers only")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Include subfolders when input is a directory")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing output files")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print ffmpeg commands without running them")
    parser.add_argument("--skip-download", action="store_true",
                        help="Never auto-download ffmpeg; require it in ~/.vidopt/bin/ or on PATH")

    args = parser.parse_args()

    try:
        ffmpeg, ffprobe = resolve_ffmpeg(skip_download=args.skip_download)
    except RuntimeError as exc:
        sys.exit(f"ERROR: {exc}")

    if args.crf is not None:
        print("WARNING: --crf is deprecated — use --quality 1-5 instead.", file=sys.stderr)
        crf = args.crf
    else:
        quality = args.quality if args.quality is not None else DEFAULT_QUALITY
        crf = (QUALITY_CRF_H265 if args.h265 else QUALITY_CRF_H264)[quality]

    if args.preset is not None:
        print("WARNING: --preset is deprecated — use --speed fast|balanced|slow|thorough instead.",
              file=sys.stderr)
        preset = args.preset
    else:
        preset = SPEED_PRESET[args.speed if args.speed is not None else DEFAULT_SPEED]

    input_path = Path(args.input)
    try:
        files = gather_inputs(input_path, recursive=args.recursive)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    if not files:
        print("No supported video files found.")
        sys.exit(0)

    print(f"vidopt — {len(files)} file(s) to process\n")

    if args.output:
        output_root = Path(args.output)
    else:
        base = input_path if input_path.is_dir() else input_path.parent
        output_root = base / OUTPUT_SUBFOLDER

    results: list[FileResult] = []

    iterable = (
        _tqdm(files, desc="Processing", unit="file")
        if HAS_TQDM and not args.dry_run and len(files) > 1
        else files
    )

    for source_file in iterable:
        if input_path.is_dir() and args.recursive:
            rel        = source_file.parent.relative_to(input_path)
            output_dir = output_root / rel
        else:
            output_dir = output_root

        try:
            result = optimize_file(
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                source=source_file,
                output_dir=output_dir,
                crf=crf,
                preset=preset,
                use_h265=args.h265,
                max_width=args.max_width,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            result = FileResult(
                source=source_file,
                output=None,
                input_size=source_file.stat().st_size if source_file.exists() else 0,
                output_size=0,
                resolution="?",
                status="FAILED",
                error=str(exc),
            )

        results.append(result)

    sys.exit(print_report(results))


if __name__ == "__main__":
    main()
