# Penyiapan cache PostgreSQL

[English](../../../guides/pgvector.md)

Server mendelegasikan cache persisten ke `PgVectorStore` resmi. Store meminjam pool
PostgreSQL yang dimiliki lifespan server dan dipakai bersama fitur database lainnya;
store tidak menutup pool tersebut. Lihat [konfigurasi storage server](../../../guides/platform-storage.md)
untuk pilihan store, variabel setup, Inspector, dan transisi layout lama.

## Konfigurasi

Pilih `CACHE_BACKEND=pgvector` dan sediakan `DATABASE_URL` secara aman. Default:
`CACHE_PGVECTOR_SCHEMA=semantix_cache`, `CACHE_PGVECTOR_TABLE_PREFIX=workbench_`.
Contoh berikut sengaja bukan koneksi yang dapat digunakan:

```env
DATABASE_URL=postgresql://replace-user:replace-password@postgres.example.invalid:5432/replace-database
```

Kredensial hanya berada di server. Batas pool dan timeout tetap menggunakan
`DATABASE_POOL_MIN_SIZE`, `DATABASE_POOL_MAX_SIZE`, `DATABASE_CONNECT_TIMEOUT_SECONDS`,
dan `DATABASE_COMMAND_TIMEOUT_SECONDS`. Role runtime tidak memerlukan wewenang migrasi.

## Setup eksplisit

Cadangkan data terlebih dahulu. Dari `apps/server`, konfigurasi khusus operator:
`MIGRATION_DATABASE_URL`, `DATABASE_RUNTIME_ROLE`, `CACHE_BACKEND=pgvector`, serta
schema/prefix yang sama, lalu jalankan:

```bash
python -m app.infrastructure.migrate
```

Job memasang pgvector, memverifikasi kepemilikan/checksum migrasi, dan memberikan
akses cache serta telemetri kepada role runtime. Startup biasa hanya memvalidasi
tabel cache, termasuk ketika mode development adalah `auto`. Compose hardened
menjalankan job eksplisit sebelum backend.

Untuk Docker development, mulai layanan `postgres` dengan profile `pgvector`.
Sediakan URL container lokal di `.env` dan variabel operator secara terpisah,
jalankan perintah di container backend sekali pakai, lalu mulai backend/frontend.
Tool host memakai port publik (default 5433); container memakai port internal 5432.
Volume lama mempertahankan kredensial aslinya.

## Instalasi lama

Baris `semantix.cache_entries` lama dipertahankan dan tidak diadopsi otomatis.
Binding resmi `semantix_cache.workbench_cache_entries` mulai kosong; request akan
menghasilkan ulang jawaban dan mengisinya. Layout, revisi, dan kepemilikan kapasitas
berbeda sehingga penyalinan/penggantian nama tabel tidak didukung. Pertahankan backup
dan tabel lama untuk rollback; periksa kesegaran jawaban sebelum memakai binary lama.
Tabel tidak ada, tanpa penanda, atau checksum tidak cocok menggagalkan startup secara aman.

## Perilaku dan verifikasi

PgVectorStore memiliki isolasi namespace dan identitas/dimensi embedding, TTL, LRU,
kapasitas terbatas, serta konfirmasi atomik revisi/expiry. Inspector membaca entri yang
sama; counter hit/miss request adalah telemetri terpisah. Pencarian tetap exact cosine
pgvector tanpa algoritma similarity baru.

Periksa `/ready`, ulangi prompt di Monitor, lalu inspect/delete/clear entri aktif.
Perubahan identitas/dimensi embedding menyembunyikan vektor lama yang tidak kompatibel.
Gunakan database sekali pakai untuk `PGVECTOR_TEST_DATABASE_URL`; job CI wajib gagal
jika test PostgreSQL dilewati tanpa sengaja. Lihat [embedded storage](../../../embedded-storage.md)
untuk kontrak schema/resource dan [deployment](../operations/deployment.md)
untuk batas production dua replika yang didukung.
