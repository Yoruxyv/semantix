# Load testing dan runtime observability

Semantix menyertakan workload k6 yang terisolasi dan endpoint metrik JSON process-local. Jalankan load test hanya terhadap instance lokal atau instance lain yang dapat dibuang.

## Konfigurasi pengujian yang aman

Mock provider merupakan default yang direkomendasikan untuk load testing karena bersifat deterministik, tidak memerlukan network, dan tidak dapat menimbulkan biaya provider:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384

CACHE_BACKEND=memory
MAX_CACHE_SIZE=500
CACHE_TTL_SECONDS=3600
RATE_LIMIT=100000/minute
PROMPT_TYPO_CORRECTION_ENABLED=false
```

Buat ulang backend setelah mengubah `apps/server/.env`:

```powershell
docker compose up --build --force-recreate -d backend frontend
```

Gunakan pgvector hanya ketika storage backend itu sendiri sedang diuji. Jangan arahkan load test ke data production. Skenario near-capacity dapat melakukan evict entri di seluruh namespace karena kapasitas cache berlaku untuk embedding space yang aktif, bukan untuk satu namespace.

Setiap run memerlukan:

```text
LOAD_ACKNOWLEDGE_PROVIDER_CALLS=true
```

Acknowledgement ini diperlukan bahkan dengan mock provider agar perubahan konfigurasi provider tidak dapat secara diam-diam membuat traffic yang dapat ditagihkan.

## Skenario

| `SCENARIO`                    | Workload                                                           | Yang dibuktikan                                                          |
| ----------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `repeated-identical`          | Lima VU mengulangi satu prompt                                     | Cache yang warm mengurangi provider calls                                |
| `mixed-hits-misses`           | Prompt yang diulangi dan prompt yang berbeda                       | Counter hit/miss dan latency campuran tetap koheren                      |
| `concurrent-identical-misses` | Dua puluh VU mengirim satu prompt cold satu kali                   | Request coalescing yang sedang berlangsung membatasi generation duplikat |
| `high-cardinality`            | Prompt unik pada arrival rate tetap                                | Traffic yang didominasi miss tetap stabil                                |
| `threshold-changes`           | Traffic berjalan saat satu VU mengubah threshold secara bergantian | Update threshold tetap aman selama query traffic                         |
| `near-capacity`               | Menulis `MAX_CACHE_SIZE + 25` prompt unik                          | Ukuran cache tetap terbatas dan eviction tercatat                        |

Skenario threshold memerlukan
`LOAD_ALLOW_THRESHOLD_CHANGES=true`. Skenario ini mencatat threshold saat ini dan memulihkannya selama teardown.

Skenario capacity memerlukan `LOAD_ALLOW_CACHE_EVICTION=true`. Gunakan hanya terhadap cache yang terisolasi karena entri yang telah di-evict tidak dapat dipulihkan.

Mock embedding tidak memiliki makna semantik. Mock embedding menguji concurrency, instrumentation, limit, dan stabilitas endpoint. Gunakan real embedding provider hanya ketika mengevaluasi kualitas semantic threshold, setelah meninjau cost, rate limit, dan persyaratan data handling-nya.

## Menjalankan dengan k6 yang telah diinstal

Dari repository root di PowerShell:

```powershell
$env:BASE_URL = "http://localhost:8000"
$env:LOAD_ACKNOWLEDGE_PROVIDER_CALLS = "true"
$env:SCENARIO = "repeated-identical"
k6 run .\ops\load-testing\semantix.js
```

Ubah `SCENARIO` untuk menjalankan workload lainnya. Untuk skenario yang dilindungi:

```powershell
$env:SCENARIO = "threshold-changes"
$env:LOAD_ALLOW_THRESHOLD_CHANGES = "true"
k6 run .\ops\load-testing\semantix.js
```

```powershell
$env:SCENARIO = "near-capacity"
$env:CACHE_CAPACITY = "500"
$env:LOAD_ALLOW_CACHE_EVICTION = "true"
k6 run .\ops\load-testing\semantix.js
```

`CACHE_CAPACITY` harus sama dengan `MAX_CACHE_SIZE`. `P95_LIMIT_MS` mengontrol threshold P95 k6 dan secara default bernilai `5000`.

## Menjalankan k6 melalui Docker

Jalankan Semantix terlebih dahulu agar network `semantix_default` tersedia. Kemudian jalankan:

```powershell
docker run --rm `
  --network semantix_default `
  --volume "${PWD}\ops\load-testing:/scripts:ro" `
  --env BASE_URL=http://backend:8000 `
  --env LOAD_ACKNOWLEDGE_PROVIDER_CALLS=true `
  --env SCENARIO=repeated-identical `
  grafana/k6 run /scripts/semantix.js
```

Docker mengunduh image k6 pada run pertama. Bind mount bersifat read-only.

## Metrik runtime

Backend mengekspos:

```text
GET /api/v1/metrics
```

Workflow load-test lokal bawaan mengasumsikan authentication dinonaktifkan. Dalam deployment dengan token authentication, endpoint process-wide ini memerlukan global administrator token; principal dengan cakupan namespace menerima `403 Forbidden`.

Periksa dari PowerShell dalam local development:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/metrics |
  ConvertTo-Json
```

Untuk deployment dengan token authentication:

