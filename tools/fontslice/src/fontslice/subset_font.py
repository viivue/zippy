"""
Subset a variable or static font and export as woff2.

Two-stage pipeline:
  1. Instance variable axes  (fontTools.varLib.instancer)
  2. Subset characters + convert format  (fontTools.subset)

Can also be run standalone:
  python -m fontslice.subset_font INPUT -o OUTPUT_BASE [options]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

SUBSET_UNICODES: dict[str, str] = {
    "latin":
        "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
        "U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,"
        "U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
    "latin-ext":
        "U+0100-02AF,U+0304,U+0308,U+0329,U+1E00-1E9F,U+1EF2-1EFF,U+2020,"
        "U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF",
    "vietnamese":
        "U+0102-0103,U+0110-0111,U+0128-0129,U+0168-0169,U+01A0-01A1,"
        "U+01AF-01B0,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0329,"
        "U+1EA0-1EF9,U+20AB",
    "cyrillic":
        "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
    "cyrillic-ext":
        "U+0460-052F,U+1C80-1C88,U+20B4,U+2DE0-2DFF,U+A640-A69F,U+FE2E-FE2F",
    "greek":
        "U+0370-0377,U+037A-037F,U+0384-038A,U+038C,U+038E-03A1,U+03A3-03FF",
    "greek-ext":
        "U+1F00-1FFF",
    # CJK — output files are large (2–10 MB); use --text-file for site-specific subsetting
    "chinese-simplified":
        "U+4E00-9FFF,U+3400-4DBF,U+20000-2A6DF,"
        "U+F900-FAFF,U+3000-303F,U+3100-312F,U+31A0-31BF,U+FF00-FFEF",
    "chinese-traditional":
        "U+4E00-9FFF,U+3400-4DBF,U+20000-2A6DF,U+2A700-2CEAF,"
        "U+F900-FAFF,U+2F800-2FA1F,U+3000-303F,U+3100-312F,U+31A0-31BF,"
        "U+FF00-FFEF,U+FE30-FE4F",
    "korean":
        "U+AC00-D7A3,U+1100-11FF,U+3130-318F,U+A960-A97F,U+D7B0-D7FF,"
        "U+4E00-9FFF,U+3000-303F,U+FF00-FFEF",
    "japanese":
        "U+3040-309F,U+30A0-30FF,U+31F0-31FF,U+FF65-FF9F,"
        "U+4E00-9FFF,U+3400-4DBF,U+3000-303F,U+FF00-FFEF",
}

DEFAULT_FEATURES = "kern,liga,clig,calt,ccmp,locl,mark,mkmk"


def _fmt_size(b: int) -> str:
    return f"{b / 1024:.1f} KB" if b >= 1024 else f"{b} B"


def _run(cmd: list[str]) -> None:
    """Run a subprocess command; raises RuntimeError on failure."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        excerpt = (e.stderr or "")[-600:].strip()
        raise RuntimeError(
            f"Command failed: {' '.join(str(c) for c in cmd)}\n{excerpt}"
        ) from e


def _font_axes(path: str) -> dict[str, float]:
    from fontTools.ttLib import TTFont
    f = TTFont(path, lazy=True)
    if "fvar" not in f:
        f.close()
        return {}
    axes = {a.axisTag: a.defaultValue for a in f["fvar"].axes}
    f.close()
    return axes


