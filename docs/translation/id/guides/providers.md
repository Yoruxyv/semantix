# AI provider

Semantix memilih embedding dan generation provider secara independen di balik port `EmbeddingProvider` dan `GenerationProvider`. Application route, logika cache, benchmark, dan orkestrasi query tidak mengimpor adapter konkret. Hugging Face tetap menjadi default untuk kedua kapabilitas tersebut.

## Kapabilitas

| Provider     | Embeddings | Generation |   Kredensial diperlukan  |
| ------------ | :--------: | :--------: | :----------------------: |
| Hugging Face |     Ya     |     Ya     |            Ya            |
| OpenAI       |     Ya     |     Ya     |            Ya            |
| Anthropic    |    Tidak   |     Ya     |            Ya            |
| Gemini       |     Ya     |     Ya     |            Ya            |
| Ollama       |     Ya     |     Ya     | Tidak untuk server lokal |
| Mock         |     Ya     |     Ya     |           Tidak          |

Atur provider secara independen:

```env
EMBEDDING_PROVIDER=huggingface
GENERATION_PROVIDER=ollama
```

Hanya field yang diperlukan oleh kapabilitas yang dipilih yang divalidasi. Sebagai contoh, Ollama generation tidak memerlukan Ollama embedding model atau dimensions. Anthropic tidak dapat dipilih untuk embeddings.

Semua respons HTTP provider menggunakan satu batas decoded-body sebelum parsing JSON:

```env
PROVIDER_MAX_RESPONSE_BYTES=4194304
```

Default 4 MiB diberlakukan secara terpusat pada hosted provider dan Ollama. Respons dengan `Content-Length` yang lebih besar dan dapat dipercaya ditolak sebelum body dibaca; jika tidak, byte hasil decoded/decompressed yang di-stream dihitung dan pembacaan dihentikan ketika batas terlampaui. Respons yang terlalu besar tidak valid dan tidak di-retry. Tingkatkan pengaturan ini hanya ketika model yang dikonfigurasi secara sah tidak dapat memenuhi batas default.

## Hosted provider

Base URL hosted provider harus berupa URL HTTPS absolut tanpa kredensial, query, atau fragment yang disematkan. Simpan API key hanya di `apps/server/.env` atau deployment secret store.

### Hugging Face

```env
EMBEDDING_PROVIDER=huggingface
GENERATION_PROVIDER=huggingface

HF_API_KEY=
HF_INFERENCE_BASE_URL=https://router.huggingface.co/hf-inference/models
HF_CHAT_BASE_URL=https://router.huggingface.co/v1
HF_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
HF_GENERATION_MODEL=Qwen/Qwen3-4B-Instruct-2507:nscale
HF_EMBEDDING_DIMENSIONS=384
```

### OpenAI

```env
EMBEDDING_PROVIDER=openai
GENERATION_PROVIDER=openai

OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_EMBEDDING_MODEL=
OPENAI_GENERATION_MODEL=
OPENAI_EMBEDDING_DIMENSIONS=
```

### Anthropic

Anthropic hanya mendukung generation:

```env
GENERATION_PROVIDER=anthropic

ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_GENERATION_MODEL=
```

### Gemini

```env
EMBEDDING_PROVIDER=gemini
GENERATION_PROVIDER=gemini

GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GEMINI_EMBEDDING_MODEL=
GEMINI_GENERATION_MODEL=
GEMINI_EMBEDDING_DIMENSIONS=
```

## Ollama

Hugging Face merupakan default yang direkomendasikan untuk sebagian besar pengguna karena tidak memerlukan download model lokal dan hardware inference. Pilih Ollama ketika local inference memang diperlukan dan mesin memiliki kapasitas disk, memory, dan compute yang memadai.

Instal dan jalankan Ollama secara terpisah dari Semantix, lalu pull model yang ingin dikonfigurasi secara persis:

```bash
ollama pull embeddinggemma
ollama pull gemma3:4b
ollama list
```

Untuk backend Semantix yang berjalan langsung pada host:

```env
EMBEDDING_PROVIDER=ollama
GENERATION_PROVIDER=ollama

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=embeddinggemma
OLLAMA_GENERATION_MODEL=gemma3:4b
OLLAMA_EMBEDDING_DIMENSIONS=768
```

Untuk backend Semantix yang di-Docker pada Docker Desktop, konfigurasikan akses ke service Ollama pada host dengan:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Ollama mungkin memerlukan `OLLAMA_HOST=0.0.0.0:11434` agar container dapat menjangkaunya. Jangan mengekspos API tanpa autentikasi tersebut ke jaringan yang tidak tepercaya. Di Linux, pastikan `host.docker.internal` mengarah ke host gateway atau gunakan alamat host yang dapat dijangkau dan diamankan secara eksplisit.

Jalankan Semantix dengan command memory-cache normal:

