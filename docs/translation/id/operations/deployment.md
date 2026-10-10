# Hardened Deployment

Jalur deployment ini opsional untuk pengembangan lokal dan wajib digunakan sebelum Semantix dibagikan kepada pengguna yang tidak tepercaya. Stack Compose produksi menjalankan dua replika backend di belakang satu frontend gateway; Semantix bukan platform multi-tenant yang lengkap.

## Deployment boundary

`docker-compose.prod.yml` hanya mempublikasikan frontend gateway. `backend-a` dan `backend-b` tidak mempublikasikan port host; gateway menjangkau keduanya melalui jaringan `edge` dan membagi request `/api`, `/health`, dan `/ready`. Kedua backend juga terhubung ke jaringan `data`, tempat PostgreSQL tidak memiliki port host dan jaringan ditandai `internal: true`.

`docker-compose.prod.yml` menggunakan explicit Compose project name `semantix-prod`. Oleh karena itu, PostgreSQL volume-nya terisolasi dari local development volume dan dari volume yang dibuat oleh versi sebelumnya dari default development stack.

Host binding default adalah:

```env
SEMANTIX_BIND_ADDRESS=127.0.0.1
SEMANTIX_PORT=8080
```

Jalankan TLS reverse proxy pada host dan teruskan traffic ke `127.0.0.1:8080`. HTTP publik tanpa TLS tidak didukung.

### Batas evaluasi dan persistensi

`EVALUATION_TIMEOUT_SECONDS` membatasi waktu run evaluasi, secara default 300 detik
dengan rentang lebih dari nol hingga 3.600 detik. Timeout membuang cache lokal run;
ini bukan bukti bahwa pekerjaan di provider jarak jauh telah dibatalkan. Batas body
request `MAX_REQUEST_BODY_BYTES=65536` terpisah dari batas waktu dan ukuran konten.

Validasi dataset inline memakai `EVALUATION_DATASET_MAX_CASES` (default 50, rentang
1–500), `EVALUATION_DATASET_MAX_DECODED_BYTES` (default 49.152, rentang 1.024–1.048.576
byte UTF-8 terdekode), dan `EVALUATION_MAX_WORKLOAD_QUERIES` (default 250, rentang
1–2.500) untuk `cases × repetitions`. Proyeksi threshold tidak mengulang request
provider. Sumber built-in dan tersimpan tidak mengulangi pemeriksaan batas workload
yang sama pada jumlah repetisi yang diminta; penyimpanan dataset memvalidasi satu
repetisi. Anggarkan pekerjaan yang diminta secara eksplisit.

`EVALUATION_DATASET_STORAGE=session` tidak menyimpan impor secara otomatis. Operator
harus menyimpan dokumen yang berhasil divalidasi secara eksplisit agar persisten.
Untuk `postgres`, siapkan `DATABASE_URL`, backup, pemulihan, serta batas retensi dan
kapasitas namespace: `EVALUATION_DATASET_DEFAULT_RETENTION_DAYS`,
`EVALUATION_DATASET_MAX_RETENTION_DAYS`, `EVALUATION_DATASET_MAX_PERSISTED_PER_NAMESPACE`
dan `EVALUATION_DATASET_CLEANUP_BATCH_SIZE`.

Riwayat run diatur terpisah dan default-nya `EVALUATION_RUN_HISTORY_STORAGE=disabled`.
Untuk `postgres`, `DATABASE_URL` dan nilai positif bagi
`EVALUATION_RUN_HISTORY_RETENTION_DAYS`, `EVALUATION_RUN_HISTORY_MAX_PER_NAMESPACE`
serta `EVALUATION_RUN_HISTORY_CLEANUP_BATCH_SIZE` wajib tersedia. Riwayat hanya
menyimpan bukti agregat terminal, tanpa prompt per kueri, respons yang dihasilkan,
atau trace yang dapat diputar ulang. Riwayat dari dataset tersimpan dibatasi oleh
kedaluwarsa sumbernya; menghapus dataset juga menghapus riwayat terkait melalui
cascade. Batas cleanup mengatur pemilihan baris induk, bukan seluruh pekerjaan
cascade. Lihat [panduan evaluasi](../../../guides/benchmarking.md) dan
[riwayat run](../../../guides/evaluation-history.md) berbahasa Inggris untuk
kontrak yang lebih rinci.

