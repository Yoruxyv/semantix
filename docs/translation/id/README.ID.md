<p align="center">
  <sub><a href="README.ID.md">ID</a> · <a href="../../../README.md">EN</a></sub>
</p>

<div align="center">

# 🧠 Semantix

### Amati, ukur, dan sesuaikan semantic caching Anda — bukan sekadar memperlakukannya sebagai kotak hitam

Semantix adalah laboratorium semantic-cache full-stack untuk memeriksa keputusan cache, mengukur penghematan provider, mengevaluasi similarity threshold, dan membandingkan provider AI serta storage yang dapat dipertukarkan.

Semantix dapat di-host sendiri untuk beberapa aplikasi dan pengguna. Akses berbasis namespace memisahkan data cache mereka; PostgreSQL + pgvector mempertahankan entri saat layanan dimulai ulang. Deployment hardened merutekan traffic melalui dua replika backend.

<sub>Monitor · Cache Inspector · Evaluations · Observability</sub>

</div>

![Monitor Semantix menampilkan cache hit, bukti similarity, dan panggilan provider yang dilewati](../../assets/screenshots/monitor-decision.png)

*Tampilan Semantix asli dengan provider mock deterministik dan contoh prompt.*

---

## ✨ Yang Ditawarkan Semantix

| Workspace | Tujuan |
|---|---|
| **Monitor** | Mengirim probe kebijakan dalam namespace dan memeriksa hit, miss, latensi, prompt yang cocok, serta bukti similarity |
| **Cache Inspector** | Mencari entri, memeriksa metadata, menghapus record, membersihkan namespace, dan mengelola threshold |
| **Evaluations** | Mengukur precision, recall, false hit, dan false miss; memeriksa bukti kasus terfilter serta mengekspor hasil run |
| **Observability** | Melacak metrik proses dan memeriksa diagnostik runtime read-only yang aman |

## Tur produk

Demo lokal dengan provider mock juga menampilkan workspace lainnya. Pilih pratinjau untuk melihat tangkapan layar berukuran penuh.

| Workspace | Tampilan saat ini |
|---|---|
| **Cache Inspector** — Cari prompt tersimpan dan periksa usia, jumlah hit, serta masa berlaku entri tanpa menampilkan embedding. | <a href="../../assets/screenshots/cache-inspector.png"><img src="../../assets/screenshots/cache-inspector.png" alt="Cache Inspector menampilkan entri contoh dengan jumlah hit dan TTL" width="320"></a> |
| **Evaluations** — Jalankan dataset terisolasi dan tinjau hit rate, panggilan provider, serta klasifikasi yang terukur. | <a href="../../assets/screenshots/evaluations-results.png"><img src="../../assets/screenshots/evaluations-results.png" alt="Evaluations menampilkan hasil quick semantic safety set bawaan" width="320"></a> |
| **Observability** — Lihat metrik request, cache, provider, dan latensi pada proses backend ini. | <a href="../../assets/screenshots/observability-metrics.png"><img src="../../assets/screenshots/observability-metrics.png" alt="Observability menampilkan metrik traffic, cache, dan latensi provider mock" width="320"></a> |

Kapabilitas inti:

- embedding dan generation provider yang independen;
- penyimpanan memory atau PostgreSQL + pgvector yang persisten;
- TTL, eviction LRU, namespace, request privat, dan kebijakan read/write;
- kontrol Monitor sesuai peran, minimisasi trace privat, dan tautan hit ke detail Cache yang diotorisasi;
- penggabungan request (request coalescing) untuk cache miss identik yang terjadi bersamaan;
- normalisasi prompt yang menyadari typo (opsional);
- threshold cache global yang dapat dilihat dan diagnostik runtime read-only khusus admin;
- peran token dan otorisasi namespace untuk deployment yang diperkeras;
- provider mock deterministik untuk pengujian lokal yang aman;
- cache evaluasi terpisah per run, confusion matrix lengkap, dan proyeksi threshold dari kandidat yang sudah diukur;
- dataset evaluasi JSON versi 1 yang tersimpan hanya selama sesi browser, dengan pratinjau tanpa panggilan provider;
- katalog dataset evaluasi PostgreSQL opsional dengan penyimpanan eksplisit dan retensi terbatas.

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
Menggunakan kembali respons yang sesuai menghindari panggilan generation berikutnya dan dapat mengurangi latensi serta biaya provider; evaluasi false match untuk workload Anda sendiri.

