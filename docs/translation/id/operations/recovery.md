# Operasi dan pemulihan

Runbook ini mencakup deployment Compose dua replika yang diperkeras. Uji setiap prosedur pada project terisolasi dan volume disposable sebelum menggunakannya untuk environment bersama.

## Kepemilikan dan kebijakan data

Semantix memperlakukan entri cache pgvector dan namespace counters sebagai data turunan yang disposable. Respons provider tetap menjadi sumber kebenaran. Menghapus cache tidak menghapus data di sisi provider, konfigurasi authentication, atau konfigurasi aplikasi.

Dataset evaluasi tersimpan berbeda: dataset dapat berisi prompt dan catatan
sensitif dari operator yang tidak tersedia di tempat lain. Saat
`EVALUATION_DATASET_STORAGE=postgres`, pemilik deployment harus menentukan apakah
data harus dapat dipulihkan atau boleh dibuang, lalu menerapkan kebijakan tersebut
pada backup, akses, retensi, dan penghapusan.

Riwayat run evaluasi yang persisten juga memerlukan keputusan retensi eksplisit.
Data ini hanya berupa agregat, tetapi dapat berisi identitas dataset, kategori,
timestamp, fingerprint konfigurasi, metadata kegagalan terminal, dan hasil agregat.
Sertakan dalam kebijakan backup, retensi, akses, dan penghapusan saat
`EVALUATION_RUN_HISTORY_STORAGE=postgres`.

Cache yang dingin memiliki konsekuensi operasional:

* request pertama yang memenuhi syarat untuk setiap kelompok semantik akan memanggil provider;
* latency dan biaya provider meningkat selama cache melakukan warm-up;
* entri cache, hit counters, dan miss counters dimulai dari nol;
* data historis cache inspector hilang.

Lakukan backup jika mempertahankan warm-cache state, dataset evaluasi tersimpan,
atau riwayat run agregat sepadan dengan biaya keamanan dan pemulihan. Backup dapat
mempertahankan konten dataset setelah kedaluwarsa atau dihapus dari aplikasi,
sehingga retensi backup dan penghapusan aman menjadi tanggung jawab operator yang
terpisah. Operator yang melakukan deployment bertanggung jawab atas backup, rotasi,
rollback, dan verifikasi. Pemilik provider harus diberi tahu sebelum destructive
rebuild yang dapat meningkatkan traffic atau biaya provider.

## Aturan keselamatan

* Jangan pernah melakukan praktik pada volume production.
* Pertahankan credential saat ini dan credential pengganti sampai verifikasi berhasil.
* Muat credential dari secret manager ke environment variables; jangan menempatkan password dalam tracked files, shell history, command arguments, atau logs.
* Hentikan query traffic sebelum melakukan rotasi database roles.
* Jangan pernah mengedit `semantix.schema_migrations` secara manual.
* Lakukan restore ke fresh volume, bukan dengan menimpa satu-satunya salinan yang tersedia.

Command di bawah mengasumsikan `.env.production` dan `docker-compose.prod.yml`.

## Rotasi password migration dan runtime

Mengubah `.env.production` saja tidak merotasi PostgreSQL role yang sudah ada. Docker initialization directory hanya berjalan ketika data directory masih baru. Gunakan migration credential saat ini untuk mengubah kedua role secara transaksional, kemudian recreate services dengan credential pengganti.

### 1. Siapkan secrets

Muat value berikut dari secret manager:

* `POSTGRES_DB`
* `POSTGRES_MIGRATION_USER`
* `POSTGRES_RUNTIME_USER`
* `CURRENT_POSTGRES_MIGRATION_PASSWORD`
* `NEW_POSTGRES_MIGRATION_PASSWORD`
* `NEW_POSTGRES_RUNTIME_PASSWORD`

Linux atau macOS:

```bash
export PGPASSWORD="$CURRENT_POSTGRES_MIGRATION_PASSWORD"
export SEMANTIX_MIGRATION_USER="$POSTGRES_MIGRATION_USER"
export SEMANTIX_MIGRATION_PASSWORD="$NEW_POSTGRES_MIGRATION_PASSWORD"
export SEMANTIX_RUNTIME_USER="$POSTGRES_RUNTIME_USER"
export SEMANTIX_RUNTIME_PASSWORD="$NEW_POSTGRES_RUNTIME_PASSWORD"
```

