<p align="center">
  <sub><a href="README.ID.md">ID</a> · <a href="../../../README.md">EN</a></sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/React-19.2.8-61DAFB?logo=react&logoColor=white" alt="React 19.2.8">
  <img src="https://img.shields.io/badge/Vite-7.3.6-646CFF?logo=vite&logoColor=white" alt="Vite 7.3.6">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white" alt="Python 3.11 hingga 3.14">
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL dengan pgvector">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Auth-Scoped%20Tokens-D4A15A" alt="Autentikasi token bercakupan (scoped)">
  <img src="https://img.shields.io/badge/Docker-Dev%20%2B%20Hardened-2496ED?logo=docker&logoColor=white" alt="Stack Docker development dan hardened">
  <img src="https://img.shields.io/badge/License-MIT-22C55E?logo=opensourceinitiative&logoColor=white" alt="Lisensi MIT">
</p>

<div align="center">

# 🧠 Semantix

### Amati, ukur, dan sesuaikan semantic caching Anda — bukan sekadar memperlakukannya sebagai kotak hitam

Semantix adalah laboratorium semantic-cache full-stack untuk memeriksa keputusan cache, mengukur penghematan provider, mengevaluasi similarity threshold, dan membandingkan provider AI serta storage yang dapat dipertukarkan.

<sub>Monitor · Cache Inspector · Benchmark Lab · Runtime Observability</sub>

</div>

---

## ✨ Yang Ditawarkan Semantix

| Workspace | Tujuan |
|---|---|
| **Monitor** | Mengirimkan prompt dan memeriksa cache hit, cache miss, latensi, prompt yang cocok (matched), dan bukti similarity |
| **Cache Inspector** | Mencari entri, memeriksa metadata, menghapus record, membersihkan namespace, dan mengelola threshold |
| **Benchmark Lab** | Mengukur precision, recall, false hit, false miss, latensi, dan panggilan provider yang berhasil dihindari |
| **Observability** | Melacak volume request, panggilan provider, aktivitas cache, coalescing, expiration, dan eviction |

Kapabilitas inti:

- embedding dan generation provider yang independen;
- penyimpanan memory atau PostgreSQL + pgvector yang persisten;
- TTL, eviction LRU, namespace, request privat, dan kebijakan read/write;
- penggabungan request (request coalescing) untuk cache miss identik yang terjadi bersamaan;
- normalisasi prompt yang menyadari typo (opsional);
- peran token dan otorisasi namespace untuk deployment yang diperkeras;
- provider mock deterministik untuk pengujian lokal yang aman.

## ⚙️ Cara Kerjanya

```text
Prompt
  │
  ▼
Normalize matching text
  │
  ▼
Create embedding
  │
  ▼
Search the active namespace and embedding space
  │
  ├── score >= threshold ──► return cached response
  │
  └── score < threshold ───► call provider ─► store response
```

Semantix hanya mengembalikan respons yang telah di-cache jika entri terdekat yang kompatibel memenuhi similarity threshold yang aktif. Lihat [Cache policies](guides/cache-policies.md) untuk aturan lengkapnya.

## 🚀 Mulai Cepat

### Prasyarat

Instal Git dan Docker Desktop, atau Docker Engine beserta Compose.

### 1. Clone repository

Linux atau macOS:

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

### 2. Konfigurasi development lokal

Untuk konfigurasi persisten tanpa kredensial (zero-key), gunakan nilai berikut di `backend/.env`:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384

CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
DATABASE_MIGRATION_MODE=auto

AUTH_MODE=disabled
AUTH_PRINCIPALS=[]
TRUSTED_PROXY_CIDRS=[]
MAX_REQUEST_BODY_BYTES=65536
```

Nilai autentikasi dan proxy ini sengaja dikosongkan atau dinonaktifkan untuk development lokal yang tepercaya. Jangan gunakan konfigurasi development ini untuk deployment publik.

Untuk menggunakan Hugging Face, OpenAI, Anthropic, Gemini, atau Ollama, lihat [Providers](guides/providers.md). Untuk setiap opsi environment, lihat [Getting started](guides/getting-started.md) dan `backend/.env.example`.

### 3. Jalankan stack development lengkap

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d
```

