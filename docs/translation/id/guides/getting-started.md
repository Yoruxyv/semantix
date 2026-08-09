# Getting Started

Semantix memiliki jalur deployment development dan hardened yang terpisah. Stack development ditujukan untuk satu developer tepercaya pada mesin lokal. Stack hardened merupakan titik awal untuk deployment bersama atau publik dan wajib berada di belakang TLS.

## Prasyarat

Instal Git dan Docker Desktop atau Docker Engine dengan Compose. Hosted provider juga memerlukan kredensial untuk kapabilitas provider yang dipilih.

## Development lokal

Clone repository dan buat file environment backend:

```bash
git clone https://github.com/Yoruxyv/semantix.git
cd semantix
cp backend/.env.example backend/.env
```

Windows PowerShell:

```powershell
git clone https://github.com/Yoruxyv/semantix.git
Set-Location semantix
Copy-Item backend\.env.example backend\.env
```

Untuk konfigurasi development tanpa akses jaringan, atur:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384
CACHE_BACKEND=memory
AUTH_MODE=disabled
```

Jalankan stack development yang disebutkan secara eksplisit:

```bash
docker compose -f docker-compose.dev.yml up --build -d
```

Docker Compose 2.20 atau yang lebih baru juga dapat menggunakan entry point kompatibilitas, yang memuat stack development yang sama:

```bash
docker compose up --build -d
```

Semua port development yang dipublikasikan secara default terikat ke `127.0.0.1`:

| Service         | Alamat                       |
| --------------- | ---------------------------- |
| Frontend        | http://localhost:4173        |
| Backend         | http://localhost:8000        |
| Dokumentasi API | http://localhost:8000/docs   |
| Liveness        | http://localhost:8000/health |
| Readiness       | http://localhost:8000/ready  |

Image frontend development menginstal dependency Node dan menjalankan development server Vite dengan HMR; image tersebut tidak melakukan kompilasi asset frontend production. `VITE_API_BASE_URL` diberikan ke development server tersebut saat runtime. Image frontend hardened melakukan production build yang dijelaskan nanti dalam panduan ini. Untuk memastikan pembaruan bind-mount tetap andal ketika native notifications tidak tersedia, stack development melakukan polling terhadap perubahan source frontend dan backend setiap satu detik. Vite mengabaikan output coverage yang dihasilkan, dan Uvicorn hanya melakukan reload untuk perubahan di bawah `backend/app`. Stack hardened tidak terpengaruh.

Perubahan biasanya terlihat dalam waktu sekitar satu detik. Jika tidak, pastikan Docker Desktop dapat membagikan drive repository, lalu buat ulang service yang terdampak. Periksa penggunaan saat idle dengan `docker stats --no-stream`. Jangan mengekspos stack development ke jaringan yang tidak tepercaya.

### Development dengan pgvector

Atur nilai database backend:

```env
CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
DATABASE_MIGRATION_MODE=auto
```

Jalankan profile:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d
```

Database tersedia untuk tool dari host di `127.0.0.1:5433` secara default. Development role sengaja memiliki tanggung jawab atas migrasi dan operasi runtime.

Perintah development mempertahankan nama Compose project `semantix` yang sudah ada di repository, sehingga volume `pgvector_data` lokal yang sudah ada akan terus digunakan.

### Toolchain lokal

Backend:

```bash
cd backend
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
cd frontend
npm ci
npm run dev
```

Atur `VITE_API_BASE_URL=http://localhost:8000` di `frontend/.env` untuk development Vite lokal.

## Deployment hardened

Stack hardened menggunakan:

* frontend terkompilasi yang disajikan oleh image Nginx non-root;
* backend internal yang tidak dipublikasikan secara langsung;
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

`GET /ready` memeriksa dependency cache yang aktif. Memory backend langsung mengembalikan hasil. Backend pgvector menjalankan query statistik cache dengan batas waktu dan mengembalikan `503` ketika database tidak tersedia.

Readiness tidak memanggil hosted AI provider sehingga tidak menggunakan kuota provider.

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
cd backend
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

Frontend:

```bash
cd frontend
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