Windows PowerShell:

```powershell
$env:PGPASSWORD = $env:CURRENT_POSTGRES_MIGRATION_PASSWORD
$env:SEMANTIX_MIGRATION_USER = $env:POSTGRES_MIGRATION_USER
$env:SEMANTIX_MIGRATION_PASSWORD = $env:NEW_POSTGRES_MIGRATION_PASSWORD
$env:SEMANTIX_RUNTIME_USER = $env:POSTGRES_RUNTIME_USER
$env:SEMANTIX_RUNTIME_PASSWORD = $env:NEW_POSTGRES_RUNTIME_PASSWORD
```

### 2. Hentikan traffic dan rotasi kedua role

Hentikan gateway dan backend, tetapi biarkan PostgreSQL tetap berjalan:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop frontend backend-a backend-b
```

Linux atau macOS:

```bash
postgres_container=$(docker compose --env-file .env.production -f docker-compose.prod.yml ps -q postgres)
test -n "$postgres_container"
docker cp ops/postgres/rotate-role-passwords.sql "$postgres_container:/tmp/rotate-role-passwords.sql"
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e PGPASSWORD -e SEMANTIX_MIGRATION_USER -e SEMANTIX_MIGRATION_PASSWORD -e SEMANTIX_RUNTIME_USER -e SEMANTIX_RUNTIME_PASSWORD postgres psql --host 127.0.0.1 --username "$POSTGRES_MIGRATION_USER" --dbname "$POSTGRES_DB" --file /tmp/rotate-role-passwords.sql
```

Windows PowerShell:

```powershell
$PostgresContainer = docker compose --env-file .env.production -f docker-compose.prod.yml ps -q postgres
if (-not $PostgresContainer) { throw "The production PostgreSQL container is not running." }
docker cp ops/postgres/rotate-role-passwords.sql "${PostgresContainer}:/tmp/rotate-role-passwords.sql"
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e PGPASSWORD -e SEMANTIX_MIGRATION_USER -e SEMANTIX_MIGRATION_PASSWORD -e SEMANTIX_RUNTIME_USER -e SEMANTIX_RUNTIME_PASSWORD postgres psql --host 127.0.0.1 --username $env:POSTGRES_MIGRATION_USER --dbname $env:POSTGRES_DB --file /tmp/rotate-role-passwords.sql
```

SQL akan gagal sebelum mengubah salah satu role apabila role tidak tersedia atau salah satu password baru kosong. Kedua perubahan password akan di-commit secara bersamaan.

### 3. Perbarui konfigurasi dan recreate services

Perbarui kedua password pada deployment secret store atau `.env.production`, kemudian recreate services:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate postgres
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate migrate backend-a backend-b frontend
```

Migration job harus berhasil exit sebelum backend menjadi healthy. Setelah itu, hapus temporary SQL file dan bersihkan temporary secret variables dari operator shell.

### 4. Verifikasi

