<p align="center">
  <sub><a href="/docs/translation/id/CONTRIBUTING.md">ID</a> · <a href="../../../CONTRIBUTING.md">EN</a></sub>
</p>

# Berkontribusi pada Semantix

Terima kasih telah meluangkan waktu untuk meningkatkan Semantix.

Semantix adalah laboratorium semantic-cache local-first yang dibangun untuk membuat keputusan cache, perilaku provider, latency, dan trade-off kualitas dapat diamati. Kontribusi harus mempertahankan tujuan tersebut: perilaku harus tetap dapat diinspeksi, konfigurasi harus tetap eksplisit, dan klaim performance harus tetap dapat direproduksi.

Sebelum berkontribusi, harap baca:

* [Code of Conduct](CODE_OF_CONDUCT.md)
* [Security Policy](SECURITY.md)
* [Architecture](reference/architecture.md)
* [Development Guide](guides/development.md)
* [Cache Policies](guides/cache-policies.md)

## Cara berkontribusi

Kontribusi yang berguna mencakup:

* perbaikan bug;
* peningkatan accessibility dan usability frontend;
* adapter provider atau cache;
* test dan skenario load-test;
* dataset benchmark dan pengukuran yang dapat direproduksi;
* dokumentasi dan contoh;
* peningkatan performance yang didukung oleh evidence;
* reproduksi issue dan technical review.

Vulnerability keamanan tidak boleh dilaporkan melalui public issue. Ikuti [SECURITY.md](SECURITY.md).

## Sebelum membuka issue

Harap:

1. Cari issue dan pull request yang sudah ada.
2. Pastikan perilaku tersebut masih terjadi pada branch `main` terbaru.
3. Periksa dokumentasi yang relevan dan known limitations.
4. Kumpulkan contoh terkecil yang dapat direproduksi.
5. Hapus API keys, access tokens, passwords, private prompts, responses, dan personal data dari log atau screenshot.

Gunakan issue form repository untuk bug, feature request, dan improvement dokumentasi.

## Setup development

### Docker development workflow

Buat file environment backend:

```powershell
Copy-Item apps\server\.env.example apps\server\.env
```

Untuk setup development tanpa credential:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384
CACHE_BACKEND=memory
AUTH_MODE=disabled
```

Jalankan development stack dengan hot-reload:

```powershell
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d
```

Command yang berguna:

```powershell
docker compose -f docker-compose.dev.yml --profile pgvector ps
docker compose -f docker-compose.dev.yml --profile pgvector logs -f backend
docker compose -f docker-compose.dev.yml --profile pgvector down
```

Gunakan hardened stack hanya ketika memvalidasi konfigurasi yang berorientasi production. Lihat [Hardened deployment](operations/deployment.md) sebelum menjalankannya.

### Local backend workflow

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), kemudian buat development environment yang terkunci:

```powershell
cd apps/server
uv sync --locked --extra dev
.\.venv\Scripts\Activate.ps1
. .\scripts\windows\enable_cache.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Script cache mengarahkan bytecode Python normal ke `apps/server/.cache/python` untuk sesi terminal saat ini. Ruff, mypy, dan pytest menggunakan direktori cache yang dikonfigurasi dalam `apps/server/pyproject.toml`.

Pytest assertion rewriting tidak bergantung pada normal bytecode-cache path milik Python. Konfigurasi test menonaktifkan penulisan rewritten bytecode sehingga test run tidak membuat ulang direktori `__pycache__` yang tersebar.

Untuk menghapus backend cache dan editable-install metadata:

```powershell
.\scripts\windows\clean_artifacts.ps1
```

### Local frontend workflow

```powershell
cd apps/web
npm ci
npm run dev
```

Lihat [Getting Started](guides/getting-started.md) dan [Development](guides/development.md) untuk detail setup lengkap.

## Branch

Buat branch yang terfokus dari branch `main` terbaru:

```bash
git switch main
git pull --ff-only origin main
git switch -c <type>/<short-description>
```

Prefix branch yang direkomendasikan:

| Prefix      | Penggunaan                                        |
| ----------- | ------------------------------------------------- |
| `feat/`     | Perilaku baru yang terlihat oleh user             |
| `fix/`      | Perbaikan bug                                     |
| `docs/`     | Perubahan yang hanya berkaitan dengan dokumentasi |
| `refactor/` | Restrukturisasi internal tanpa perubahan perilaku |
| `perf/`     | Peningkatan performance yang terukur              |
| `test/`     | Pekerjaan yang hanya berkaitan dengan test        |
| `chore/`    | Maintenance atau tooling                          |
| `ci/`       | Perubahan continuous integration                  |
| `build/`    | Perubahan build system atau dependency            |

