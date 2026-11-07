"""Klasifikasi ruang disk: mana yang bisa dibuat ulang, mana yang tidak.

Ini inti pembeda DiskPulse. `du`, `ncdu`, dan `dust` hanya memberi satu angka
total; mereka tidak bisa memberi tahu bahwa 1.9 GB dari angka itu adalah
`node_modules` yang bisa dipulihkan dengan satu `npm install`, sedangkan 2.5 GB
sisanya adalah data yang tidak tergantikan.

Klasifikasi dilakukan berdasarkan:
  1. nama direktori leluhur (paling dalam menang), lalu
  2. ekstensi file.

Semua aturan bersifat konservatif: kalau ragu, masuk `unique`.
"""

from __future__ import annotations

from pathlib import Path

DEPS = "deps"
CACHE = "cache"
BUILD = "build"
VCS = "vcs"
LOG = "log"
UNIQUE = "unique"

#: Kategori yang boleh dihapus tanpa kehilangan data (bisa diregenerasi).
REGENERABLE = frozenset({DEPS, CACHE, BUILD})

KIND_LABEL = {
    DEPS: "Dependensi (bisa di-install ulang)",
    CACHE: "Cache (dibuat ulang otomatis)",
    BUILD: "Artefak build",
    VCS: "Metadata version control",
    LOG: "Log",
    UNIQUE: "Data unik",
}

KIND_HINT = {
    DEPS: "jalankan installer paket (npm/pip/cargo/go mod) untuk memulihkan",
    CACHE: "dibuat ulang otomatis saat program dijalankan lagi",
    BUILD: "jalankan build ulang untuk memulihkan",
    VCS: "JANGAN dihapus: ini riwayat repo, bukan cache",
    LOG: "aman dihapus, tapi catatan diagnostik akan hilang",
    UNIQUE: "tidak bisa dipulihkan, tinjau manual",
}

#: Prioritas label di output (urutan tampil).
KIND_ORDER = (DEPS, BUILD, CACHE, LOG, VCS, UNIQUE)

# nama direktori -> (kategori, cara regenerasi)
_DIR_RULES = {
    # JavaScript / TypeScript
    "node_modules": (DEPS, "npm install"),
    ".yarn": (CACHE, "yarn install"),
    ".pnpm-store": (CACHE, "pnpm install"),
    ".next": (BUILD, "next build"),
    ".nuxt": (BUILD, "nuxt build"),
    "dist": (BUILD, "npm run build"),
    "out": (BUILD, "npm run build"),
    ".output": (BUILD, "nuxt build"),
    "storybook-static": (BUILD, "build-storybook"),
    "coverage": (BUILD, "jalankan test dengan coverage"),
    "htmlcov": (BUILD, "coverage run"),
    ".angular": (CACHE, "ng build"),
    ".dart_tool": (CACHE, "flutter pub get"),
    ".expo": (CACHE, "expo start"),
    ".serverless": (BUILD, "serverless package"),
    "_site": (BUILD, "jekyll build"),
    "site": (BUILD, "mkdocs build"),
    ".svelte-kit": (BUILD, "svelte-kit sync"),
    ".turbo": (CACHE, "turbo build"),
    ".parcel-cache": (CACHE, "parcel build"),
    "bower_components": (DEPS, "bower install"),
    # Python
    "__pycache__": (CACHE, "dibuat ulang saat import"),
    ".venv": (DEPS, "python -m venv .venv && pip install -r requirements.txt"),
    "venv": (DEPS, "python -m venv venv && pip install -r requirements.txt"),
    ".tox": (CACHE, "tox"),
    ".nox": (CACHE, "nox"),
    ".pytest_cache": (CACHE, "pytest"),
    ".mypy_cache": (CACHE, "mypy"),
    ".ruff_cache": (CACHE, "ruff"),
    ".hypothesis": (CACHE, "pytest"),
    # Rust / Go / JVM / .NET / mobile
    "target": (BUILD, "cargo build"),
    "pkg": (BUILD, "wasm-pack build"),
    ".gradle": (CACHE, "gradle build"),
    ".m2": (CACHE, "maven"),
    "DerivedData": (BUILD, "xcodebuild"),
    "Pods": (DEPS, "pod install"),
    "obj": (BUILD, "dotnet build"),
    ".terraform": (CACHE, "terraform init"),
    # metadata VCS — BUKAN cache, jangan dihapus
    ".git": (VCS, "jangan dihapus"),
    ".hg": (VCS, "jangan dihapus"),
    ".svn": (VCS, "jangan dihapus"),
    # log
    "logs": (LOG, "rotasi/hapus"),
    "log": (LOG, "rotasi/hapus"),
    "crashdumps": (LOG, "hapus"),
}

# ekstensi -> (kategori, cara regenerasi)
_EXT_RULES = {
    ".pyc": (CACHE, "dibuat ulang saat import"),
    ".pyo": (CACHE, "dibuat ulang saat import"),
    ".pyd": (BUILD, "build ekstensi ulang"),
    ".o": (BUILD, "kompilasi ulang"),
    ".obj": (BUILD, "kompilasi ulang"),
    ".class": (BUILD, "javac"),
    ".tmp": (CACHE, "hapus"),
    ".temp": (CACHE, "hapus"),
    ".cache": (CACHE, "hapus"),
    ".swp": (CACHE, "hapus"),
    ".log": (LOG, "rotasi/hapus"),
    ".ds_store": (CACHE, "hapus"),
    ".thumbs": (CACHE, "hapus"),
}

# nama file persis (bukan ekstensi)
_FILE_RULES = {
    ".ds_store": (CACHE, "hapus"),
    "thumbs.db": (CACHE, "hapus"),
    "desktop.ini": (CACHE, "hapus"),
}


def classify(rel: Path) -> tuple[str, str]:
    """Tentukan (kategori, cara regenerasi) untuk path relatif.

    Direktori terdalam yang cocok menang, sehingga `proyek/node_modules/x/.git`
    dikenali sebagai metadata VCS, bukan dependensi.
    """
    rel = Path(rel)
    for part in reversed([p.lower() for p in rel.parts[:-1]]):
        rule = _DIR_RULES.get(part)
        if rule:
            return rule

    name = rel.name.lower()
    rule = _FILE_RULES.get(name)
    if rule:
        return rule

    rule = _EXT_RULES.get(rel.suffix.lower())
    if rule:
        return rule

    return UNIQUE, KIND_HINT[UNIQUE]


def sort_kinds(kinds: dict) -> list[tuple[str, int]]:
    """Urutkan kategori: yang bisa dibebaskan dulu, lalu yang terbesar."""
    def key(item):
        kind, size = item
        rank = KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)
        return (rank, -size)
    return sorted(kinds.items(), key=key)
