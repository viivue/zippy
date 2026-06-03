"""
FontSlice — standalone orchestrator.

Subset and convert source variable/static fonts to optimized woff2 files.
Scans all .ttf/.otf files in the theme's fonts folder (skips icomoon* and fontawesome* files).
Uses weight ranges from $fonts in _config.scss when defined; falls back to font
file axes.

Usage:
    fontslice [--fonts-dir PATH] [--config PATH] [--subsets SUBSETS]

Options:
    --dir         Project root to scan for fonts/ and _config.scss
    --fonts-dir   Path to theme assets/fonts folder (auto-detected if omitted)
    --config      Path to _config.scss (auto-detected if omitted)
    --subsets     Comma-separated subset names — skips the interactive prompt
                  Valid: latin, latin-ext, vietnamese, cyrillic, cyrillic-ext,
                         greek, greek-ext
"""

from __future__ import annotations

import argparse
import os
import sys

from .list_fonts import discover_fonts
from .subset_font import SUBSET_UNICODES, process_font

VALID_SUBSETS = list(SUBSET_UNICODES)


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(b: int) -> str:
    return f"{b / 1024:.1f} KB" if b >= 1024 else f"{b} B"


def _print_table(headers: list[str], rows: list[list]) -> None:
    col_widths = [
        max(len(str(row[i])) for row in [headers] + rows)
        for i in range(len(headers))
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("-" * (sum(col_widths) + 2 * (len(col_widths) - 1)))
    for row in rows:
        print(fmt.format(*[str(v) for v in row]))


def _ask_weights(fonts: list[dict]) -> list[dict]:
    """Prompt per-font weight overrides when no _config.scss was found."""
    print("No _config.scss found — weight ranges were read from the font files.")
    print("Press Enter to accept each value, or type a new range (e.g. 300 900 or 400).")
    print()
    updated = []
    for font in fonts:
        wmin, wmax = font["weight_min"], font["weight_max"]
        current = f"{wmin} {wmax}" if wmin != wmax else wmin
        val = input(f"  {font['basename']} [{current}]: ").strip()
        if val:
            parts = val.split()
            try:
                nums = [int(p) for p in parts]
                font = {**font, "weight_min": str(min(nums)), "weight_max": str(max(nums))}
            except ValueError:
                print(f"    Invalid input — keeping {current}")
        updated.append(font)
    print()
    return updated


def _ask_subsets() -> str:
    print()
    print("Which character subsets should I build?")
    print(f"Available: {', '.join(VALID_SUBSETS)}")
    val = input(
        "Enter one or more comma-separated values, "
        "or press Enter for the default [latin]: "
    ).strip()
    return val or "latin"


def _validate_subsets(subsets_str: str) -> str:
    names = [s.strip() for s in subsets_str.split(",") if s.strip()]
    bad   = [n for n in names if n not in VALID_SUBSETS]
    if bad:
        sys.exit(
            f"Error: unknown subset(s): {', '.join(bad)}\n"
            f"Valid: {', '.join(VALID_SUBSETS)}"
        )
    return ",".join(names)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        prog="fontslice",
        description="Subset and convert theme fonts to optimized woff2 files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--dir",       help="Project root to scan for fonts/ and _config.scss")
    p.add_argument("--fonts-dir", help="Path to theme assets/fonts folder (auto-detected if omitted)")
    p.add_argument("--config",    help="Path to _config.scss (auto-detected if omitted)")
    p.add_argument("--subsets",   help="Comma-separated subset names — skips the interactive prompt")
    args = p.parse_args()

    # ── Step 1: discover and list fonts ───────────────────────────────────────
    print("Scanning for fonts...")
    try:
        fonts_dir, config_path, fonts = discover_fonts(
            base=args.dir, fonts_dir=args.fonts_dir, config=args.config
        )
    except FileNotFoundError as exc:
        sys.exit(f"Error: {exc}")

    print(f"  FONTS_DIR : {fonts_dir}")
    print(f"  CONFIG    : {config_path}")
    print()

    if not fonts:
        print("No fonts found.")
        sys.exit(0)

    rows = [
        [
            f["basename"], f["family_name"],
            f["weight_min"], f["weight_max"],
            f["opsz"] or "-", f["status"],
        ]
        for f in fonts
    ]
    _print_table(["Basename", "Family", "Min", "Max", "opsz", "Status"], rows)

    needs_build = [f for f in fonts if f["status"] == "NEEDS_BUILD"]
    if not needs_build:
        print("\nAll fonts are up to date.")
        sys.exit(0)

    # ── Step 2 (optional): confirm weights when no config found ───────────────
    if config_path == "NONE":
        fonts       = _ask_weights(fonts)
        needs_build = [f for f in fonts if f["status"] == "NEEDS_BUILD"]

    # ── Step 3: choose subsets ────────────────────────────────────────────────
    subsets = _validate_subsets(args.subsets or _ask_subsets())

    # ── Step 4: process each font ─────────────────────────────────────────────
    print(f"\nBuilding {len(needs_build)} font(s) with subset(s): {subsets}\n")
    built: list[dict] = []

    for font in fonts:
        if font["status"] == "UP_TO_DATE":
            print(f"  {font['basename']}: up to date — skipping")
            continue

        print(f"\n── {font['basename']} ──────────────────────────────────────")
        orig_size = os.path.getsize(font["font_path"])

        weight_arg = (
            font["weight_min"]
            if font["weight_min"] == font["weight_max"]
            else f"{font['weight_min']}:{font['weight_max']}"
        )

        try:
            sizes = process_font(
                src=font["font_path"],
                output_base=os.path.join(fonts_dir, font["basename"]),
                weight=weight_arg,
                opsz=font["opsz"] or None,
                subsets=subsets,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue

        woff2_size = sizes.get("woff2", 0)
        savings    = (1 - woff2_size / orig_size) * 100 if orig_size else 0

        built.append({
            **font,
            "orig_size":  orig_size,
            "woff2_size": woff2_size,
            "savings":    savings,
        })

    if not built:
        sys.exit(1)

    # ── Step 5: summary table ─────────────────────────────────────────────────
    print("\n\n" + "=" * 64)
    print("Summary")
    print("=" * 64)

    total_orig  = sum(b["orig_size"]  for b in built)
    total_woff2 = sum(b["woff2_size"] for b in built)

    sum_rows = []
    for b in built:
        wrange = (
            b["weight_min"]
            if b["weight_min"] == b["weight_max"]
            else f"{b['weight_min']}-{b['weight_max']}"
        )
        sum_rows.append([
            b["basename"],
            _fmt_size(b["orig_size"]),
            _fmt_size(b["woff2_size"]),
            wrange,
            f"{b['savings']:.0f}%",
        ])

    _print_table(
        ["Font", "Original", "woff2", "Weight range", "Savings"],
        sum_rows,
    )
    print(f"\nTotal saved (original -> woff2): {_fmt_size(total_orig - total_woff2)}")

    # ── Step 6: @font-face CSS ────────────────────────────────────────────────
    print("\n\n" + "=" * 64)
    print("@font-face rules — paste into fonts.css")
    print("=" * 64 + "\n")

    for b in built:
        wrange = (
            b["weight_min"]
            if b["weight_min"] == b["weight_max"]
            else f"{b['weight_min']} {b['weight_max']}"
        )
        print(f"@font-face {{")
        print(f"  font-family: '{b['family_name']}';")
        print(f"  src: url('assets/fonts/{b['basename']}.woff2') format('woff2');")
        print(f"  font-weight: {wrange};")
        print(f"  font-style: normal;")
        print(f"  font-display: swap;")
        print(f"}}")
        print()

    print("Note: url() paths are relative to where fonts.css lives — adjust if needed.")


if __name__ == "__main__":
    main()
