from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .classify import KIND_HINT, KIND_LABEL, sort_kinds
from .core import (as_json, clean_plan, diff_scans, find_duplicates, health,
                   human_size, parse_size, scan, snapshot, watch)

SNAPSHOT_FILE = ".diskpulse-snapshot.json"


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("root", nargs="?", default=".",
                        help="direktori yang dianalisis (default: .)")
    parser.add_argument("--json", action="store_true",
                        help="output JSON (stabil, untuk skrip/CI)")
    parser.add_argument("--skip-hidden", action="store_true",
                        help="lewati file/direktori berawalan titik "
                             "(default: dihitung, karena .git/.cache nyata)")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="POLA",
                        help="lewati nama yang cocok (bisa diulang, glob)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diskpulse",
        description="Analisis disk yang tahu bedanya data penting dan "
                    "sampah yang bisa dibuat ulang (read-only).")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="ringkasan penggunaan + klasifikasi ruang")
    _add_root(p)
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--no-classify", action="store_true",
                   help="sembunyikan bagian klasifikasi")

    p = sub.add_parser("health", help="skor kesehatan disk + saran konkret")
    _add_root(p)
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("duplicates", help="temukan file dengan isi identik")
    _add_root(p)
    p.add_argument("--min-size", default="1M")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--no-fast", action="store_true",
                   help="matikan penyaringan partial-hash (lebih lambat, "
                        "selalu SHA-256 penuh)")

    p = sub.add_parser("clean-plan", help="file lama untuk DITINJAU (tidak dihapus)")
    _add_root(p)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--min-size", default="0")

    p = sub.add_parser("watch", help="pantau perubahan ukuran secara real-time")
    _add_root(p)
    p.add_argument("--interval", type=float, default=2.0,
                   help="jeda antar siklus dalam detik (default 2)")
    p.add_argument("--cycles", type=int, default=0,
                   help="berhenti setelah N siklus (0 = tanpa batas)")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("diff", help="bandingkan dengan snapshot sebelumnya")
    _add_root(p)
    p.add_argument("--save", action="store_true",
                   help="simpan hasil scan sebagai snapshot acuan")
    p.add_argument("--compare", action="store_true",
                   help="bandingkan dengan snapshot tersimpan")
    p.add_argument("--file", default=None,
                   help=f"lokasi snapshot (default: <root>/{SNAPSHOT_FILE})")
    p.add_argument("--limit", type=int, default=15)
    return parser


def _print_top(rows) -> None:
    for label, value in rows:
        print(f"  {human_size(value):>10}  {label}")


def _scan_kwargs(args) -> dict:
    # None = pakai DEFAULT_EXCLUDES; set kosong akan mematikan filter default.
    return {"skip_hidden": args.skip_hidden,
            "excludes": frozenset(args.exclude) if args.exclude else None}


def cmd_scan(args) -> int:
    result = scan(Path(args.root), limit=args.limit, **_scan_kwargs(args))
    if args.json:
        print(as_json(result))
        return 0
    print(f"Root        : {result.root}")
    print(f"Total       : {human_size(result.total_bytes)} "
          f"di {result.file_count:,} file")
    print(f"Kecepatan   : {result.speed:,.0f} file/detik ({result.elapsed:.2f}s)")
    if result.errors:
        print(f" Dilewati   : {len(result.errors)} path tidak terbaca")

    if not args.no_classify and result.kinds:
        reclaim = result.reclaimable_bytes
        print()
        print(f"Klasifikasi ruang "
              f"(bisa dibebaskan: {human_size(reclaim)} "
              f"= {reclaim / max(result.total_bytes, 1) * 100:.0f}%):")
        for kind, size in sort_kinds(result.kinds):
            pct = size / max(result.total_bytes, 1) * 100
            print(f"  {human_size(size):>10}  {pct:>5.1f}%  {KIND_LABEL[kind]}")
            print(f"  {'':>10}  {'':>5}   -> {KIND_HINT[kind]}")

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


