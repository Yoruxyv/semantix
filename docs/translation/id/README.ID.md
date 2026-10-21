<!-- readme-source-sha256: 5151d092370146a2aa0fdbc3131ef2585b08f19fa502dedc8b6ed7e8966cdf93 -->

<div align="center">

<h1>🧠 Semantix</h1>

<p><strong>Semantic caching asinkron untuk Python.</strong></p>

<p>Penyimpanan memory, SQLite, MySQL, PostgreSQL, Redis, atau Valkey. Alur generation tetap Anda kendalikan.</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-555555?logo=python&amp;logoColor=FFD43B&amp;labelColor=3776AB" alt="Python 3.11–3.14" />
  <a href="../../../LICENSE"><img src="https://img.shields.io/badge/License-MIT-3DA639" alt="MIT license" /></a>
</p>

<p><sub><a href="../../../README.md">EN</a> · <a href="README.ID.md">ID</a></sub></p>

</div>

<p align="center">
  <a href="#instalasi-dan-contoh-awal">Mulai cepat</a> ·
  <a href="#cara-kerja-embedded">Cara kerja</a> ·
  <a href="#kompatibilitas-dan-backend-yang-didukung">Kompatibilitas</a> ·
  <a href="#dashboard-opsional--mulai-cepat">Dashboard</a> ·
  <a href="README.md">Dokumentasi</a>
</p>

**semantix-cache** adalah library Python embedded utama dan produk PyPI publik
pertama yang direncanakan.
API 0.1.0 hanya asinkron dan berjalan di dalam proses Python Anda. Tidak
memerlukan server Semantix, web UI, Docker, atau PostgreSQL.

