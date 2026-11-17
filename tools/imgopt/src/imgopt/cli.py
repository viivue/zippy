"""
imgopt — web-optimised image compression for teams.

Compresses JPEG, PNG, WebP, GIF, BMP, and TIFF images using Pillow.
Source files are never modified. Outputs land in an 'optimized/' subfolder
unless --output is given. Metadata is stripped by default, except author and
copyright fields and non-sRGB colour profiles, which are always kept.
"""

from __future__ import annotations

import argparse
import re
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
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

# Chunks oxipng must not strip: its "safe" set plus the text/EXIF chunks we
# wrote on purpose (copyright, author, or everything with --keep-exif).
OXIPNG_KEEP_CHUNKS = [
    b"cICP", b"iCCP", b"sRGB", b"pHYs", b"acTL", b"fcTL", b"fdAT",
    b"tEXt", b"iTXt", b"zTXt", b"eXIf",
]

# ── Rights metadata kept even when stripping ─────────────────────────────────
RIGHTS_EXIF_TAGS = (0x013B, 0x8298)  # Artist, Copyright
RIGHTS_PNG_KEYS = {"Author", "Copyright", "Disclaimer"}
PNG_XMP_KEY = "XML:com.adobe.xmp"

# Free-text fields (JPEG/GIF comment, PNG Comment/Description) are kept when
# stripping only if they look like a rights notice.
RIGHTS_TEXT_KEYS = {"Comment", "Description"}
RIGHTS_TEXT_PATTERN = re.compile(
    r"©|\(c\)|copyright|all rights reserved|licen[cs]e", re.IGNORECASE,
)

# IPTC-IIM datasets (record, dataset) kept when stripping: coded character set,
# By-line, By-line Title, Credit, Source, Copyright Notice, Contact.
IIM_CHARSET = (1, 90)
IIM_BYLINE = (2, 80)
IIM_COPYRIGHT = (2, 116)
RIGHTS_IIM_DATASETS = {IIM_CHARSET, IIM_BYLINE, (2, 85), (2, 110), (2, 115), IIM_COPYRIGHT, (2, 118)}
IIM_UTF8 = b"\x1b%G"

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
RIGHTS_XMP_FIELDS = {
    f"{{{XMP_NAMESPACES['dc']}}}rights",
    f"{{{XMP_NAMESPACES['dc']}}}creator",
    f"{{{XMP_NAMESPACES['photoshop']}}}Credit",
    f"{{{XMP_NAMESPACES['photoshop']}}}Source",
    f"{{{XMP_NAMESPACES['Iptc4xmpCore']}}}CreatorContactInfo",
    f"{{{XMP_NAMESPACES['Iptc4xmpExt']}}}DigitalSourceType",
}
XMP_DIGITAL_SOURCE_TYPE = f"{{{XMP_NAMESPACES['Iptc4xmpExt']}}}DigitalSourceType"

# C2PA Content Credentials live in a JUMBF box labelled "c2pa" (JPEG APP11,
# PNG caBX, WebP C2PA chunk). The signature covers the original pixels, so a
# re-encode invalidates it; the AI-generated marker inside is carried to XMP.
C2PA_MARKERS = (b"jumb", b"c2pa")
DIGITAL_SOURCE_TYPE_PATTERN = re.compile(
    rb"https?://cv\.iptc\.org/newscodes/digitalsourcetype/[A-Za-z]+"
)
# Every field in these namespaces is licensing data (xmpRights:*, PLUS license IDs).
RIGHTS_XMP_NAMESPACES = {XMP_NAMESPACES["xmpRights"], XMP_NAMESPACES["plus"]}
for _prefix, _uri in XMP_NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)

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
    note: str = ""


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
            strip=oxipng.StripChunks.keep(OXIPNG_KEEP_CHUNKS),
        )
    except Exception:
        pass


# ── Metadata ──────────────────────────────────────────────────────────────────

def _is_rights_xmp_field(tag: str) -> bool:
    """True for an XMP property (Clark notation) that carries rights data."""
    namespace = tag[1:].split("}", 1)[0] if tag.startswith("{") else ""
    return tag in RIGHTS_XMP_FIELDS or namespace in RIGHTS_XMP_NAMESPACES


