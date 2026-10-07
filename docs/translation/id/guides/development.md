# Development

Gunakan toolchain lokal untuk integrasi IDE, hot reload, dan pemeriksaan kualitas. Workflow Docker didokumentasikan di [Getting started](getting-started.md).

## Contributor embedded cache

Kerjakan `semantix-cache` secara terpisah dari produk server/web opsional. Dari
root repository, siapkan development environment terkunci yang sudah ada:

```text
cd packages/cache
uv sync --locked --extra dev
```

Gunakan [check contributor cache](../../../../packages/cache/README.md#contributor-checks)
untuk Ruff, formatting, mypy, pytest/coverage, contoh, dan pemeriksaan artifact.
[Workflow Quality](../../../../.github/workflows/quality.yml) mencatat matrix
CI Python 3.11-3.14 dan target analisis lengkap. Kasus PostgreSQL memerlukan
`PGVECTOR_TEST_DATABASE_URL` yang secara eksplisit menunjuk database disposable;
tanpa itu kasus tersebut dilewati. Test provider normal deterministik dan offline.

- Penulis store: [conformance CacheStore](../../../cache-store-conformance.md).
- Contributor provider: [tool live-verification](../../../provider-live-verification.md).
  Request/biaya live memerlukan izin terpisah; test biasa tidak memerlukan key.
- Maintainer evidence: [metodologi reuse-quality dan workflow penggantian](../../../../packages/cache/benchmarks/reuse_quality/README.md#automatic-validation-and-explicit-evidence-replacement).

Dari `packages/cache`, validasi evidence reviewed yang sudah ada tanpa download
model atau penulisan file:

```text
uv run --no-sync --offline python -B -m benchmarks.reuse_quality.benchmark validate
```

Pre-commit memilih input evidence staged yang relevan; CI memvalidasi keadaan
akhir. Keduanya tidak membuat ulang receipt atau menyetujui label. Waktu yang
berlalu, HEAD berbeda, dan commit yang tidak terkait tidak membuat evidence stale:
perubahan hash input/config/corpus yang relevan membuatnya stale. Setelah perubahan
relevan yang disengaja, ikuti workflow review/penggantian dari source bersih yang
ditautkan; jangan membuat ulang evidence hanya agar CI lolos.

## Backend

Rentang interpreter yang didukung adalah Python 3.11 hingga 3.14. Backend image menggunakan Python 3.14, seluruh quality suite dijalankan pada 3.14, dan compatibility suite juga dijalankan pada 3.11, 3.12, dan 3.13 di CI.

Windows PowerShell:

```powershell
cd apps/server
uv sync --locked --extra dev
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

macOS atau Linux:

```bash
cd apps/server
uv sync --locked --extra dev
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Instal [uv](https://docs.astral.sh/uv/getting-started/installation/) sebelum menggunakan workflow backend lokal. `pyproject.toml` mendeklarasikan rentang versi yang didukung, sedangkan `uv.lock` mencatat resolusi lintas-platform yang tepat dan digunakan oleh CI serta backend image.

Backend membaca `apps/server/.env`. Dengan `CACHE_BACKEND=pgvector`, database yang dapat dijangkau diperlukan sebelum startup aplikasi selesai. Memory dan mock provider merupakan konfigurasi development dengan dependency paling sedikit.

## Frontend

Gunakan Node.js 24.0.0 atau yang lebih baru dalam release line Node 24. Ini sesuai dengan frontend image dan CI, serta memenuhi persyaratan runtime dari dependency frontend saat ini:

```bash
cd apps/web
npm ci
npm run dev
```

Server Vite berjalan di http://localhost:5173. Konfigurasikan `VITE_API_BASE_URL=http://localhost:8000` di `apps/web/.env`.

## Laporan helper repository

Direktori root `scripts/` berisi laporan repository untuk developer dengan entry point PowerShell dan Bash yang berpasangan.

Hitung baris pada file teks yang dilacak Git dan tidak diabaikan:

Windows PowerShell:

```powershell
.\scripts\windows\get_total_lines.ps1
```

Linux:

```bash
bash scripts/linux/get_total_lines.sh
```

Laporan menampilkan total file dan baris, total untuk setiap ekstensi, ekstensi dengan jumlah baris terbanyak, serta tabel file per file dalam setiap ekstensi. File binary, `package.json`, dan `package-lock.json` dilewati.

Temukan file production dan konfigurasi yang tidak direferensikan menggunakan path yang persis relatif terhadap repository di dokumen Markdown mana pun:

Windows PowerShell:

```powershell
.\scripts\windows\find_undocumented_files.ps1
```

Linux:

```bash
bash scripts/linux/find_undocumented_files.sh
```

Laporan dokumentasi secara sengaja mengecualikan test, package marker Python, package manifest, dependency lockfile, file yang diabaikan, dependency yang terinstal, dan build output. Laporan ini merupakan laporan maintenance informasional, bukan CI gate: file yang dilaporkan mungkin sudah dijelaskan secara memadai melalui feature atau package yang memilikinya meskipun path persisnya tidak disebutkan.

## Pemeriksaan kualitas

Backend:

```bash
cd apps/server
uv run --locked pytest -m "not pgvector" --cov=app
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

Frontend:

```bash
cd apps/web
npm run lint
npm run imports:check
npm run test:coverage
npm run build
npm run bundle:check
```

`npm run build` mencakup validasi TypeScript secara ketat melalui `tsc --noEmit`. Bundle check melaporkan chunk JavaScript hasil emit terbesar terhadap budget raw dan gzip saat ini. Jika budget terlampaui, akan muncul peringatan CI sehingga pertumbuhan dapat terlihat tanpa memblokir build.

Coverage floor yang disimpan di repository sengaja ditetapkan di bawah baseline yang terukur, sehingga refactor kecil tidak membuat gate menjadi rapuh sementara regresi besar tetap menyebabkan CI gagal. Pengujian aksesibilitas browser dan coverage reverse-proxy terautentikasi dijalankan melalui `npm run test:e2e` terhadap hardened Compose stack.

Pengujian provider normal menggunakan `httpx.MockTransport` dan tidak boleh memanggil service eksternal.

Pengujian integrasi pgvector bersifat opt-in dan menggunakan `PGVECTOR_TEST_DATABASE_URL`; lihat [pgvector](pgvector.md). Load testing memiliki acknowledgment keselamatan tersendiri; lihat [Load testing](../operations/load-testing.md).

## Aturan arsitektur

* Pertahankan perilaku feature pada feature yang memilikinya.
* Tambahkan layer `api`, `application`, `domain`, atau `infrastructure` hanya ketika feature memiliki tanggung jawab yang berbeda tersebut.
* Pertahankan feature kecil yang kohesif tetap flat.
* Gunakan provider dan cache port sebagai dependency dari application code.
* Pertahankan perilaku API eksternal dan storage yang konkret di dalam adapter.
* Cerminkan kepemilikan feature production dalam test.
* Utamakan composition yang sederhana dibandingkan registry atau framework dependency-injection.
* Pertahankan strict typing; jangan gunakan `Any` untuk melewati contract.

Lihat [Architecture](../reference/architecture.md) untuk batas kepemilikan saat ini.

## Kontribusi

1. Buat branch yang fokus:

   ```bash
   git switch -c feat/short-description
   ```

2. Pertahankan perubahan dalam satu concern yang jelas.

3. Tambahkan atau perbarui test dan dokumentasi yang relevan.

4. Jalankan pemeriksaan backend dan frontend yang terdampak oleh perubahan.

5. Validasi konfigurasi Docker:

   ```bash
   docker compose config --quiet
   docker compose build
   ```

6. Buat pull request yang menjelaskan perubahan behavior, validasi, dan konfigurasi.

Jangan commit file `.env`, kredensial provider, database lokal, virtual environment, dependency, test cache, atau build output.