Periksa service state dan readiness:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl --fail http://127.0.0.1:8080/ready
```

Kirim unique prompt melalui Monitor atau `POST /api/v1/query`, kemudian kirim prompt yang sama sekali lagi. Request pertama harus berupa miss dan request kedua harus berupa hit. Pastikan cache inspector dapat membaca entri baru tersebut.

### Rollback rotasi

Jika role rotation berhasil di-commit tetapi recreated stack gagal:

1. Pertahankan traffic dalam keadaan berhenti.
2. Connect menggunakan `NEW_POSTGRES_MIGRATION_PASSWORD`.
3. Jalankan SQL file yang sama dengan previous migration dan runtime passwords sebagai target values.
4. Restore previous deployment secret version.
5. Recreate PostgreSQL, migrate, backend, dan frontend lagi.
6. Ulangi readiness dan cache-round-trip verification.

Jangan hanya me-restore environment file setelah database roles berubah; hal tersebut akan menciptakan credential mismatch yang sama dalam arah sebaliknya.

## Backup warm cache

Buat custom-format dump tanpa ownership atau access-control statements:

```bash
mkdir -p backups
postgres_container=$(docker compose --env-file .env.production -f docker-compose.prod.yml ps -q postgres)
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e PGPASSWORD postgres pg_dump --host 127.0.0.1 --username "$POSTGRES_MIGRATION_USER" --dbname "$POSTGRES_DB" --format custom --no-owner --no-acl --file /tmp/semantix.dump
docker cp "$postgres_container:/tmp/semantix.dump" backups/semantix.dump
```

Dalam PowerShell, buat directory dengan `New-Item -ItemType Directory -Force
backups` dan gunakan `"${PostgresContainer}:/tmp/semantix.dump"` sebagai `docker cp`
source.

Catat application commit, migration list, embedding provider/model,
embedding dimensions, cache schema/table prefix, pengaturan storage/retensi dataset
evaluasi, pengaturan storage/retensi/kapasitas riwayat run, database name, dan dump
checksum di samping backup. Perlakukan dump sebagai data sensitif karena dapat
berisi respons provider yang di-cache serta prompt dan catatan dataset tersimpan.
Backup yang dibuat untuk satu embedding space tidak otomatis berguna setelah
embedding model atau dimensions diubah.

## Restore backup

Lakukan restore hanya ke empty, isolated volume:

1. Hentikan stack.
2. Pindahkan volume lama atau buat Compose project terpisah.
3. Jalankan hanya PostgreSQL agar initialization membuat kedua database roles.
4. Copy `semantix.dump` ke PostgreSQL container baru.
5. Restore sebagai migration role:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e PGPASSWORD postgres pg_restore --host 127.0.0.1 --username "$POSTGRES_MIGRATION_USER" --dbname "$POSTGRES_DB" --exit-on-error --no-owner --no-acl /tmp/semantix.dump
docker compose --env-file .env.production -f docker-compose.prod.yml up --force-recreate migrate
```

