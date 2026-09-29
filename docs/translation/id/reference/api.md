# API

FastAPI menyajikan dokumentasi interaktif di <http://localhost:8000/docs>.
Error aplikasi menggunakan objek stabil yang berisi `error` dan `detail`.

## Endpoint

| Method | Endpoint | Tujuan |
|---|---|---|
| `POST` | `/api/v1/query` | Mengirimkan sebuah kueri |
| `GET` | `/api/v1/cache/stats` | Membaca statistik cache global atau per-namespace |
| `GET` | `/api/v1/cache/threshold` | Membaca similarity threshold yang aktif |
| `PUT` | `/api/v1/cache/threshold` | Memperbarui threshold aktif |
| `GET` | `/api/v1/cache/entries` | Mencari, mengurutkan, dan melakukan paginasi terhadap metadata cache yang aman |
| `GET` | `/api/v1/cache/entries/{cache_key}` | Membaca satu record metadata cache yang aman |
| `DELETE` | `/api/v1/cache/entries/{cache_key}` | Menghapus satu entri |
| `DELETE` | `/api/v1/cache` | Membersihkan seluruh entri atau satu namespace |
| `GET` | `/api/v1/benchmarks/datasets` | Menampilkan daftar dataset benchmark terkontrol |
| `POST` | `/api/v1/benchmarks/run` | Menjalankan benchmark yang terisolasi |
| `GET` | `/api/v1/metrics` | Membaca metrik agregat process-local (hanya admin global) |
| `GET` | `/health` | Membaca status kesehatan aplikasi dan tipe provider |
| `GET` | `/ready` | Memeriksa kesiapan penyimpanan yang aktif |

## Request kueri

```json
{
  "prompt": "Explain semantic caching",
  "namespace": "default",
  "cache_enabled": true,
  "cache_read_enabled": true,
  "cache_write_enabled": true,
  "private": false
}
```

Hanya `prompt` yang wajib diisi. `cache_enabled=false` akan menimpa (override) kedua flag granular. `private=true` juga menonaktifkan read dan write. Menonaktifkan read sambil membiarkan write tetap aktif akan me-refresh entri dari provider; menonaktifkan write tetap mengizinkan respons cache yang eligible untuk digunakan.

Lihat [Cache policies](../guides/cache-policies.md) untuk urutan prioritas dan aturan namespace.

## Bukti respons kueri

```json
{
  "response": "A previously generated answer",
  "cache_hit": true,
  "similarity_score": 0.967,
  "similarity_threshold": 0.92,
  "matched_prompt": "What is semantic caching?",
  "matched_cache_key": "29769c1b33db361734e377b6e20368cd58ab3d7d048545073402ad830a0513ab",
  "cache_entry_created_at": "2026-07-17T10:00:00Z",
  "cache_entry_age_seconds": 18.4,
  "generation_skipped": true,
  "provider_called": false,
  "latency_ms": 7.2
}
```

Kesebelas key respons selalu ada; field bukti yang nullable berisi `null` jika nilainya tidak tersedia. Pada saat cache miss, field matched-entry bernilai `null`. Similarity terdekat mungkin tetap ada meski suatu entri ada namun tidak memenuhi threshold. Leader dari sebuah cache miss yang di-generate melaporkan `provider_called=true`; follower yang di-coalesce tetap berupa cache miss namun melaporkan `generation_skipped=true` dan `provider_called=false` karena ia menunggu (await) hasil dari leader.

Embedding dan respons inspector yang lengkap tidak pernah diekspos melalui kontrak query atau cache-management.

## Kueri cache inspector

`GET /api/v1/cache/entries` menerima:

- `namespace`: namespace eksak, bersifat opsional;
- `search`: fragmen prompt case-insensitive, bersifat opsional;
- `sort`: `newest`, `oldest`, `most_hit`, atau `nearest_expiry`;
- `offset`: offset hasil berbasis nol (zero-based);
- `limit`: ukuran halaman dari 1 hingga 100.

Respons berisi `items`, `total`, `offset`, `limit`, dan `has_more`. Item mencakup prompt asli dan pratinjau (preview) respons yang dipotong, namun tidak menyertakan embedding maupun respons cache yang lengkap.

`GET /api/v1/cache/stats?namespace=...` dan
`DELETE /api/v1/cache?namespace=...` menyasar satu namespace. Mengabaikan parameter tersebut akan mengembalikan statistik global atau membersihkan embedding space yang aktif.

## Metrik runtime

`GET /api/v1/metrics` mengembalikan nilai agregat process-local. Dengan autentikasi token diaktifkan, endpoint ini memerlukan principal `admin` dengan
`namespaces:["*"]`. Viewer, operator, dan admin namespace yang bercakupan (scoped) akan menerima `403 Forbidden`. Development lokal dengan autentikasi dinonaktifkan tetap mempertahankan akses melalui admin global implisitnya.

Counter ini bersifat global terhadap proses backend dan tidak bercakupan per-namespace. Pengguna namespace sebaiknya menggunakan `GET /api/v1/cache/stats`, yang menerapkan cakupan namespace yang mereka miliki otorisasinya.

```json
{
  "observed_at": "2026-07-19T08:00:00Z",
  "uptime_seconds": 3600.0,
  "request_count": 120,
  "error_count": 1,
  "cache_hits": 72,
  "cache_misses": 48,
  "provider_calls": 46,
  "in_flight_coalesced_requests": 0,
  "average_latency_ms": 325.4,
  "p95_latency_ms": 1280.2,
  "latency_sample_size": 120,
  "cache_size": 48,
  "evictions": 3,
  "expirations": 2
}
```

Counter akan direset saat backend restart. Sampel P95 yang dibatasi (bounded) menyimpan paling banyak 2.048 latensi kueri yang telah selesai. Kegagalan validasi dan penolakan rate-limit terjadi sebelum application service kueri dan karenanya tidak termasuk dalam counter request/error-nya.

Untuk semantik load-testing dan perbedaan antara keputusan caller dan cache lookup yang sebenarnya, lihat [Load testing](../operations/load-testing.md).
