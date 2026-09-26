<p align="center">
  <sub><a href="/docs/translation/id/SECURITY.md">ID</a> · <a href="../../../SECURITY.md">EN</a></sub>
</p>

# Kebijakan Keamanan

Semantix adalah laboratorium semantic-cache local-first. Development stack yang disebutkan secara eksplisit ditujukan untuk satu developer tepercaya dan tidak boleh diekspos ke network yang tidak tepercaya. Jalur deployment yang diperkeras dan terpisah disediakan sebagai prasyarat untuk penggunaan bersama.

## Versi yang didukung

| Version                               | Supported |
| ------------------------------------- | :-------: |
| `main` branch                         |    Yes    |
| Latest tagged release, when available |    Yes    |
| Older releases and historical commits |     No    |
| Third-party forks                     |     No    |

## Melaporkan vulnerability

Jangan membuka public issue untuk suspected vulnerability. Gunakan Security tab repository, buka Advisories, pilih **Report a vulnerability**, dan kirimkan laporan secara private.

Sertakan commit yang terdampak, deployment mode, endpoint atau provider, langkah yang dapat direproduksi, behavior yang diharapkan dan yang diamati, dampak yang realistis, evidence yang telah disanitasi, dan suggested remediation jika diketahui.

Hapus API keys, access tokens, database passwords, private prompts, complete responses, personal data, dan production information yang tidak terkait.

## Dalam cakupan

Laporan yang berguna mencakup issue konkret yang melibatkan:

* exposure terhadap provider credentials, access tokens, prompts, atau cached responses;
* authentication atau role bypass;
* kegagalan authorization namespace;
* kebocoran data antar-embedding-space;
* SQL injection atau operasi pgvector yang tidak aman;
* server-side request forgery melalui konfigurasi provider;
* akses file atau command execution secara arbitrer;
* vulnerability dependency yang dapat dieksploitasi;
* kegagalan pada boundary CORS, trusted-proxy, request-size, atau rate-limit;
* exposure yang tidak disengaja terhadap operasi cache-management;
* behavior migration, Docker, atau startup yang merusak security boundary yang telah didokumentasikan.

## Ekspektasi deployment

Development stack menggunakan hot reload, development credentials, automatic migration, dan port yang hanya terikat pada loopback. Public exposure terhadap stack tersebut tidak didukung.

Hardened stack memerlukan:

* TLS termination sebelum public traffic mencapai Semantix;
* token authentication dan authorization berdasarkan role/namespace;
* token dan database password yang kuat dan dikelola sebagai secret;
* trusted-proxy CIDR yang eksplisit;
* satu backend process kecuali shared rate-limit storage ditambahkan;
* role database migration dan runtime yang terpisah;
* tidak ada backend atau database port yang dapat diakses secara langsung oleh publik;
* review operator terhadap data handling dan retention provider.

Hardened stack yang disediakan bukan merupakan complete multi-tenant service. Stack tersebut tidak menambahkan distributed coordination, deployment-wide metrics, tenant billing, atau general identity provider.

## Keterbatasan desain yang diketahui

* Metrics dan request coalescing tetap bersifat process-local; rate limiting produksi dan lockout sesi autentikasi memakai koordinasi PostgreSQL bersama. Runtime
  metrics merupakan global operational surface yang dibatasi untuk global
  administrator; namespace user memiliki scoped cache statistics sebagai gantinya.
* Hosted provider menerima prompt yang dipilih oleh authorized operator.
* Semantic similarity tetap bersifat probabilistik dan memerlukan threshold evaluation.
* Access token yang dikonfigurasi melalui `AUTH_PRINCIPALS` merupakan credential yang dikelola operator, bukan federated identity.
* Production frontend default terikat ke loopback dan bergantung pada external TLS reverse proxy.

## Di luar cakupan

Harap hindari laporan yang hanya didasarkan pada model quality, provider latency atau pricing yang diharapkan, keterbatasan local-development yang telah didokumentasikan, serangan yang memerlukan kontrol terhadap trusted host atau Docker daemon, output dependency scanner tanpa dampak yang dapat direproduksi, atau unauthorized testing terhadap third-party infrastructure.

Jangan melakukan destructive testing, mengakses data yang bukan milik Anda, menurunkan kualitas service, atau menimbulkan provider charges tanpa authorization eksplisit.

## Coordinated disclosure

Berikan waktu yang wajar untuk investigation dan remediation sebelum public disclosure. Good-faith research yang mengikuti policy ini dan menghindari privacy violation atau service disruption akan diperlakukan sebagai authorized untuk meningkatkan Semantix. Policy ini tidak mengizinkan testing terhadap GitHub, Docker, hosting platform, atau third-party provider.