def _looks_like_rights(text: str | bytes) -> bool:
    """True when free text reads like a copyright or license notice."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return bool(RIGHTS_TEXT_PATTERN.search(text))


def _read_iim(img) -> dict:
    """Return the IPTC-IIM datasets of a JPEG/TIFF as {(record, dataset): bytes | list}."""
    try:
        from PIL import IptcImagePlugin  # type: ignore[import]
        return IptcImagePlugin.getiptcinfo(img) or {}
    except Exception:
        return {}


def _iim_values(value: bytes | list) -> list[bytes]:
    return value if isinstance(value, list) else [value]


def _iim_text(iim: dict, key: tuple[int, int]) -> str | None:
    """Decode the first value of an IIM dataset, honouring its character set."""
    if key not in iim:
        return None
    raw = _iim_values(iim[key])[0]
    utf8 = _iim_values(iim.get(IIM_CHARSET, b""))[0] == IIM_UTF8
    return raw.decode("utf-8" if utf8 else "latin-1", "replace").strip() or None


def _iim_app13(iim: dict, keep_all: bool) -> bytes | None:
    """Serialise IIM datasets into a complete JPEG APP13 (Photoshop) segment.

    Returns None when no record-2 dataset is left to write.
    """
    data = b""
    for (record, dataset), value in sorted(iim.items()):
        if not keep_all and (record, dataset) not in RIGHTS_IIM_DATASETS:
            continue
        for v in _iim_values(value):
            if len(v) <= 0x7FFF:
                data += struct.pack(">BBBH", 0x1C, record, dataset, len(v)) + v
    if b"\x1c\x02" not in data:
        return None
    resource = (
        b"8BIM" + struct.pack(">H", 0x0404) + b"\0\0"
        + struct.pack(">I", len(data)) + data + b"\0" * (len(data) % 2)
    )
    payload = b"Photoshop 3.0\0" + resource
    if len(payload) + 2 > 0xFFFF:
        return None
    return b"\xff\xed" + struct.pack(">H", len(payload) + 2) + payload


def _rights_xmp(xmp: bytes | str) -> bytes | None:
    """Return a minimal XMP packet holding only the source's rights fields.

    Returns None when the packet is unparseable or has no rights fields.
    """
    if isinstance(xmp, str):
        xmp = xmp.encode("utf-8")
    try:
        root = ET.fromstring(xmp.strip())
    except ET.ParseError:
        return None

    out_desc = ET.Element(f"{{{_RDF}}}Description", {f"{{{_RDF}}}about": ""})
    found = False
    for desc in root.iter(f"{{{_RDF}}}Description"):
        for key, value in desc.attrib.items():
            if _is_rights_xmp_field(key):
                out_desc.set(key, value)
                found = True
        for child in desc:
            if _is_rights_xmp_field(child.tag):
                out_desc.append(child)
                found = True
    if not found:
        return None

    meta = ET.Element(f"{{{XMP_NAMESPACES['x']}}}xmpmeta")
    ET.SubElement(meta, f"{{{_RDF}}}RDF").append(out_desc)
    return ET.tostring(meta, encoding="utf-8")


def _scan_c2pa(path: Path) -> tuple[bool, str | None]:
    """Detect C2PA Content Credentials in a file.

    Returns (found, digital_source_type), the latter being the IPTC
    DigitalSourceType URL declared in the manifest, if any.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return False, None
    if not all(marker in data for marker in C2PA_MARKERS):
        return False, None
    match = DIGITAL_SOURCE_TYPE_PATTERN.search(data)
    return True, match.group(0).decode("ascii") if match else None


def _iim_xmp_values(iim: dict) -> dict[str, str]:
    """Map IIM rights datasets to their XMP properties, for outputs without IIM.

    XMP is UTF-8, so non-ASCII names and the © sign survive, unlike in EXIF.
    """
    dc, ps = XMP_NAMESPACES["dc"], XMP_NAMESPACES["photoshop"]
    mapping = {
        f"{{{dc}}}rights": IIM_COPYRIGHT,
        f"{{{dc}}}creator": IIM_BYLINE,
        f"{{{ps}}}Credit": (2, 110),
        f"{{{ps}}}Source": (2, 115),
    }
    values = {tag: _iim_text(iim, key) for tag, key in mapping.items()}
    return {tag: text for tag, text in values.items() if text}


def _xmp_add(xmp: bytes | None, values: dict[str, str]) -> bytes | None:
    """Add simple XMP properties, leaving any the packet already has alone."""
    if not values:
        return xmp
    dc = XMP_NAMESPACES["dc"]

    root = None
    if xmp:
        try:
            root = ET.fromstring(xmp.strip())
        except ET.ParseError:
            root = None
    if root is None:
        root = ET.Element(f"{{{XMP_NAMESPACES['x']}}}xmpmeta")
    rdf = root if root.tag == f"{{{_RDF}}}RDF" else root.find(f"{{{_RDF}}}RDF")
    if rdf is None:
        rdf = ET.SubElement(root, f"{{{_RDF}}}RDF")
    desc = rdf.find(f"{{{_RDF}}}Description")
    if desc is None:
        desc = ET.SubElement(rdf, f"{{{_RDF}}}Description", {f"{{{_RDF}}}about": ""})

    present = set()
    for d in rdf.iter(f"{{{_RDF}}}Description"):
        present.update(d.attrib)
        present.update(child.tag for child in d)

    for tag, text in values.items():
        if tag in present:
            continue
        el = ET.SubElement(desc, tag)
        if tag == f"{{{dc}}}rights":
            li = ET.SubElement(ET.SubElement(el, f"{{{_RDF}}}Alt"), f"{{{_RDF}}}li")
            li.set("{http://www.w3.org/XML/1998/namespace}lang", "x-default")
            li.text = text
        elif tag == f"{{{dc}}}creator":
            ET.SubElement(ET.SubElement(el, f"{{{_RDF}}}Seq"), f"{{{_RDF}}}li").text = text
        else:
            el.text = text
    return ET.tostring(root, encoding="utf-8")