def cmd_health(args) -> int:
    result = scan(Path(args.root), limit=args.limit, **_scan_kwargs(args))
    report = health(result)
    if args.json:
        report["scan"] = {
            "total_bytes": result.total_bytes,
            "file_count": result.file_count,
            "kinds": result.kinds,
        }
        print(as_json(report))
        return 0
    print(f"Root   : {result.root}")
    print(f"Total  : {human_size(result.total_bytes)} di {result.file_count:,} file")
    print(f"Skor   : {report['score']}/100  (grade {report['grade']})")
    bar = "#" * (report["score"] // 5) + "." * (20 - report["score"] // 5)
    print(f"         [{bar}]")
    print(f"Bisa dibebaskan: {report['reclaimable_human']}")
    if report["actions"]:
        print()
        print("Yang perlu ditindak:")
        for item in report["actions"]:
            print(f"  - {item['human']} ({item['percent']}%)  "
                  f"{KIND_LABEL.get(item['kind'], item['kind'])}")
            print(f"    -> {item['suggestion']}")
    else:
        print()
        print("Tidak ada pemborosan signifikan. Bagus.")
    return 0


def cmd_duplicates(args) -> int:
    try:
        min_size = parse_size(args.min_size)
    except ValueError as exc:
        print(f"error: --min-size tidak valid: {exc}", file=sys.stderr)
        return 2
    groups = find_duplicates(Path(args.root), min_size=min_size,
                             limit=args.limit, fast=not args.no_fast,
                             **_scan_kwargs(args))
    if args.json:
        print(as_json(groups))
        return 0
    if not groups:
        print("Tidak ada duplikat yang memenuhi filter.")
        return 0
    wasted = sum(g[0].size * (len(g) - 1) for g in groups)
    print(f"{len(groups)} grup duplikat - potensi hemat: {human_size(wasted)}\n")
    for i, group in enumerate(groups, 1):
        print(f"#{i} {len(group)} file x {human_size(group[0].size)} "
              f"(hemat {human_size(group[0].size * (len(group) - 1))}):")
        for item in group:
            print(f"    {item.path}")
    return 0


def cmd_clean_plan(args) -> int:
    try:
        min_size = parse_size(args.min_size)
    except ValueError as exc:
        print(f"error: --min-size tidak valid: {exc}", file=sys.stderr)
        return 2
    files = clean_plan(Path(args.root), days=args.days, min_size=min_size,
                       **_scan_kwargs(args))
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


def cmd_watch(args) -> int:
    if args.json:
        cycles = args.cycles or 1
        for i, (ts, total, count, delta, entries) in enumerate(
                watch(Path(args.root), args.interval, args.limit, **_scan_kwargs(args)), 1):
            print(as_json({"timestamp": ts, "total_bytes": total,
                           "file_count": count, "delta_bytes": delta,
                           "changed": entries}))
            if cycles and i >= cycles:
                break
        return 0
    print(f"Memantau {Path(args.root).resolve()} setiap {args.interval}s "
          f"(Ctrl+C untuk berhenti)\n")
    try:
        for i, (ts, total, count, delta, entries) in enumerate(
                watch(Path(args.root), args.interval, args.limit, **_scan_kwargs(args)), 1):
            sign = "+" if delta > 0 else "" if delta == 0 else ""
            print(f"[{i:>3}] {human_size(total):>10}  {count:>7,} file  "
                  f"{sign}{human_size(delta)}")
            for item in entries:
                print(f"        {human_size(item.size):>10}  {item.path}")
            if args.cycles and i >= args.cycles:
                break
    except KeyboardInterrupt:
        print("\nBerhenti.")
    return 0


def cmd_diff(args) -> int:
    path = Path(args.file) if args.file else Path(args.root) / SNAPSHOT_FILE
    result = scan(Path(args.root), limit=args.limit, **_scan_kwargs(args))

    # Mode default = simpan saja. --compare HARUS membaca snapshot lama dulu,
    # baru menimpanya; kalau dibalik, delta-nya selalu 0.
    if not args.compare:
        path.write_text(as_json(snapshot(result)), encoding="utf-8")
        if args.json:
            print(as_json({"saved": str(path), "total_bytes": result.total_bytes}))
        else:
            print(f"Snapshot disimpan: {path}")
            print(f"  {human_size(result.total_bytes)} di {result.file_count:,} file")
        return 0

    if not path.exists():
        print(f"error: snapshot tidak ditemukan: {path} "
              f"(jalankan `diskpulse diff` dulu untuk membuatnya)", file=sys.stderr)
        return 2
    old = json.loads(path.read_text(encoding="utf-8"))
    changes = diff_scans(old, result, args.limit)
    if args.save:
        path.write_text(as_json(snapshot(result)), encoding="utf-8")
    if args.json:
        print(as_json(changes))
        return 0
    delta = changes["delta_bytes"]
    arrow = "NAIK" if delta > 0 else "TURUN" if delta < 0 else "TETAP"
    print(f"Snapshot : {old.get('timestamp', '?')}")
    print(f"Sebelum  : {human_size(changes['previous_total'])} "
          f"({changes['previous_files']:,} file)")
    print(f"Sekarang : {human_size(changes['current_total'])} "
          f"({changes['current_files']:,} file)")
    print(f"Perubahan: {arrow} {human_size(abs(delta))}")
    if changes["changes"]:
        print()
        print("Direktori yang berubah:")
        for item in changes["changes"]:
            sign = "+" if item["delta"] > 0 else "-"
            print(f"  {sign}{human_size(abs(item['delta'])):>10}  {item['directory']}")
    return 0


COMMANDS = {"scan": cmd_scan, "health": cmd_health,
            "duplicates": cmd_duplicates, "clean-plan": cmd_clean_plan,
            "watch": cmd_watch, "diff": cmd_diff}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"error: bukan direktori: {root}", file=sys.stderr)
        return 2
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
