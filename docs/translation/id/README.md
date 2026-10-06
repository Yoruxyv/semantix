# Dokumentasi Semantix

Mulai dengan **semantix-cache** untuk caching Python embedded/in-process, tanpa
server Semantix. [README utama](README.ID.md) menjelaskan jalur instalasi 0.1.0
yang belum diterbitkan dan contoh MemoryStore tanpa kredensial.

Server/workbench resmi bersifat opsional. semantix-client adalah HTTP client
referensi yang dipelihara untuk server tersebut, bukan target PyPI publik pertama.

## Library Python embedded

Panduan embedded berikut tersedia dalam bahasa Inggris.

| Panduan | Gunakan untuk |
| --- | --- |
| [Paket cache](../../../packages/cache/README.md) | Penggunaan awal, kebijakan, hasil, lifecycle, dan kompatibilitas 0.1.x kanonis |
| [Provider embedded](../../embedded-providers.md) | Adapter yang dipelihara, extra opsional, dan embedding/generation kustom |
| [Identitas konteks dan migrasi](../../context-identity-and-migration.md) | Scope eksplisit, revisi embedding, contoh offline, dan migrasi aman |
| [Storage embedded](../../embedded-storage.md) | Memory, PostgreSQL/pgvector, dan database milik aplikasi |
| [Integrasi kustom](../../../packages/cache/examples/custom_integration.py) | Alur embedding dan generation asinkron yang sudah ada |
| [Store kustom](../../../packages/cache/examples/custom_store.py) | CacheStore struktural dan conformance bersama |
| [Contoh support persisten](../../../packages/cache/examples/persistent_support.py) | Inisialisasi eksplisit dan cache customer-support yang bertahan antarproses |
| [Benchmark runtime](../../../packages/cache/benchmarks/README.md) | Workload reproducible, profiling, dan batas pengukuran |
| [Eksperimen coalescing](../../../packages/cache/benchmarks/COALESCING.md) | Pengurangan kerja provider dan tradeoff latensi cold follower |

## Server/workbench dan HTTP client opsional

| Panduan                                                     | Gunakan untuk                                                                    |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [Tur produk](README.ID.md#tur-produk)                         | Cuplikan empat workspace aplikasi saat ini                                      |
| [Getting started](guides/getting-started.md)                | Environment file, local toolchain, workflow Docker, dan troubleshooting          |
| [Providers](guides/providers.md)                            | Konfigurasi Hugging Face, OpenAI, Anthropic, Gemini, Ollama, dan mock            |
| [Adapter provider kustom (Inggris)](../../guides/provider-extensions.md) | Registrasi adapter server tepercaya dan kontrak lifecycle |
| [pgvector](guides/pgvector.md)                              | Persistent cache storage, port, migrasi, dan verifikasi database                 |
| [Cache policies](guides/cache-policies.md)                  | Threshold, TTL, LRU, namespace, privacy, dan request coalescing                  |
| [Benchmarking](guides/benchmarking.md)                      | Dataset, metric, safeguard, projection, dan export                               |
| [Riwayat evaluasi (Inggris)](../../guides/evaluation-history.md) | Riwayat agregat persisten, retensi, namespace, dan pemulihan |
| [Prompt normalization](guides/prompt-typo-normalization.md) | Perilaku dan batasan typo-correction opsional                                    |
| [Python SDK](../../../packages/client/README.md)                          | Instalasi dan penggunaan client HTTP sinkron dan asinkron                       |
| [Development](guides/development.md)                        | Toolchain yang didukung, pemeriksaan kualitas, aturan arsitektur, dan kontribusi |

## Reference

| Reference                                   | Gunakan untuk                                                        |
| ------------------------------------------- | -------------------------------------------------------------------- |
| [API](reference/api.md)                     | Endpoint, autentikasi, request, response, dan error contract         |
| [Schema dataset evaluasi v1 (Inggris)](../../reference/evaluation-dataset-schema-v1.md) | Field JSON, validasi, batas, persistensi, dan retensi |
| [Architecture](reference/architecture.md)   | Runtime flow, feature ownership, boundary, dan deployment constraint |
| [Accessibility](reference/accessibility.md) | Ekspektasi aksesibilitas dan command verifikasi                      |

## Operations

| Runbook                                             | Gunakan untuk                                                             |
| --------------------------------------------------- | ------------------------------------------------------------------------- |
| [Hardened deployment](operations/deployment.md)     | Autentikasi, role, proxy, TLS, request limit, dan database permission     |
| [Kesiapan autoscaling terkelola (Inggris)](../../operations/autoscaling-readiness.md) | Kebijakan replika terbatas, kapasitas, readiness, draining, dan bukti perubahan skala |
| [Operations and recovery](operations/recovery.md)   | Rotasi credential, backup, restore, cache rebuild, rollback, dan incident |
| [Load testing](operations/load-testing.md#baseline-kapasitas-pada-host-docker-lokal) | Baseline kapasitas, skenario k6 yang aman, dan runtime observability |
| [Audit runtime produksi (Inggris)](../../operations/production-runtime-audit.md) | Keamanan topologi yang diuji, pemulihan, dan bukti beban |
| [Supply-chain security](operations/supply-chain.md) | Image pin, security scan, artifact SBOM/provenance, dan dependency update |
