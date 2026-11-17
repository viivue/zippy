"""
vidopt — web-optimised video encoding for teams.

Encodes MP4/MOV source files to streaming-ready H.264 (or H.265) MP4 using
ffmpeg. Source files are never modified. Outputs land in an 'optimized/'
subfolder unless --output is given.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
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

# Container tags carried over even though all other metadata is stripped.
RIGHTS_TAGS = ("copyright", "artist", "author", "album_artist", "composer", "license")

# ISO BMFF top-level "uuid" boxes. C2PA Content Credentials are signed over
# the original media, so a re-encode invalidates them; the AI-generated marker
# inside is carried over to an XMP box instead.
C2PA_UUID = bytes.fromhex("d8fec3d61b0e483c92975828877ec481")
XMP_UUID = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")
DIGITAL_SOURCE_TYPE_PATTERN = re.compile(
    rb"https?://cv\.iptc\.org/newscodes/digitalsourcetype/[A-Za-z]+"
)

# XMP rights fields carried over from the source (same set as imgopt).
XMP_NAMESPACES = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xmpRights": "http://ns.adobe.com/xap/1.0/rights/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "Iptc4xmpCore": "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/",
    "Iptc4xmpExt": "http://iptc.org/std/Iptc4xmpExt/2008-02-29/",
    "plus": "http://ns.useplus.org/ldf/xmp/1.0/",
}
_RDF = XMP_NAMESPACES["rdf"]
XMP_DIGITAL_SOURCE_TYPE = f"{{{XMP_NAMESPACES['Iptc4xmpExt']}}}DigitalSourceType"
RIGHTS_XMP_FIELDS = {
    f"{{{XMP_NAMESPACES['dc']}}}rights",
    f"{{{XMP_NAMESPACES['dc']}}}creator",
    f"{{{XMP_NAMESPACES['photoshop']}}}Credit",
    f"{{{XMP_NAMESPACES['photoshop']}}}Source",
    f"{{{XMP_NAMESPACES['Iptc4xmpCore']}}}CreatorContactInfo",
    XMP_DIGITAL_SOURCE_TYPE,
}
RIGHTS_XMP_NAMESPACES = {XMP_NAMESPACES["xmpRights"], XMP_NAMESPACES["plus"]}
for _prefix, _uri in XMP_NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)

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
    rights_tags: dict[str, str] = field(default_factory=dict)


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
    note: str = ""


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

    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    rights = {k: str(tags[k]) for k in RIGHTS_TAGS if tags.get(k)}

    return VideoInfo(
        path=path,
        duration=duration,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        video_codec=video.get("codec_name", "unknown"),
        has_audio=audio is not None,
        has_attached_pic=attached_pic,
        rights_tags=rights,
    )


# ── Provenance metadata ───────────────────────────────────────────────────────

def _iter_boxes(f, start: int, end: int):
    """Yield (type, payload_offset, payload_size) for ISO BMFF boxes in [start, end)."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            return
        size, box_type = struct.unpack(">I4s", header)
        header_len = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            header_len = 16
        elif size == 0:
            size = end - pos
        if size < header_len or pos + size > end:
            return
        yield box_type, pos + header_len, size - header_len
        pos += size


def _read_uuid_box(path: Path, uuid: bytes, max_size: int = 64 * 1024 * 1024) -> bytes | None:
    """Return the payload (after the 16-byte UUID) of a top-level uuid box."""
    try:
        with path.open("rb") as f:
            end = path.stat().st_size
            for box_type, offset, size in _iter_boxes(f, 0, end):
                if box_type != b"uuid" or size < 16 or size > max_size:
                    continue
                f.seek(offset)
                if f.read(16) == uuid:
                    return f.read(size - 16)
    except OSError:
        return None
    return None


def _append_uuid_box(path: Path, uuid: bytes, payload: bytes) -> None:
    """Append a top-level uuid box; earlier boxes and their offsets are untouched."""
    with path.open("ab") as f:
        f.write(struct.pack(">I4s", 8 + 16 + len(payload), b"uuid") + uuid + payload)


