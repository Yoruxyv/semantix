# Normalisasi typo prompt (opsional)

Server Semantix opsional dapat mengoreksi kesalahan ejaan bahasa Inggris yang umum dan pemisahan kata yang tidak disengaja sebelum membuat embedding yang digunakan untuk semantic-cache matching. Feature ini dinonaktifkan secara default karena koreksi otomatis dapat mengubah nama yang tidak dikenal atau istilah khusus domain.

## Konfigurasi

Untuk backend yang dijalankan langsung atau Compose development, atur nilai berikut di `apps/server/.env`:

```env
PROMPT_TYPO_CORRECTION_ENABLED=true
PROMPT_TYPO_MAX_EDIT_DISTANCE=2
```

Edit distance menerima nilai dari `0` hingga `3`. Nilai yang lebih besar memungkinkan koreksi yang lebih agresif. Default `2` menangani contoh seperti:

```text
semntic caching -> semantic caching
cahcing         -> caching
ex plain        -> explain
```

Pengaturan ini diterapkan saat startup; diagnostics admin di dashboard bersifat
read-only. Compose production menerimanya melalui pemetaan environment eksplisit,
bukan file `.env` development. Restart backend yang dijalankan langsung atau buat
ulang container yang terdampak setelah perubahan konfigurasi; restart container
saja tidak memperbarui environment yang dikonfigurasikan. Lihat
[deployment](../operations/deployment.md).

Perubahan preprocessing dapat membuat embedding tersimpan tidak kompatibel.
Rencanakan transisi terkoordinasi antar-replica: drain pekerjaan aktif, pertahankan
data yang dapat dipulihkan, pilih storage terisolasi yang kompatibel atau migrasi
yang ditinjau secara eksplisit, verifikasi konfigurasi baru, dan tentukan rollback
sebelum mengembalikan traffic. Fingerprint diagnostics saja tidak mengisolasi vektor
lama. Penghapusan adalah keputusan terpisah yang memerlukan otorisasi, bukan langkah
konfigurasi otomatis. Lihat [storage server](../../../guides/platform-storage.md) dan
[identitas preprocessing dan migrasi](../../../embedded/context-identity-and-migration.md#embedding-revision-and-preprocessing).

## Behavior

Koreksi hanya diterapkan pada text yang diteruskan ke embedding provider untuk cache lookup dan storage. Semantix tetap:

* mengirim original prompt ke generation provider saat terjadi cache miss;
* menyimpan dan menampilkan original prompt di cache inspector;
* melaporkan original cached prompt sebagai matched prompt.

Hal ini menjaga generated response tetap sesuai dengan user input sekaligus membuat variasi typo yang tidak berbahaya lebih mungkin menghasilkan cache embedding yang kompatibel. Benchmark run menggunakan normalizer yang dikonfigurasi sama seperti query biasa. SymSpell juga dapat menstandarkan punctuation dan whitespace dalam matching text; hal ini tidak mengubah original prompt.

Ketika konversi Unicode ke huruf kecil mengubah jumlah token SymSpell, misalnya
pada `İstanbul`, Semantix menggunakan seluruh prompt yang diberikan tanpa perubahan
sebagai matching text, alih-alih meneruskan daftar token yang tidak sejajar ke
compound correction. Lookup dan embedding baru untuk write menggunakan fallback
deterministik yang sama; typo lain dalam prompt tersebut tidak dikoreksi. Input
dengan token yang sejajar tetap mengikuti behavior koreksi yang sudah ada, termasuk
keterbatasannya untuk text non-Inggris. Guard ini tidak menambahkan case folding,
kanonisasi Unicode, atau jaminan kompatibilitas jawaban, dan tidak menghapus entry
yang tersimpan. Gunakan behavior preprocessing yang sama pada semua replica dan
ikuti langkah transisi cache yang sudah berlaku jika embedding tersimpan dibuat
dengan behavior berbeda.

Normalizer menggunakan English frequency dictionary yang dibundel dengan `symspellpy`. Normalizer tidak pernah men-download dictionary data saat runtime. Ketika correction diaktifkan, Semantix memuat dictionary selama application startup dan menolak untuk memulai jika dictionary tidak tersedia atau tidak valid. Ketika correction dinonaktifkan, dictionary tidak dimuat.

Semantix menambahkan protected vocabulary kecil untuk istilah umum project, termasuk `Semantix`, `pgvector`, `namespace`, `OpenAI`, dan `FastAPI`. Proper name yang tidak dikenal dan vocabulary khusus tetap dapat dikoreksi secara keliru, sehingga biarkan feature tetap dinonaktifkan ketika mempertahankan ejaan secara persis lebih penting daripada typo tolerance.

## Kapitalisasi dan matching

Server saat ini memakai `transfer_casing=True` milik SymSpell sehingga kapitalisasi
input umumnya dipertahankan. Ini bukan case-insensitive matching. Pada edit distance
2 dengan dictionary bawaan, matching text yang dihasilkan adalah:

| Application prompt | Matching text |
| --- | --- |
| `Explain semantic caching` | `Explain semantic caching` |
| `explain semantic caching` | `explain semantic caching` |
| `expln semantic caching` | `explain semantic caching` |
| `explainn semantic caching` | `explain semantic caching` |

Dua input pertama dapat menghasilkan embedding dan similarity score yang berbeda.
Kapitalisasi tidak selalu menyebabkan miss, dan koreksi ejaan tidak menjamin hit.
Reuse tetap memerlukan threshold similarity yang dikonfigurasikan serta pemeriksaan
kelayakan lain, termasuk namespace, space yang kompatibel, expiry, dan revisi aktif.
Koreksi maupun similarity tidak membuktikan kompatibilitas jawaban. Dictionary tetap
dapat mengubah nama yang tidak dikenal, identifier, atau text non-Inggris. Distance 0
saat fitur aktif tetap memakai compound preprocessing; ini tidak sama dengan
menonaktifkan koreksi.

## Paket mandiri dan preprocessing kustom

Paket independen `semantix-cache` menyediakan callable sinkron `prompt_normalizer`
pada `AsyncSemanticCache`. Instalasi paket tidak memasang SymSpell, mengaktifkan
pengaturan server ini, atau menyertakan protected vocabulary server. Hook hanya
mengubah embedding text; generation dan cache entry tetap memakai application
prompt yang sudah dikanonisasi. Lihat [kontrak paket](../../../../packages/cache/README.md#matching-text-preprocessing).

Aplikasi dapat memasok transformasi casing, whitespace, atau vocabulary yang sudah
dievaluasi melalui hook tersebut. Ini implementasi kustom, bukan mode bawaan.
Jangan sembarang menghapus punctuation, stop word, negasi, angka, identifier,
konteks tenant atau izin, system instruction, atau conversation history: informasi
tersebut dapat menentukan jawaban yang sesuai. Pertahankan konteks yang diperlukan
dalam request aplikasi dan identitas cache-nya. Buat preprocessing deterministik,
versikan bersama embedding space, dan gunakan storage terisolasi yang kompatibel
ketika mengubahnya. Ikuti panduan identitas/migrasi yang ditautkan, alih-alih sekadar
mengganti label vektor yang sudah ada.
