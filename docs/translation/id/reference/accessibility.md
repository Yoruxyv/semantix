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