Migration job memverifikasi checksum migration server dan package serta memulihkan
runtime grants. Jalankan pemeriksaan read-only berikut sebagai role migration/operator;
role runtime tidak memiliki akses umum ke ledger migration server. SQL ini
menggunakan default server `CACHE_PGVECTOR_SCHEMA=semantix_cache` dan
`CACHE_PGVECTOR_TABLE_PREFIX=workbench_`. Jika dikustomisasi, ganti schema/prefix
dengan nilai binding yang dipulihkan; gunakan nilai yang sama untuk migration job dan runtime.

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
SELECT version, checksum FROM semantix.schema_migrations ORDER BY version;
SELECT version, checksum
FROM semantix_cache.workbench_schema_migrations ORDER BY version;
SELECT embedding_space, embedding_dimensions, revision, access_order
FROM semantix_cache.workbench_binding_state
ORDER BY embedding_space, embedding_dimensions;
SELECT COUNT(*) FROM semantix_cache.workbench_cache_entries;
SELECT COUNT(*) FROM semantix.cache_namespace_counters;
```

`workbench_cache_entries` menyimpan entri cache resmi yang aktif.
`workbench_binding_state` mencatat identitas/dimensi embedding space, revision,
dan access order; bandingkan space yang dipulihkan dengan backup dan konfigurasi
runtime. Binding yang belum digunakan dapat tidak memiliki baris state. Ledger
package `workbench_schema_migrations` terpisah dari `semantix.schema_migrations`.
Job dan startup cache biasa memeriksa ownership marker ketiga table resmi
(`semantix-cache:pgvector:v1`) serta version/checksum yang diharapkan package;
sekadar menampilkan checksum atau menemukan baris tidak memvalidasi integritas.

Table legacy `semantix.cache_entries` yang dipertahankan bukan cache aktif dan tidak
dapat memverifikasi restore ini. `semantix.cache_namespace_counters` adalah telemetry
request server, bukan sumber otoritatif untuk entri, eligibility, atau revision.
Pertahankan table legacy. Job memberikan `USAGE` schema, `SELECT` ledger package,
serta `SELECT, INSERT, UPDATE, DELETE` pada table entri/state resmi dan telemetry
kepada runtime; job tidak memberikan wewenang migration kepada runtime.

Jika `EVALUATION_DATASET_STORAGE=postgres`, verifikasi juga katalog dataset:

```sql
SELECT COUNT(*) FROM semantix.evaluation_datasets;
SELECT COUNT(*) FROM semantix.evaluation_dataset_cases;
```

Jika `EVALUATION_RUN_HISTORY_STORAGE=postgres`, verifikasi juga riwayat run yang disimpan:

```sql
SELECT COUNT(*) FROM semantix.evaluation_runs;
SELECT COUNT(*) FROM semantix.evaluation_run_thresholds;
```

Bandingkan jumlah baris dengan backup dan ekspektasi retensi. Baris cache dapat
kosong atau kedaluwarsa; jumlah bukan nol saja tidak membuktikan entri dapat
digunakan atau izin runtime benar. Kemudian jalankan backend dan frontend, periksa
`/ready`, dan lakukan cache round trip yang diotorisasi untuk namespace (prompt
unik: miss, pengulangan: hit, entri terbaca di Cache Inspector). Saat mempertahankan
warm-cache state, verifikasi juga bahwa entri hasil restore yang belum kedaluwarsa
dapat diinspeksi dan digunakan kembali dengan konfigurasi embedding semula.
Verifikasi request list/detail dataset yang diotorisasi untuk namespace dan pembacaan
riwayat run jika persistensinya aktif. Baris dataset kedaluwarsa dari backup lama
tetap disembunyikan dan dihapus secara oportunistis. Pertahankan volume lama dan
backup sampai verifikasi selesai.

## Buang dan rebuild cache

Ini adalah recovery path default hanya jika cache tidak perlu dipertahankan dan
semua data evaluasi berbasis PostgreSQL yang penting, termasuk dataset tersimpan
dan riwayat run, dinonaktifkan, telah di-backup secara terpisah, atau memang boleh
dibuang. Periksa kembali volume label sebelum penghapusan:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
docker volume inspect semantix-prod_pgvector_data
docker volume rm semantix-prod_pgvector_data
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Jangan mengganti dengan wildcard atau menghapus semua Docker volume. Startup
berikutnya membuat roles, menjalankan migrations, dan memulai dengan cache tables
dan counters yang kosong. Penghapusan volume juga menghapus dataset evaluasi
tersimpan dan riwayat run agregat secara permanen. Rencanakan cold-cache latency
dan penggunaan provider selama entri melakukan warm-up.

## Rollback migration

Setiap migration dan version record-nya diterapkan dalam satu transaction. Migration yang gagal akan di-rollback tanpa mencatat version tersebut. Applied migrations bersifat forward-only dan dilindungi checksum.

Untuk application regression tanpa destructive schema changes, redeploy previous application image dan biarkan database tetap utuh. Untuk schema regression yang tidak kompatibel:

* buang dan rebuild volume hanya ketika cache, dataset tersimpan, dan riwayat run
  boleh dibuang; atau
* restore pre-deployment dump ke fresh volume ketika data harus dipertahankan.

Jangan pernah menulis ulang applied migration, menghapus checksum row, atau membuat down-migration secara improvisasi selama incident.

## Checklist incident

1. Hentikan frontend dan backend traffic.
2. Catat waktu, deployed commit, Compose state, readiness response, dan sanitized logs.
3. Tentukan apakah incident merupakan credential mismatch, migration failure, storage failure, atau application regression.
4. Pertahankan volume atau buat dump ketika evidence atau warm-cache state penting.
5. Gunakan rotation rollback, application rollback, fresh restore, atau destructive rebuild seperti yang didokumentasikan di atas.
6. Verifikasi role connectivity, migration checksums, `/ready`, dan cache round trip.
7. Buka kembali traffic dan monitor provider calls, latency, cache misses, dan errors selama warm-up.
8. Rotasi credential apa pun yang mungkin telah terekspos dan dokumentasikan incident owner, keputusan, serta pekerjaan tindak lanjut.
