<div align="center">

<h1>🧠 Semantix</h1>

<p><strong>Semantic caching asinkron untuk Python.</strong></p>

<p>Penyimpanan memory atau PostgreSQL. Alur generation tetap Anda kendalikan.</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-555555?logo=python&amp;logoColor=FFD43B&amp;labelColor=3776AB" alt="Python 3.11–3.14" />
  <a href="../../../LICENSE"><img src="https://img.shields.io/badge/License-MIT-3DA639" alt="MIT license" /></a>
</p>

<p><sub><a href="../../../README.md">EN</a> · <a href="README.ID.md">ID</a></sub></p>

</div>

<p align="center">
  <a href="#instalasi-dan-contoh-awal">Mulai</a> ·
  <a href="#cara-kerja-embedded">Cara kerja</a> ·
  <a href="#provider-embedded">Provider</a> ·
  <a href="#storage-embedded">Storage</a> ·
  <a href="#performa-embedded">Benchmark</a>
</p>

**semantix-cache** adalah produk PyPI publik pertama yang direncanakan.
API 0.1.0 hanya asinkron dan berjalan di dalam proses Python Anda. Tidak
memerlukan server Semantix, web UI, Docker, atau PostgreSQL.

## Instalasi dan contoh awal

> [!NOTE]
> **0.1.0 belum diterbitkan.** Perintah instalasi publik berikut berlaku setelah publikasi.

```bash
python -m pip install semantix-cache
```

Sebelum publikasi, instal wheel kandidat yang sudah dibangun dari direktori yang memuatnya:

```bash
python -m pip install semantix_cache-0.1.0-py3-none-any.whl
```

Lihat [panduan paket](../../../packages/cache/README.md) untuk build lokal dan kontrak
lengkap. Paket minimal bergantung pada NumPy dan Pydantic; dependensi jaringan
provider serta driver PostgreSQL bersifat opsional.

Contoh tanpa kredensial berikut dapat dijalankan sebagai skrip. Vektor sederhana
hanya menunjukkan cara integrasi, bukan pemahaman bahasa atau kualitas pencocokan
semantik. Ganti embedder dan fungsi generation dengan integrasi asinkron aplikasi Anda.

```python
import asyncio
from semantix_cache import AsyncSemanticCache, EmbeddingSpace, MemoryStore

class DemoEmbedder:
    embedding_space = EmbeddingSpace(identity="demo-v1", dimensions=2)

    async def embed(self, text: str) -> tuple[float, float]:
        return (1.0, 0.0) if "weather" in text.lower() else (0.0, 1.0)

async def generate(prompt: str) -> str:
    return "Completed answer for: " + prompt

async def main() -> None:
    embedder = DemoEmbedder()
    async with MemoryStore(embedding_space=embedder.embedding_space) as store:
        async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
            prompt = "weather today"
            miss = await cache.resolve(prompt, namespace="demo", generate=generate)
            hit = await cache.resolve(prompt, namespace="demo", generate=generate)
            assert miss.provider_called and miss.cache_written
            assert hit.cache_hit and hit.generation_skipped
            print(hit.response, "cache_hit=", hit.cache_hit)

asyncio.run(main())
```

Resolve pertama menghasilkan dan menyimpan jawaban; resolve kedua melaporkan hit
cache yang telah dikonfirmasi dan melewati generation. Gunakan ulang store/cache
antar-request: membuat MemoryStore baru menghilangkan entri process-local sebelumnya.
Context manager menutup facade dan store; resource lain yang diinjeksi tetap dimiliki aplikasi.

## Sekilas

| Aspek | Ringkasan |
| --- | --- |
| **Runtime** | Python asinkron, in-process |
| **Storage** | MemoryStore atau PostgreSQL/pgvector opsional |
| **Generation** | Callable asinkron milik Anda |

## Mengapa Semantix?

