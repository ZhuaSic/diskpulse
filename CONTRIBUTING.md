# Berkontribusi pada DiskPulse

Terima kasih! Fokus proyek ini adalah tool penyimpanan yang **aman, cepat, dan
mudah diaudit**.

## Menjalankan lokal

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m diskpulse --help
```

## Standar

- Python 3.9+, stdlib saja untuk runtime.
- Tidak ada penghapusan file tanpa persetujuan eksplisit dan dry-run terlebih dahulu.
- Tambahkan unit test untuk setiap perbaikan bug.
- Hindari perubahan format output JSON yang memutus pengguna.

## Alur PR

1. Buat issue yang menjelaskan masalah dan ukuran keberhasilan.
2. Tulis test yang gagal sebelum memperbaiki bug.
3. Jalankan `python -m unittest discover -s tests`.
4. Jelaskan perilaku sebelum/sesudah di PR.
