"""Command-line entry point: `python main.py --location 78704 --limit 10`."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from shadescout.config import load_settings
from shadescout.errors import ConfigError
from shadescout.pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shadescout",
        description="Find qualified pergola/shade leads in a target area.",
    )
    parser.add_argument(
        "--location",
        required=True,
        help="Target ZIP code (e.g. 78704) or city (e.g. 'Austin, TX').",
    )
    parser.add_argument("--limit", type=int, default=10, help="Max properties to evaluate (default: 10).")
    parser.add_argument("--output", default="-", help="Output file path, or '-' for stdout (default).")
    parser.add_argument("--save-images", action="store_true", help="Save satellite/street-view images to --image-dir.")
    parser.add_argument("--image-dir", default="images", help="Directory to save images into (default: images/).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable INFO-level logging to stderr.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    leads = run(
        args.location,
        limit=args.limit,
        settings=settings,
        save_images=args.save_images,
        image_dir=args.image_dir,
    )

    output_json = json.dumps([lead.to_dict() for lead in leads], indent=2)
    if args.output == "-":
        print(output_json)
    else:
        with open(args.output, "w") as f:
            f.write(output_json + "\n")
        print(f"Wrote {len(leads)} qualified lead(s) to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
