"""
Scan a theme's fonts folder and return font metadata.

Can also be run standalone to print a TSV report:
  python -m fontslice.list_fonts [--dir PATH] [--fonts-dir PATH] [--config PATH]
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

from fontTools.ttLib import TTFont

_EXCLUDE_DIRS = {"node_modules", "vendor", ".git", ".claude", "__pycache__"}


def normalize(s: str) -> str:
    return re.sub(r"[\s-]", "", s).lower()


def _discover(base: str) -> tuple[str | None, str]:
    """Walk base and return (fonts_dir, config_path)."""
    fonts_dir   = None
    config_path = "NONE"
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
        if fonts_dir is None and os.path.basename(root).lower() == "fonts":
            fonts_dir = root
        if config_path == "NONE" and "_config.scss" in files:
            config_path = os.path.join(root, "_config.scss")
        if fonts_dir and config_path != "NONE":
            break
    return fonts_dir, config_path


def _parse_config_weights(config_path: str) -> dict[str, tuple[int, int]]:
    """Return {norm_key: (weight_min, weight_max)} from $fonts in _config.scss."""
    if config_path == "NONE" or not os.path.exists(config_path):
        return {}
    with open(config_path, encoding="utf-8") as fh:
        text = fh.read()
    block = re.search(r"\$fonts\s*:\s*\((.+?)\)\s*;", text, re.S)
    if not block:
        return {}
    weights: dict[str, tuple[int, int]] = {}
    current_face = None
    for line in block.group(1).splitlines():
        line = line.strip().rstrip(",")
        m = re.match(r"font-face\s*:\s*(.+)", line)
        if m:
            face_val = m.group(1).strip().strip('"').strip("'")
            fm = re.match(r"[A-Za-z][\w\s-]*", face_val.lstrip("'"))
            current_face = fm.group(0).strip() if fm else None
        m = re.match(r"weight\s*:\s*([\d\s]+)", line)
        if m and current_face:
            vals = list(map(int, m.group(1).split()))
            weights[normalize(current_face)] = (min(vals), max(vals))
            current_face = None
    return weights


def _lookup(
    config_weights: dict[str, tuple[int, int]], k: str
) -> tuple[int, int] | None:
    """Exact match first, then prefix match (e.g. 'inter' matches 'intervariable')."""
    if k in config_weights:
        return config_weights[k]
    for ck in config_weights:
        if k.startswith(ck):
            return config_weights[ck]
    return None


def _clean_stem(fname: str) -> str:
    stem = fname.rsplit(".", 1)[0]
    stem = re.sub(r"\[.*?\]", "", stem)
    stem = re.sub(r"_[a-z]{4}(?:,[a-z]{4})*$", "", stem)
    return stem.rstrip(" -_")


def discover_fonts(
    base: str | None = None,
    fonts_dir: str | None = None,
    config: str | None = None,
) -> tuple[str, str, list[dict]]:
    """Locate fonts and return (fonts_dir, config_path, font_list).

    Each font dict has keys:
      basename, family_name, weight_min, weight_max, opsz, font_path, status
    where status is 'NEEDS_BUILD' or 'UP_TO_DATE'.
    """
    if fonts_dir:
        resolved_fonts_dir = fonts_dir
        resolved_config    = config or "NONE"
    else:
        resolved_fonts_dir, resolved_config = _discover(base or os.getcwd())
        if config:
            resolved_config = config

    if not resolved_fonts_dir:
        raise FileNotFoundError(
            "Could not find a fonts/ folder — run from inside the project "
            "or pass --fonts-dir."
        )

    config_weights = _parse_config_weights(resolved_config)

    files = sorted(
        f
        for ext in ("*.ttf", "*.otf")
        for f in glob.glob(os.path.join(resolved_fonts_dir, ext))
        if "icomoon" not in os.path.basename(f).lower()
    )

    fonts: list[dict] = []
    for font_path in files:
        basename = _clean_stem(os.path.basename(font_path))

        f = TTFont(font_path, lazy=True)
        name_table  = f["name"]
        family_name = (
            name_table.getBestFamilyName()
            or name_table.getDebugName(1)
            or basename
        )

        if "fvar" in f:
            axes         = {a.axisTag: a for a in f["fvar"].axes}
            opsz_default = int(axes["opsz"].defaultValue) if "opsz" in axes else None
            wght_ax      = axes.get("wght")
            font_wmin    = int(wght_ax.minValue) if wght_ax else None
            font_wmax    = int(wght_ax.maxValue) if wght_ax else None
        else:
            wc           = int(f["OS/2"].usWeightClass)
            font_wmin    = font_wmax = wc
            opsz_default = None
        f.close()

        matched = _lookup(config_weights, normalize(family_name)) or _lookup(
            config_weights, normalize(basename)
        )
        if matched:
            weight_min, weight_max = matched
        elif font_wmin is not None:
            weight_min, weight_max = font_wmin, font_wmax
        else:
            weight_min = weight_max = 400

        woff2_out = os.path.join(resolved_fonts_dir, basename + ".woff2")
        status = (
            "UP_TO_DATE"
            if os.path.isfile(woff2_out)
            and os.path.getmtime(woff2_out) >= os.path.getmtime(font_path)
            else "NEEDS_BUILD"
        )

        fonts.append({
            "basename":    basename,
            "family_name": family_name,
            "weight_min":  str(weight_min),
            "weight_max":  str(weight_max),
            "opsz":        str(opsz_default) if opsz_default is not None else "",
            "font_path":   font_path,
            "status":      status,
        })

    return resolved_fonts_dir, resolved_config, fonts


def main() -> None:
    """Standalone CLI: print TSV of fonts to process."""
    p = argparse.ArgumentParser(description="List fonts to process as TSV.")
    p.add_argument("--dir",       default=None,
                   help="Project root to scan for fonts/ and _config.scss")
    p.add_argument("--fonts-dir", default=None,
                   help="Path to theme assets/fonts folder")
    p.add_argument("--config",    default=None,
                   help="Path to _config.scss")
    args = p.parse_args()

    try:
        fonts_dir, config_path, fonts = discover_fonts(
            base=args.dir, fonts_dir=args.fonts_dir, config=args.config
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"# FONTS_DIR: {fonts_dir}")
    print(f"# CONFIG_PATH: {config_path}")
    for f in fonts:
        print(
            f"{f['basename']}\t{f['family_name']}\t{f['weight_min']}\t"
            f"{f['weight_max']}\t{f['opsz']}\t{f['font_path']}\t{f['status']}"
        )


if __name__ == "__main__":
    main()