```bash
docker compose up --build -d
```

Atau aktifkan pgvector secara independen:

```bash
docker compose --profile pgvector up --build -d
```

Semantix tidak pernah melakukan pull model saat application startup. Nama dan tag model harus sama persis dengan `ollama list`; misalnya, mengonfigurasi `gemma3` tidak memilih model terinstal bernama `gemma3:4b`.

Semantix memanggil native Ollama API:

* `POST /api/embed` untuk embeddings;
* `POST /api/generate` dengan streaming dinonaktifkan untuk generation.

Model Ollama dapat menggunakan beberapa gigabyte. Untuk berhenti menggunakan Ollama, pulihkan provider selector di `apps/server/.env`, buat ulang backend, lalu hapus model melalui Ollama:

```bash
ollama rm embeddinggemma
ollama rm gemma3:4b
```

Menghapus model bersifat permanen. Uninstall aplikasi Ollama pada host secara terpisah ketika sudah tidak diperlukan. Tindakan ini tidak mengubah volume pgvector Semantix.

## Mock provider

Mock provider membuat seluruh aplikasi dapat digunakan tanpa kredensial atau network call:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384
```

Mock embedding menggunakan fitur token SHA-256 deterministik dan dinormalisasi secara unit. Mock generation mengembalikan respons deterministik dengan prefix `[mock provider]`. Mock provider ditujukan untuk automated test, demonstrasi, dan UI development—bukan untuk semantic embedding atau jawaban berkualitas production.

## Kompatibilitas embedding

Dimensi embedding harus sesuai dengan vector yang dikembalikan oleh model yang dikonfigurasi secara persis. Semantix menolak vector yang malformed, non-finite, kosong, dan tidak valid secara dimensional, alih-alih melakukan truncation atau padding.

Mengubah embedding provider, model, atau dimensions akan menghasilkan embedding space yang berbeda. Backend pgvector memisahkan embedding space tersebut sehingga vector yang tidak kompatibel tidak dibandingkan. Backend in-memory dimulai dalam keadaan kosong ketika process dimulai ulang.

## Smoke test

Generic smoke script menjalankan provider apa pun yang dipilih di `apps/server/.env`:

```powershell
cd apps/server

python scripts/smoke_provider.py generation "Explain semantic caching"
python scripts/smoke_provider.py embedding "Explain semantic caching"
```

Mock smoke test tidak memerlukan service eksternal. Ollama smoke test memerlukan Ollama yang sedang berjalan dengan model yang dikonfigurasi dan sudah tersedia.

## Langkah berikutnya

Kembali ke [Getting started](getting-started.md) untuk membuka workbench.
[Tur produk](../README.ID.md#tur-produk) menampilkan workspace saat ini, dan
[Python SDK](../../../../packages/client/README.md) menghubungkan aplikasi ke HTTP API publik
yang sama.

## Tradeoff dan keamanan

* Hosted provider sederhana secara operasional tetapi memerlukan kredensial dan dapat menimbulkan latency, biaya penggunaan, serta pertimbangan pemrosesan data.
* Ollama menjaga inference tetap lokal tetapi memerlukan penyimpanan model, hardware yang memadai, dan pengelolaan lifecycle lokal.
* Mock provider bersifat deterministik dan gratis tetapi tidak menghasilkan jawaban production yang bermakna.
* Jangan pernah commit API key atau kredensial database.
* Jangan mengekspos API Ollama tanpa autentikasi ke jaringan yang tidak tepercaya.
* Endpoint `/health` hanya melaporkan nama tipe provider. Endpoint tersebut tidak mengekspos URL provider, model, key, atau melakukan readiness call eksternal.

## Troubleshooting Ollama

| Gejala                               | Pemeriksaan                                                                                             |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Connection refused                   | Pastikan `ollama serve` sedang berjalan dan port `11434` dapat dijangkau                                |
| Docker tidak dapat menjangkau Ollama | Periksa `http://host.docker.internal:11434`, `OLLAMA_HOST`, dan resolusi host-gateway                   |
| Model tidak ditemukan                | Jalankan `ollama list` dan konfigurasikan tag terinstal yang persis, atau pull model yang dikonfigurasi |
| Embedding dimension error            | Atur `OLLAMA_EMBEDDING_DIMENSIONS` ke ukuran output model yang persis                                   |
| Request timeout                      | Tingkatkan `PROVIDER_TIMEOUT_SECONDS` dalam batas tervalidasinya atau gunakan model yang lebih kecil    |
| Backend gagal saat startup           | Periksa field model provider yang dipilih dan Ollama base URL                                           |

Lihat dokumentasi resmi Ollama untuk [local API](https://docs.ollama.com/api/introduction), [generation endpoint](https://docs.ollama.com/api/generate), [embedding endpoint](https://docs.ollama.com/api/embed), dan [network configuration](https://docs.ollama.com/faq).
