# DiskPulse

> Cari tahu **ke mana ruang disk kamu pergi** — dan dapatkan rencana pembersihan
> yang aman — dalam satu perintah, tanpa dependensi.

[![CI](https://github.com/ZhuaSic/diskpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuaSic/diskpulse/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)

`diskpulse` memindai direktori dan menjawab tiga pertanyaan yang biasanya butuh
beberapa tool GUI terpisah:

| Pertanyaan | Perintah |
|---|---|
| Folder dan tipe file apa yang paling banyak makan ruang? | `scan` |
| File mana yang isinya identik (duplikat)? | `duplicates` |
| File apa yang sudah lama tidak disentuh dan layak ditinjau? | `clean-plan` |

**Semua operasi bersifat read-only.** DiskPulse tidak pernah menghapus,
memindahkan, atau mengubah file apa pun. Kamu yang memutuskan.

## Kenapa DiskPulse

- **Nol dependensi.** Hanya Python standard library. Tidak ada supply chain,
  tidak ada `pip install` yang berat, jalan di mana saja.
- **Cepat.** Memindai ~50.000 file / 2,7 GB dalam **~10 detik** di Windows
  (satu `os.stat` per file, symlink tidak diikuti).
- **Saringan cerdas.** `node_modules`, `__pycache__`, `.git`, `.venv`,
  `dist`, `build` dan sejenisnya dilewati default — hasilnya mencerminkan
  data kamu, bukan artefak build.
- **Duplikat berbasis isi.** SHA-256, bukan nama file. Ukuran dipakai lebih
  dulu sebagai saringan murah, jadi hashing hanya dilakukan pada kandidat nyata.
- **Output JSON stabil** untuk CI, cron, atau dashboard.
- **Lintas platform.** Diuji di Linux, macOS, dan Windows (lihat CI).

## Instalasi

```bash
git clone https://github.com/ZhuaSic/diskpulse.git
cd diskpulse
python -m pip install -e .
```

Atau jalankan tanpa instalasi:

```bash
python -m diskpulse --help
```

Syarat: Python 3.9 atau lebih baru.

## Cara pakai

### `scan` — ke mana ruang pergi

```bash
diskpulse scan ~/projects
```

```
Root        : /home/user/projects
Total       : 4.8 GB di 24,193 file

Direktori terbesar:
    1.2 GB  node_modules
  842.1 MB  .git
  310.5 MB  build

Tipe file terbesar:
  1.9 GB  .so
  620.4 MB  .png

File terbesar:
    120.3 MB  assets/video.mp4
```

### `duplicates` — temukan file kembar

```bash
diskpulse duplicates ~/Downloads --min-size 1M
```

```
3 grup duplikat - potensi hemat: 84.2 MB

#1 2 file x 40.1 MB:
    foto/liburan.jpg
    backup/foto/liburan.jpg
#2 3 file x 2.1 MB:
    installer/setup.exe
    lama/setup.exe
    temp/setup.exe
```

Hasil diurutkan berdasarkan **potensi ruang yang bisa dihemat**
(`ukuran × (jumlah file − 1)`), jadi yang paling berdampak muncul lebih dulu.

### `clean-plan` — file lama untuk ditinjau

```bash
diskpulse clean-plan . --days 180
```

```
14 file lebih tua dari 180 hari (total 210.4 MB) - untuk DITINJAU, tidak ada yang dihapus:

   88.1 MB   412h  arsip/old-dump.sql
   40.2 MB   731h  video/lama.mp4
```

### Opsi umum

```bash
--json              # output JSON, untuk skrip/CI
--hidden            # sertakan file/direktori tersembunyi
--exclude "*.log"   # tambahan pola untuk dilewati (bisa diulang)
```

Contoh pipeline:

```bash
diskpulse scan /data --json > report.json
diskpulse duplicates . --min-size 10M --json | jq 'length'
```

## Cara kerja

1. `os.walk` menelusuri direktori; direktori pada daftar exclude dipangkas
   dari traversal (bukan difilter setelahnya), jadi tetap cepat.
2. Setiap file diambil metadatanya dengan satu `os.stat(follow_symlinks=False)`.
3. `scan` mengagregasi ukuran per direktori induk dan per ekstensi.
4. `duplicates` mengelompokkan berdasarkan ukuran dulu, lalu SHA-256 per blok
   1 MB hanya untuk grup yang ukurannya sama.
5. `clean-plan` membandingkan `mtime` dengan ambang umur.

Ditulis dengan Python murni, tanpa asumsi layout filesystem tertentu.

## Batasan yang jujur

- Hash file besar butuh waktu; gunakan `--min-size` untuk membatasi.
- Symlink tidak diikuti secara default (mencegah loop dan keluar dari root).
- File tanpa izin baca dilewati, bukan menggagalkan seluruh pemindaian.
- Belum menangani hardlink sebagai satu entitas; dua hardlink akan terlihat
  seperti duplikat. Ini ada di roadmap.

## Roadmap

- [ ] Deteksi hardlink agar tidak dilaporkan sebagai duplikat
- [ ] Mode `--interactive` dengan konfirmasi per file sebelum dihapus
- [ ] Ekspor CSV/HTML untuk laporan
- [ ] Cache hasil hash agar pemindaian ulang lebih cepat
- [ ] Grafik batang di terminal

## Berkontribusi

Sangat terbuka untuk PR kecil. Baca [CONTRIBUTING.md](CONTRIBUTING.md) dulu —
singkatnya: stdlib saja, tambahkan test, jangan menambah perilaku yang
menghapus file tanpa konfirmasi eksplisit.

```bash
python -m unittest discover -s tests -v
```

## Lisensi

[MIT](LICENSE) © 2026 ZhuaSic
