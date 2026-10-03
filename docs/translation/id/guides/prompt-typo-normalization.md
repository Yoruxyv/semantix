# Normalisasi typo prompt (opsional)

Semantix dapat mengoreksi kesalahan ejaan bahasa Inggris yang umum dan pemisahan kata yang tidak disengaja sebelum membuat embedding yang digunakan untuk semantic-cache matching. Feature ini dinonaktifkan secara default karena koreksi otomatis dapat mengubah nama yang tidak dikenal atau istilah khusus domain.

## Konfigurasi

Atur nilai berikut di `apps/server/.env`:

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

Restart backend setelah mengubah salah satu pengaturan. Hapus cache entry yang sudah ada ketika mengaktifkan, menonaktifkan, atau mengubah correction distance agar setiap stored embedding menggunakan prompt-processing behavior yang sama.

## Behavior

Koreksi hanya diterapkan pada text yang diteruskan ke embedding provider untuk cache lookup dan storage. Semantix tetap:

* mengirim original prompt ke generation provider saat terjadi cache miss;
* menyimpan dan menampilkan original prompt di cache inspector;
* melaporkan original cached prompt sebagai matched prompt.

Hal ini menjaga generated response tetap sesuai dengan user input sekaligus membuat variasi typo yang tidak berbahaya lebih mungkin menghasilkan cache embedding yang kompatibel. Benchmark run menggunakan normalizer yang dikonfigurasi sama seperti query biasa. SymSpell juga dapat menstandarkan punctuation dan whitespace dalam matching text; hal ini tidak mengubah original prompt.

Normalizer menggunakan English frequency dictionary yang dibundel dengan `symspellpy`. Normalizer tidak pernah men-download dictionary data saat runtime. Ketika correction diaktifkan, Semantix memuat dictionary selama application startup dan menolak untuk memulai jika dictionary tidak tersedia atau tidak valid. Ketika correction dinonaktifkan, dictionary tidak dimuat.

Semantix menambahkan protected vocabulary kecil untuk istilah umum project, termasuk `Semantix`, `pgvector`, `namespace`, `OpenAI`, dan `FastAPI`. Proper name yang tidak dikenal dan vocabulary khusus tetap dapat dikoreksi secara keliru, sehingga biarkan feature tetap dinonaktifkan ketika mempertahankan ejaan secara persis lebih penting daripada typo tolerance.
