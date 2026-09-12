# Architecture diagrams

This directory is the M0 kernel picture produced by Archify. It is **not**
an M2 two-host / WSL CUDA diagram and must not be cited as such.

## Landed (readable)

| File | Status |
| --- | --- |
| [m0-kernel.architecture.json](m0-kernel.architecture.json) | Source diagram. Revision `d17043a`. Views: main loop, simulation, non-launch boundary. |
| [m0-kernel.architecture.html](m0-kernel.architecture.html) | Rendered M0 kernel diagram. |

## Generated / incomplete

| File | Status |
| --- | --- |
| `m0-kernel.architecture.visual-check.json` | Automated browser containment. `status: pass`. **`visualReview: pending`** — no human visual sign-off in this pack. |
| `m0-kernel.architecture.visual-check.html` | Generated visual-check page. Incomplete until visual review. |
| `m0-kernel.architecture.visual-check.*.png` | Generated screenshots (1440×900 and 2048×1320, light/dark). Optional; the HTML is the readable artifact. |

Do not re-run Archify for M2 closure. Do not treat these files as
evidence that charter §14.4 dashboards shipped.