Batasi setiap branch pada satu concern yang jelas.

## Ekspektasi arsitektur

Semantix mengikuti feature-first ownership.

* Pertahankan query behavior di dalam query feature.
* Pertahankan cache behavior di dalam cache feature.
* Pertahankan HTTP behavior khusus provider di dalam provider adapter.
* Pertahankan behavior khusus storage di dalam cache infrastructure adapter.
* Pertahankan operational asset level-repository di bawah `ops/`.
* Pertahankan PostgreSQL bootstrap asset di bawah `ops/postgres/`.
* Pertahankan workload k6 di bawah `ops/load-testing/`.
* Gunakan protocol dari application code, bukan concrete adapter, sebagai dependency.
* Tambahkan architectural layer hanya ketika sebuah feature memiliki responsibility yang berbeda.
* Pertahankan feature kecil yang kohesif tetap flat.
* Pertahankan strict typing; jangan gunakan `Any` hanya untuk melewati contract.
* Jangan menyebarkan conditional pemilihan provider atau cache ke berbagai route atau application service.
* Jangan membandingkan embedding dari provider, model, atau dimensions yang berbeda.
* Jangan mengekspos prompt, full response, provider URL, model name, atau secret melalui aggregate telemetry.

Review [Architecture](reference/architecture.md) sebelum melakukan perubahan struktural.

## Ekspektasi coding

### Backend

* Targetkan range Python 3.11 hingga 3.14 yang telah diuji.
* Tambahkan type hint pada public function dan method baru.
* Gunakan pattern Pydantic settings dan validation yang sudah ada.
* Konversikan failure dari external provider menjadi stable error type milik project.
* Gunakan kembali shared vector validation daripada melakukan truncation atau padding pada embedding.
* Pertahankan provider test tetap offline melalui `httpx.MockTransport` atau deterministic mock provider.
* Pertahankan migration bersama cache infrastructure yang memilikinya.
* Tambahkan docstring ringkas ketika behavior tidak dapat dipahami secara langsung.

### Frontend

* Pertahankan strict TypeScript validation.
* Pertahankan feature page, component, hook, API adapter, type, dan route bersama feature yang memilikinya.
* Gunakan kembali shared UI primitive jika sesuai.
* Pertahankan accessibility untuk form, control, dialog, table, dan chart.
* Jangan mengekspos backend secret melalui variable `VITE_*`.
* Perbarui API type setiap kali public response contract berubah.

### Dokumentasi

Dokumentasi harus sesuai dengan behavior yang diimplementasikan.

Perbarui guide yang relevan ketika mengubah:

* environment variable;
* dukungan provider;
* cache policy;
* API contract;
* behavior benchmark;
* behavior Docker atau deployment;
* behavior migration atau persistence;
* load-testing safeguard;
* requirement CI;
* known limitation.

Jangan melaporkan hasil benchmark atau performance tanpa mencatat provider, model, dataset, threshold, cache state, hardware, dan runtime condition yang relevan.

## Test dan quality check

Jalankan check yang terdampak oleh perubahan Anda sebelum melakukan push.

### Backend

```powershell
cd apps/server
.\.venv\Scripts\Activate.ps1
. .\scripts\windows\enable_cache.ps1
uv run --locked pytest -m "not pgvector" --cov=app
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

### Frontend

```powershell
cd apps/web
npm ci
npm run lint
npm run imports:check
npm run test:coverage
npm run build
```

### Docker Compose

Dari repository root:

```powershell
docker compose config --quiet
docker compose -f docker-compose.dev.yml --profile pgvector config --quiet
docker compose --env-file .env.production.example -f docker-compose.prod.yml config --quiet
```

Pgvector integration test bersifat opt-in dan memerlukan disposable database:

```powershell
$env:PGVECTOR_TEST_DATABASE_URL = `
  "postgresql://semantix:semantix@localhost:5433/semantix"

cd apps/server
.\.venv\Scripts\python.exe -m pytest -m pgvector
```

Jangan menjalankan test terhadap production data atau billable provider kecuali hal tersebut secara eksplisit diperlukan dan telah diakui.

## Continuous integration

Workflow `Quality` GitHub Actions berjalan untuk pull request yang menargetkan `main`, push ke `main`, dan manual dispatch.

