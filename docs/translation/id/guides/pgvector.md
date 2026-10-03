# Cache pgvector persisten

Semantix menggunakan cache in-memory secara default. Backend pgvector opsional mengimplementasikan cache port yang sama dan mempertahankan entry, namespace counter, hit count, dan access timestamp di seluruh restart backend.

## Konfigurasi

Atur nilai berikut di `apps/server/.env`:

```env
CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
DATABASE_POOL_MIN_SIZE=1
DATABASE_POOL_MAX_SIZE=5
DATABASE_CONNECT_TIMEOUT_SECONDS=10
DATABASE_COMMAND_TIMEOUT_SECONDS=30
```

`DATABASE_URL` hanya diperlukan ketika `CACHE_BACKEND=pgvector`. Backend memory tidak terhubung ke PostgreSQL, bahkan ketika database URL tersedia. Ukuran pool minimum tidak boleh melebihi maksimum. Connection timeout membatasi pembentukan koneksi pool; command timeout secara independen membatasi SQL statement setelah koneksi tersedia. Tingkatkan command timeout untuk migrasi atau operasi cache yang lama berdasarkan hasil pengukuran tanpa melemahkan deteksi kegagalan koneksi.

Docker profile yang disediakan menggunakan `semantix` sebagai database PostgreSQL sekaligus application schema. Nama database yang berbeda dapat digunakan dalam `DATABASE_URL`; application table tetap berada dalam schema `semantix`.

## Setup Docker

Build dan jalankan PostgreSQL, backend, dan frontend secara bersamaan:

```powershell
docker compose --profile pgvector up --build -d
```

Compose menunggu health check PostgreSQL sebelum menjalankan backend. Backend kemudian menerapkan migrasi yang tertunda sebelum FastAPI menjadi ready.

Profile mempublikasikan PostgreSQL pada host port `5433` secara default dan meneruskannya ke port `5432` di dalam container:

```text
localhost:5433 -> postgres:5432
```

Hal ini menghindari konflik dengan instalasi PostgreSQL yang sudah menggunakan host port standar. Override host port jika diperlukan:

```powershell
$env:POSTGRES_PORT = "55432"
docker compose --profile pgvector up -d --wait postgres
```

Backend yang berjalan di dalam container harus tetap menggunakan alamat service internal:

```env
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
```

Tool yang berjalan pada host, termasuk pgAdmin dan integration test, terhubung ke:

```text
Host: localhost
Port: 5433
Database: semantix
Username: semantix
Password: semantix
```

Ketika backend sendiri berjalan di luar Docker, gunakan `localhost` dan host port yang dipublikasikan dalam `DATABASE_URL`. Mengubah host port tidak mengubah container port atau URL backend yang berada di dalam container.

## Verifikasi database

Setelah menjalankan pgvector profile, pastikan semua service dalam kondisi sehat:

```powershell
docker compose --profile pgvector ps
```

Pastikan PostgreSQL menerima koneksi dan migrasi saat startup telah membuat schema, extension, dan table:

```powershell
docker compose exec postgres psql -U semantix -d semantix -c `
  "SELECT extname FROM pg_extension WHERE extname = 'vector';"

docker compose exec postgres psql -U semantix -d semantix -c `
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'semantix' ORDER BY table_name;"
```

Kemudian kirim dua prompt yang secara semantik serupa melalui aplikasi. Request pertama seharusnya mengisi PostgreSQL dan request kedua yang cukup serupa seharusnya memenuhi syarat untuk cache hit. Restart backend dan pastikan cache entry tetap tersedia:

```powershell
docker compose restart backend
```

pgAdmin bersifat opsional dan hanya diperlukan untuk inspeksi visual. Docker volume baru diinisialisasi secara otomatis menggunakan credential Compose. Volume yang sudah ada mempertahankan credential aslinya meskipun nilai Compose kemudian berubah.

## Migrasi otomatis dan perilaku startup

Backend memperoleh PostgreSQL advisory lock dan menjalankan cache migration yang tertunda selama startup FastAPI. Bootstrap migrasi dan versi pertama:

1. mengaktifkan `vector` extension;
2. membuat schema `semantix` dan migration-history table;
3. membuat cache entry dan namespace counter;
4. membuat index untuk filtering berdasarkan scope, expiry, dan recency.

Oleh karena itu, database role yang dikonfigurasi memerlukan permission untuk membuat pgvector extension dan schema `semantix` pada startup pertama. Migrasi selesai sebelum application lifespan menjadi ready. Jika `DATABASE_URL` tidak tersedia, tidak valid, atau tidak dapat dijangkau, atau jika migrasi gagal, backend tidak akan berjalan.

Versi yang telah diterapkan dicatat dalam `semantix.schema_migrations`. SQL migrasi disimpan bersama cache feature di `app/cache/infrastructure/migrations`.

## Perilaku storage

Backend persisten menyimpan:

* namespace dan cache key;
* prompt dan response;
* embedding dan dimensions-nya secara persis;
* identitas embedding provider/model;
* timestamp pembuatan dan expiration;
* hit count dan timestamp akses terakhir;
* hit dan miss counter per namespace.

Cosine nearest-neighbor lookup menggunakan operator `<=>` milik pgvector. Entry yang telah expired dihapus sebelum operasi cache. Insertion memberlakukan batas maksimum global yang dikonfigurasi untuk embedding space aktif dengan melakukan eviction terhadap entry yang paling lama tidak digunakan. Namespace filtering, targeted clearing, individual deletion, inspector sorting, dan pagination menggunakan public cache interface yang sama seperti memory storage.

## Kompatibilitas embedding

Row dipartisi berdasarkan embedding provider, model, dan dimension. Mengubah salah satu pengaturan tersebut akan memulai logical embedding space baru, sehingga vector yang tidak kompatibel tidak pernah dibandingkan. Row lama tetap berada di PostgreSQL tetapi tidak terlihat oleh space yang baru dikonfigurasi. Cache API hanya menghapus embedding space yang aktif.

Setelah memastikan bahwa model lama tidak akan digunakan kembali, row dan counter-nya dapat dihapus secara manual dengan mencocokkan `embedding_space` pada kedua table `semantix`.

## Integration test

Integration test tidak pernah menggunakan `DATABASE_URL` secara implisit. Arahkan dedicated test variable ke database pgvector yang dapat dibuang:

```powershell
$env:PGVECTOR_TEST_DATABASE_URL = `
  "postgresql://semantix:semantix@localhost:5433/semantix"

cd apps/server
.\.venv\Scripts\python.exe -m pytest -m pgvector
```

Test menggunakan identity embedding-space yang unik dan menghapus row serta counter-nya setelah selesai. Tanpa `PGVECTOR_TEST_DATABASE_URL`, parameter pgvector akan dilewati sementara memory suite lengkap tetap dijalankan.

## Batasan saat ini

* Nearest-neighbor search bersifat exact. Approximate index pgvector memerlukan fixed-dimensional indexed expression; Semantix secara sengaja mengizinkan model embedding dan dimensions yang berbeda dalam satu table.
* Eksekusi migrasi berlangsung saat application startup; tidak terdapat migration CLI terpisah.
* Endpoint cache-management tidak menggunakan autentikasi dan tetap ditujukan untuk development lokal.
* Credential Docker merupakan default untuk development. Ganti credential tersebut di luar mesin lokal dan jangan pernah commit credential production.
