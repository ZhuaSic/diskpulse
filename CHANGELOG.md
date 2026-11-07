# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/) dan
[Semantic Versioning](https://semver.org/lang/id/).

## [Unreleased]

## [0.1.0] - 2026-01-01

### Added

- `scan`: total ukuran, jumlah file, direktori terbesar, tipe file terbesar, file terbesar.
- `duplicates`: deteksi duplikat berbasis SHA-256 dengan filter ukuran minimum.
- `clean-plan`: daftar file lama berdasarkan umur, tanpa menghapus apa pun.
- Output `--json` untuk semua subcommand.
- Unit test dan workflow CI lintas OS/Python.