## Access token

Backend hanya menyimpan token digest SHA-256 dalam configuration. User memasukkan original token saat runtime. Browser menyimpannya di `sessionStorage`; token tidak di-compile ke dalam frontend bundle.

Deployment produksi harus menggunakan HTTPS. Skema digest ini mengasumsikan access token acak dengan entropi tinggi; jangan menggunakannya untuk menyimpan password biasa yang dipilih pengguna. Buat token dan digest dengan Python:

```bash
python -c "import hashlib,secrets; t=secrets.token_urlsafe(32); print('token='+t); print('sha256='+hashlib.sha256(t.encode()).hexdigest())"
```

Windows PowerShell 5.1 atau lebih baru:

```powershell
$RandomBytes = New-Object byte[] 32
$Random = [Security.Cryptography.RandomNumberGenerator]::Create()
$Random.GetBytes($RandomBytes)
$Random.Dispose()
$Token = [Convert]::ToBase64String($RandomBytes)
$Bytes = [Text.Encoding]::UTF8.GetBytes($Token)
$Sha256 = [Security.Cryptography.SHA256]::Create()
$HashBytes = $Sha256.ComputeHash($Bytes)
$Sha256.Dispose()
$Hash = -join ($HashBytes | ForEach-Object { $_.ToString("x2") })
"token=$Token"
"sha256=$Hash"
```

Linux/macOS shell:

```bash
Token=$(openssl rand -base64 32)
Hash=$(echo -n "$Token" | openssl dgst -sha256 -hex | sed 's/^.* //')
echo "token=$Token"
echo "sha256=$Hash"
```

Siapkan operator token sebagai berikut:

1. Generate random token dengan entropy tinggi menggunakan salah satu command di atas.
2. Hitung digest SHA-256 lowercase-nya.
3. Simpan hanya digest tersebut di `AUTH_PRINCIPALS`.
4. Berikan original token kepada operator yang berwenang melalui secure channel. Jangan pernah menyimpan plaintext token di `AUTH_PRINCIPALS`.
5. Set `AUTH_MODE=token`.
6. Buat ulang kedua container `backend-a` dan `backend-b` agar menerima environment yang telah diubah.
7. Verifikasi bahwa `/api/v1/auth/config` melaporkan authentication sebagai required.
8. Uji satu wrong token, lalu lakukan authentication dengan original token yang valid.

Environment value yang relevan adalah:

```env
AUTH_MODE=token
AUTH_PRINCIPALS=[{"name":"ops-admin","token_sha256":"<64-lowercase-hex>","role":"admin","namespaces":["*"]},{"name":"team-reader","token_sha256":"<64-lowercase-hex>","role":"viewer","namespaces":["team-a"]}]
```

Simpan token asli di secret manager. Rotasi token berarti membuat token baru, mengganti digest-nya, dan membuat ulang kedua container backend.

Untuk local Docker development, `docker-compose.dev.yml` membaca kedua value dari `apps/server/.env`. Setelah mengubah value apa pun dalam file tersebut, recreate backend container agar Compose memberikan environment baru. Plain container restart tidak memuat ulang environment value yang telah berubah. Image rebuild tidak diperlukan untuk perubahan environment saja.

Dari repository root di Windows PowerShell:

```powershell
docker compose `
  -f docker-compose.dev.yml `
  --profile pgvector `
  up -d --force-recreate backend
```

Verifikasi container dan public authentication configuration:

```powershell
docker compose -f docker-compose.dev.yml --profile pgvector exec backend printenv AUTH_MODE
```

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/auth/config
```

Token mode melaporkan:

```text
authentication_required
-----------------------
True
```

Uji rejected token lalu original token yang valid:

```powershell
$WrongHeaders = @{ Authorization = "Bearer intentionally-wrong-token" }
try {
    Invoke-RestMethod http://localhost:8000/api/v1/auth/session -Headers $WrongHeaders
} catch {
    $_.Exception.Response.StatusCode.value__
}

$ValidHeaders = @{ Authorization = "Bearer $Token" }
Invoke-RestMethod http://localhost:8000/api/v1/auth/session -Headers $ValidHeaders
```

### Progressive authentication lockout

