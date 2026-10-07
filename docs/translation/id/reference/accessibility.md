# Verifikasi aksesibilitas

Semantix menjaga data chart tetap tersedia sebagai tabel semantik dan memeriksa token warna small-text bersama terhadap persyaratan kontras WCAG AA sebesar 4.5:1.

## Matriks kontras

Rasio di bawah ini menggunakan warna token yang telah dikompositkan dari `apps/web/src/index.css`.

| Foreground     | Background     |  Rasio | Teks normal |
| -------------- | -------------- | -----: | ----------- |
| `--text-muted` | `--ink`        | 6.79:1 | Lulus       |
| `--text-muted` | `--surface`    | 6.58:1 | Lulus       |
| `--text-faint` | `--ink`        | 5.18:1 | Lulus       |
| `--text-faint` | `--surface`    | 5.05:1 | Lulus       |
| `--coral-text` | `--ink`        | 5.85:1 | Lulus       |
| `--coral-text` | `--surface`    | 5.48:1 | Lulus       |
| `--ink`        | `--coral-text` | 5.85:1 | Lulus       |

Token `--coral` yang lebih gelap tetap tersedia untuk border, plot mark, dan aksen dekoratif. Teks coral berukuran kecil menggunakan `--coral-text`.

## Review visual manual

Periksa hal-hal berikut pada lebar desktop dan mobile:

* label muted dan teks penjelas faint tetap mudah dibaca pada kedua background utama;
* error coral, destructive action, dan label MISS tetap mudah dibaca tanpa terlihat lebih terang daripada konten utama;
* outline fokus tetap terlihat saat melakukan navigasi menggunakan keyboard;
* line chart benchmark dan histogram similarity tetap mempertahankan tampilan visualnya sekaligus menyediakan nilai yang sama dalam tabel untuk screen reader;
* bin histogram yang kosong tidak memiliki bar yang terlihat.

Jalankan pemeriksaan token otomatis dengan:

```powershell
cd apps/web
npm run test -- tests/shared/accessibility/contrast.test.ts
```

## Navigasi workspace dan konteks request

Subview evaluasi memakai tautan native dengan `aria-current` dan state URL:
`/evaluations?view=runs`, `?view=datasets`, `?view=history`, serta
`?view=reuse-quality`. Refresh, berbagi URL, dan riwayat browser mempertahankan
subview; nilai tidak dikenal menampilkan Runs. Redirect `/benchmarks`
mempertahankan search dan hash.

Kontrol namespace Monitor berada di luar Advanced cache policy. Pilihan wajib
yang kosong atau tidak valid memiliki penjelasan terlihat yang terhubung ke tombol
submit nonaktif dan input namespace. Tenant tidak dipilih diam-diam. Workspace
dimuat ulang ketika permission principal berubah.
Label pilihan namespace bawaan `default` tampil sebagai “Default”; identifier
yang dapat diedit, payload request, metadata cache, dan diagnostik tetap memakai
`default`. Label namespace lainnya tidak berubah.

Advanced cache policy selalu terlihat di samping kontrol namespace. Request cache
mode memakai tombol dan listbox milik fitur dengan style kontrol form yang ada.
Enter atau Space membuka daftar; panah serta Home/End memindahkan fokus tanpa
memilih. Enter atau klik memilih opsi. Escape membatalkan, Tab menutup dan
melanjutkan urutan fokus normal, serta interaksi di luar menutup tanpa merebut
fokus. State terpilih, state terbuka, fokus terlihat, dan helper mode terpilih tetap
tersedia untuk teknologi asistif; penekanan perilaku trace private dipertahankan.

Plot similarity mengikuti lebar kontainer tanpa scrollbar horizontal. Geometri
skala penuh −1.00 sampai 1.00, band referensi, titik, dan marker threshold tetap sama.
Legenda band yang bisa membungkus, label sumbu berukuran tetap, tick rapat pada
satu baseline, dan caption marker yang dibatasi tepi tetap terbaca di layar sempit.

Reuse quality menjelaskan scope bukti statis sebelum state loading dan gagal,
menautkan metodologi, serta menyediakan region tabel threshold yang bisa digulir
dengan keyboard. Denominator metrik dipertahankan dan nilainya berasal dari
receipt yang ditinjau. Observability mempertahankan timestamp observasi proses
terakhir yang berhasil ketika refresh gagal.

Polling dan revalidasi latar belakang mempertahankan data terakhir yang berhasil tanpa skeleton, indikator sibuk, atau peredupan. Placeholder loading hanya muncul saat belum ada data yang dapat dipakai. Aksi Refresh eksplisit tetap menampilkan feedback pending; refresh gagal mempertahankan observasi sebelumnya yang aman beserta pesan stale/error. Pergantian namespace atau principal tidak memakai ulang data dari scope lain.
