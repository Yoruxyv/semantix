# Dokumentasi Semantix

Gunakan indeks ini untuk menemukan panduan terperinci untuk tugas yang sedang dikerjakan. Root repository [README](../../../README.md) tetap menjadi ringkasan singkat proyek dan quick start.

## Panduan

| Panduan                                                     | Gunakan untuk                                                                    |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [Tur produk](README.ID.md#tur-produk)                         | Cuplikan empat workspace aplikasi saat ini                                      |
| [Getting started](guides/getting-started.md)                | Environment file, local toolchain, workflow Docker, dan troubleshooting          |
| [Providers](guides/providers.md)                            | Konfigurasi Hugging Face, OpenAI, Anthropic, Gemini, Ollama, dan mock            |
| [pgvector](guides/pgvector.md)                              | Persistent cache storage, port, migrasi, dan verifikasi database                 |
| [Cache policies](guides/cache-policies.md)                  | Threshold, TTL, LRU, namespace, privacy, dan request coalescing                  |
| [Benchmarking](guides/benchmarking.md)                      | Dataset, metric, safeguard, projection, dan export                               |
| [Prompt normalization](guides/prompt-typo-normalization.md) | Perilaku dan batasan typo-correction opsional                                    |
| [Python SDK](../../../packages/client/README.md)                          | Instalasi dan penggunaan client HTTP sinkron dan asinkron                       |
| [Development](guides/development.md)                        | Toolchain yang didukung, pemeriksaan kualitas, aturan arsitektur, dan kontribusi |

## Reference

| Reference                                   | Gunakan untuk                                                        |
| ------------------------------------------- | -------------------------------------------------------------------- |
| [API](reference/api.md)                     | Endpoint, autentikasi, request, response, dan error contract         |
| [Architecture](reference/architecture.md)   | Runtime flow, feature ownership, boundary, dan deployment constraint |
| [Accessibility](reference/accessibility.md) | Ekspektasi aksesibilitas dan command verifikasi                      |

## Operations

| Runbook                                             | Gunakan untuk                                                             |
| --------------------------------------------------- | ------------------------------------------------------------------------- |
| [Hardened deployment](operations/deployment.md)     | Autentikasi, role, proxy, TLS, request limit, dan database permission     |
| [Operations and recovery](operations/recovery.md)   | Rotasi credential, backup, restore, cache rebuild, rollback, dan incident |
| [Load testing](operations/load-testing.md#baseline-kapasitas-pada-host-docker-lokal) | Baseline kapasitas, skenario k6 yang aman, dan runtime observability |
| [Supply-chain security](operations/supply-chain.md) | Image pin, security scan, artifact SBOM/provenance, dan dependency update |
