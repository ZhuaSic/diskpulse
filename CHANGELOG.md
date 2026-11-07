# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/) dan
[Semantic Versioning](https://semver.org/lang/id/).

## [Unreleased]

## [0.2.1] - 2026-11-07

### Fixed

- **Klasifikasi salah pada nama direktori generik.** `node_modules/pkg/index.js`
  dilaporkan sebagai `build` hanya karena `pkg` lebih dalam dari
  `node_modules`. Nama yang ambigu (`pkg`, `out`, `bin`, `obj`, `site`, `log`,
  `coverage`) sekarang ada di tabel *aturan lemah* yang hanya dipakai kalau
  tidak ada aturan kuat sama sekali di path tersebut — jadi aturan kuat kini
  selalu menang tanpa memandang kedalaman.
- **`elapsed` bisa 0.0 di Windows.** `time.monotonic()` beresolusi kasar di
  Windows; pemindaian beberapa file bisa selesai dalam < 1 tick sehingga
  `speed` dilaporkan `0.0 file/detik`. Beralih ke `time.perf_counter()` dengan
  clamp `1e-9`.
- **CI gagal di Ubuntu karena Python 3.9.** Runner `ubuntu-latest` sudah
  Ubuntu 26.04 yang tidak menyediakan binary Python 3.9. Matrix dipin ke
  `ubuntu-24.04`.
- Langkah verifikasi CI tidak lagi bergantung pada `mkdir -p`/`/dev/zero`,
  yang tidak ada di runner Windows.

### Changed

- Job CI kini juga memverifikasi klasifikasi dan skor `health` pada struktur
  direktori nyata (`node_modules/pkg`, `dist`, `.git`, `docs`) di ketiga OS.

## [0.2.0] - 2026-11-07

Rilis ini mengubah DiskPulse dari "penghitung ukuran" menjadi "penilai ruang".
Fokusnya satu: menjawab *berapa yang bisa saya bebaskan, dan yang mana?* —
pertanyaan yang tidak dijawab `du`, `ncdu`, maupun GUI sejenis.

### Added

- **Klasifikasi ruang** (`diskpulse/classify.py`): 6 kategori — `deps`,
  `cache`, `build`, `log`, `vcs`, `unique`. Aturan per nama direktori
  (terdalam menang), per nama file, dan per ekstensi. Setiap kategori
  membawa cara regenerasi spesifik (`npm install`, `cargo build`, dst).
- **`health`**: skor 0–100 + grade A/B/C/D dengan daftar tindakan berangka.
- **`watch`**: pemantauan real-time, hanya menampilkan file yang berubah,
  dengan delta ukuran per siklus.
- **`diff`**: snapshot lalu bandingkan — direktori mana yang tumbuh.
- `reclaimable_bytes` pada `ScanResult`: hanya menghitung kategori yang
  benar-benar bisa diregenerasi (`deps`, `cache`, `build`). `.git` tidak
  pernah masuk hitungan ini.
- `partial_hash`: penyaringan 3 blok (awal/tengah/akhir) sebelum SHA-256
  penuh, sehingga file besar yang jelas berbeda tidak di-hash dua kali.
- `scan` melaporkan kecepatan (`file/detik`) dan waktu tempuh.
- `--skip-hidden` eksplisit; sebelumnya penyaringan file tersembunyi implisit.

### Changed

- **Total sekarang jujur.** `DEFAULT_EXCLUDES` menjadi kosong dan file
  tersembunyi dihitung default. Sebelumnya `node_modules`, `.git`, dan
  `__pycache__` dibuang dari hasil, sehingga total lebih kecil dari kenyataan
  dan kategori terpenting tidak pernah muncul. Pakai `--exclude` /
  `--skip-hidden` bila memang ingin menyaring.
- `duplicates` memakai 3 tahap penyaringan (ukuran → partial → penuh);
  `--no-fast` memaksa SHA-256 penuh.
- Pesan `scan` menyertakan jumlah path yang dilewati karena tidak terbaca.

### Fixed

- `human_size` berhenti di TB sehingga 1 PB tampil sebagai `1073741824.0 TB`.
  Sekarang naik sampai YB.
- `diff --save --compare` menyimpan snapshot sebelum membandingkan, jadi
  delta-nya selalu 0. Sekarang snapshot lama dibaca lebih dulu.
- `--exclude` kosong menimpa daftar default sehingga filter mati tanpa
  peringatan.

## [0.1.0] - 2026-01-01

### Added

- `scan`: total ukuran, jumlah file, direktori terbesar, tipe file terbesar,
  file terbesar.
- `duplicates`: deteksi duplikat berbasis SHA-256 dengan filter ukuran minimum.
- `clean-plan`: daftar file lama berdasarkan umur, tanpa menghapus apa pun.
- Output `--json` untuk semua subcommand.
- Unit test dan workflow CI lintas OS/Python.