```powershell
$Headers = @{ Authorization = "Bearer $GlobalAdminToken" }
Invoke-RestMethod http://localhost:8000/api/v1/metrics -Headers $Headers |
  ConvertTo-Json
```

Field response:

| Field                          | Arti                                                     |
| ------------------------------ | -------------------------------------------------------- |
| `request_count`                | Interactive query request yang dimulai dalam process ini |
| `error_count`                  | Query workflow yang selesai dengan error                 |
| `cache_hits`                   | Cache lookup aktual yang dilayani dari cache             |
| `cache_misses`                 | Cache lookup aktual yang menghasilkan miss               |
| `provider_calls`               | Upaya generation, termasuk upaya yang gagal              |
| `in_flight_coalesced_requests` | Follower yang saat ini berbagi pekerjaan leader          |
| `average_latency_ms`           | Latency query selesai rata-rata sejak startup            |
| `p95_latency_ms`               | P95 nearest-rank dari sample terbaru yang dibatasi       |
| `latency_sample_size`          | Sample yang saat ini dipertahankan untuk P95             |
| `cache_size`                   | Entri saat ini dalam embedding space yang aktif          |
| `evictions`                    | Entri yang dihapus oleh size limit yang dikonfigurasi    |
| `expirations`                  | Entri yang dihapus setelah TTL expired                   |
| `uptime_seconds`               | Usia metrics collector                                   |
| `observed_at`                  | Timestamp snapshot UTC                                   |

Average dan P95 latency bernilai `null` sebelum sebuah query selesai. Window P95 dibatasi hingga 2,048 request yang selesai. Counter di-reset ketika process backend restart dan tidak disimpan di pgvector.

Validation error dan rate-limit rejection terjadi sebelum `QueryService` dan karena itu tidak termasuk dalam `request_count` atau `error_count`. Error pada level HTTP tetap terlihat dalam metric k6 `http_req_failed`.

## Membaca hasil

Pemeriksaan k6 memerlukan:

* lebih dari 99% check berhasil;
* kurang dari 1% HTTP request gagal;
* HTTP P95 di bawah `P95_LIMIT_MS`.

Script juga melaporkan:

* `semantix_cache_hits`;
* `semantix_cache_misses`;
* `semantix_provider_calls`;
* `semantix_query_errors`;
* `semantix_query_latency_ms`.

Counter hit dan miss k6 menjelaskan keputusan yang dikembalikan kepada setiap caller. Counter backend menjelaskan cache lookup aktual. Follower yang mengalami coalescing karena itu dapat menerima response miss tanpa melakukan lookup lain atau provider call. Selama traffic concurrent, gunakan counter backend `cache_misses` dan `provider_calls` untuk mengukur pekerjaan yang dihindari oleh coalescing.

Saat teardown, k6 mencetak snapshot metrik backend dan menghapus namespace yang dibuatnya. Bandingkan kedua tampilan:

* traffic yang berulang seharusnya memiliki hit yang jauh lebih banyak daripada provider calls;
* concurrent identical misses biasanya seharusnya menghasilkan satu provider call;
* traffic high-cardinality seharusnya didominasi miss;
* ukuran cache tidak boleh melebihi `MAX_CACHE_SIZE`;
* capacity run seharusnya meningkatkan eviction;
* coalesced gauge kembali ke nol setelah traffic berhenti.

Kecepatan provider, model warm-up, hardware, resource limit Docker, latency database, dan kondisi network semuanya memengaruhi latency absolut. Catat environment bersama setiap hasil performance daripada menganggap satu local run sebagai benchmark universal.

## Baseline kapasitas pada host Docker lokal

Baseline ini memakai stack hardened dengan PostgreSQL + pgvector dan koordinasi bersama, token authentication, provider mock deterministik, serta satu atau dua replika backend. k6 menjalankan profil cache-heavy, generation-heavy, mixed-policy, dan cold burst pada tangga 50, 100, 250, 500, dan 1.000 virtual user dengan jeda 2–4 detik. Hasil dan perintah reproduksi lengkap ada di [runbook berbahasa Inggris](../../../operations/load-testing.md#capacity-baseline-on-the-local-docker-host).

Pada host Windows 11 dengan AMD Ryzen 9 5900HX dan Docker Desktop, dua replika menyelesaikan soak cache-heavy 10 menit dengan 1.000 virtual user: 195.961 request (sekitar 324 RPS), P95 186 ms, dan nol kegagalan HTTP 4xx/5xx, transport, serta readiness yang disampel. Pada pengukuran generation-heavy yang distabilkan, satu replika menghasilkan sekitar 167 RPS/P95 4,86 detik; dua replika sekitar 270 RPS/P95 1,95 detik. Koneksi dan lock PostgreSQL mencapai batas terukur, sehingga hasil ini tidak menjamin skala linear atau kapasitas produksi.

Satu pengukuran mixed-policy dua replika pada 1.000 VU menghasilkan 1.585 respons 5xx; pengulangan terisolasi menghasilkan nol 5xx. Connection reset di gateway/upstream juga teramati pada pengukuran lain, tetapi akar penyebab lonjakan mixed-policy belum dikonfirmasi. Raw result lokal di `ops/load-testing/results/` diabaikan oleh Git; tabel, metodologi, dan batasan yang dapat ditinjau tersimpan dalam runbook berbahasa Inggris.