def process_font(
    src: str,
    output_base: str,
    weight: str | None = None,
    opsz: str | None = None,
    extra_axes: list[str] | None = None,
    subsets: str = "latin",
    unicodes: str | None = None,
    text_file: str | None = None,
    features: str = DEFAULT_FEATURES,
    formats: str = "woff2",
) -> dict[str, int]:
    """Instance axes then subset and convert one font file.

    Returns a dict mapping each output format to its file size in bytes.
    Raises RuntimeError on any failure.
    """
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Input not found: {src}")

    orig_size = os.path.getsize(src)
    print(f"Input : {src} ({_fmt_size(orig_size)})")

    if text_file:
        if not os.path.isfile(text_file):
            raise FileNotFoundError(f"Text file not found: {text_file}")
        subset_arg = f"--text-file={text_file}"
        print(f"  Subsetting to characters in: {text_file}")
    elif unicodes:
        subset_arg = f"--unicodes={unicodes}"
    else:
        names = [s.strip() for s in subsets.split(",")]
        bad   = [n for n in names if n not in SUBSET_UNICODES]
        if bad:
            raise ValueError(
                f"Unknown subset(s): {', '.join(bad)}\n"
                f"Valid names: {', '.join(SUBSET_UNICODES)}"
            )
        subset_arg = "--unicodes=" + ",".join(SUBSET_UNICODES[n] for n in names)

    axis_specs: list[str] = []
    if weight:
        axis_specs.append(f"wght={weight}")
    if opsz:
        axis_specs.append(f"opsz={opsz}")
    axis_specs.extend(extra_axes or [])

    out_dir = os.path.dirname(output_base)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    instanced    = output_base + "_instanced.ttf"
    is_woff2_src = src.lower().endswith(".woff2")
    is_variable  = (not is_woff2_src) and bool(_font_axes(src))

    if axis_specs and is_variable:
        print(f"  Instancing axes: {', '.join(axis_specs)}")
        _run(
            [sys.executable, "-m", "fontTools.varLib.instancer", src]
            + axis_specs
            + ["-o", instanced]
        )
        work = instanced
    else:
        if axis_specs and not is_variable and not is_woff2_src:
            print("  Not a variable font — skipping instancing step.")
        work = src

    fmt_list = [f.strip() for f in formats.split(",")]
    results: dict[str, int] = {}

    for fmt in fmt_list:
        if fmt == "woff2":
            out   = output_base + ".woff2"
            extra = ["--flavor=woff2"]
        elif fmt == "ttf":
            out   = output_base + ".ttf"
            extra = []
        else:
            print(f"  Warning: unknown format '{fmt}', skipping.", file=sys.stderr)
            continue

        print(f"  -> {fmt}: {out}")
        _run([
            sys.executable, "-m", "fontTools.subset", work,
            subset_arg,
            f"--output-file={out}",
            f"--layout-features={features}",
        ] + extra)
        results[fmt] = os.path.getsize(out)

    print(f"\nSizes:")
    print(f"  original : {_fmt_size(orig_size)}")
    for fmt, size in results.items():
        pct = (1 - size / orig_size) * 100
        print(f"  {fmt:<8} : {_fmt_size(size)}  ({pct:.0f}% smaller)")

    if work == instanced:
        print(f"\n  Instanced TTF saved at: {instanced}")

    return results


def main() -> None:
    """Standalone CLI: subset and convert a single font file."""
    p = argparse.ArgumentParser(
        description="Subset and convert a font to woff2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", help="Source font file (.ttf, .otf, or .woff2)")
    p.add_argument("-o", "--output-base", required=True,
                   help="Output path without extension (e.g. assets/fonts/MyFont)")
    p.add_argument("--weight",   help="wght axis range or pin: 400:700 or 400")
    p.add_argument("--opsz",     help="opsz axis range or pin (optional)")
    p.add_argument("--axis",     action="append", default=[], metavar="TAG=VALUE",
                   help="Additional axis spec, repeatable (e.g. --axis wdth=100)")
    p.add_argument("--subsets",  default="latin",
                   help="Comma-separated subset names (default: latin)")
    p.add_argument("--unicodes",
                   help="Custom unicode range; overrides --subsets")
    p.add_argument("--text-file",
                   help="Path to text file; subsets to exactly those characters (overrides --subsets/--unicodes)")
    p.add_argument("--features", default=DEFAULT_FEATURES,
                   help="OpenType features to keep")
    p.add_argument("--formats",  default="woff2",
                   help="Output formats: woff2,ttf (default: woff2)")
    args = p.parse_args()

    try:
        process_font(
            src=args.input,
            output_base=args.output_base,
            weight=args.weight,
            opsz=args.opsz,
            extra_axes=args.axis,
            subsets=args.subsets,
            unicodes=args.unicodes,
            text_file=args.text_file,
            features=args.features,
            formats=args.formats,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