Workflow tersebut memvalidasi:

* backend lock yang telah di-commit, test, Ruff linting, Ruff formatting, dan mypy;
* frontend linting, import normalization, test, dan production build;
* compatibility, development, dan hardened Docker Compose configuration;
* development dan hardened image build;
* pgvector integration test terhadap disposable service;
* dependency change yang diperkenalkan oleh pull request.
* build amd64 dan arm64 untuk setiap Dockerfile;
* immutable container image digest yang telah disetujui;
* CodeQL dan verified-secret scanning;
* vulnerability production-image High atau Critical yang memiliki fix;
* SPDX SBOM dan Buildx provenance artifact yang dapat diunduh.

Required status check terakhir adalah:

```text
Quality gate
```

`Quality gate` hanya berhasil ketika backend, frontend, container, dan pgvector check berhasil. Multi-platform build, CodeQL, secret scanning, image scanning, dan supply-chain artifact generation juga harus berhasil. Dependency review harus berhasil pada pull request. Job required yang masih pending, dibatalkan, atau gagal harus memblokir merge normal.

Lihat [Supply-chain security](operations/supply-chain.md) untuk threshold dan cadence.

Repository ruleset mewajibkan pull request dan check `Quality gate`. CODEOWNERS menentukan ownership review. Akses ruleset bypass dicadangkan untuk memperbaiki repository automation yang rusak atau kasus administratif luar biasa lainnya; akses tersebut tidak boleh digunakan untuk melakukan merge terhadap product failure yang sudah diketahui.

## Commit message

Gunakan Conventional Commits:

```text
<type>(<optional-scope>): <imperative description>
```

Contoh:

```text
feat(providers): add Ollama generation adapter
fix(cache): isolate pgvector embedding spaces
refactor(repo): consolidate operational assets
ci(quality): validate development and hardened Compose files
docs(contributing): document the quality gate
```

Type yang umum:

* `feat`
* `fix`
* `docs`
* `style`
* `refactor`
* `perf`
* `test`
* `chore`
* `ci`
* `build`

Tulis subject commit yang ringkas dalam imperative mood. Hindari mencampurkan perubahan yang tidak terkait dalam satu commit.

## Pull request

Sebelum membuka pull request:

1. Update branch Anda dari `main` terbaru.
2. Hapus perubahan formatting dan generated-file yang tidak terkait.
3. Tambahkan atau perbarui test yang relevan.
4. Perbarui dokumentasi.
5. Jalankan quality check lokal yang relevan.
6. Validasi Docker Compose ketika konfigurasi terdampak.
7. Review diff untuk credential, private prompt, response, dan personal data.
8. Isi pull request template dengan jujur.
9. Tunggu `Quality gate` berhasil sebelum melakukan merge.

Pull request yang baik harus menjelaskan:

* masalah atau behavior yang diubah;
* pendekatan implementasi;
* pengaruh terhadap public API, configuration, migration, atau compatibility;
* command verifikasi dan hasilnya;
* limitation atau follow-up work apa pun.

Gunakan squash merge agar history `main` final berisi satu focused commit untuk setiap pull request.

Screenshot dianjurkan untuk perubahan frontend yang terlihat. Output benchmark yang dapat direproduksi diperlukan untuk klaim performance.

Draft pull request diperbolehkan untuk mendapatkan architectural feedback lebih awal.

## Kontribusi dengan bantuan AI

Pekerjaan dengan bantuan AI diperbolehkan, tetapi contributor tetap bertanggung jawab atas hasilnya.

Sebelum mengirimkan perubahan yang dibantu AI:

* review dan pahami setiap baris yang dimodifikasi;
* verifikasi license dan attribution;
* hapus claim yang dibuat-buat atau command yang belum diverifikasi;
* jalankan test yang relevan;
* pastikan dokumentasi yang dihasilkan sesuai dengan implementasi;
* pastikan tidak ada private prompt, credential, atau proprietary content yang disertakan.

Generated code yang tidak direview dapat ditolak.

## Lisensi

Dengan mengirimkan sebuah kontribusi, Anda menyetujui bahwa kontribusi tersebut dapat didistribusikan berdasarkan [MIT License](../../../LICENSE). Hanya kirimkan pekerjaan yang Anda memiliki hak untuk melisensikan dan mendistribusikan kembali.

Terima kasih telah membantu membuat semantic caching lebih mudah untuk diinspeksi, dievaluasi, dan dipahami.
