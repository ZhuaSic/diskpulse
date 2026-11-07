# DiskPulse

> Analisis disk yang tahu bedanya **data penting** dan **sampah yang bisa
> dibuat ulang** — bukan sekadar menghitung total.

[![CI](https://github.com/ZhuaSic/diskpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuaSic/diskpulse/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)

```bash
diskpulse scan ~/proyek
```

```
Total       : 381.2 KB di 99 file

Klasifikasi ruang (bisa dibebaskan: 190.7 KB = 50%):
    190.7 KB   50.0%  Cache (dibuat ulang otomatis)
                      -> dibuat ulang otomatis saat program dijalankan lagi
      1.1 KB    0.3%  Log
                      -> aman dihapus, tapi catatan diagnostik akan hilang
     41.0 KB   10.8%  Metadata version control
                      -> JANGAN dihapus: ini riwayat repo, bukan cache
    148.3 KB   38.9%  Data unik
                      -> tidak bisa dipulihkan, tinjau manual
```

Satu angka total dari `du` tidak bisa memberi tahu kamu ini. Semua operasi
DiskPulse **read-only** — ia tidak pernah menghapus apa pun.

## Bedanya dengan tool lain

| Tool | Yang tidak bisa dilakukan DiskPulse |
|---|---|
| `du`, WinDirStat, TreeSize | Hanya total. Tidak tahu `node_modules` 1.9 GB bisa dibebaskan dengan satu `npm install`. |
| WizTree | Cepat tapi butuh GUI + MFT (NTFS-only). DiskPulse jalan di semua OS, SSH, CI. |
| `ncdu` | Interaktif TUI, tidak bisa di-pipe/otomasi. DiskPulse punya `--json` yang stabil. |
| `dust`, `dua` | Rust binary; tidak bisa kamu baca kodenya untuk mengecek apa yang dihitung. DiskPulse ~600 baris Python yang bisa kamu audit. |
| CCleaner dkk | **Menghapus** otomatis. DiskPulse 100% read-only, rencana saja yang dihasilkan. |
| Semua di atas | Tidak ada yang menampilkan total yang jujur: `node_modules` & `.git` biasanya dieskip dari angka. DiskPulse menghitung SEMUA lalu mengklasifikasikan. |

Ringkasnya: tool lain menjawab *"apa yang paling besar?"*.
DiskPulse menjawab *"berapa yang bisa saya bebaskan, dan yang mana?"*.

## Fitur

- **Klasifikasi ruang** — 6 kategori (dependensi, cache, build, log, metadata
  VCS, data unik) dengan cara regenerasi spesifik per kategori:
  `npm install`, `cargo build`, `next build`, bukan sekadar "hapus".
- **`health`** — skor kesehatan 0–100 + daftar tindakan dengan angka ruang
  yang bisa dibebaskan. Grade A/B/C/D.
- **`watch`** — pantau folder real-time; hanya file yang berubah yang
  ditampilkan, dengan delta ukuran per siklus.
- **`diff`** — simpan snapshot, bandingkan nanti: folder mana yang tumbuh
  sejak terakhir dicek.
- **`duplicates`** — 3 tahap: ukuran → partial hash (3 blok) → SHA-256 penuh.
  File besar tidak di-hash dua kali kalau partial hash-nya sudah beda.
- **`clean-plan`** — file lama untuk DITINJAU. Tidak ada yang dihapus.
- **`--json` stabil** untuk semua subcommand — untuk CI, cron, dashboard.
- **Total yang jujur** — file tersembunyi dihitung default. `--skip-hidden`
  kalau memang mau menyaring.
- **Nol dependensi**, Python 3.9+.

## Instalasi

```bash
git clone https://github.com/ZhuaSic/diskpulse.git
cd diskpulse
python -m pip install -e .
```

Atau tanpa instalasi: `python -m diskpulse --help`

## Cara pakai

### `scan` — klasifikasi ruang

```bash
diskpulse scan ~/proyek
diskpulse scan ~/proyek --no-classify   # ringkasan saja
```

### `health` — skor + saran

```bash
diskpulse health ~/proyek
```

```
Skor   : 85/100  (grade B)
         [#################...]
Bisa dibebaskan: 190.7 KB

Yang perlu ditindak:
  - 190.7 KB (50.0%)  Cache (dibuat ulang otomatis)
    -> hapus cache, dibuat ulang otomatis
```

### `duplicates` — file kembar

```bash
diskpulse duplicates ~/Downloads --min-size 1M
```

```
2 grup duplikat - potensi hemat: 84.2 MB

#1 2 file x 40.1 MB (hemat 40.1 MB):
    foto/liburan.jpg
    backup/foto/liburan.jpg
```

### `clean-plan` — file lama

```bash
diskpulse clean-plan . --days 180
```

```
14 file lebih tua dari 180 hari (total 210.4 MB) - untuk DITINJAU, tidak ada yang dihapus:

   88.1 MB   412h  arsip/old-dump.sql
```

### `watch` — pantau real-time

```bash
diskpulse watch ~/proyek --interval 2
```

```
[  1]   381.2 KB       99 file  +381.2 KB
[  2]   381.2 KB       99 file  0 B
        +2.3 KB  build/output.js        <- hanya file yang berubah
```

### `diff` — snapshot & bandingkan

```bash
diskpulse diff ~/proyek              # simpan snapshot
# ... jalankan build, download, dsb ...
diskpulse diff ~/proyek --compare    # apa yang tumbuh?
```

```
Sebelum  : 167.6 KB (76 file)
Sekarang : 169.1 KB (78 file)
Perubahan: NAIK 1.5 KB

Direktori yang berubah:
  +    1.5 KB  .
```

### Opsi umum

```bash
--json           # output JSON untuk semua subcommand
--skip-hidden    # lewati file/direktori berawalan titik
--exclude "x"    # pola glob untuk dilewati (bisa diulang)
```

Pipeline:

```bash
diskpulse scan /data --json | jq '.kinds'
diskpulse health . --json | jq -r '.actions[].suggestion'
```

## Cara kerja

1. `os.walk` menelusuri direktori; `--exclude` dipangkas dari traversal.
2. Satu `os.stat(follow_symlinks=False)` per file; symlink tidak diikuti.
3. Klasifikasi: nama direktori leluhur (terdalam menang) → nama file →
   ekstensi. `x/node_modules/y/.git` dikenali sebagai VCS, bukan dependensi.
4. `duplicates`: ukuran → partial hash (awal+tengah+akhir) → SHA-256 penuh.
5. `health`: pengurang skor per kategori dengan ambang, bukan angka acak.

## Batasan yang jujur

- Hash file besar butuh waktu; batasi dengan `--min-size`.
- Symlink tidak diikuti (mencegah loop keluar root).
- File tanpa izin baca dilewati, bukan menggagalkan pemindaian.
- Hardlink masih terlihat seperti duplikat (di roadmap).
- Klasifikasi berbasis nama/ekstensi — heuristik, bukan kepastian.

## Roadmap

- [ ] Deteksi hardlink
- [ ] Mode `--interactive` dengan konfirmasi per file
- [ ] Ekspor CSV/HTML
- [ ] Cache hash agar pemindaian ulang lebih cepat

## Berkontribusi

Baca [CONTRIBUTING.md](CONTRIBUTING.md). Intinya: stdlib saja, tambahkan test,
jangan menambah perilaku yang menghapus file tanpa konfirmasi eksplisit.

```bash
python -m unittest discover -s tests -v
```

## Lisensi

[MIT](LICENSE) © 2026 ZhuaSic
