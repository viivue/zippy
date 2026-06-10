"""
FontSlice — standalone orchestrator.

Subset and convert source variable/static fonts to optimized woff2 files.
Scans all .ttf/.otf files in the theme's fonts folder, plus any .woff2 files
that have no corresponding .ttf/.otf source (skips icomoon* and fontawesome*).
Uses weight ranges from $fonts in _config.scss when defined; falls back to font
file axes. woff2-source outputs are saved as <basename>.opt.woff2.

Usage:
    fontslice [--fonts-dir PATH] [--config PATH] [--subsets SUBSETS]

Options:
    --dir         Project root to scan for fonts/ and _config.scss
    --fonts-dir   Path to theme assets/fonts folder (auto-detected if omitted)
    --config      Path to _config.scss (auto-detected if omitted)
    --subsets     Comma-separated subset names — skips the interactive prompt
                  Use 'all' to include every defined subset.
                  Valid: latin, latin-ext, vietnamese, cyrillic, cyrillic-ext,
                         greek, greek-ext, chinese-simplified, chinese-traditional,
                         korean, japanese, all
    --weights     Weight override; repeatable; applies to all fonts or a specific one.
                  Format: [FontName:]<spec> where spec is:
                    400         pin to a single weight  → FontName-400.woff2
                    400,700     pin to multiple weights → FontName-400.woff2 + FontName-700.woff2
                    400-700     keep range 400–700      → FontName.woff2 (still variable in range)
                  Examples:
                    --weights 400,700
                    --weights NotoSansSC:400-700
                    --weights NotoSansSC:400-700 --weights Inter:300,400,700
    --text-file   Path to a text file; subsets each font to exactly the characters
                  in that file. Overrides --subsets. Recommended for CJK fonts.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from .list_fonts import discover_fonts, normalize
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
    print(f"Available: {', '.join(VALID_SUBSETS)}, all")
    val = input(
        "Enter one or more comma-separated values, 'all', "
        "or press Enter for the default [latin]: "
    ).strip()
    return val or "latin"


def _validate_subsets(subsets_str: str) -> str:
    if subsets_str.strip() == "all":
        return ",".join(VALID_SUBSETS)
    names = [s.strip() for s in subsets_str.split(",") if s.strip()]
    bad   = [n for n in names if n not in VALID_SUBSETS]
    if bad:
        sys.exit(
            f"Error: unknown subset(s): {', '.join(bad)}\n"
            f"Valid: {', '.join(VALID_SUBSETS)}, all"
        )
    return ",".join(names)


def _parse_weight_entry(raw: str) -> dict:
    """Parse one --weights value into {target, kind, values}.

    target — normalized font name, or None for global
    kind   — 'range' or 'pins'
    values — [lo, hi] for range, [w1, w2, ...] for pins
    """
    if ":" in raw:
        target, spec = raw.split(":", 1)
        target = normalize(target.strip())
    else:
        target, spec = None, raw.strip()

    spec = spec.strip()
    if re.match(r"^\d+-\d+$", spec):
        parts = spec.split("-", 1)
        lo, hi = int(parts[0]), int(parts[1])
        return {"target": target, "kind": "range", "values": [min(lo, hi), max(lo, hi)]}

    try:
        pins = [int(p.strip()) for p in spec.split(",") if p.strip()]
    except ValueError:
        sys.exit(f"Error: invalid weight spec '{raw}'")
    if not pins:
        sys.exit(f"Error: empty weight spec '{raw}'")
    return {"target": target, "kind": "pins", "values": pins}


def _resolve_weight_spec(font: dict, specs: list[dict]) -> dict | None:
    """Return the best matching weight spec for a font, or None."""
    fn = normalize(font["family_name"])
    bn = normalize(font["basename"])
    for spec in specs:
        t = spec["target"]
        if t and (fn == t or bn == t or fn.startswith(t) or bn.startswith(t)):
            return spec
    for spec in specs:
        if spec["target"] is None:
            return spec
    return None


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
    p.add_argument("--subsets",   help="Comma-separated subset names, or 'all' — skips the interactive prompt")
    p.add_argument(
        "--weights",
        action="append",
        metavar="[FONT:]SPEC",
        help=(
            "Weight override, repeatable. SPEC: 400 | 400,700 | 400-700. "
            "Prefix with FontName: to target one font. "
            "Pins produce per-weight files (Font-400.woff2); ranges produce one file."
        ),
    )
    p.add_argument(
        "--text-file",
        metavar="PATH",
        help=(
            "Path to a text file; subsets each font to exactly those characters. "
            "Overrides --subsets. Recommended for CJK fonts."
        ),
    )
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
    if config_path == "NONE" and not args.weights:
        fonts       = _ask_weights(fonts)
        needs_build = [f for f in fonts if f["status"] == "NEEDS_BUILD"]

    # ── Step 3: choose subsets (skip when --text-file is used) ───────────────
    if args.text_file:
        if not os.path.isfile(args.text_file):
            sys.exit(f"Error: text file not found: {args.text_file}")
        subsets = None
        print(f"\nUsing text-based subsetting from: {args.text_file}")
    else:
        subsets = _validate_subsets(args.subsets or _ask_subsets())

    # ── Step 4: parse weight specs ────────────────────────────────────────────
    weight_specs = [_parse_weight_entry(w) for w in (args.weights or [])]

    # ── Step 5: process each font ─────────────────────────────────────────────
    subset_label = args.text_file or subsets
    print(f"\nBuilding {len(needs_build)} font(s)  subsets: {subset_label}\n")
    built: list[dict] = []

    for font in fonts:
        if font["status"] == "UP_TO_DATE":
            print(f"  {font['basename']}: up to date — skipping")
            continue

        print(f"\n── {font['basename']} ──────────────────────────────────────")
        orig_size    = os.path.getsize(font["font_path"])
        is_woff2_src = font["font_path"].lower().endswith(".woff2")
        base_stem    = font["basename"] + (".opt" if is_woff2_src else "")

        # Build list of (weight_arg, out_stem) jobs
        spec = _resolve_weight_spec(font, weight_specs) if weight_specs else None

        if spec is None:
            w = (
                font["weight_min"]
                if font["weight_min"] == font["weight_max"]
                else f"{font['weight_min']}:{font['weight_max']}"
            )
            jobs: list[tuple[str | None, str]] = [(w, base_stem)]
        elif spec["kind"] == "range":
            lo, hi = spec["values"]
            w = f"{lo}:{hi}" if lo != hi else str(lo)
            jobs = [(w, base_stem)]
        else:  # pins
            jobs = [(str(pin), f"{base_stem}-{pin}") for pin in spec["values"]]

        for weight_arg, out_stem in jobs:
            try:
                sizes = process_font(
                    src=font["font_path"],
                    output_base=os.path.join(fonts_dir, out_stem),
                    weight=weight_arg,
                    opsz=font["opsz"] or None,
                    subsets=subsets or "latin",
                    text_file=args.text_file,
                )
            except (FileNotFoundError, ValueError, RuntimeError) as exc:
                print(f"  ERROR: {exc}", file=sys.stderr)
                continue

            woff2_size = sizes.get("woff2", 0)
            savings    = (1 - woff2_size / orig_size) * 100 if orig_size else 0

            built.append({
                **font,
                "orig_size":   orig_size,
                "woff2_size":  woff2_size,
                "savings":     savings,
                "out_stem":    out_stem,
                "weight_arg":  weight_arg,
            })

    if not built:
        sys.exit(1)

    # ── Step 6: summary table ─────────────────────────────────────────────────
    print("\n\n" + "=" * 64)
    print("Summary")
    print("=" * 64)

    total_orig  = sum(b["orig_size"]  for b in built)
    total_woff2 = sum(b["woff2_size"] for b in built)

    sum_rows = []
    for b in built:
        w = b["weight_arg"]
        wdisplay = w.replace(":", "-") if ":" in w else w
        sum_rows.append([
            b["out_stem"],
            _fmt_size(b["orig_size"]),
            _fmt_size(b["woff2_size"]),
            wdisplay,
            f"{b['savings']:.0f}%",
        ])

    _print_table(
        ["Font", "Original", "woff2", "Weight", "Savings"],
        sum_rows,
    )
    print(f"\nTotal saved (original -> woff2): {_fmt_size(total_orig - total_woff2)}")

    # ── Step 7: @font-face CSS ────────────────────────────────────────────────
    print("\n\n" + "=" * 64)
    print("@font-face rules — paste into fonts.css")
    print("=" * 64 + "\n")

    for b in built:
        w = b["weight_arg"]
        if ":" in w:
            lo, hi = w.split(":", 1)
            wrange = f"{lo} {hi}"
        else:
            wrange = w

        is_woff2_src = b["font_path"].lower().endswith(".woff2")
        woff2_file   = b["out_stem"] + ".woff2"
        print(f"@font-face {{")
        print(f"  font-family: '{b['family_name']}';")
        print(f"  src: url('assets/fonts/{woff2_file}') format('woff2');")
        print(f"  font-weight: {wrange};")
        print(f"  font-style: normal;")
        print(f"  font-display: swap;")
        print(f"}}")
        print()

    print("Note: url() paths are relative to where fonts.css lives — adjust if needed.")


if __name__ == "__main__":
    main()