Gunakan ulang respons yang telah selesai dalam aplikasi asinkron Anda, sementara
penyusunan prompt, pemilihan model, RAG, tools, dan persetujuan output tetap berada
di kode aplikasi. Atur threshold similarity serta retensi secara eksplisit, periksa
bukti hit/miss yang dikembalikan, dan tambahkan persistensi bila diperlukan.

## Cara kerja embedded

Untuk kebijakan NORMAL bawaan, alurnya adalah:

```mermaid
flowchart LR
    A[Aplikasi Anda] --> B[AsyncSemanticCache]
    B --> C[Embed]
    C --> D{Hit cache terkonfirmasi?}
    D -->|Ya| H[Kembalikan hit]
    D -->|Tidak| G[Generation, validasi dan simpan]
    G --> R[Kembalikan miss]
```

Kandidat yang memenuhi syarat harus lolos validasi dan konfirmasi TTL/revisi
secara atomik sebelum hit dikembalikan.

Aplikasi memiliki masa hidup embedder, generator, dan store. CacheStore dapat berupa
MemoryStore, PgVectorStore opsional, atau implementasi Anda. Kebijakan lain mengatur
read/generation/write; coalescing opt-in menambahkan penantian dan lookup terkonfirmasi
milik setiap follower. Lihat [kontrak cache](../../../packages/cache/README.md#contract).

## Perilaku semantic cache

Pencocokan memakai embedding tervalidasi dan cosine similarity, bukan syarat string
yang identik. Threshold inklusif bawaannya 0.92; evaluasi false match untuk model dan
workload Anda. Prompt yang diulang pun tetap melalui embedding dan lookup. Namespace
dan EmbeddingSpace mengisolasi data cache yang kompatibel, bukan menggantikan otorisasi aplikasi.

Versikan namespace ketika konteks respons, model, izin, atau kebijakan persetujuan
berubah. Pertahankan identitas embedding untuk kombinasi model/revisi/dimensi/
preprocessing yang sama. Dimensi yang sama saja tidak membuktikan kompatibilitas.
TTL dimulai saat write dan tidak diperpanjang oleh hit. Lihat
[kebijakan, TTL, dan pencocokan](../../../packages/cache/README.md#contract).

## Kapabilitas utama

- **API asinkron** — AsyncSemanticCache dengan CachePolicy, CacheResult, dan bukti CacheHit yang eksplisit.
- **Memory** — MemoryStore terbatas dengan cosine float64 eksak, TTL, dan LRU berdasarkan hit terkonfirmasi.
- **Persistensi** — PostgreSQL/pgvector opsional dengan inisialisasi schema yang eksplisit.
- **Ekstensi** — Adapter embedding/generation yang dipelihara serta kontrak integrasi kustom struktural.
- **Coalescing** — Cold miss NORMAL secara opt-in dalam satu instance cache dan event loop.

## Performa embedded

Pengukuran development historis membandingkan base yang sudah dioptimasi `ee915140`
dengan coalescing opt-in, melalui tiga pasangan control/treatment bergantian dengan
proses baru untuk setiap store. Workload memakai 256 request, concurrency 128, dua
prompt yang kompatibel, dan generation deterministik dengan jeda 200 ms. Panggilan
generation turun dari 256 menjadi 2; panggilan embedding tetap 256.

| Store | Burst P50, nonaktif → aktif | Burst P95, nonaktif → aktif |
| --- | ---: | ---: |
| MemoryStore | 294.095 → 434.127 ms | 316.949 → 458.839 ms |
| PgVectorStore | 916.670 → 941.012 ms | 1366.900 → 1087.602 ms |

Angka ini adalah median persentil burst per trial, bukan timing follower secara
terpisah.

Pengurangan kerja provider dapat meningkatkan latensi cold follower, seperti pada
MemoryStore. Sharing mensyaratkan input setara yang ditegaskan pemanggil, admission
terbatas, serta persistensi/konfirmasi yang berhasil. Fitur ini nonaktif secara
bawaan dan tidak menjamin latensi, penghapusan duplikasi, atau penghematan biaya
untuk semua aplikasi. Lihat [tradeoff lengkap](../../../packages/cache/README.md#measured-provider-work-and-latency-tradeoff).
Pengukuran server opsional dipertahankan di bawah dan memakai workload yang berbeda.

<details>
<summary>Lingkungan pengukuran dan metodologi</summary>

Kondisi: Windows 11, Ryzen 9 5900HX/16 CPU logis/sekitar 32 GiB RAM;
Python 3.14.6, NumPy 2.4.6, Pydantic 2.13.5; 384 dimensi, 500 kandidat awal,
kapasitas 5.000, threshold 0.92, TTL 3.600 s; thread BLAS proses anak=1. PostgreSQL
17.10/pgvector 0.8.5 memakai container lokal empat CPU/2 GiB, asyncpg 0.31.0 dan
pool delapan koneksi. Setup/warmup/cleanup tidak dihitung; request terukur selesai tanpa error.

Lihat [eksperimen coalescing](../../../packages/cache/benchmarks/COALESCING.md)
dan [metodologi benchmark runtime](../../../packages/cache/benchmarks/README.md) untuk reproduksi.

</details>

## Perilaku operasional

Facade meminjam resource yang diinjeksi. Adapter meminjam HTTP client;
PgVectorStore.connect memiliki pool-nya, sedangkan pool yang diinjeksi dipinjam.
Tuntaskan atau batalkan pekerjaan aktif sebelum menutup resource: resource sibuk
memunculkan CacheBusyError. Deadline total terbatas, cancellation diteruskan, dan
tidak ada retry generation otomatis. Transport/callback yang dikonfigurasi pemanggil
tetap menjadi tanggung jawab pemanggil.

Kegagalan lookup/write diteruskan sebagai error; generation yang diikuti write gagal
bukan resolve yang berhasil. Error bertipe dan bukti hasil yang terbatas dijelaskan
di [panduan paket](../../../packages/cache/README.md#extension-and-ownership).
Coalescing membutuhkan pernyataan eksplisit melalui `coalescing_key`; Semantix tidak
menyimpulkan kesetaraan ContextVars/closure atau berkoordinasi antarproses. Follower
mengonfirmasi hit masing-masing. Mengubah key itu saja tidak membatalkan jawaban
tersimpan. Baca [aturan keamanan coalescing](../../../packages/cache/README.md#optional-cold-miss-coalescing).

[Kebijakan kompatibilitas 0.1.x](../../../packages/cache/README.md#01x-compatibility)
lengkap tetap kanonis di panduan paket.

## Provider embedded

Adapter bawaan berada di `semantix_cache.adapters`, di luar impor root minimal.
Pilih model dan identitas embedding-space secara eksplisit, serta berikan HTTPX
client yang dipinjam. Extra HTTP opsional tidak memasang SDK provider.

| Provider | Embedding | Generation teks selesai |
| --- | --- | --- |
| OpenAI | Ya | Ya |
| Hugging Face | Ya | Ya |
| Gemini | Ya | Ya |
| Ollama | Ya | Ya |
| Anthropic | Memerlukan embedding kustom | Ya |

Lihat [provider embedded dan integrasi kustom](../../embedded-providers.md) untuk
extra, impor, kredensial, default, override endpoint yang kompatibel, dan batas respons.
API eksternal dapat berubah secara independen; versi/provider yang belum didukung
dapat memakai kontrak embedding dan generation kustom.

## Storage embedded

Mulai dengan MemoryStore untuk state process-local yang terbatas. Opsional
`semantix_cache.stores.pgvector.PgVectorStore` mempertahankan data antarproses/restart
melalui database PostgreSQL yang dikendalikan aplikasi. Siapkan extension vector dan
inisialisasi schema cache terpisah yang bertanda secara eksplisit; operasi cache
normal tidak menjalankan DDL. Runtime memeriksa penanda kepemilikan, versi, dan
checksum migrasi, bukan fingerprint katalog lengkap. Lindungi perubahan schema di luar migrasi.

Lihat [storage embedded dan database pengguna](../../embedded-storage.md) untuk akses
runtime dengan izin minimum, kepemilikan pool, migrasi, dan store kustom. pgvector
menyimpan vektor float32; skor dekat threshold dapat berbeda dari scoring float64 MemoryStore.

## Titik ekstensi

Berikan EmbeddingAdapter struktural (`embedding_space` dan `embed` asinkron),
GenerationCallable asinkron yang mengembalikan teks selesai yang disetujui, atau
CacheStore struktural. Tidak perlu subclass atau registry. Alur streaming/RAG/tools
dapat memakai `get`/`set` di sekitar teks akhir yang disetujui; Semantix tidak
menjalankan workflow aplikasi tersebut.

## Contoh

- [Embedding dan generation kustom](../../../packages/cache/examples/custom_integration.py).
- [CacheStore kustom dan conformance](../../../packages/cache/examples/custom_store.py).
- [Customer support persisten](../../../packages/cache/examples/persistent_support.py).
- [API publik dan struktur source](../../../packages/cache/src/README.md).

## Komponen repository

| Path | Komponen |
| --- | --- |
| `packages/cache/` | Library embedded utama semantix-cache; produk PyPI pertama yang direncanakan |
| `apps/server/` | Server FastAPI resmi yang opsional untuk self-hosting |
| `apps/web/` | Web/workbench resmi yang opsional untuk memeriksa dan mengevaluasi keputusan cache server |
| `packages/client/` | HTTP client opsional/referensi semantix-client yang dipelihara; bukan target PyPI rilis pertama |

Server/workbench opsional merupakan laboratorium full-stack untuk memeriksa keputusan
cache, mengevaluasi threshold, dan mengukur kerja provider. Otorisasi namespace dan
deployment hardened dua replika adalah fitur server, bukan prasyarat embedded.
Tooling operasional berada di `ops/`; tooling developer di `scripts/`.

<details>
<summary>Server/workbench opsional: tur, setup Docker, dan bukti deployment</summary>

![Monitor Semantix menampilkan cache hit, bukti similarity, dan panggilan provider yang dilewati](../../assets/screenshots/monitor-decision.png)

*Tampilan Semantix asli dengan provider Hugging Face dan contoh prompt.*

---

### ✨ Yang Ditawarkan Semantix

| Workspace | Tujuan |
|---|---|
| **Monitor** | Mengirim probe kebijakan dalam namespace dan memeriksa hit, miss, latensi, prompt yang cocok, serta bukti similarity |
| **Cache Inspector** | Mencari entri, memeriksa metadata, menghapus record, membersihkan namespace, dan mengelola threshold |
| **Evaluations** | Mengukur precision, recall, false hit, dan false miss; memeriksa bukti kasus terfilter serta mengekspor hasil run |
| **Observability** | Melacak metrik proses dan memeriksa diagnostik runtime read-only yang aman |

### Tur produk

Demo lokal dengan provider Hugging Face juga menampilkan workspace lainnya. Pilih pratinjau untuk melihat tangkapan layar berukuran penuh.

| Workspace | Tampilan saat ini |
|---|---|
| **Cache Inspector** — Cari prompt tersimpan dan periksa usia, jumlah hit, serta masa berlaku entri tanpa menampilkan embedding. | <a href="../../assets/screenshots/cache-inspector.png"><img src="../../assets/screenshots/cache-inspector.png" alt="Cache Inspector menampilkan entri contoh dengan jumlah hit dan TTL" width="320"></a> |
| **Evaluations** — Jalankan dataset terisolasi dan tinjau hit rate, panggilan provider, serta klasifikasi yang terukur. | <a href="../../assets/screenshots/evaluations-results.png"><img src="../../assets/screenshots/evaluations-results.png" alt="Evaluations menampilkan hasil quick semantic safety set bawaan" width="320"></a> |
| **Observability** — Periksa diagnostik runtime yang aman, kategori provider, fingerprint pencocokan, dan kesiapan layanan. | <a href="../../assets/screenshots/observability-diagnostics.png"><img src="../../assets/screenshots/observability-diagnostics.png" alt="Diagnostik runtime Observability menampilkan provider Hugging Face dan kesiapan layanan" width="320"></a> |

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

### 🚀 Mulai Cepat

#### Prasyarat

Instal Git dan Docker Desktop, atau Docker Engine beserta Compose.

#### 1. Clone repository

Linux atau macOS:

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

#### 2. Konfigurasi development lokal

Untuk konfigurasi persisten tanpa kredensial (zero-key), gunakan nilai berikut di `apps/server/.env`:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384

CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
DATABASE_MIGRATION_MODE=auto
EVALUATION_DATASET_STORAGE=postgres
EVALUATION_DATASET_DEFAULT_RETENTION_DAYS=30

AUTH_MODE=disabled
AUTH_PRINCIPALS=[]
TRUSTED_PROXY_CIDRS=[]
MAX_REQUEST_BODY_BYTES=65536
```

Nilai autentikasi dan proxy ini sengaja dikosongkan atau dinonaktifkan untuk development lokal yang tepercaya. Jangan gunakan konfigurasi development ini untuk deployment publik.

Untuk menggunakan Hugging Face, OpenAI, Anthropic, Gemini, atau Ollama, lihat [Providers](guides/providers.md). Untuk setiap opsi environment, lihat [Getting started](guides/getting-started.md) dan `apps/server/.env.example`.

#### 3. Jalankan stack development lengkap

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d
```

Perintah tunggal ini akan menjalankan:

- frontend React dengan Vite hot reload;
- backend FastAPI dengan Uvicorn reload;
- PostgreSQL dengan pgvector;
- migrasi database development otomatis.

#### 4. Buka aplikasi

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

### 🔌 Provider

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

### 🛡️ Deployment Development dan Hardened

| Mode | Penggunaan yang dituju | Perilaku utama |
|---|---|---|
| **Development** | Satu developer lokal yang tepercaya | Hot reload, port loopback, autentikasi dinonaktifkan, migrasi otomatis |
| **Hardened** | Deployment dua replika yang dibagikan atau publik | Autentikasi token, peran namespace, jaringan backend/database internal, migrasi eksternal, proxy TLS wajib |

Buat `.env.production` dari `.env.production.example` hanya ketika Anda menyiapkan deployment yang diperkeras (hardened):

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Jangan menjalankannya sebelum setiap placeholder diganti. Lihat [Hardened deployment](operations/deployment.md) untuk pembuatan token, trusted proxy, peran database, TLS, dan validasi.

### 📈 Performa dan skalabilitas

Stack hardened menyeimbangkan replika backend di atas state PostgreSQL + pgvector bersama. PostgreSQL juga mengoordinasikan batas laju tingkat deployment, penguncian sesi, dan perubahan threshold cache. Failover, draining, serta perubahan jumlah replika yang terkendali telah diuji.

Dalam uji Docker lokal pada perangkat keras yang didokumentasikan, stack dua replika menyelesaikan **uji cache-heavy 10 menit dengan 1.000 virtual user**: 195.961 request (sekitar 324 RPS), latensi P95 186 ms, serta nol kegagalan HTTP 4xx, HTTP 5xx, transport, atau readiness yang disampel. Workload memakai provider mock deterministik dan jeda 2–4 detik per virtual user. Angka ini berlaku untuk mesin dan workload tersebut, bukan jaminan kapasitas produksi.

Perbandingan generation-heavy terkontrol pada 1.000 virtual user menunjukkan sekitar 167 RPS dan P95 4,86 detik dengan satu replika, dibandingkan 270 RPS dan P95 1,95 detik dengan dua replika. Tekanan koneksi dan lock PostgreSQL membatasi ekstrapolasi ke lebih banyak replika. Lihat [Pengujian kapasitas](../../operations/load-testing.md#capacity-baseline-on-the-local-docker-host) untuk perangkat keras, metodologi, semua profil, kegagalan, dan batasannya. Python SDK juga diuji melalui gateway dengan load balancer.

### 📊 Benchmark semantic cache

Uji coba lokal pada 19 Juli 2026 menggunakan **Quick semantic safety set** yang berisi delapan kueri, provider Hugging Face, normalisasi typo, cache terisolasi yang kosong, dan threshold `0.92`:

| Panggilan provider yang dihindari | Rata-rata hit | Rata-rata miss | Precision / Recall / F1 |
|---:|---:|---:|---:|
| **4 dari 8 (50%)** | **330,3 ms** | **3772,7 ms** | **1,0 / 1,0 / 1,0** |

Ini adalah satu pengukuran bertanggal, bukan jaminan performa. Lihat [Benchmarking](guides/benchmarking.md) untuk dataset, detail uji coba, dan batasannya.

### ⚠️ Batasan Penting

- Similarity semantik bersifat probabilistik dan harus dievaluasi untuk setiap model dan beban kerja (workload).
- Hosted provider dapat menerima prompt dan dapat menimbulkan biaya, latensi, serta kebutuhan penanganan data eksternal.
- Metrik runtime, diagnostik, dan request coalescing bersifat process-local; rate limiting produksi memakai koordinasi PostgreSQL bersama.
- Stack hardened menyeimbangkan dua replika backend; ini bukan platform multi-tenant atau sistem autoscaling umum yang lengkap.
- Provider mock ditujukan untuk pengujian, demonstrasi, dan pengembangan UI.
- Sweep evaluasi menggunakan proyeksi dari satu run terukur, bukan pemutaran ulang berurutan atau rekomendasi threshold otomatis.

</details>

Gunakan semantix-client dengan server Semantix kompatibel yang sudah berjalan.
Paket ini tetap dipelihara, bukan target PyPI rilis pertama, dan tidak menyediakan
engine embedded.

### HTTP client referensi

Aplikasi Python dapat memakai distribusi `semantix-client` melalui HTTP API publik. Paket ini menyediakan `SemantixClient` dan `AsyncSemantixClient` tanpa memerlukan modul internal backend. Paket belum diterbitkan di PyPI; lihat [panduan Python SDK](../../../packages/client/README.md) untuk instalasi dari repository atau wheel.

```python
from semantix_client import SemantixClient

with SemantixClient(base_url="http://localhost:8000") as client:
    result = client.query("Explain semantic caching", namespace="default")

print(result.response, result.cache_hit)
```

## Dokumentasi

[Indeks dokumentasi](README.md) memisahkan panduan embedded dan server.

| Mulai di sini | Gunakan untuk |
| --- | --- |
| [Panduan paket cache](../../../packages/cache/README.md) | Quick start embedded, kebijakan, kepemilikan, dan kompatibilitas kanonis |
| [Provider embedded](../../embedded-providers.md) | Adapter yang dipelihara dan embedding/generation kustom |
| [Storage embedded](../../embedded-storage.md) | Memory, PostgreSQL opsional, dan database aplikasi |
| [Contoh](../../../packages/cache/examples/) | Generation dan store yang dikendalikan aplikasi |
| [Metodologi benchmark](../../../packages/cache/benchmarks/README.md) | Workload runtime lokal yang reproducible beserta batasannya |
| [Getting started server](guides/getting-started.md) | Environment dan workflow Docker untuk server opsional |
| [Panduan HTTP client](../../../packages/client/README.md) | Client bertipe untuk server kompatibel yang sudah berjalan |
| [Arsitektur server](reference/architecture.md) | Kepemilikan fitur dan alur request |
| [Hardened deployment](operations/deployment.md) | Auth server, TLS, role database, dan validasi |

## Berkontribusi

Lihat [CONTRIBUTING](CONTRIBUTING.md), [pemeriksaan contributor cache](../../../packages/cache/README.md#separate-products),
dan [development server/web](guides/development.md).

<details>
<summary>Struktur repository dan pemeriksaan development server/web</summary>

### 🗂️ Struktur Proyek

```text
semantix/
├── apps/
│   ├── server/
│   └── web/
├── packages/
│   ├── cache/
│   │   ├── src/semantix_cache/
│   │   └── tests/
│   └── client/
│       ├── src/semantix_client/
│       └── tests/
├── ops/
│   ├── ci/
│   ├── load-testing/
│   ├── postgres/
│   └── supply-chain/
├── scripts/
│   ├── linux/
│   └── windows/
├── docs/
├── .github/
├── docker-compose.yml
├── docker-compose.dev.yml
├── docker-compose.prod.yml
└── README.md
```

`apps/server` adalah aplikasi FastAPI resmi untuk self-hosting; `apps/web` adalah
web/workbench resmi. `packages/cache` berisi library utama **semantix-cache**,
distribusi PyPI publik pertama yang direncanakan. `packages/client` berisi HTTP
client opsional/referensi **semantix-client** yang tetap dipelihara dan saat ini
tidak diwajibkan untuk rilis publik pertama tersebut. `ops` berisi tooling
operasional, sedangkan `scripts` berisi tooling repository/developer.

Backend dan frontend menggunakan kepemilikan feature-first. Lihat [Architecture](reference/architecture.md) untuk alur runtime dan batas paket.

### ✅ Pemeriksaan Kualitas

#### Persiapan cache backend

Cache tool backend dipusatkan di `apps/server/.cache/`. Aktifkan redirect cache bytecode Python sebelum menjalankan perintah backend.

Dari root repository:

Windows PowerShell:

```powershell
. .\apps\server\scripts\windows\enable_cache.ps1
```

Linux atau macOS:

```bash
source apps/server/scripts/linux/enable_cache.sh
```

Ketika sudah berada di dalam `apps/server/`:

Windows PowerShell:

```powershell
. .\scripts\windows\enable_cache.ps1
```

Linux atau macOS:

```bash
source scripts/linux/enable_cache.sh
```

Tanda titik di depan pada PowerShell dan `source` pada Bash diperlukan agar `PYTHONPYCACHEPREFIX` tetap aktif di terminal saat ini. Ruff, mypy, dan pytest menggunakan path cache-nya dari `apps/server/pyproject.toml`.

Untuk menghapus cache yang dihasilkan dan metadata editable-install:

```powershell
.\apps\server\scripts\windows\clean_artifacts.ps1
```

Untuk Linux atau macOS:

```bash
bash apps/server/scripts/linux/clean_artifacts.sh
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
cd apps/server
uv sync --locked --extra dev
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

Lihat [Development](guides/development.md) untuk toolchain lokal, aturan arsitektur, dan langkah-langkah kontribusi.

</details>

## Keamanan

Aplikasi memiliki tanggung jawab atas otorisasi, konteks generation, kredensial,
keamanan transport, dan penanganan data provider. Pemisahan namespace bukan otorisasi.
Lihat [SECURITY](SECURITY.md) untuk pelaporan dan batas deployment server,
serta panduan [provider embedded](../../embedded-providers.md) dan
[storage](../../embedded-storage.md) untuk tanggung jawab resource dan database pemanggil.

## 📄 Lisensi

Dilisensikan di bawah [MIT License](../../../LICENSE).
