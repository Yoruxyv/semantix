# Getting Started

Panduan ini membahas **backend/dashboard opsional**. Untuk library Python embedded
utama, gunakan [contoh package](../../../../packages/cache/README.md#run-from-source);
pengguna embedded tidak memerlukan Docker atau server resmi.

Semantix memiliki jalur deployment development dan hardened yang terpisah. Stack development ditujukan untuk satu developer tepercaya pada mesin lokal. Stack hardened merupakan titik awal untuk deployment bersama atau publik dan wajib berada di belakang TLS.

## Prasyarat

Instal Git, Docker Desktop atau Docker CLI/Engine 23+ lokal (API 1.42+) dengan Compose 2.20+, dan Python 3.11–3.14 untuk launcher development yang direkomendasikan. Launcher hanya memakai standard library; dependency backend tetap di Docker. [uv](https://docs.astral.sh/uv/guides/scripts/) juga dapat menjalankannya tanpa environment backend di host. Jalur Docker langsung dan deployment hardened tidak memerlukan Python di host. Hosted provider memerlukan kredensial kapabilitas yang dipilih.

## Development lokal

Clone repository dan buat file environment backend:

```bash
git clone https://github.com/Yoruxyv/semantix.git
cd semantix
cp apps/server/.env.example apps/server/.env
```

Windows PowerShell:

```powershell
git clone https://github.com/Yoruxyv/semantix.git
Set-Location semantix
Copy-Item apps\server\.env.example apps\server\.env
```

Untuk konfigurasi mock tanpa kredensial, atur:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384
CACHE_BACKEND=memory
EVALUATION_DATASET_STORAGE=session
EVALUATION_RUN_HISTORY_STORAGE=disabled
COORDINATION_BACKEND=memory
AUTH_MODE=disabled
```

Untuk inference hosted atau lokal, pilih embedding dan generation provider dalam
panduan [Providers](providers.md) sebelum menjalankan stack. Respons mock
hanyalah keluaran contoh, bukan jawaban production. Build awal dapat mengunduh image dan dependency; provider mock tidak memanggil API AI.

### Direkomendasikan: launcher development

Setelah menyiapkan `apps/server/.env`, jalankan dari root repository:

```bash
python scripts/dev.py up
```

Atau melalui uv, tanpa root project atau instalasi dependency backend pada host:

```bash
uv run --no-project scripts/dev.py up
```

Pilih interpreter terpasang secara eksplisit dengan
`uv run --no-project --python 3.14 scripts/dev.py up`. Bentuk yang sama berlaku
di PowerShell dan shell Linux/macOS. Gunakan context Docker Engine/Desktop lokal;
hapus override `DOCKER_HOST` dan pilih context lokal melalui tool Docker.

Launcher membaca environment backend hasil resolusi Compose dan memvalidasi
settings. Service dipilih berdasarkan cache **dan** kebutuhan PostgreSQL fitur
lain. Konfigurasi memory murni tidak menjalankan database. Launcher membangun
image development, menjalankan setup terpisah hanya untuk volume yang dibuat dan
diverifikasi pada pemanggilan itu, memvalidasi storage yang sudah ada, menunggu
`/ready` backend, lalu memulai frontend. Origin dashboard yang dicetak harus
cocok dengan `ALLOWED_ORIGINS`. Jangan mengubah konfigurasi saat startup berjalan.

Lengkapi konfigurasi PostgreSQL/Redis di bawah sebelum memakai storage persisten.
Volume yang sudah ada dan URL eksternal hanya divalidasi. Launcher tidak
menghapus data, merotasi password, mengadopsi schema tanpa penanda, atau membuat
binding yang hilang dalam storage yang sudah ada. Tidak ada fallback atau replay
setup gagal secara otomatis.

### Lanjutan: Docker Compose langsung

Konfigurasi memory di atas hanya memerlukan Git dan Docker:

```bash
docker compose -f docker-compose.dev.yml up --build -d --wait --wait-timeout 120 backend frontend
```

Compose 2.20+ juga mendukung
`docker compose up --build -d --wait --wait-timeout 120 backend frontend`.
Perintah tersebut tidak memilih profile dari `CACHE_BACKEND` atau melakukan
provisioning. Storage persisten memerlukan profile yang sesuai dan
[setup operator eksplisit](#development-dengan-storage-persisten) sebelum aplikasi dimulai.

Semua port development yang dipublikasikan secara default terikat ke `127.0.0.1`:

| Service         | Alamat                       |
| --------------- | ---------------------------- |
| Frontend        | http://localhost:4173        |
| Backend         | http://localhost:8000        |
| Dokumentasi API | http://localhost:8000/docs   |
| Liveness        | http://localhost:8000/health |
| Readiness       | http://localhost:8000/ready  |

Buka frontend lalu jalankan kueri di Monitor. [Tur produk](../README.ID.md#tur-produk)
menampilkan Cache Inspector, Evaluations, dan Observability saat ini. Untuk
request dari aplikasi Python, lanjutkan ke [Python SDK](../../../../packages/client/README.md).

Image frontend development menginstal dependency Node dan menjalankan development server Vite dengan HMR; image tersebut tidak melakukan kompilasi asset frontend production. `VITE_API_BASE_URL` diberikan ke development server tersebut saat runtime. Image frontend hardened melakukan production build yang dijelaskan nanti dalam panduan ini. Untuk memastikan pembaruan bind-mount tetap andal ketika native notifications tidak tersedia, stack development melakukan polling terhadap perubahan source frontend dan backend setiap satu detik. Vite mengabaikan output coverage yang dihasilkan, dan Uvicorn hanya melakukan reload untuk perubahan di bawah `apps/server/app`. Stack hardened tidak terpengaruh.

Perubahan biasanya terlihat dalam waktu sekitar satu detik. Jika tidak, pastikan Docker Desktop dapat membagikan drive repository, lalu buat ulang service yang terdampak. Periksa penggunaan saat idle dengan `docker stats --no-stream`. Jangan mengekspos stack development ke jaringan yang tidak tepercaya.

### Development dengan storage persisten

Dashboard mendukung `memory`, `pgvector` dan `redis`. SQLite dan MySQL hanya
tersedia bagi package embedded, bukan backend dashboard. PostgreSQL juga
diperlukan oleh `EVALUATION_DATASET_STORAGE=postgres`,
`EVALUATION_RUN_HISTORY_STORAGE=postgres` atau `COORDINATION_BACKEND=postgres`,
termasuk jika cache memakai memory/Redis. Penuhi batas retensi dan kapasitas
fitur tersebut di `apps/server/.env`.

#### Kredensial runtime PostgreSQL

Buat password runtime sendiri; password ini **bukan** dari provider AI:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Jaga keluaran tetap privat. Ganti `replace-runtime-password` di file
`apps/server/.env` yang tidak dilacak Git:

```env
CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix_runtime:replace-runtime-password@postgres:5432/semantix
DATABASE_MIGRATION_MODE=external
```

`semantix_runtime` adalah akun aplikasi terbatas. Pada volume yang baru dibuat
launcher, akun itu dibuat dengan password yang dikonfigurasi, kemudian migration
resmi dijalankan melalui wewenang bootstrap terpisah. Backend normal tidak menerima
wewenang migration. Akun bootstrap Compose lokal adalah `semantix`; jangan
gunakan akun tersebut sebagai user runtime pada `DATABASE_URL`.

Password acak URL-safe di atas tidak memerlukan encoding tambahan. Jika password
yang sudah ada mengandung `@`, `:`, `/`, `#`, `%` atau karakter URL khusus lain,
encode komponen username/password dengan `urllib.parse.quote(value, safe="")`,
bukan seluruh URL. Jangan commit kredensial, menempelkannya pada issue, menulisnya
ke logs, atau memasukkannya ke `VITE_*`/frontend. Jauhkan URL operator dan
kredensial initialization dari `.env` backend.

Password untuk role yang sudah ada harus cocok dengan database. Mengubah `.env`
tidak merotasinya. URL hilang/placeholder ditolak saat validasi konfigurasi;
kredensial salah atau schema parsial ditolak saat validasi storage. Tinjau akun
aktual dan backup data alih-alih menghapus volume atau mengulang setup berhak
tinggi tanpa pemeriksaan. Database yang sudah dibuat namun setup-nya belum lengkap
sengaja dibiarkan untuk recovery eksplisit.

Untuk jalur Compose langsung, ikuti
[langkah PostgreSQL](../README.ID.md#opsional-persistensi-postgresql)
yang menjelaskan akun terpisah, setup eksplisit, data legacy, dan startup aplikasi.

#### Konfigurasi Redis

Untuk service standalone Redis lokal milik project:

```env
CACHE_BACKEND=redis
REDIS_URL=redis://redis:6379/0
```

Launcher hanya menginisialisasi binding pada volume Redis baru yang dimilikinya.
Binding yang sudah ada divalidasi tanpa mengubah descriptor atau data. Profile
lokal tetap memakai AOF dan `noeviction`. URL lain memerlukan setup eksplisit
terlebih dahulu dengan ACL/TLS yang sesuai; `rediss` tidak diubah menjadi
plaintext. Lihat [setup operator Redis](../../../guides/platform-storage.md#redis-setup-permissions-and-recovery).

#### Shutdown dan recovery

```bash
docker compose -f docker-compose.dev.yml --profile pgvector --profile redis down
```

Named volume dipertahankan. Jangan menambahkan `--volumes` kecuali memang hendak
menghapus data. Startup rutin menggunakan perintah launcher yang sama.

Setup dan readiness memiliki batas waktu. Setup yang gagal/terputus dapat
meninggalkan storage parsial. Menghentikan client tidak membuktikan DDL server
berhenti atau rollback; tinjau hasil yang belum pasti sebelum recovery operator.
Tidak ada perbaikan atau retry otomatis. Lock
Docker per project menyerialkan pemanggilan launcher yang bekerja sama.
Setelah interupsi paksa, pastikan tidak ada launcher/job setup yang masih aktif.
Periksa nama, state dan label kepemilikan saja, bukan seluruh environment:

```bash
docker ps -a --filter "name=<project>-dev-"
docker inspect --format '{{json .Config.Labels}}' <container-id>
docker inspect --format '{{.State.Running}}' <container-id>
```

Verifikasi label project/checkout Compose pada job setup dan label
`com.semantix.dev-startup.project` / `.checkout` pada lock yang berhenti.
Token pemilik `com.semantix.dev-startup` keduanya harus sama. Setelah itu,
hentikan/hapus hanya job setup yang ditinggalkan dan container lock
berhenti berdasarkan ID. Jangan hapus volume. Jika job belum dapat dipastikan
berhenti, pertahankan lock dan selesaikan masalah Docker/kepemilikan dahulu.
Tinjau state database parsial dengan wewenang operator secara terpisah;
membuat nama project baru bukan recovery data lama.

Volume lokal yang sudah ada memerlukan mount service development yang cocok
atau penanda kepemilikan launcher sebelumnya untuk checkout ini. Volume sebelum
launcher yang tersisa setelah `compose down`, atau checkout yang dipindahkan,
mungkin tidak memiliki bukti tersebut. Tinjau dengan konfigurasi development
aslinya dan alur setup lanjutan; launcher tidak mengadopsi, memberi label ulang,
atau mereset volume yang tidak dikenal.

`BACKEND_PORT` juga mengatur URL API Vite. Jika `FRONTEND_PORT` diubah,
tambahkan origin browser loopback tersebut pada `ALLOWED_ORIGINS`. Pemeriksaan
startup tidak menyertifikasi provider hosted, TLS production, atau mencegah admin
Docker mengubah resource secara bersamaan. Deployment hardened tetap terpisah.

### Toolchain lokal

Backend:

```bash
cd apps/server
uv sync --locked --extra dev
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Aktivasi Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instal [uv](https://docs.astral.sh/uv/getting-started/installation/) sebelum menggunakan workflow backend lokal. Lock yang disertakan dalam repository menjaga resolusi dependency lokal, CI, dan container tetap selaras.

Frontend:

```bash
cd apps/web
npm ci
npm run dev
```

Atur `VITE_API_BASE_URL=http://localhost:8000` di `apps/web/.env` untuk development Vite lokal.

## Deployment hardened

Stack hardened menggunakan:

* frontend terkompilasi yang disajikan oleh image Nginx non-root;
* dua replika backend (`backend-a` dan `backend-b`) di belakang gateway, tanpa port backend yang dipublikasikan;
* database pada jaringan Docker internal tanpa host port;
* autentikasi token, peran, dan cakupan namespace;
* rate limiting yang memperhitungkan proxy;
* batas ukuran request reverse-proxy dan ASGI;
* peran database untuk migrasi dan runtime yang terpisah;
* liveness check yang tidak dikenai rate limit dan readiness check yang memperhitungkan dependency.

Buat file environment deployment:

```bash
cp .env.production.example .env.production
```

Buat password database dan access token yang kuat, ganti setiap placeholder, lalu jalankan:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Frontend gateway terikat ke `127.0.0.1:8080` secara default. Hentikan TLS pada reverse proxy host dan teruskan traffic ke alamat loopback tersebut. Jangan publikasikan port backend atau database.

Stack hardened menggunakan Compose project `semantix-prod` yang terpisah dan tidak menggunakan kembali volume PostgreSQL development.

Lihat [Hardened deployment](../operations/deployment.md) untuk hashing token, konfigurasi peran, proxy trust, privilege database, perilaku readiness, dan validasi.

## Health checks

`GET /health` adalah process liveness check yang ringan dan tidak dikenai rate limit.

`GET /ready` memeriksa statistik cache aktif, katalog dataset evaluasi persisten
yang dikonfigurasi, dan koordinasi threshold PostgreSQL bila diaktifkan. Endpoint
ini mengembalikan `503` untuk kegagalan storage yang ditangani. Endpoint ini
tidak memeriksa langsung repository riwayat run opsional atau hosted AI provider.

## Shutdown dan volume

Development:

```bash
docker compose -f docker-compose.dev.yml down
```

Deployment hardened:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

Named volume tetap dipertahankan. Menambahkan `--volumes` akan menghapus data PostgreSQL secara permanen.

## Pemeriksaan kualitas

Backend:

```bash
cd apps/server
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

Frontend:

```bash
cd apps/web
npm ci
npm run lint
npm run imports:check
npm run test
npm run build
```

Validasi container:

```bash
docker compose -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.dev.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml build
```