Perintah tunggal ini akan menjalankan:

- frontend React dengan Vite hot reload;
- backend FastAPI dengan Uvicorn reload;
- PostgreSQL dengan pgvector;
- migrasi database development otomatis.

### 4. Buka aplikasi

| Layanan | Alamat |
|---|---|
| Frontend | <http://localhost:4173> |
| Backend | <http://localhost:8000> |
| Dokumentasi API | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness | <http://localhost:8000/ready> |
| Metrik runtime | <http://localhost:8000/api/v1/metrics> |
| PostgreSQL dari host | `127.0.0.1:5433` |

Perintah yang berguna:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector ps
docker compose -f docker-compose.dev.yml --profile pgvector logs -f backend
docker compose -f docker-compose.dev.yml --profile pgvector down
```

`down` tetap mempertahankan named volume. Menambahkan `--volumes` akan menghapus data PostgreSQL lokal.

## 🔌 Provider

Embedding provider dan generation provider dipilih secara independen.

| Provider | Embedding | Generation | Kredensial |
|---|:---:|:---:|:---:|
| Hugging Face | Ya | Ya | Diperlukan |
| OpenAI | Ya | Ya | Diperlukan |
| Anthropic | Tidak | Ya | Diperlukan |
| Gemini | Ya | Ya | Diperlukan |
| Ollama | Ya | Ya | Tidak diperlukan secara lokal |
| Mock | Ya | Ya | Tidak diperlukan |

Hanya pengaturan yang diperlukan oleh kapabilitas yang dipilih yang akan divalidasi. Lihat [Providers](guides/providers.md) untuk contoh konfigurasi dan catatan jaringan.

## 🛡️ Deployment Development dan Hardened

| Mode | Penggunaan yang dituju | Perilaku utama |
|---|---|---|
| **Development** | Satu developer lokal yang tepercaya | Hot reload, port loopback, autentikasi dinonaktifkan, migrasi otomatis |
| **Hardened** | Deployment single-instance yang dibagikan atau publik | Autentikasi token, peran namespace, jaringan backend/database internal, migrasi eksternal, proxy TLS wajib |

Buat `.env.production` dari `.env.production.example` hanya ketika Anda menyiapkan deployment yang diperkeras (hardened):

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Jangan menjalankannya sebelum setiap placeholder diganti. Lihat [Hardened deployment](operations/deployment.md) untuk pembuatan token, trusted proxy, peran database, TLS, dan validasi.

## 📊 Benchmark Terukur

Uji coba lokal pada 19 Juli 2026 menggunakan **Quick semantic safety set** yang berisi delapan kueri, provider Hugging Face, normalisasi typo, cache terisolasi yang kosong, dan threshold `0.92`:

| Panggilan provider yang dihindari | Rata-rata hit | Rata-rata miss | Precision / Recall / F1 |
|---:|---:|---:|---:|
| **4 dari 8 (50%)** | **330,3 ms** | **3772,7 ms** | **1,0 / 1,0 / 1,0** |

Ini adalah satu pengukuran bertanggal, bukan jaminan performa. Lihat [Benchmarking](guides/benchmarking.md) untuk dataset, detail uji coba, dan batasannya.

## ✅ Pemeriksaan Kualitas

### Persiapan cache backend

Cache tool backend dipusatkan di `backend/.cache/`. Aktifkan redirect cache bytecode Python sebelum menjalankan perintah backend.

Dari root repository:

Windows PowerShell:

```powershell
. .\backend\scripts\windows\enable_cache.ps1
```

Linux atau macOS:

```bash
source backend/scripts/linux/enable_cache.sh
```

Ketika sudah berada di dalam `backend/`:

Windows PowerShell:

```powershell
. .\scripts\windows\enable_cache.ps1
```

Linux atau macOS:

```bash
source scripts/linux/enable_cache.sh
```

Tanda titik di depan pada PowerShell dan `source` pada Bash diperlukan agar `PYTHONPYCACHEPREFIX` tetap aktif di terminal saat ini. Ruff, mypy, dan pytest menggunakan path cache-nya dari `backend/pyproject.toml`.

Untuk menghapus cache yang dihasilkan dan metadata editable-install:

```powershell
.\backend\scripts\windows\clean_artifacts.ps1
```

Untuk Linux atau macOS:

```bash
bash backend/scripts/linux/clean_artifacts.sh
```

Otomasi yang spesifik-platform berada di direktori `windows/` dan `linux/`. Overlay Compose bersama tetap berada di samping direktori tersebut di bawah `ops/ci/`. Sebagai contoh, smoke test kesehatan development memiliki entry point yang sepadan:

Windows PowerShell:

```powershell
.\ops\ci\windows\dev-healthcheck-smoke.ps1
```

Linux atau macOS:

```bash
bash ops/ci/linux/dev-healthcheck-smoke.sh
```

Entry point smoke test menghasilkan password database dan token autentikasi yang bersifat sementara (ephemeral) untuk setiap uji coba, kecuali variabel environment yang bersangkutan sudah diset. Kredensial tidak disimpan dalam skrip.

Laporan developer untuk seluruh repository tersedia melalui helper platform berpasangan:

```powershell
.\scripts\windows\get_total_lines.ps1
.\scripts\windows\find_undocumented_files.ps1
```

```bash
bash scripts/linux/get_total_lines.sh
bash scripts/linux/find_undocumented_files.sh
```

Skrip-skrip ini memeriksa file proyek yang dilacak Git dan tidak diabaikan (unignored), sehingga dependensi, cache, virtual environment, dan build output yang diabaikan otomatis dikecualikan.

Backend:

```bash
cd backend
uv sync --locked --extra dev
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

