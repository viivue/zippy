import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-fonts",
        description="Font build pipeline — subset, compile, and package webfonts.",
    )
    parser.add_argument(
        "--input", "-i",
        metavar="FILE",
        required=False,
        help="Input font file (.ttf or .otf).",
    )
    parser.add_argument(
        "--output-dir", "-o",
        metavar="DIR",
        default="dist/fonts",
        help="Directory to write compiled fonts to (default: dist/fonts).",
    )
    parser.add_argument(
        "--formats",
        metavar="FMT,...",
        default="woff2",
        help="Comma-separated list of output formats: woff2, woff, ttf (default: woff2).",
    )
    parser.add_argument(
        "--unicodes",
        metavar="RANGE",
        default=None,
        help="Unicode range to subset, e.g. U+0000-00FF. Omit to keep all glyphs.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.input is None:
        parser.print_help()
        sys.exit(0)

    formats = [f.strip() for f in args.formats.split(",")]

    # Placeholder — wire up fonttools here once added as a dependency.
    print(f"[build-fonts] input:      {args.input}")
    print(f"[build-fonts] output-dir: {args.output_dir}")
    print(f"[build-fonts] formats:    {', '.join(formats)}")
    if args.unicodes:
        print(f"[build-fonts] unicodes:   {args.unicodes}")
    print("[build-fonts] (placeholder — build logic not yet implemented)")


if __name__ == "__main__":
    main()