## 🐍 Python SDK

Aplikasi Python dapat memakai distribusi `semantix-client` melalui HTTP API publik. Paket ini menyediakan `SemantixClient` dan `AsyncSemantixClient` tanpa memerlukan modul internal backend. Paket belum diterbitkan di PyPI; lihat [panduan Python SDK](../../../sdk/README.md) untuk instalasi dari repository atau wheel.

```python
from semantix_client import SemantixClient

with SemantixClient(base_url="http://localhost:8000") as client:
    result = client.query("Explain semantic caching", namespace="default")

print(result.response, result.cache_hit)
```

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
| Diagnostik runtime | <http://localhost:8000/api/v1/diagnostics> |
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
| **Hardened** | Deployment dua replika yang dibagikan atau publik | Autentikasi token, peran namespace, jaringan backend/database internal, migrasi eksternal, proxy TLS wajib |

Buat `.env.production` dari `.env.production.example` hanya ketika Anda menyiapkan deployment yang diperkeras (hardened):

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Jangan menjalankannya sebelum setiap placeholder diganti. Lihat [Hardened deployment](operations/deployment.md) untuk pembuatan token, trusted proxy, peran database, TLS, dan validasi.

## 📈 Performa dan skalabilitas

Stack hardened menyeimbangkan replika backend di atas state PostgreSQL + pgvector bersama. PostgreSQL juga mengoordinasikan batas laju tingkat deployment, penguncian sesi, dan perubahan threshold cache. Failover, draining, serta perubahan jumlah replika yang terkendali telah diuji.

Dalam uji Docker lokal pada perangkat keras yang didokumentasikan, stack dua replika menyelesaikan **uji cache-heavy 10 menit dengan 1.000 virtual user**: 195.961 request (sekitar 324 RPS), latensi P95 186 ms, serta nol kegagalan HTTP 4xx, HTTP 5xx, transport, atau readiness yang disampel. Workload memakai provider mock deterministik dan jeda 2–4 detik per virtual user. Angka ini berlaku untuk mesin dan workload tersebut, bukan jaminan kapasitas produksi.

Perbandingan generation-heavy terkontrol pada 1.000 virtual user menunjukkan sekitar 167 RPS dan P95 4,86 detik dengan satu replika, dibandingkan 270 RPS dan P95 1,95 detik dengan dua replika. Tekanan koneksi dan lock PostgreSQL membatasi ekstrapolasi ke lebih banyak replika. Lihat [Pengujian kapasitas](../../operations/load-testing.md#capacity-baseline-on-the-local-docker-host) untuk perangkat keras, metodologi, semua profil, kegagalan, dan batasannya. Python SDK juga diuji melalui gateway dengan load balancer.

## 📊 Benchmark semantic cache

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
├── sdk/
│   ├── src/
│   └── tests/
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
- Metrik runtime, diagnostik, dan request coalescing bersifat process-local; rate limiting produksi memakai koordinasi PostgreSQL bersama.
- Stack hardened menyeimbangkan dua replika backend; ini bukan platform multi-tenant atau sistem autoscaling umum yang lengkap.
- Provider mock ditujukan untuk pengujian, demonstrasi, dan pengembangan UI.
- Sweep evaluasi menggunakan proyeksi dari satu run terukur, bukan pemutaran ulang berurutan atau rekomendasi threshold otomatis.

## 📚 Dokumentasi

[Indeks dokumentasi](README.md) mengelompokkan seluruh panduan berdasarkan tujuannya.

| Mulai di sini | Gunakan untuk |
|---|---|
| [Getting started](guides/getting-started.md) | Setup lokal, file environment, dan alur kerja Docker |
| [Providers](guides/providers.md) | Konfigurasi provider hosted, lokal, dan mock |
| [Python SDK](../../../sdk/README.md) | Instalasi dan penggunaan HTTP client sinkron dan asinkron |
| [Architecture](reference/architecture.md) | Alur runtime, kepemilikan fitur, dan batas paket |
| [Hardened deployment](operations/deployment.md) | Autentikasi, TLS, peran database, dan validasi produksi |
| [Pengujian kapasitas](../../operations/load-testing.md#capacity-baseline-on-the-local-docker-host) | Profil beban, perangkat keras, hasil satu/dua replika, dan soak 1.000 VU |

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
