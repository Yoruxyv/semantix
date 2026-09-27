# Benchmarking

Workspace Benchmark mengukur kualitas cache, latency, dan penghematan provider call terhadap prompt yang diurutkan dengan keputusan `HIT` atau `MISS` yang eksplisit. Workspace ini menggunakan cache in-memory yang terisolasi dan tidak pernah membaca atau menulis cache interaktif.

## Measured reference run

Hasil README berasal dari pengujian benchmark API yang benar-benar dijalankan:

| Properti run           | Nilai                                  |
| ---------------------- | -------------------------------------- |
| Run ID                 | `0488b35e487b4d0f94e151a97271847b`     |
| Started                | July 19, 2026 at 08:15:30 UTC          |
| Dataset                | Quick semantic safety set              |
| Queries                | 8                                      |
| Repetitions            | 1                                      |
| Cache reset            | Yes                                    |
| Threshold              | `0.92`                                 |
| Providers              | Hugging Face embeddings and generation |
| Prompt typo correction | Enabled                                |

Metric yang diukur:

| Metric                      |           Hasil |
| --------------------------- | --------------: |
| Cache hits / misses         |           4 / 4 |
| Provider calls / avoided    |           4 / 4 |
| Hit rate                    |             50% |
| Average latency             |       2051.5 ms |
| Median latency              |       1314.3 ms |
| P95 latency                 |       5550.0 ms |
| Average hit latency         |        330.3 ms |
| Average miss latency        |       3772.7 ms |
| Estimated latency saved     |     13,769.6 ms |
| False positives / negatives |           0 / 0 |
| Precision / recall / F1     | 1.0 / 1.0 / 1.0 |

Ini adalah satu observasi lokal, bukan klaim service-level. Aplikasi melaporkan tipe provider tetapi secara sengaja tidak mengekspos model identifier dalam health atau benchmark response. Provider load, model yang dipilih, network, normalization, machine resources, dan urutan dataset memengaruhi hasil.

Pada projected threshold `0.70`, skor yang sama yang diamati menghasilkan satu false positive. Pada `0.98`, skor tersebut menghasilkan satu false negative. Karena itu, README melaporkan threshold yang dievaluasi dan quality error bersama latency.

## Built-in dataset

| Dataset    | Queries | Expected hits | Expected misses | Coverage                                                                       |
| ---------- | ------: | ------------: | --------------: | ------------------------------------------------------------------------------ |
| `quick`    |       8 |             4 |               4 | Seed, exact duplicate, paraphrase, typo, unrelated, negation, different intent |
| `extended` |      12 |             6 |               6 | Quick set plus more paraphrase, typo, negation, and intent boundaries          |

Case diurutkan karena miss sebelumnya menjadi seed untuk expected hit berikutnya. Setiap case memiliki klasifikasi expected yang eksplisit.

## Menjalankan dari frontend

1. Buka http://localhost:4173/benchmarks.
2. Pilih dataset dan threshold.
3. Gunakan satu repetition dan aktifkan reset untuk run independen yang singkat.
4. Tinjau expected external generation-call warning.
5. Konfirmasikan run.
6. Periksa summary metrics, per-query evidence, threshold projections, dan similarity distributions.
7. Export JSON untuk hasil lengkap atau CSV untuk per-query evidence.

Benchmark request dapat memanggil generation provider yang dipilih. Tinjau biaya provider, rate limit, dan data handling sebelum melakukan konfirmasi.

Meninggalkan Benchmark workspace akan membatalkan browser request dan mencegah late response memperbarui page yang sudah di-unmount. Hal ini tidak menjamin bahwa pekerjaan provider yang sudah diterima oleh backend telah berhenti.

## Menjalankan melalui API

PowerShell:

```powershell
$body = @{
    dataset_id = "quick"
    threshold = 0.92
    repetitions = 1
    reset_cache_before_run = $true
    estimated_cost_per_request_usd = 0
    estimated_cost_per_1k_tokens_usd = 0
    allow_external_provider_calls = $true
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/benchmarks/run" `
    -ContentType "application/json" `
    -Body $body
```

`allow_external_provider_calls=true` wajib digunakan. Ini mencegah benchmark secara tidak sengaja membuat provider traffic tanpa diketahui.

## Interpretasi metric

* **Provider calls avoided** sama dengan jumlah query yang dilayani dari benchmark cache.
* **Precision** menjawab: dari hit yang dikembalikan, berapa banyak yang merupakan expected hit?
* **Recall** menjawab: dari expected hit, berapa banyak yang dikembalikan sebagai hit?
* **False positive** berarti cache mengembalikan response ketika dataset mengharapkan miss.
* **False negative** berarti cache menghasilkan response baru ketika reuse diharapkan.
* **Estimated latency saved** menggunakan average hit/miss latency yang diamati pada run.
* **Estimated token savings** menggunakan pendekatan sederhana berbasis karakter.
* **Estimated costs** menggunakan nilai opsional yang diberikan oleh operator.

Estimasi cost dan token merupakan alat bantu evaluasi, bukan catatan billing provider.

Threshold chart merupakan **frozen-candidate projection**. Chart tersebut mengklasifikasikan ulang nearest-match score yang diamati pada original run tanpa mengulangi cache write pada setiap alternate threshold. Karena candidate set tidak berkembang, estimasi quality, provider-savings, dan latency dapat berbeda dari ordered run aktual pada threshold tersebut. Projection tidak membuat provider call tambahan dan menggunakan average hit dan miss latency dari original run.

## Membandingkan run secara bertanggung jawab

Catat setidaknya:

* timestamp dan run ID;
* dataset dan ordering;
* threshold dan repetition count;
* cache-reset policy;
* embedding dan generation providers/models;
* prompt normalization settings;
* backend dan database mode;
* local hardware dan Docker resource limits;
* kondisi provider atau network yang relevan.

Jangan membandingkan run seolah-olah hanya threshold yang berubah ketika item lain dalam daftar tersebut juga berubah.
