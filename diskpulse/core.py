from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

# Direktori yang hampir selalu bukan milik pengguna: dilewati secara default
# supaya hasil scan mencerminkan data nyata, bukan cache build.
DEFAULT_EXCLUDES = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".nuxt", ".cache", "target",
})


@dataclass(frozen=True)
class FileInfo:
    path: str
    size: int
    mtime: float

    @property
    def age_days(self) -> int:
        return max(0, int((time.time() - self.mtime) // 86400))


@dataclass
class ScanResult:
    root: str
    total_bytes: int = 0
    file_count: int = 0
    errors: list[str] = field(default_factory=list)
    directories: dict[str, int] = field(default_factory=dict)
    extensions: dict[str, int] = field(default_factory=dict)
    largest: list[FileInfo] = field(default_factory=list)


def human_size(value: float) -> str:
    """1024 -> '1.0 KB', 0 -> '0 B'."""
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{int(amount)} B" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{int(value)} B"


def parse_size(text: str) -> int:
    """'1M' -> 1048576. Menerima B/K/M/G/T (basis 1024, case-insensitive)."""
    raw = str(text).strip().upper()
    if raw.endswith("B") and len(raw) > 1:
        raw = raw[:-1]
    if not raw:
        raise ValueError("ukuran kosong")
    multipliers = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    suffix = raw[-1]
    if suffix in multipliers:
        return int(float(raw[:-1]) * multipliers[suffix])
    return int(float(raw))


def _excluded(name: str, patterns) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def iter_files(
    root: Path,
    follow_symlinks: bool = False,
    hidden: bool = False,
    excludes=DEFAULT_EXCLUDES,
) -> Iterator[tuple[Path, os.stat_result]]:
    """Telusuri file di bawah `root`.

    Melewati direktori pada `excludes` dan (kecuali `hidden=True`) entri
    berawalan titik. Symlink tidak diikuti secara default untuk menghindari
    loop dan keluar dari `root`.
    """
    root = Path(root)
    for current, dirs, files in os.walk(root, followlinks=follow_symlinks):
        kept = []
        for d in dirs:
            if _excluded(d, excludes) or (not hidden and d.startswith(".")):
                continue
            kept.append(d)
        dirs[:] = kept
        for name in files:
            if not hidden and name.startswith("."):
                continue
            if _excluded(name, excludes):
                continue
            path = Path(current) / name
            try:
                if follow_symlinks:
                    stat = path.stat()
                else:
                    # os.stat(follow_symlinks=False) = 1 syscall, bukan 2
                    stat = os.stat(path, follow_symlinks=False)
                    if stat.st_mode & 0o170000 == 0o120000:  # S_IFLNK
                        continue
            except OSError:
                continue
            yield path, stat


def scan(root: Path, limit: int = 20, **kwargs) -> ScanResult:
    root = Path(root)
    result = ScanResult(root=str(root))
    directories: dict[str, int] = defaultdict(int)
    extensions: dict[str, int] = defaultdict(int)
    largest: list[FileInfo] = []

    for path, stat in iter_files(root, **kwargs):
        size = stat.st_size
        result.total_bytes += size
        result.file_count += 1
        relative = path.relative_to(root)
        parent = str(relative.parent)
        directories[parent if parent != "." else "."] += size
        ext = path.suffix.lower() or "<tanpa ekstensi>"
        extensions[ext] += size
        largest.append(FileInfo(str(relative), size, stat.st_mtime))

    largest.sort(key=lambda item: item.size, reverse=True)
    result.directories = dict(sorted(directories.items(), key=lambda kv: kv[1], reverse=True))
    result.extensions = dict(sorted(extensions.items(), key=lambda kv: kv[1], reverse=True))
    result.largest = largest[: max(0, limit)]
    return result


def sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicates(root: Path, min_size: int = 1, limit: int = 100, **kwargs) -> list[list[FileInfo]]:
    """Kelompokkan file dengan isi identik (SHA-256).

    Ukuran dipakai lebih dulu sebagai saringan murah, jadi hashing hanya
    dilakukan pada kandidat yang ukurannya sama. Grup diurutkan berdasarkan
    potensi ruang yang bisa dihemat: ukuran x (jumlah file - 1).
    """
    root = Path(root)
    by_size: dict[int, list[tuple[Path, os.stat_result]]] = defaultdict(list)
    for path, stat in iter_files(root, **kwargs):
        if stat.st_size >= min_size:
            by_size[stat.st_size].append((path, stat))

    groups: list[list[FileInfo]] = []
    for candidates in by_size.values():
        if len(candidates) < 2:
            continue
        by_hash: dict[str, list[FileInfo]] = defaultdict(list)
        for path, stat in candidates:
            try:
                digest = sha256(path)
            except OSError:
                continue
            by_hash[digest].append(
                FileInfo(str(path.relative_to(root)), stat.st_size, stat.st_mtime))
        for files in by_hash.values():
            if len(files) > 1:
                files.sort(key=lambda f: f.path)
                groups.append(files)
    groups.sort(key=lambda g: g[0].size * (len(g) - 1), reverse=True)
    return groups[: max(0, limit)]


def clean_plan(root: Path, days: int = 180, min_size: int = 0, **kwargs) -> list[FileInfo]:
    """File yang lebih tua dari `days` hari - untuk DITINJAU, bukan dihapus."""
    root = Path(root)
    cutoff = time.time() - days * 86400
    result = []
    for path, stat in iter_files(root, **kwargs):
        if stat.st_mtime < cutoff and stat.st_size >= min_size:
            result.append(
                FileInfo(str(path.relative_to(root)), stat.st_size, stat.st_mtime))
    return sorted(result, key=lambda item: item.size, reverse=True)


def as_json(value) -> str:
    def default(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        return str(obj)
    return json.dumps(value, default=default, indent=2, sort_keys=True,
                      ensure_ascii=False)
