from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import (as_json, clean_plan, find_duplicates, human_size,
                   parse_size, scan)


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("root", nargs="?", default=".",
                        help="direktori yang dianalisis (default: .)")
    parser.add_argument("--json", action="store_true",
                        help="output JSON (stabil, untuk skrip/CI)")
    parser.add_argument("--hidden", action="store_true",
                        help="sertakan file/direktori tersembunyi")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="POLA",
                        help="lewati nama yang cocok (bisa diulang, glob)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diskpulse",
        description="Analisis penggunaan disk, temukan duplikat, "
                    "dan rencanakan pembersihan yang aman (read-only).")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="ringkasan penggunaan disk")
    _add_root(p)
    p.add_argument("--limit", type=int, default=15,
                   help="jumlah item teratas (default 15)")

    p = sub.add_parser("duplicates", help="temukan file dengan isi identik")
    _add_root(p)
    p.add_argument("--min-size", default="1M",
                   help="ukuran minimum, contoh 1M / 500K / 0 (default 1M)")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("clean-plan", help="file lama untuk DITINJAU (tidak dihapus)")
    _add_root(p)
    p.add_argument("--days", type=int, default=180,
                   help="umur minimum dalam hari (default 180)")
    p.add_argument("--min-size", default="0")
    return parser


def _print_top(rows) -> None:
    for label, value in rows:
        print(f"  {human_size(value):>10}  {label}")


def cmd_scan(args) -> int:
    result = scan(Path(args.root), limit=args.limit)
    if args.json:
        print(as_json(result))
        return 0
    print(f"Root        : {result.root}")
    print(f"Total       : {human_size(result.total_bytes)} "
          f"di {result.file_count:,} file")
    print()
    print("Direktori terbesar:")
    _print_top(list(result.directories.items())[:args.limit])
    print()
    print("Tipe file terbesar:")
    _print_top(list(result.extensions.items())[:args.limit])
    print()
    print("File terbesar:")
    for item in result.largest:
        print(f"  {human_size(item.size):>10}  {item.path}")
    return 0


def cmd_duplicates(args) -> int:
    try:
        min_size = parse_size(args.min_size)
    except ValueError as exc:
        print(f"error: --min-size tidak valid: {exc}", file=sys.stderr)
        return 2
    groups = find_duplicates(Path(args.root), min_size=min_size,
                             limit=args.limit)
    if args.json:
        print(as_json(groups))
        return 0
    if not groups:
        print("Tidak ada duplikat yang memenuhi filter.")
        return 0
    wasted = sum(g[0].size * (len(g) - 1) for g in groups)
    print(f"{len(groups)} grup duplikat - potensi hemat: "
          f"{human_size(wasted)}\n")
    for i, group in enumerate(groups, 1):
        print(f"#{i} {len(group)} file x {human_size(group[0].size)}:")
        for item in group:
            print(f"    {item.path}")
    return 0


def cmd_clean_plan(args) -> int:
    try:
        min_size = parse_size(args.min_size)
    except ValueError as exc:
        print(f"error: --min-size tidak valid: {exc}", file=sys.stderr)
        return 2
    files = clean_plan(Path(args.root), days=args.days, min_size=min_size)
    if args.json:
        print(as_json(files))
        return 0
    total = sum(f.size for f in files)
    print(f"{len(files)} file lebih tua dari {args.days} hari "
          f"(total {human_size(total)}) - untuk DITINJAU, tidak ada yang dihapus:\n")
    for item in files[:50]:
        print(f"  {human_size(item.size):>10}  {item.age_days:>4}h  {item.path}")
    if len(files) > 50:
        print(f"  ... dan {len(files) - 50} file lagi (gunakan --json untuk semua)")
    return 0


COMMANDS = {"scan": cmd_scan, "duplicates": cmd_duplicates,
            "clean-plan": cmd_clean_plan}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"error: bukan direktori: {root}", file=sys.stderr)
        return 2
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