def _is_srgb(icc: bytes) -> bool:
    """True when an ICC profile is plain sRGB, which browsers assume anyway."""
    try:
        from io import BytesIO

        from PIL import ImageCms  # type: ignore[import]
        desc = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(BytesIO(icc)))
    except Exception:
        return False
    return "srgb" in desc.lower()


def _metadata_kwargs(
    info: dict, exif, png_text: dict, iim: dict, out_fmt: str, keep_all: bool,
    ai_source_type: str | None = None,
) -> dict:
    """Build Pillow save kwargs that carry source metadata into the output.

    Pillow copies no metadata on save unless told to. A non-sRGB ICC profile is
    always kept so colours don't shift. With keep_all, EXIF/XMP/IPTC/text and
    any ICC profile go through as-is; otherwise only author, copyright and
    license fields survive.
    """
    from PIL import Image, PngImagePlugin  # type: ignore[import]

    comment = info.get("comment")
    keep_comment = bool(comment) and (keep_all or _looks_like_rights(comment))

    if out_fmt == "GIF":
        return {} if keep_comment else {"comment": b""}
    if out_fmt not in ("JPEG", "PNG", "WEBP"):
        return {}

    kwargs: dict = {}
    icc = info.get("icc_profile")
    if icc and (keep_all or not _is_srgb(icc)):
        kwargs["icc_profile"] = icc

    if keep_all:
        exif_out = exif
    else:
        exif_out = Image.Exif()
        for tag in RIGHTS_EXIF_TAGS:
            if tag in exif:
                exif_out[tag] = exif[tag]

    app13 = _iim_app13(iim, keep_all) if out_fmt == "JPEG" else None
    if app13:
        kwargs["extra"] = app13

    if len(exif_out):
        kwargs["exif"] = exif_out.tobytes()

    xmp = info.get("xmp") or png_text.get(PNG_XMP_KEY)
    if isinstance(xmp, str):
        xmp = xmp.encode("utf-8")
    xmp_out = xmp if keep_all or not xmp else _rights_xmp(xmp)
    extra_xmp = _iim_xmp_values(iim) if iim and not app13 else {}
    if ai_source_type:
        extra_xmp[XMP_DIGITAL_SOURCE_TYPE] = ai_source_type
    xmp_out = _xmp_add(xmp_out, extra_xmp)

    if out_fmt == "PNG":
        pnginfo = PngImagePlugin.PngInfo()
        for key, value in png_text.items():
            if key == PNG_XMP_KEY:
                continue
            rights_text = key in RIGHTS_TEXT_KEYS and _looks_like_rights(str(value))
            if keep_all or key in RIGHTS_PNG_KEYS or rights_text:
                pnginfo.add_itxt(key, str(value))
        if xmp_out:
            pnginfo.add_itxt(PNG_XMP_KEY, xmp_out.decode("utf-8", "replace"))
        if pnginfo.chunks:
            kwargs["pnginfo"] = pnginfo
    else:
        if xmp_out:
            kwargs["xmp"] = xmp_out
        if out_fmt == "JPEG":
            kwargs["comment"] = comment if keep_comment else b""

    return kwargs


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
        png_text = dict(getattr(img, "text", None) or {})
        src_iim = _read_iim(img)
        has_c2pa, ai_source_type = _scan_c2pa(source)

        # Correct EXIF orientation before any resize so thumbnails face the right way.
        img = ImageOps.exif_transpose(img)
        src_info = dict(img.info)
        src_exif = img.getexif()

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

        save_kwargs = _metadata_kwargs(
            src_info, src_exif, png_text, src_iim, out_fmt, keep_all=not strip_exif,
            ai_source_type=ai_source_type,
        )

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

    note = ""
    if has_c2pa:
        note = (
            "Content Credentials (C2PA) found. Re-encoding invalidates their "
            "signature, so they were not copied."
        )
        if ai_source_type and out_fmt != "GIF":
            note += " The AI-generated marker was kept in XMP."
        print(f"  NOTE: {source.name}: {note}")
    return FileResult(
        source=source, output=output_path,
        input_size=input_size, output_size=output_size,
        status="LARGER" if is_larger else "OK",
        note=note,
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
                        help="Preserve all metadata (EXIF, XMP, text). Without it, only the "
                             "author/copyright fields and non-sRGB colour profiles are kept")
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