| Gunakan Semantix | Mulai di sini |
| --- | --- |
| **Python embedded (utama)** | [Contoh dari source](#instalasi-dan-contoh-awal); tanpa Docker atau server resmi |
| **Backend/dashboard (opsional)** | [Mulai dashboard](#dashboard-opsional--mulai-cepat); aplikasi lokal opsional |
| **Persistensi PostgreSQL** | [Setup embedded](../../embedded/storage.md#new-postgresql-database) atau [setup dashboard](#opsional-persistensi-postgresql); inisialisasi eksplisit diperlukan |

## Instalasi dan contoh awal

> [!NOTE]
> **0.1.0 belum diterbitkan di PyPI.** Gunakan source GitHub atau wheel yang dibangun
> secara lokal. Nama distribusinya **semantix-cache**; impor Python-nya **semantix_cache**.

Instal Git, Python 3.11–3.14, dan [uv](https://docs.astral.sh/uv/getting-started/installation/).
Mulai dari checkout baru, atau gunakan checkout yang sudah ada dan masuk ke `packages/cache`.

Bash (Linux/macOS):

```bash
git clone https://github.com/Yoruxyv/semantix.git
cd semantix/packages/cache
```

Windows PowerShell:

```powershell
git clone https://github.com/Yoruxyv/semantix.git
Set-Location semantix/packages/cache
```

Lalu jalankan perintah berikut pada salah satu shell tersebut:

```bash
uv sync --locked
uv run --no-sync python -m examples.custom_integration
```

[Contoh integrasi kustom](../../../packages/cache/examples/custom_integration.py) yang
dipelihara memakai `AsyncSemanticCache`, `EmbeddingSpace`, dan `MemoryStore` tanpa
API key, Docker, server, atau database. Contoh selesai tanpa output jika berhasil
dan memunculkan error jika resolve pertama tidak menjalankan generation/write
atau resolve kedua tidak mengonfirmasi hit dan melewati generation. Vektor
deterministik dua dimensinya memverifikasi integrasi API, **bukan pemahaman semantik
atau kualitas pencocokan**. `provider_called` berarti callable generation lokal
milik aplikasi dijalankan; contoh ini tidak memanggil API provider.
Setup mengunduh dependensi Python; contoh itu sendiri berjalan offline.

Untuk proyek Python terpisah, lihat [instalasi source lokal dan wheel](../../../packages/cache/README.md#use-in-another-python-project).
Paket minimal bergantung pada NumPy dan Pydantic; dependensi jaringan provider serta
driver storage persisten bersifat opsional. Backend/dashboard adalah aplikasi
opsional terpisah; penggunaan embedded tidak melewatinya.

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
| **Storage** | MemoryStore, SQLite lokal, MySQL, PostgreSQL/pgvector, Redis, atau Valkey opsional |
| **Generation** | Callable asinkron milik Anda |

## Kompatibilitas dan backend yang didukung

Paket embedded `semantix-cache` mendukung **CPython 3.11–3.14**.
Tautan backend di bawah menjelaskan persyaratan setup dan rincian sertifikasi lengkap.

| Backend | Server/runtime yang didukung | Driver Python | Ketersediaan |
| --- | --- | --- | --- |
| [MemoryStore](../../embedded/storage.md#choose-a-store) | In-process, tidak persisten; tanpa database eksternal | Termasuk dalam core minimal; tanpa driver database | Embedded + server/dashboard opsional |
| [SQLiteStore](../../embedded/storage.md#sqlite-local-file-persistence) | SQLite yang ditautkan ke Python dan mendukung thread: **>=3.51.3, kecuali 3.52.0 yang ditarik**, atau hanya rilis upstream berpatch WAL **3.44.6 / 3.50.7** | `sqlite3` dari standard library Python; tanpa paket driver tambahan | Embedded + server satu proses |
| [MySQLStore](../../embedded/mysql.md#verified-compatibility) | Runtime: MySQL Community **8.4.x**; tersertifikasi di CI: **8.4.11 / 8.4.12** | `[mysql]`: PyMySQL versi persis **1.2.1, 1.2.2, atau 1.2.3** | Hanya embedded |
| [PgVectorStore](../../embedded/storage.md#verified-postgresql-combinations) | Pasangan PostgreSQL / pgvector terverifikasi: **16.15 / 0.8.7**, **17.10 / 0.8.5**, **18.6 / 0.8.7** | `[pgvector]`: `asyncpg>=0.31,<=0.32.0`; tersertifikasi **0.31.0 / 0.32.0** dalam kombinasi CI yang berbeda | Embedded + server/dashboard opsional |
| [RedisStore — Redis Open Source](../../embedded/redis.md#supported-versions) | Keluarga versi minor yang diterima dan batas patch minimumnya: **7.4.x >=7.4.11; 8.2.x >=8.2.10; 8.4.x >=8.4.7; 8.6.x >=8.6.7; 8.8.x >=8.8.3; 8.10.x >=8.10.2** | `[redis]`: redis-py versi persis **7.4.1**, versi persis **8.0.1**, atau rilis stabil **8.1.x** | Embedded + server/dashboard opsional |
| [RedisStore — Valkey](../../embedded/redis.md#valkey-912) | Produk server terpisah; versi persis **Valkey 9.1.2** | RedisStore dan extra `[redis]` yang sama; redis-py **8.1.0** terverifikasi, tanpa dependensi khusus Valkey | Embedded tersertifikasi; jalur server `redis` yang sudah ada (lihat di bawah) |

Versi yang **diterima saat runtime** lolos kebijakan kompatibilitas implementasi.
Kombinasi yang **diverifikasi di CI** adalah target persis yang dijalankan dalam
pengujian yang dipelihara, sebagaimana tercantum dalam panduan terkait. Penerimaan
versi tidak berarti setiap kombinasi server, extension, driver, Python, arsitektur,
OS, atau layanan terkelola telah diuji. Target PostgreSQL di atas **bukan versi
minimum runtime**.

Lockfile development tetap memakai asyncpg **0.31.0**, PyMySQL **1.2.3**, dan
redis-py **8.1.0**. Rentang resolver dependensi Redis lebih luas daripada versi yang
diterima saat runtime; lihat [kebijakan driver](../../embedded/redis.md). redis-py
**8.0.1** tidak berarti server Redis **8.0** didukung. MySQL 8.0/9.x, MariaDB,
dan varian terkelola berada di luar batas verifikasi MySQL.

Untuk SQLite, gunakan build upstream tepercaya atau verifikasi asal-usul patch
WAL dari vendor: nomor versi saja tidak mengautentikasi sebuah binary. Sertifikasi
Valkey mencakup kombinasi **9.1.2 / redis-py 8.1.0 / Linux x86-64 / CPython 3.14**,
dengan bukti tambahan dari klien Windows lokal. Rilis, driver, dan platform Valkey
lain belum tersertifikasi secara individual. Batas TLS, layanan terkelola, dan
failover tetap mengikuti panduan masing-masing; migrasi file data Redis/Valkey
belum terverifikasi.

[Server/dashboard opsional](../../guides/platform-storage.md) hanya menerima
`CACHE_BACKEND=memory`, `pgvector`, `redis`, atau `sqlite`. SQLite memerlukan
server native satu proses pada disk lokal tepercaya dan setup eksplisit; Compose
bawaan tidak didukung. MySQL tetap khusus embedded. Valkey memakai jalur `redis` yang sudah ada, tanpa ValkeyStore atau
selector `valkey` terpisah. Deployment dashboard Valkey secara end-to-end belum
tersertifikasi secara terpisah.

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
MemoryStore, SQLiteStore, MySQLStore/PgVectorStore/RedisStore opsional, atau implementasi Anda. Kebijakan lain mengatur
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

Lihat [identitas konteks dan migrasi](../../embedded/context-identity-and-migration.md)
untuk contoh scope model/tenant/knowledge/output, revisi embedding, dan migrasi aman.

### Normalisasi prompt

Normalisasi mengubah text untuk lookup berbasis embedding dan embedding baru saat
write. Generation dan cache entry tetap memakai application prompt sesuai aturan
kanonisasi yang sudah berlaku. Proses ini dapat membantu matching, tetapi tidak
memverifikasi kebenaran jawaban.

**Server** opsional mengoreksi typo bahasa Inggris yang umum dan pemisahan kata yang
tidak disengaja memakai SymSpell; fitur ini nonaktif secara default. Aktifkan saat
startup dengan `PROMPT_TYPO_CORRECTION_ENABLED=true` dan atur distance memakai
`PROMPT_TYPO_MAX_EDIT_DISTANCE=2`. Kapitalisasi umumnya dipertahankan: koreksi typo
bukan case-insensitive matching, dan perbedaan kapitalisasi saja tidak menjamin hit
ataupun miss. Pengaturan ini tidak dapat diedit dari dashboard.

Paket **semantix-cache** mandiri menyediakan callable sinkron `prompt_normalizer`;
instalasi paket saja tidak memasang SymSpell atau mengaktifkan behavior koreksi milik
server. Lihat [hook paket](../../../packages/cache/README.md#matching-text-preprocessing)
dan [panduan normalisasi](guides/prompt-typo-normalization.md) untuk contoh,
konfigurasi, dan batasannya. Perubahan preprocessing memerlukan isolasi storage yang
kompatibel dan transisi terkoordinasi; ikuti
[panduan identitas dan migrasi](../../embedded/context-identity-and-migration.md).

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

[Bukti numerik coalescing](../../embedded/observability.md) bersifat opsional melalui
`collect_coalescing_metrics=True`. Instrumentasi umum tetap dimiliki aplikasi.

Penggunaan `AsyncSemanticCache` yang terdokumentasi dicakup oleh
[kebijakan kompatibilitas 0.1.x paket](../../../packages/cache/README.md#01x-compatibility).

## Provider AI terverifikasi

Contoh hosted provider bersifat opsional, memerlukan kredensial Anda sendiri, dan
dapat menimbulkan biaya. Mulai dengan workflow MemoryStore tanpa kredensial di atas.

Adapter OpenAI, Gemini, dan Hugging Face yang dipelihara diuji melalui API nyata
pada **2026-10-05**,
mencakup embedding, generation, serta alur `AsyncSemanticCache` + MemoryStore
miss → generate → write → confirmed hit. Generation dilewati pada hit untuk
prompt yang diulang; pemeriksaan ini mencakup model yang tercantum dalam
[panduan provider](../../embedded/providers.md#010-verification).

| Provider | Embeddings | Generation | Verifikasi |
| --- | --- | --- | --- |
| OpenAI | Ya | Ya | ✅ Terverifikasi melalui API nyata |
| Gemini | Ya | Ya | ✅ Terverifikasi melalui API nyata |
| Hugging Face | Ya | Ya | ✅ Terverifikasi melalui API nyata |
| Ollama | Ya | Ya | Pernah diuji secara lokal; bukti verifikasi rilis saat ini belum lengkap |
| Anthropic | Tidak menyediakan API embedding native | Ya | ⚠️ Teruji kontrak; verifikasi langsung API pihak pertama masih tertunda |

**Jalur ekstensi publik terverifikasi.** Integrasi HTTPX untuk OpenAI, Gemini,
dan Hugging Face yang ditulis secara independen hanya memakai antarmuka
ekstensi publik `AsyncSemanticCache`, tanpa adapter provider bawaan atau helper
privat. Masing-masing menyelesaikan alur nyata miss → generate → write →
confirmed hit.

> **Anthropic:** Adapter generation dicakup pengujian kontrak dan regresi
> deterministik, tetapi belum diverifikasi langsung melalui API Anthropic pihak
> pertama untuk 0.1.0. Anthropic tidak menyediakan API embedding native; pasangkan
> generation dengan adapter embedding mana pun yang didukung. Kontribusi dari
> pengguna dengan akses API Anthropic pihak pertama milik sendiri diterima untuk
> verifikasi, laporan kompatibilitas yang dapat direproduksi, serta perbaikan
> terfokus dengan pengujian regresi jika cacat telah direproduksi.

Adapter bawaan berada di `semantix_cache.adapters`, di luar impor root minimal.
Pilih model dan identitas embedding-space secara eksplisit, serta berikan HTTPX
client yang dipinjam. Extra HTTP opsional tidak memasang SDK provider. Lihat
[provider embedded dan integrasi kustom](../../embedded/providers.md) untuk
konfigurasi dan jalur provider kustom.

API provider berkembang secara independen dari Semantix. Saya berniat menjaga
integrasi yang dipelihara tetap sesuai; laporan kompatibilitas yang dapat
direproduksi dan perbaikan terfokus sangat diterima. Jangan sertakan API key,
kredensial, atau respons provider mentah dalam issue, commit, log, atau fixture.

## Storage embedded

Mulai dengan MemoryStore untuk state process-local yang terbatas. Lihat
[tabel kompatibilitas](#kompatibilitas-dan-backend-yang-didukung) untuk versi yang
diterima, target terverifikasi, serta ketersediaan embedded dibandingkan server.

Untuk persistensi lokal, `semantix_cache.stores.sqlite.SQLiteStore` memiliki file
khusus dan worker sendiri, dengan setup eksplisit. Periksa runtime yang ditautkan
ke Python, dukungan thread, serta asal-usul patch WAL; versi Python saja tidak
cukup. Dari `packages/cache`, jalankan
`uv run --no-sync python -m examples.sqlite_cache` untuk memeriksa miss/write/hit
dan pembukaan ulang tanpa kredensial. Lihat
[setup dan batas SQLite](../../embedded/storage.md#sqlite-local-file-persistence)
untuk pemindaian float64 lengkap yang dibatasi, kepemilikan file, dan batas pembatalan.

`connect()` tidak membuat atau mengadopsi file. Tidak ada extra SQLite atau
dependensi runtime tambahan. Contoh tersebut memverifikasi integrasi API, bukan
pemahaman semantik. Pemindaian lengkap dibatasi 5.000 entri, 16.000 dimensi, dan
`capacity * dimensions * 8 <= 64 MiB`; RSS total lebih besar. Setiap hit menulis
melalui lock writer seluruh file. Gunakan disk lokal privat dan hentikan pekerjaan
aktif sebelum menutup store. Panduan yang sama menjelaskan TTL berdasarkan jam
host, pembatalan di sekitar COMMIT, pemulihan, dan durabilitas.

Opsional `semantix_cache.stores.mysql.MySQLStore` memakai extra `[mysql]` dari wheel
lokal, worker milik store, TLS terverifikasi, serta setup eksplisit pada database
khusus MySQL Community 8.4.x. Hosted CI mencakup kedua rilis server tersertifikasi
dan ketiga versi PyMySQL yang diterima, dalam kombinasi yang tercantum di
[panduan MySQL](../../embedded/mysql.md#verified-compatibility). Baca panduan itu
untuk grant dengan izin minimum, verifier schema terkunci, pencarian float64 eksak,
deadline, ketidakpastian COMMIT, dan pemulihan konstruksi gagal yang dibatasi.

`semantix_cache.stores.redis.RedisStore` memakai `[redis]` untuk Redis Open Source
atau Valkey versi persis 9.1.2. Keduanya memerlukan inisialisasi binding eksplisit
dan primary standalone yang dapat ditulis, diakses langsung, serta memakai
**noeviction**. Operator bertanggung jawab atas persistensi, backup, TLS, dan
pemulihan; Cluster, Sentinel, pembacaan dari replika, dan failover otomatis tidak
didukung. Lihat [setup dan batas Redis serta Valkey](../../embedded/redis.md).

Opsional `semantix_cache.stores.pgvector.PgVectorStore` mempertahankan data
antarproses/restart melalui database PostgreSQL yang dikendalikan aplikasi. Siapkan
extension vector dan inisialisasi schema cache terpisah yang bertanda secara
eksplisit; operasi cache normal tidak menjalankan DDL. Runtime memeriksa penanda
kepemilikan, versi, dan checksum migrasi, bukan fingerprint katalog lengkap.
Lindungi perubahan schema di luar migrasi.

`PgVectorStore.connect()` dapat memunculkan error bertipe dan tidak mengembalikan
store yang dapat digunakan jika gagal. Aplikasi menentukan pemulihan atau keputusan
menggagalkan startup; lihat [kegagalan koneksi PostgreSQL](../../embedded/storage.md#connections-cancellation-and-failures).

Lihat [storage embedded dan database pengguna](../../embedded/storage.md) untuk
akses runtime dengan izin minimum, kepemilikan pool, migrasi, dan store kustom.
pgvector menyimpan vektor float32; skor dekat threshold dapat berbeda dari scoring
float64 MemoryStore.

## Titik ekstensi

Berikan EmbeddingAdapter struktural (`embedding_space` dan `embed` asinkron),
GenerationCallable asinkron yang mengembalikan teks selesai yang disetujui, atau
CacheStore struktural. Tidak perlu subclass atau registry. Alur streaming/RAG/tools
dapat memakai `get`/`set` di sekitar teks akhir yang disetujui; Semantix tidak
menjalankan workflow aplikasi tersebut.

## Contoh

- [Embedding dan generation kustom](../../../packages/cache/examples/custom_integration.py).
- [CacheStore kustom](../../../packages/cache/examples/custom_store.py) dan [kit conformance untuk pengembang](../../embedded/cache-store-conformance.md).
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

<a id="-mulai-cepat"></a>

## Dashboard Opsional — Mulai Cepat

<a id="prasyarat"></a>

Instal Git, Python 3.11–3.14, dan Docker Desktop atau Docker CLI/Engine 23+
(API 1.42+) dengan Compose 2.20+. Jalankan engine Docker lokal. Python pada host
hanya diperlukan launcher development; dependency backend tetap di Docker.

<a id="1-clone-repository"></a>

Gunakan [checkout di atas](#instalasi-dan-contoh-awal) dan jalankan dari **root
repository** (`cd ../..` jika masih berada di `packages/cache`). Untuk konfigurasi
baru, salin contoh; jika `apps/server/.env` sudah ada, pertahankan dan edit file itu:

```bash
cp apps/server/.env.example apps/server/.env
```

Di PowerShell, gunakan `Copy-Item apps/server/.env.example apps/server/.env`.

<a id="2-konfigurasi-development-lokal"></a>

Atur nilai berikut dalam `apps/server/.env` yang **tidak dilacak Git**, dengan
mempertahankan default contoh lainnya, untuk dashboard MemoryStore tanpa kredensial:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384
CACHE_BACKEND=memory
EVALUATION_DATASET_STORAGE=session
EVALUATION_RUN_HISTORY_STORAGE=disabled
COORDINATION_BACKEND=memory
AUTH_MODE=disabled
AUTH_PRINCIPALS=[]
TRUSTED_PROXY_CIDRS=[]
MAX_REQUEST_BODY_BYTES=65536
```

<a id="3-jalankan-stack-development-lengkap"></a>

Lalu mulai dashboard:

```bash
python scripts/dev.py up
```

Atau gunakan `uv run --no-project scripts/dev.py up`. Launcher menunggu readiness
backend sebelum memulai frontend; konfigurasi ini tidak memerlukan database atau
API key provider. Build pertama dapat mengunduh image dan dependency.

<a id="4-buka-aplikasi"></a>

Buka **<http://localhost:4173>** (atau URL yang dicetak untuk port pilihan Anda).
Respons mock hanyalah contoh deterministik; cache memory/data sesi hilang saat
backend dimulai ulang. Autentikasi dinonaktifkan hanya untuk **penggunaan lokal
tepercaya**; jangan mengekspos stack development ini ke publik.

Untuk [provider lain](guides/providers.md), storage persisten, atau startup
langsung hanya dengan Docker, ikuti [Getting started](guides/getting-started.md#development-lokal), termasuk
[kredensial/setup PostgreSQL](guides/getting-started.md#kredensial-runtime-postgresql)
dan [Compose langsung lanjutan](guides/getting-started.md#lanjutan-docker-compose-langsung).

<details>
<summary>Server/workbench opsional: tur, setup Docker, dan bukti deployment</summary>

![Monitor Semantix menampilkan cache hit, bukti similarity, dan panggilan provider yang dilewati](../../assets/screenshots/monitor-decision.png)

*Tampilan Semantix asli dengan provider Hugging Face dan contoh prompt.*

---

### ✨ Workspace server opsional

| Workspace | Tujuan |
|---|---|
| **Monitor** | Mengirim probe kebijakan dalam namespace dan memeriksa hit, miss, latensi, prompt yang cocok, serta bukti similarity |
| **Cache Inspector** | Mencari entri, memeriksa metadata, menghapus record, membersihkan namespace dengan aman |
| **Evaluations** | Mengukur precision, recall, false hit, dan false miss; memeriksa bukti kasus terfilter serta mengekspor hasil run |
| **Observability** | Melacak metrik proses dan memeriksa diagnostik runtime read-only yang aman untuk reproduksibilitas evaluasi |

### Tur produk

Workbench server opsional memeriksa cache server yang terhubung, menjalankan
evaluasi berurutan, dan mendiagnosis server tersebut. Workbench tidak mengamati
cache embedded dari sembarang proses aplikasi. Demo lokal Hugging Face menampilkan
workspace yang sama. Tangkapan layar di bawah menunjukkan UI saat ini; pilih gambar
untuk membuka resolusi aslinya.

#### Cache Inspector

Cari prompt tersimpan dan periksa usia, jumlah hit, kedaluwarsa, serta metadata
cache tanpa menampilkan embedding mentah.

[![Cache Inspector menampilkan entri cache contoh yang aman dengan jumlah hit dan TTL](../../assets/screenshots/cache-inspector.png)](../../assets/screenshots/cache-inspector.png)

#### Evaluations

Jalankan dataset terisolasi dan periksa perilaku cache, panggilan provider,
latensi, serta hasil klasifikasi yang terukur. Simpan URL `/evaluations?view=runs`,
`?view=datasets`, `?view=history`, atau `?view=reuse-quality` untuk membuka kembali
view yang dipilih. Reuse quality menampilkan
[bukti statis library yang ditinjau dan metodologinya](../../../packages/cache/benchmarks/reuse_quality/README.md),
dengan hasil calibration dan held-out terpisah dari run server berurutan. Hasil
sintetis ini tidak membuktikan kualitas produksi atau threshold yang aman secara universal.

[![Evaluations menampilkan hasil dataset semantic safety bawaan](../../assets/screenshots/evaluations-results.png)](../../assets/screenshots/evaluations-results.png)

#### Observability

Periksa diagnostik runtime yang aman, kategori provider, fingerprint pencocokan,
readiness storage, dan sinyal reproduksibilitas lainnya.

[![Observability menampilkan diagnostik runtime dan readiness provider](../../assets/screenshots/observability-diagnostics.png)](../../assets/screenshots/observability-diagnostics.png)

Kapabilitas inti:

- embedding provider dan generation provider yang independen;
- penyimpanan MemoryStore, PostgreSQL/pgvector, atau RedisStore;
- TTL, eviction LRU, namespace, request privat, dan kebijakan read/write;
- kontrol Monitor sesuai peran, minimisasi trace privat, dan tautan hit langsung
  ke detail Cache yang diotorisasi;
- penggabungan request (request coalescing) untuk miss identik yang terjadi bersamaan;
- normalisasi prompt yang menyadari typo (opsional);
- threshold cache global yang terlihat dan diagnostik runtime read-only khusus
  global admin, dengan kategori provider yang aman, fingerprint, readiness,
  dan batas evaluasi;
- peran token dan otorisasi namespace untuk deployment hardened;
- provider mock deterministik untuk pengujian lokal yang aman;
- cache evaluasi terpisah per run, confusion matrix lengkap, serta sweep threshold
  terbatas yang dapat dikonfigurasi dengan kandidat yang dibekukan;
- dataset evaluasi JSON berversi yang hanya hidup selama sesi, dengan pratinjau
  tanpa panggilan provider, validasi ketat, dan tanpa persistensi di browser;
- katalog dataset evaluasi PostgreSQL opsional dengan otorisasi namespace,
  penyimpanan eksplisit, retensi terbatas, dan tanpa menyimpan hasil run.

### Endpoint dan operasi dashboard

| Layanan | Alamat |
|---|---|
| Frontend | <http://localhost:4173> |
| Backend | <http://localhost:8000> |
| Dokumentasi API | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness | <http://localhost:8000/ready> |
| Metrik runtime | <http://localhost:8000/api/v1/metrics> |
| Diagnostik runtime | <http://localhost:8000/api/v1/diagnostics> |
| PostgreSQL dari host (hanya profil persisten) | `127.0.0.1:5433` |

Kirim prompt Monitor unik dua kali: harapkan miss diikuti hit yang terkonfirmasi.
Respons mock adalah contoh deterministik, bukan keluaran model yang di-host.

Perintah yang berguna:

```bash
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml logs -f backend
docker compose -f docker-compose.dev.yml down
```

`down` tetap mempertahankan named volume. Menambahkan `--volumes` akan menghapus data PostgreSQL lokal.

#### Opsional: persistensi PostgreSQL

Untuk entri cache dan dataset evaluasi tersimpan yang persisten, pertahankan
pengaturan provider mock di atas dan ubah nilai berikut di `apps/server/.env`.
Ganti placeholder URL dengan login runtime terpisah yang dibuat di bawah;
lakukan URL-encoding pada kredensial bila perlu. Pertahankan volume yang ada dan
backup database yang sudah ada sebelum setup.

```env
CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix_runtime:replace-runtime-password@postgres:5432/semantix
DATABASE_MIGRATION_MODE=external
EVALUATION_DATASET_STORAGE=postgres
EVALUATION_DATASET_DEFAULT_RETENTION_DAYS=30
```

Untuk volume baru yang dibuat launcher, ikuti
[kredensial PostgreSQL](guides/getting-started.md#kredensial-runtime-postgresql),
lalu jalankan `python scripts/dev.py up`. Akun runtime terbatas dibuat dengan
password yang Anda konfigurasikan, melalui setup terpisah. Role/data lama tidak
diperbaiki atau ditimpa otomatis. Password ini bukan dari provider eksternal.

**Compose langsung (lanjutan):** langkah berikut memerlukan wewenang operator eksplisit.
Jalankan hanya PostgreSQL dan tunggu health check-nya:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up -d --wait --wait-timeout 60 postgres
```

Database development hanya membuat role bootstrap lokal `semantix`. Jangan
menggunakan role berhak istimewa tersebut dalam `DATABASE_URL` backend. Muat
variabel operator berikut secara aman ke shell, tanpa menyimpan kredensial
migration di `apps/server/.env`, tracked files, shell history, atau logs:

- `DATABASE_RUNTIME_ROLE`: nama login terbatas pada `DATABASE_URL`;
- `MIGRATION_DATABASE_URL`: koneksi bootstrap/migration untuk database development
  ini, dengan wewenang mengaktifkan pgvector, menginisialisasi schema, dan memberikan akses.

Di dalam container, kedua URL menggunakan `postgres:5432/semantix`. Tool pada host
menggunakan `127.0.0.1:5433` secara default (`POSTGRES_PORT` dapat mengubah port
publikasi). Untuk volume yang sudah ada, gunakan kredensial aktual dan lakukan
backup sebelum setup.

Untuk role runtime yang benar-benar belum ada, buka psql dengan wewenang bootstrap lokal:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector exec postgres psql -X --set ON_ERROR_STOP=1 --username semantix --dbname semantix
```

Di psql, buat role terbatas dan masukkan password dari `DATABASE_URL` pada prompt
`\password` yang tidak menampilkannya. Jika role sudah ada, berhenti dan periksa
hak/kredensial secara terpisah; jangan reset password-nya.

```sql
CREATE ROLE semantix_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
GRANT CONNECT ON DATABASE semantix TO semantix_runtime;
\password semantix_runtime
\q
```

Prompt password menghindari plaintext password pada SQL dan argumen proses.
Migration memberikan akses schema/table, bukan membuat login.
Di PowerShell, masukkan wewenang migration melalui prompt tersamar:

```powershell
$env:DATABASE_RUNTIME_ROLE = 'semantix_runtime'
$env:MIGRATION_DATABASE_URL = [pscredential]::new(
    'migration', (Read-Host 'URL database migration' -AsSecureString)
).GetNetworkCredential().Password
```

Pada shell lain, muat dua variabel operator yang sama secara aman tanpa menulis
secret dalam shell history atau argumen.

Jalankan setup eksplisit dalam container backend sekali jalan dan lanjutkan hanya
jika perintah berhasil exit:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector run --rm --no-deps --build -e DATABASE_MIGRATION_MODE=external -e MIGRATION_DATABASE_URL -e DATABASE_RUNTIME_ROLE backend python -m app.infrastructure.migrate
```

Image backend menyediakan Python, dependencies, dan working directory
`/apps/server`. Container mewarisi pengaturan schema/prefix cache dan evaluasi dari
`apps/server/.env`; samakan dengan runtime. Flag `-e` meneruskan variabel operator
dari shell hanya ke job ini. Bersihkan variabel operator setelahnya.

Startup cache biasa memvalidasi schema resmi dan tidak pernah menginisialisasinya.
`DATABASE_MIGRATION_MODE=auto` hanya berlaku untuk fitur PostgreSQL lain yang aktif,
termasuk penyimpanan evaluasi. Compose development membaca mode dari
`apps/server/.env`; pertahankan nilai `external` untuk role runtime terbatas.
Setelah setup berhasil, jalankan stack persisten dengan satu perintah pada kedua OS:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d --wait --wait-timeout 120 postgres backend frontend
```

Ini menjalankan frontend React dengan Vite hot reload dan FastAPI dengan Uvicorn
reload setelah setup database eksplisit. Pastikan `/ready` mengembalikan HTTP 200,
lalu kirim prompt Monitor unik dua kali: harapkan miss diikuti hit dan entri yang
dapat dibaca di Cache Inspector. Table cache resmi yang kosong segera setelah
setup adalah valid; setup tidak menyalin baris cache legacy yang dipertahankan.
Lihat [setup storage server](../../guides/platform-storage.md) untuk kepemilikan dan
validasi schema. Prosedur ini tetap untuk development lokal yang tepercaya; gunakan
[deployment yang diperkeras](operations/deployment.md) sebelum berbagi dengan pengguna tak tepercaya.

### 🔌 Provider

Embedding provider dan generation provider dipilih secara independen.

| Provider | Embedding | Generation | Kredensial |
|---|:---:|:---:|:---:|
| Hugging Face | Ya | Ya | Diperlukan |
| OpenAI | Ya | Ya | Diperlukan |
| Anthropic | Tidak menyediakan API embedding native | Ya (teruji kontrak; verifikasi langsung tertunda) | Diperlukan |
| Gemini | Ya | Ya | Diperlukan |
| Ollama | Ya | Ya | Tidak diperlukan secara lokal |
| Mock | Ya | Ya | Tidak diperlukan |

Hanya pengaturan yang diperlukan oleh kapabilitas yang dipilih yang akan divalidasi. Lihat [Providers](guides/providers.md) untuk contoh konfigurasi dan catatan jaringan.

### 🛡️ Deployment Development dan Hardened

| Mode | Penggunaan yang dituju | Perilaku utama |
|---|---|---|
| **Development** | Satu developer lokal yang tepercaya | Hot reload, port loopback, autentikasi dinonaktifkan, setup cache persisten terpisah |
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

Aplikasi Python eksternal dapat memakai distribusi `semantix-client` yang dapat
diinstal secara mandiri melalui HTTP API publik. Kode Python mengimpornya sebagai
`semantix_client`. Paket ini menyediakan client sinkron (`SemantixClient`) dan
asinkron (`AsyncSemantixClient`) bertipe tanpa memasang atau mengimpor modul
internal backend Semantix.

Paket ini belum diterbitkan di PyPI; instal dari wheel yang dibangun atau langsung
dari repository sesuai panduan lengkap.

```python
from semantix_client import SemantixClient

with SemantixClient(base_url="http://localhost:8000") as client:
    result = client.query("Explain semantic caching", namespace="default")

print(result.response, result.cache_hit)
```

[Panduan lengkap Python SDK →](../../../packages/client/README.md)

## Dokumentasi

[Indeks dokumentasi](README.md) memisahkan panduan embedded dan server.

| Mulai di sini | Gunakan untuk |
| --- | --- |
| [Panduan paket cache](../../../packages/cache/README.md) | Quick start embedded, kebijakan, kepemilikan, dan kompatibilitas kanonis |
| [Provider embedded](../../embedded/providers.md) | Adapter yang dipelihara dan embedding/generation kustom |
| [Identitas konteks dan migrasi](../../embedded/context-identity-and-migration.md) | Scope eksplisit, identitas model/tenant/knowledge/output, revisi embedding, dan migrasi aman |
| [Storage embedded](../../embedded/storage.md) | Memory, SQLite, MySQL, PostgreSQL, Redis, Valkey, dan database milik pengguna |
| [Contoh](../../../packages/cache/examples/) | Generation dan store yang dikendalikan aplikasi |
| [Kualitas reuse yang ditinjau](../../../packages/cache/benchmarks/reuse_quality/README.md) | Baseline semantik, kontrol leksikal, pemisahan calibration/held-out, dan batas bukti |
| [Metodologi benchmark](../../../packages/cache/benchmarks/README.md) | Workload runtime lokal yang reproducible beserta batasannya |
| [Getting started server](guides/getting-started.md) | Environment dan workflow Docker untuk server opsional |
| [Panduan HTTP client](../../../packages/client/README.md) | Client bertipe untuk server kompatibel yang sudah berjalan |
| [Arsitektur server](reference/architecture.md) | Kepemilikan fitur dan alur request |
| [Hardened deployment](operations/deployment.md) | Auth server, TLS, role database, dan validasi |

## Berkontribusi

Lihat [CONTRIBUTING](CONTRIBUTING.md), [pemeriksaan contributor cache](../../../packages/cache/README.md#contributor-checks),
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
npm run format:check
npm run imports:check
npm run test:coverage
npm run build
npm run bundle:check
```

Lihat [Development](guides/development.md) untuk toolchain lokal, aturan arsitektur, dan langkah-langkah kontribusi.

</details>

## Keamanan

Aplikasi memiliki tanggung jawab atas otorisasi, konteks generation, kredensial,
keamanan transport, dan penanganan data provider. Pemisahan namespace bukan otorisasi.
Lihat [SECURITY](SECURITY.md) untuk pelaporan dan batas deployment server,
serta panduan [provider embedded](../../embedded/providers.md) dan
[storage](../../embedded/storage.md) untuk tanggung jawab resource dan database pemanggil.

## 📄 Lisensi

Dilisensikan di bawah [MIT License](../../../LICENSE).