Lihat [Development](guides/development.md) untuk toolchain lokal, aturan arsitektur, dan langkah-langkah kontribusi.

## 🗂️ Struktur Proyek

```text
semantix/
├── backend/
├── frontend/
├── ops/
│   ├── ci/
│   ├── load-testing/
│   ├── postgres/
│   └── supply-chain/
├── scripts/
│   ├── linux/
│   └── windows/
├── docs/
├── docker-compose.dev.yml
├── docker-compose.prod.yml
└── README.md
```

Backend dan frontend menggunakan kepemilikan feature-first. Lihat [Architecture](reference/architecture.md) untuk alur runtime dan batas paket.

## ⚠️ Batasan Penting

- Similarity semantik bersifat probabilistik dan harus dievaluasi untuk setiap model dan beban kerja (workload).
- Hosted provider dapat menerima prompt dan dapat menimbulkan biaya, latensi, serta kebutuhan penanganan data eksternal.
- Metrik runtime, rate limiting, dan request coalescing bersifat process-local.
- Stack hardened adalah baseline single-instance, bukan platform multi-tenant atau multi-replica yang lengkap.
- Provider mock ditujukan untuk pengujian, demonstrasi, dan pengembangan UI.

## 📚 Dokumentasi

[Indeks dokumentasi](README.md) mengelompokkan seluruh panduan berdasarkan tujuannya.

| Mulai di sini | Gunakan untuk |
|---|---|
| [Getting started](guides/getting-started.md) | Setup lokal, file environment, dan alur kerja Docker |
| [Providers](guides/providers.md) | Konfigurasi provider hosted, lokal, dan mock |
| [Architecture](reference/architecture.md) | Alur runtime, kepemilikan fitur, dan batas paket |
| [Hardened deployment](operations/deployment.md) | Autentikasi, TLS, peran database, dan validasi produksi |

## 🤝 Kontributor

Dibuat dengan ❤️ oleh:

<table>
  <tr>
    <td align="center" width="180">
      <a href="https://github.com/Yoruxyv">
        <img src="https://github.com/Yoruxyv.png?size=96" width="96" alt="Avatar Hans"><br>
        <b>Hans</b>
      </a><br>
    </td>
    <td align="center" width="180">
      <a href="https://github.com/Kasanee-Teto">
        <img src="https://github.com/Kasanee-Teto.png?size=96" width="96" alt="Avatar Louis"><br>
        <b>Louis</b>
      </a><br>
    </td>
  </tr>
</table>

## 📄 Lisensi

Dilisensikan di bawah [MIT License](../../../LICENSE).