Hanya authentication attempt yang gagal terhadap `/api/v1/auth/session` yang memajukan lockout. Tiga kegagalan pertama mengunci client address tersebut selama 30 detik. Setelah lock berakhir, tiga kegagalan tambahan menguncinya selama 60 detik. Setelah lock tersebut berakhir, tiga kegagalan tambahan menguncinya selama 3.600 detik. Tahap selanjutnya tetap pada 3.600 detik. Authentication yang berhasil sepenuhnya me-reset client ke tahap awal.

`/api/v1/auth/config` adalah authentication bootstrap endpoint yang tidak diukur. Successful `/api/v1/auth/session` restoration juga dikecualikan dari quota `RATE_LIMIT` biasa sehingga browser refresh tidak menggunakan application request capacity. Invalid session attempt tetap dilindungi oleh progressive lockout di atas. Query, cache, benchmark, observability, dan API route terbatas lainnya tetap menggunakan `RATE_LIMIT` yang dikonfigurasi.

Request yang dibuat selama lock aktif menerima HTTP `429`, header `Retry-After`, dan standard JSON error `authentication_temporarily_locked`. Request tersebut tidak memperpanjang lock atau dihitung sebagai failure tambahan. Authentication failure pada protected endpoint lain tidak memajukan state ini.

Production Compose menyimpan lockout state di PostgreSQL sehingga progression bertahan setelah backend restart dan berlaku lintas replica berdasarkan client address tepercaya. Pengembangan lokal secara default memakai memory process. Jika koordinasi PostgreSQL tidak tersedia, autentikasi sesi mengembalikan HTTP `503` tanpa melewati perlindungan lockout.

## Peran

| Peran      | Allowed operations                                                               |
| ---------- | -------------------------------------------------------------------------------- |
| `viewer` | Membaca metadata cache, threshold, dataset built-in, dataset tersimpan dan riwayat/perbandingan yang diizinkan namespace |
| `operator` | Semua operasi viewer, ditambah kueri provider, validasi lokal sesi, penyimpanan dataset eksplisit dan run evaluasi |
| `admin` | Semua operasi operator, ditambah penghapusan cache, namespace clear, dataset tersimpan dan riwayat run |

Updating global similarity threshold dan membaca process-wide runtime metrics memerlukan `admin` principal dengan `namespaces:["*"]`. Namespace administrator tetap terbatas pada cache operation yang diotorisasi dan menerima `403 Forbidden` dari `/api/v1/metrics`.

## Namespace authorization

Setiap principal menerima satu atau lebih namespace. Non-global principal tidak dapat melakukan query, inspect, delete, atau clear pada namespace lain.

Principal dengan tepat satu namespace dibatasi ke namespace tersebut bila operasi
berscope tidak menyebutkannya. Principal dengan beberapa namespace harus memilih
salah satunya untuk pembuatan. Hanya `namespaces:["*"]` yang dapat melakukan listing
global. `*` adalah scope otorisasi, bukan kepemilikan data: admin wildcard tetap
harus memilih namespace konkret untuk membuat/menghapus dataset, menyimpan riwayat
built-in, menghapus riwayat, dan menjalankan kueri Monitor. Run dataset tersimpan
mewarisi namespace sumbernya. Riwayat asing dan ID yang tidak ada memakai respons
not-found yang sama.

Ini adalah server-side authorization. Frontend control tidak dianggap sebagai security boundary.

## Proxy-aware client addresses

Frontend gateway mengganti `X-Forwarded-For` yang masuk dengan alamat peer yang dilihatnya. Limiter hanya mempercayai alamat dari gateway ketika direct peer backend termasuk dalam `TRUSTED_PROXY_CIDRS`. Pemanggil langsung di luar CIDR tersebut tidak dapat mengubah identitasnya melalui header.

Production Compose network menggunakan `172.28.0.0/24`, sehingga default-nya adalah:

```env
TRUSTED_PROXY_CIDRS=["172.28.0.0/24"]
```

Docker Desktop dapat menampilkan TLS proxy pada host dan proses host lain kepada gateway sebagai bridge peer yang sama (`172.28.0.1` pada network produksi yang diuji). CIDR sumber saja tidak dapat mengautentikasi proxy host. Secara default gateway mengabaikan `X-Forwarded-For`, `X-Real-IP`, dan `Forwarded` yang masuk sebagai identitas dan meneruskan peer yang dilihatnya; pengguna di belakang proxy host tersebut lalu berbagi kuota rate-limit.

