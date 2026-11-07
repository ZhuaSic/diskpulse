"""Mesin inti DiskPulse: scanning, duplikat, kesehatan, watch, tren.

Semua fungsi read-only. Tidak ada satu pun yang menghapus/memindahkan file.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .classify import (BUILD, CACHE, DEPS, LOG, REGENERABLE, UNIQUE, VCS,
                       classify, sort_kinds)

#: Tidak ada yang dilewati default — DISENGAJA.
#:
#: Tool lain menyembunyikan node_modules/.git/dist dari hasil, sehingga angka
#: totalnya lebih kecil dari kenyataan dan kamu tidak pernah tahu ke mana
#: sisa ruangnya pergi. DiskPulse menghitung SEMUA, lalu mengklasifikasikan
#: mana yang bisa dibebaskan. Total yang jujur > total yang enak dilihat.
#: Pakai `--exclude` kalau memang ingin menyaring.
DEFAULT_EXCLUDES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FileInfo:
    path: str
    size: int
    mtime: float

    @property
    def age_days(self) -> int:
        return max(0, int((time.time() - self.mtime) / 86400))


@dataclass
class ScanResult:
    root: str
    total_bytes: int = 0
    file_count: int = 0
    directories: dict[str, int] = field(default_factory=dict)
    extensions: dict[str, int] = field(default_factory=dict)
    largest: list[FileInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    kinds: dict[str, int] = field(default_factory=dict)

    @property
    def reclaimable_bytes(self) -> int:
        """Byte pada kategori yang bisa diregenerasi."""
        return sum(v for k, v in self.kinds.items() if k in REGENERABLE)

    @property
    def speed(self) -> float:
        return self.file_count / self.elapsed if self.elapsed > 0 else 0.0


_UNITS = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")


def human_size(num: float) -> str:
    """Format ukuran byte. Selalu naik satuan sampai < 1024 atau habis unit."""
    num = float(num)
    for unit in _UNITS:
        if abs(num) < 1024.0 or unit == _UNITS[-1]:
            return f"{int(num)} B" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} EB"


def parse_size(text: str) -> int:
    text = text.strip().upper()
    suffixes = {"K": 1, "M": 2, "G": 3, "T": 4, "KB": 1, "MB": 2, "GB": 3, "TB": 4}
    for suffix, power in sorted(suffixes.items(), key=lambda kv: -len(kv[0])):
        if text.endswith(suffix):
            return int(float(text[: -len(suffix)]) * 1024 ** power)
    return int(text)


def iter_files(root: Path, skip_hidden: bool = False,
               excludes=None, follow_symlinks: bool = False):
    """Walk yang efisien: dir exclude dipangkas dari traversal, 1 stat per file.

    `hidden`/`skip_hidden` sengaja default-nya MENGHITUNG file tersembunyi:
    .git, .venv, dan .cache adalah bagian nyata dari pemakaian disk. Menyembunyikannya
    membuat total lebih kecil dari kenyataan.
    """
    skip = DEFAULT_EXCLUDES if excludes is None else set(excludes)
    hide = skip_hidden
    root = Path(root)
    for current, dirs, files in os.walk(root, followlinks=follow_symlinks):
        dirs[:] = sorted(d for d in dirs if not _excluded(d, skip, hide))
        for name in sorted(files):
            if _excluded(name, skip, hide):
                continue
            path = Path(current) / name
            try:
                if follow_symlinks:
                    stat = path.stat()
                else:
                    # 1 syscall: symlink dilewati, bukan diikuti.
                    stat = os.stat(path, follow_symlinks=False)
                    if stat.st_mode & 0o170000 == 0o120000:  # S_IFLNK
                        continue
            except OSError:
                continue
            yield path, stat


def _excluded(name: str, patterns, hide: bool) -> bool:
    if hide and name.startswith("."):
        return True
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def scan(root: Path, limit: int = 15, **kwargs) -> ScanResult:
    start = time.monotonic()
    result = ScanResult(root=str(Path(root).resolve()))
    directories: dict[str, int] = defaultdict(int)
    extensions: dict[str, int] = defaultdict(int)
    kinds: dict[str, int] = defaultdict(int)
    largest: list[FileInfo] = []
    for path, stat in iter_files(root, **kwargs):
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        size = stat.st_size
        result.total_bytes += size
        result.file_count += 1
        directories[str(rel.parent)] += size
        extensions[path.suffix.lower() or "(tanpa ekstensi)"] += size
        kinds[classify(rel)[0]] += size
        largest.append(FileInfo(str(rel), size, stat.st_mtime))
    largest.sort(key=lambda item: item.size, reverse=True)
    result.directories = dict(sorted(directories.items(), key=lambda kv: kv[1], reverse=True))
    result.extensions = dict(sorted(extensions.items(), key=lambda kv: kv[1], reverse=True))
    result.kinds = dict(sorted(kinds.items(), key=lambda kv: kv[1], reverse=True))
    result.largest = largest[: max(0, limit)]
    result.elapsed = time.monotonic() - start
    return result


# ---------------------------------------------------------------- duplikat

def sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def partial_hash(path: Path, size: int, chunk_size: int = 65536) -> str:
    """Hash murah: blok awal + blok tengah + blok akhir.

    Menghindari membaca file besar berkali-kali: file dengan partial hash
    berbeda pasti bukan duplikat, sehingga tidak perlu hash penuh.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        digest.update(handle.read(chunk_size))
        if size > chunk_size * 2:
            handle.seek(max(0, (size // 2) - chunk_size // 2))
            digest.update(handle.read(chunk_size))
        if size > chunk_size:
            handle.seek(max(0, size - chunk_size))
            digest.update(handle.read(chunk_size))
    return digest.hexdigest()


def find_duplicates(root: Path, min_size: int = 1, limit: int = 100,
                    fast: bool = True, **kwargs) -> list[list[FileInfo]]:
    """Kelompokkan file dengan isi identik (SHA-256).

    3 tahap penyaringan, masing-masing jauh lebih murah dari berikutnya:
      1. ukuran file,
      2. partial hash (3 blok) bila fast=True,
      3. SHA-256 penuh hanya untuk kandidat yang lolos.
    """
    root = Path(root)
    by_size: dict[int, list[tuple[Path, os.stat_result]]] = defaultdict(list)
    for path, stat in iter_files(root, **kwargs):
        if stat.st_size >= min_size:
            by_size[stat.st_size].append((path, stat))

    groups: list[list[FileInfo]] = []
    for size, candidates in by_size.items():
        if len(candidates) < 2:
            continue
        pools = [candidates]
        if fast and size > 65536 * 2:
            by_partial: dict[str, list[tuple[Path, os.stat_result]]] = defaultdict(list)
            for path, stat in candidates:
                try:
                    by_partial[partial_hash(path, size)].append((path, stat))
                except OSError:
                    continue
            pools = [p for p in by_partial.values() if len(p) > 1]

        for pool in pools:
            by_hash: dict[str, list[FileInfo]] = defaultdict(list)
            for path, stat in pool:
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


# ------------------------------------------------------------- kesehatan

def health(result: ScanResult) -> dict:
    """Skor 0-100 + saran konkret dengan angka ruang yang bisa dibebaskan.

    Skor bukan dekorasi: setiap pengurang punya ambang dan saran yang bisa
    langsung dieksekusi, sehingga dua proyek berbeda mendapat skor berbeda.
    """
    total = max(result.total_bytes, 1)
    penalty = 0
    actions = []

    def add(kind: str, threshold: float, weight: float, suggestion: str):
        nonlocal penalty
        size = result.kinds.get(kind, 0)
        ratio = size / total
        if ratio > threshold:
            penalty += min(weight, (ratio - threshold) * 100 * weight / 30)
            actions.append({
                "kind": kind,
                "bytes": size,
                "human": human_size(size),
                "percent": round(ratio * 100, 1),
                "suggestion": suggestion,
            })

    add(DEPS, 0.30, 30, "install ulang paket hanya di proyek yang aktif")
    add(BUILD, 0.20, 20, "hapus artefak build, lalu build ulang bila perlu")
    add(CACHE, 0.10, 15, "hapus cache, dibuat ulang otomatis")
    add(LOG, 0.05, 10, "rotasi atau hapus log lama")

    old = [f for f in result.largest if f.age_days > 365]
    if old:
        bytes_old = sum(f.size for f in old)
        penalty += min(15, len(old) * 2)
        actions.append({
            "kind": "stale", "bytes": bytes_old, "human": human_size(bytes_old),
            "percent": round(bytes_old / total * 100, 1),
            "suggestion": f"{len(old)} file terbesar belum disentuh > 1 tahun",
        })

    score = max(0, min(100, round(100 - penalty)))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 55 else "D"
    return {"score": score, "grade": grade, "actions": actions,
            "reclaimable_bytes": result.reclaimable_bytes,
            "reclaimable_human": human_size(result.reclaimable_bytes)}


# ------------------------------------------------------------- watch/tren

def watch(root: Path, interval: float = 2.0, limit: int = 10, **kwargs):
    """Yield (timestamp, total_bytes, file_count, delta, entries) tiap siklus.

    Hanya mengembalikan file yang berubah sejak siklus sebelumnya, bukan
    seluruh daftar — jadi bisa dipakai untuk memantau build atau download.
    """
    previous: dict[str, int] = {}
    while True:
        total = 0
        current: dict[str, int] = {}
        entries = []
        for path, stat in iter_files(root, **kwargs):
            rel = str(path.relative_to(root))
            current[rel] = stat.st_size
            total += stat.st_size
            if previous.get(rel) != stat.st_size:
                entries.append(FileInfo(rel, stat.st_size, stat.st_mtime))
        entries.sort(key=lambda f: f.size, reverse=True)
        yield (time.time(), total, len(current),
               total - sum(previous.values()), entries[:limit])
        previous = current
        time.sleep(interval)


def diff_scans(old: dict, new: ScanResult, limit: int = 15) -> dict:
    """Bandingkan snapshot sebelumnya dengan hasil scan sekarang."""
    old_total = int(old.get("total_bytes", 0))
    old_dirs = old.get("directories", {})
    changes = []
    for name, size in new.directories.items():
        delta = size - old_dirs.get(name, 0)
        if delta:
            changes.append({"directory": name, "delta": delta, "now": size})
    changes.sort(key=lambda c: abs(c["delta"]), reverse=True)
    return {
        "root": new.root,
        "previous_total": old_total,
        "current_total": new.total_bytes,
        "delta_bytes": new.total_bytes - old_total,
        "delta_human": human_size(new.total_bytes - old_total),
        "previous_files": int(old.get("file_count", 0)),
        "current_files": new.file_count,
        "changes": changes[:limit],
    }


def snapshot(result: ScanResult) -> dict:
    return {
        "version": 1,
        "root": result.root,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_bytes": result.total_bytes,
        "file_count": result.file_count,
        "directories": result.directories,
        "kinds": result.kinds,
    }


def as_json(value) -> str:
    def default(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        return str(obj)
    return json.dumps(value, default=default, indent=2, sort_keys=True,
                      ensure_ascii=False)
