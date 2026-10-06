# BudgetKu — Shared Family Account (PostgreSQL-ready)

BudgetKu adalah aplikasi keuangan keluarga berbasis Flask dengan satu akun keluarga yang bisa dipakai bersama Putri dan Suami. Semua transaksi, saldo rekening, budget, dan target tabungan berada dalam dataset keluarga yang sama. Setiap transaksi menyimpan field **Dicatat oleh** melalui member.

## Fitur
- Login akun keluarga
- Gabung akun keluarga menggunakan share code
- Dataset keuangan bersama antar perangkat
- Member Putri / Suami dan field **Dicatat oleh**
- Rekening & e-wallet
- Pengeluaran & pemasukan
- Budget per rekening + kategori
- Target tabungan
- Backup JSON
- UI pastel BudgetKu dipertahankan dari versi terakhir

## Database
- **Local development:** SQLite (`budgetku.db`) jika `DATABASE_URL` tidak di-set.
- **Production:** PostgreSQL jika `DATABASE_URL` di-set.

## Jalankan lokal
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Buka `http://127.0.0.1:5000`.

## Deploy ke Render
Repository ini sudah disiapkan dengan `render.yaml`.

Render Web Service untuk Flask menggunakan build command `pip install -r requirements.txt` dan start command `gunicorn app:app`. `DATABASE_URL` diarahkan ke Render Postgres dan `SECRET_KEY` dibuat sebagai environment variable. Render mendukung Blueprint melalui `render.yaml` untuk mendefinisikan web service dan database bersama. 

### Catatan penting
- Untuk production, gunakan PostgreSQL; jangan mengandalkan SQLite lokal karena filesystem service Render bersifat ephemeral.
- Setelah deploy, gunakan URL `https://<nama-service>.onrender.com`.
- Jika ingin tetap gratis, perhatikan batasan free tier Render. Dokumentasi Render saat ini menyebut free web service dapat sleep setelah 15 menit tidak aktif dan free Postgres memiliki masa berlaku 30 hari.

## Environment variable
- `DATABASE_URL` — connection string PostgreSQL. Jika kosong, otomatis fallback ke SQLite.
- `SECRET_KEY` — secret untuk session Flask. Di Render, gunakan generated environment variable.


## GitHub iPhone upload
This version intentionally has only root files. Templates and CSS are embedded in app.py, so you can upload app.py, requirements.txt, render.yaml, README.md, and .python-version directly to the repository root.