Untuk mempertahankan identitas tiap klien, biarkan port publikasi terikat ke loopback dan atur TLS proxy host agar **mengganti** `X-Forwarded-For` yang masuk dengan alamat TCP peer klien yang sebenarnya. Proxy juga harus mengganti `X-Semantix-Host-Proxy-Token` dengan token privat acak sepanjang 64 karakter heksadesimal; jangan meneruskan kedua header dari pemanggil eksternal. Untuk Nginx pada host, lokasi upstream memerlukan konfigurasi setara dengan:

```nginx
proxy_pass http://127.0.0.1:8080;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Semantix-Host-Proxy-Token "<token-privat-64-hex>";
```

Buat token dengan `python -c "import secrets; print(secrets.token_hex(32))"`. Simpan satu entri map dalam file privat di luar repository, dengan **alamat sumber proxy host yang benar-benar dilihat gateway** dan token yang sama:

```nginx
"172.28.0.1|<token-privat-64-hex>" $http_x_forwarded_for;
```

Atur `SEMANTIX_HOST_PROXY_RULE_FILE` ke path absolut file tersebut pada host sebelum menjalankan production Compose. Compose memasangnya secara read-only menggantikan file aturan gateway yang nonaktif. Verifikasi alamat sumber pada host Docker tujuan; `172.28.0.1` adalah nilai Docker Desktop yang diuji, bukan asumsi untuk semua platform. Jaga file aturan tetap privat dan tidak dilacak Git. Gateway menerima alamat dari proxy hanya jika **sumber dan token** cocok. Token, `X-Real-IP`, dan `Forwarded` dihapus sebelum backend. Jika trust tidak cocok, gateway memakai peer yang dilihatnya; alamat forwarded yang rusak ditolak secara aman oleh backend. Proxy perantara yang tidak tepercaya tetap menjadi klien yang dilihat proxy host kecuali diautentikasi secara terpisah di sana. Batasi `TRUSTED_PROXY_CIDRS` pada network gateway backend yang nyata; jangan tambahkan rentang publik yang luas.

Production Compose memakai PostgreSQL untuk bucket `RATE_LIMIT` bersama per client dan per route. `/auth/session` tetap di luar kuota biasa dan dilindungi progressive lockout. Pengembangan lokal secara default memakai memory process. Saat koordinasi PostgreSQL tidak tersedia, route yang dibatasi mengembalikan HTTP `503`, tanpa fallback ke counter terpisah per replica. Query coalescing lintas replica tetap ditunda. Similarity threshold global juga disimpan di PostgreSQL: `SIMILARITY_THRESHOLD` hanya mengisi nilai awal saat tabel kosong; perubahan Admin berikutnya bertahan setelah restart backend dan dibaca semua replica. `GET /ready` memeriksa otoritas ini dan mengembalikan `503` jika tidak tersedia.

## Operasi dua replika

Pertahankan `CACHE_BACKEND=pgvector` dan konfigurasi auth, provider, embedding,
cache serta koordinasi yang sama pada kedua replika. PostgreSQL berbagi entri
cache resmi dan koordinasi; dataset/riwayat dibagi bila persistensinya aktif.
Setiap replika memiliki HTTP client, pool PostgreSQL, lock run evaluasi dan
metrik runtime sendiri. Coalescing dan `/api/v1/metrics` tetap lokal per proses;
gabungkan observasi berlabel replika secara eksternal.

Respons `/ready` melalui gateway hanya mencakup replika yang dipilih. Periksa
masing-masing replika sebelum dan sesudah rollout:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T frontend curl -f http://backend-a:8000/ready
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T frontend curl -f http://backend-b:8000/ready
```

Untuk restart terencana, salin `apps/web/upstream.prod.conf` ke file host privat
dan atur `SEMANTIX_UPSTREAM_FILE` ke path absolutnya sebelum memulai Compose.
Hapus baris `server` replika target dari file yang dipasang, validasi dan reload
Nginx, lalu tunggu request yang sudah diterima selesai. Setelah itu hentikan atau
buat ulang replika target. Masukkan kembali barisnya hanya setelah pemeriksaan
`/ready` langsung berhasil, lalu validasi dan reload lagi:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T frontend nginx -t
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T frontend nginx -s reload
docker compose --env-file .env.production -f docker-compose.prod.yml stop backend-a
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --no-deps --force-recreate backend-a
```