def _read_udta_xmp(path: Path, max_size: int = 16 * 1024 * 1024) -> bytes | None:
    """Return the QuickTime moov/udta/XMP_ payload, where .mov files keep XMP."""
    try:
        with path.open("rb") as f:
            start, end = 0, path.stat().st_size
            for wanted in (b"moov", b"udta", b"XMP_"):
                for box_type, offset, size in _iter_boxes(f, start, end):
                    if box_type == wanted:
                        start, end = offset, offset + size
                        break
                else:
                    return None
            if end - start > max_size:
                return None
            f.seek(start)
            return f.read(end - start)
    except OSError:
        return None


def _is_rights_xmp_field(tag: str) -> bool:
    namespace = tag[1:].split("}", 1)[0] if tag.startswith("{") else ""
    return tag in RIGHTS_XMP_FIELDS or namespace in RIGHTS_XMP_NAMESPACES


def _rights_xmp(xmp: bytes | None, digital_source_type: str | None) -> bytes | None:
    """Build an XMP packet with only the source's rights fields plus the AI marker.

    Returns None when there is nothing to write.
    """
    out_desc = ET.Element(f"{{{_RDF}}}Description", {f"{{{_RDF}}}about": ""})
    present: set[str] = set()
    if xmp:
        try:
            root = ET.fromstring(xmp.strip(b"\0").strip())
        except ET.ParseError:
            root = None
        for desc in root.iter(f"{{{_RDF}}}Description") if root is not None else ():
            for key, value in desc.attrib.items():
                if _is_rights_xmp_field(key):
                    out_desc.set(key, value)
                    present.add(key)
            for child in desc:
                if _is_rights_xmp_field(child.tag):
                    out_desc.append(child)
                    present.add(child.tag)
    if digital_source_type and XMP_DIGITAL_SOURCE_TYPE not in present:
        ET.SubElement(out_desc, XMP_DIGITAL_SOURCE_TYPE).text = digital_source_type
        present.add(XMP_DIGITAL_SOURCE_TYPE)
    if not present:
        return None
    meta = ET.Element(f"{{{XMP_NAMESPACES['x']}}}xmpmeta")
    ET.SubElement(meta, f"{{{_RDF}}}RDF").append(out_desc)
    return ET.tostring(meta, encoding="utf-8")


def carry_over_provenance(source: Path, output: Path) -> str:
    """Carry rights XMP and provenance from source to a finished output MP4.

    ffmpeg drops XMP, so the source's XMP rights fields (top-level uuid box
    or QuickTime moov/udta/XMP_) and any C2PA AI marker are written to a new
    XMP uuid box. Returns a note for the user, or "" when there is none.
    """
    xmp = _read_uuid_box(source, XMP_UUID) or _read_udta_xmp(source)

    note = ""
    digital_source_type = None
    manifest = _read_uuid_box(source, C2PA_UUID)
    if manifest is not None:
        note = (
            "Content Credentials (C2PA) found. Re-encoding invalidates their "
            "signature, so they were not copied."
        )
        match = DIGITAL_SOURCE_TYPE_PATTERN.search(manifest)
        if match:
            digital_source_type = match.group(0).decode("ascii")
            note += " The AI-generated marker was kept in XMP."

    packet = _rights_xmp(xmp, digital_source_type)
    if packet:
        _append_uuid_box(output, XMP_UUID, packet)
    return note


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

    # Strip container-level metadata (creation date, GPS, device, etc.) but
    # write back copyright/author tags. Rotation is baked in by ffmpeg's
    # default -autorotate behaviour.
    cmd += ["-map_metadata", "-1"]
    for key, value in info.rights_tags.items():
        cmd += ["-metadata", f"{key}={value}"]

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

    note = carry_over_provenance(source, output_path)
    if note:
        print(f"  NOTE: {note}")

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
        note=note,
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
