# Hardened Deployment

Deployment path ini bersifat opsional untuk local development dan wajib digunakan sebelum Semantix dibagikan kepada pengguna yang tidak tepercaya. Ini adalah baseline single-instance, bukan platform multi-tenant atau arsitektur multi-replica.

## Deployment boundary

`docker-compose.prod.yml` hanya mempublikasikan frontend gateway. Backend hanya dapat dijangkau melalui internal `edge` network. PostgreSQL hanya dapat dijangkau melalui internal `data` network. Frontend gateway melakukan proxy `/api`, `/health`, dan `/ready` ke backend.

`docker-compose.prod.yml` menggunakan explicit Compose project name `semantix-prod`. Oleh karena itu, PostgreSQL volume-nya terisolasi dari local development volume dan dari volume yang dibuat oleh versi sebelumnya dari default development stack.

Host binding default adalah:

```env
SEMANTIX_BIND_ADDRESS=127.0.0.1
SEMANTIX_PORT=8080
```

Jalankan TLS reverse proxy pada host dan forward ke `127.0.0.1:8080`. Public plaintext HTTP tidak didukung.

## Access token

Backend hanya menyimpan token digest SHA-256 dalam configuration. User memasukkan original token saat runtime. Browser menyimpannya di `sessionStorage`; token tidak di-compile ke dalam frontend bundle.

Production deployment harus menggunakan HTTPS. Generate token dan digest dengan Python:

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
6. Recreate backend container agar menerima environment yang telah diubah.
7. Verifikasi bahwa `/api/v1/auth/config` melaporkan authentication sebagai required.
8. Uji satu wrong token, lalu lakukan authentication dengan original token yang valid.

Environment value yang relevan adalah:

```env
AUTH_MODE=token
AUTH_PRINCIPALS=[{"name":"ops-admin","token_sha256":"<64-lowercase-hex>","role":"admin","namespaces":["*"]},{"name":"team-reader","token_sha256":"<64-lowercase-hex>","role":"viewer","namespaces":["team-a"]}]
```

Simpan original token di secret manager. Rotasi token berarti membuat token baru, mengganti digest-nya, dan melakukan recreate backend container.

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
| `viewer`   | Read permitted cache metadata, threshold state, dan benchmark datasets           |
| `operator` | All viewer operations plus provider-backed queries dan benchmark runs            |
| `admin`    | All operator operations plus cache deletion, namespace clear, dan administration |

Updating global similarity threshold dan membaca process-wide runtime metrics memerlukan `admin` principal dengan `namespaces:["*"]`. Namespace administrator tetap terbatas pada cache operation yang diotorisasi dan menerima `403 Forbidden` dari `/api/v1/metrics`.

## Namespace authorization

Setiap principal menerima satu atau lebih namespace. Non-global principal tidak dapat melakukan query, inspect, delete, atau clear pada namespace lain.

Ketika principal memiliki tepat satu namespace, cache list/stat request tanpa namespace secara otomatis di-scope ke namespace tersebut. Principal dengan beberapa namespace harus memilih salah satunya. Hanya `namespaces:["*"]` yang dapat melakukan global operation.

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

## URL configuration validation

Entry `ALLOWED_ORIGINS` harus berupa bare HTTP atau HTTPS origin: sebuah host (termasuk `localhost` atau bracketed IPv6 host) dan optional valid port. Single trailing slash dinormalisasi dan dihapus. Credential, path, parameter, query, fragment, dan malformed port ditolak.

`DATABASE_URL` tetap menerima PostgreSQL DSN dengan optional valid port, query parameter, IPv6 host, dan percent-encoded credential. Malformed port sekarang gagal selama startup validation. Hal ini secara sengaja menolak configuration yang sebelumnya diterima meskipun bukan URL yang dapat digunakan.

## Request-size limits

Frontend gateway menerapkan `client_max_body_size 64k`. Backend secara independen menerapkan `MAX_REQUEST_BODY_BYTES=65536` sebelum JSON parsing.

ASGI limit menangani `Content-Length` yang dideklarasikan maupun streamed/chunked request body. Oversized request mengembalikan HTTP `413` dengan standard JSON error structure.

Jaga agar value proxy dan backend tetap selaras. Backend limit merupakan final authority ketika request melewati atau diteruskan oleh proxy lain.

## Liveness dan readiness

`GET /health` mengonfirmasi bahwa process dapat merespons dan hanya melaporkan configured provider types. Endpoint ini murah dan tidak dikenai rate limit.

`GET /ready` memverifikasi active cache dependency. Endpoint ini tidak memanggil hosted embedding atau generation provider. Gangguan pgvector yang terjadi kemudian menghasilkan HTTP `503`, sehingga mencegah Compose frontend berjalan terhadap backend yang tidak tersedia.

## Database roles dan migrasi

Production database memiliki dua role. Gunakan random password yang aman untuk URL pada contoh Compose, atau lakukan percent-encode pada credential sebelum menempatkannya dalam PostgreSQL URL.

* `POSTGRES_MIGRATION_USER` memiliki extension/schema migration work;
* `POSTGRES_RUNTIME_USER` hanya menerima schema usage dan DML privilege pada tabel cache, evaluasi, dan koordinasi yang dikonfigurasi.

Initialization script membuat runtime login. One-shot `migrate` service terhubung menggunakan `MIGRATION_DATABASE_URL`, menginstal pgvector, menerapkan versioned migration termasuk koordinasi `0004`, memberikan runtime privilege, lalu keluar. Backend hanya berjalan setelah job tersebut berhasil.

Applied migration mencatat checksum SHA-256. Startup menolak packaged migration yang isinya tidak lagi cocok dengan recorded checksum. Legacy `0001` row tanpa checksum hanya di-backfill setelah released cache table dan required column diverifikasi; version berikutnya tanpa checksum akan fail closed dan memerlukan operator review.

Backend hanya menerima `DATABASE_URL` untuk runtime role dan menetapkan:

```env
DATABASE_MIGRATION_MODE=external
```

Local development tetap menggunakan:

```env
DATABASE_MIGRATION_MODE=auto
```

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