Ulangi untuk `backend-b` setelah `backend-a` kembali melayani traffic. Read timeout
gateway adalah 330 detik dan stop grace backend 360 detik untuk timeout evaluasi
default 300 detik; sesuaikan bersama bila batas evaluasi berubah. Retry pada error
koneksi/timeout tidak menjamin semua request gagal diputar ulang atau tidak ada
error gateway; lihat [audit runtime](../../../operations/production-runtime-audit.md)
untuk kegagalan residual dan batas buktinya. Prosedur rinci
dan batas retry tersedia pada [panduan dua replika berbahasa Inggris](../../../operations/deployment.md#two-replica-operation).

`DATABASE_POOL_MAX_SIZE=5` berlaku per replika, sehingga dua backend dapat memakai
hingga sepuluh koneksi runtime, ditambah koneksi migrasi, pemeliharaan dan monitoring.
Anggarkan kuota provider terhadap gabungan miss, retry dan run evaluasi dari kedua
replika. Bukti uji mock tidak menetapkan kuota provider jarak jauh, kapasitas HA
PostgreSQL, atau dukungan jumlah replika sembarang.

[Audit multi-replika](../../../operations/multi-replica-readiness.md) memuat snapshot
historis satu replika sebelum koordinasi bersama, lalu hasil verifikasi dua replika;
snapshot itu bukan instruksi deployment saat ini. [Kebijakan autoscaling](../../../operations/autoscaling-readiness.md)
memerlukan validasi tersendiri pada platform tujuan.

## URL configuration validation

Entry `ALLOWED_ORIGINS` harus berupa bare HTTP atau HTTPS origin: sebuah host (termasuk `localhost` atau bracketed IPv6 host) dan optional valid port. Single trailing slash dinormalisasi dan dihapus. Credential, path, parameter, query, fragment, dan malformed port ditolak.

`DATABASE_URL` tetap menerima PostgreSQL DSN dengan optional valid port, query parameter, IPv6 host, dan percent-encoded credential. Malformed port sekarang gagal selama startup validation. Hal ini secara sengaja menolak configuration yang sebelumnya diterima meskipun bukan URL yang dapat digunakan.

## Request-size limits

Frontend gateway menerapkan `client_max_body_size 64k`. Backend secara independen menerapkan `MAX_REQUEST_BODY_BYTES=65536` sebelum JSON parsing.

ASGI limit menangani `Content-Length` yang dideklarasikan maupun streamed/chunked request body. Oversized request mengembalikan HTTP `413` dengan standard JSON error structure.

Jaga agar value proxy dan backend tetap selaras. Backend limit merupakan final authority ketika request melewati atau diteruskan oleh proxy lain.

## Liveness dan readiness

`GET /health` mengonfirmasi bahwa process dapat merespons dan hanya melaporkan configured provider types. Endpoint ini murah dan tidak dikenai rate limit.

`GET /ready` memeriksa statistik cache aktif, repository dataset evaluasi
persisten bila dikonfigurasi, dan threshold koordinasi bila dikonfigurasi.
Kegagalan storage cache, dataset atau koordinasi yang ditangani menghasilkan HTTP
`503` dengan error `not_ready`; kegagalan lain mengikuti batas error biasa.

Respons sukses melaporkan `cache_backend` dan `evaluation_dataset_storage`, tanpa
hasil readiness riwayat yang terpisah. Mengaktifkan riwayat run persisten tidak
menambahkan probe langsung ke repository riwayat. Endpoint ini tidak memanggil
hosted embedding/generation provider dan tidak membuktikan semua operasi baca/tulis
berikutnya akan berhasil. Compose menunggu kedua backend healthy sebelum memulai
frontend; ini bukan jaminan bahwa gateway terus memeriksa `/ready` setiap replika
setelah startup. Gunakan [pemeriksaan langsung dan drain](#operasi-dua-replika)
untuk rollout.

## Database roles dan migrasi

Production database memiliki dua role. Gunakan random password yang aman untuk URL pada contoh Compose, atau lakukan percent-encode pada credential sebelum menempatkannya dalam PostgreSQL URL.

* `POSTGRES_MIGRATION_USER` memiliki extension/schema migration work;
* `POSTGRES_RUNTIME_USER` menerima schema usage dan DML pada tabel yang dipilih, ditambah akses baca saja ke ledger migrasi cache resmi. Grant ini tidak memberi wewenang migrasi atau mencabut privilege yang sudah ada.

Initialization script membuat login runtime. Service satu kali `migrate`
menggunakan `MIGRATION_DATABASE_URL` untuk fitur PostgreSQL yang dipilih, memberi
runtime grants, lalu keluar. Setup cache eksplisit mengaktifkan pgvector,
menerapkan migrasi legacy server `0001`, lalu menginisialisasi schema dan ledger
cache resmi milik package. Entri legacy dipertahankan tanpa diadopsi atau dikonversi.
Bundle evaluasi berisi `0002` untuk dataset/case dan `0003` untuk agregat riwayat;
pilihan penyimpanan dan grant kedua fitur tetap terpisah. Koordinasi `0004` memiliki
rate bucket, lockout autentikasi dan threshold global. Kedua backend menunggu job
berhasil; jangan menjalankan migrasi berprivilege pada setiap replika. Job ini tidak
membangun provider atau memverifikasi kredensialnya.

Satu pool PostgreSQL per backend dipakai bersama oleh fitur PostgreSQL yang aktif.
Cache memory dapat memakai persistensi evaluasi secara terpisah, tetapi bukan
pilihan cache bersama untuk deployment dua replika ini. Lihat
[setup storage dan transisi legacy](../../../guides/platform-storage.md#postgresql-setup-and-legacy-transition)
untuk schema/prefix resmi dan pemisahan telemetry server dari entri otoritatif.

Runner migrasi mencatat dan memverifikasi checksum SHA-256 atas konten SQL;
mismatch checksum yang sudah tercatat menggagalkan setup. Baris legacy `0001`
tanpa checksum hanya di-backfill setelah pemeriksaan relation dan nama kolom wajib
yang diimplementasikan, bukan audit kesetaraan schema lengkap. Versi berikutnya
tanpa checksum fail closed dan memerlukan pemeriksaan operator. Backend produksi
dalam mode `external` tidak menjalankan ulang migrasi server. Startup cache biasa
memvalidasi layout dan ledger resmi milik package.

Backend hanya menerima `DATABASE_URL` untuk runtime role dan menetapkan:

```env
DATABASE_MIGRATION_MODE=external
```

Local development tetap menggunakan:

```env
DATABASE_MIGRATION_MODE=auto
```

Mode development `auto` menerapkan migrasi koordinasi/evaluasi PostgreSQL yang
aktif, tanpa menginisialisasi schema cache resmi. Ikuti setup storage eksplisit
sebelum memulai cache persisten.

Jangan pernah memberikan migration DSN kepada production backend service.

Mengubah Compose password variable tidak memperbarui role pada existing volume. Ikuti [Operations and recovery](recovery.md) untuk credential rotation, backup, restore, destructive rebuild, migration rollback, dan incident response.

## Static server behavior

Production frontend image:

* menjalankan `npm ci` dan `npm run build` dalam Node build stage;
* hanya menyalin `dist/` ke unprivileged Nginx runtime;
* menyediakan SPA fallback untuk client-side route;
* mengompresi text asset;
* memberikan immutable caching pada fingerprinted asset;
* mencegah caching terhadap `index.html`;
* menambahkan CSP, frame, referrer, MIME-sniffing, dan permissions header.

`vite preview` tidak digunakan sebagai production server.

## Validation

```bash
docker compose -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.dev.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml build
```

Verifikasi production runtime:

```bash
curl -i http://127.0.0.1:8080/health
curl -i http://127.0.0.1:8080/ready
curl -i http://127.0.0.1:8080/cache
```

Request `/cache` harus mengembalikan SPA entry document. API request tanpa token harus mengembalikan `401`. Viewer token tidak boleh menghapus atau melakukan global clear terhadap cache data. Inspect running frontend container dan pastikan user-nya non-root.
