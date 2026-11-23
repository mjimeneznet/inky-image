# render-modes

Add two dithering strategies next to the current one, selectable in Settings, without
changing what the current mode does. Requested by the user after tuning brightness and
contrast was not enough to make photos read well on the 7-colour panel.

## Specs

S1 — The existing render path stays byte-for-byte identical as the default mode. A new
`render_mode` config key selects between `default`, `palette` and `oklab`, defaults to
`default`, and is validated on load and at the API like `slideshow_mode`. It is part of the
render signature, so switching repaints.

S2 — Mode `palette`: our own conversion, handed to the driver as a **P image**, so the driver
copies indices straight to the buffer instead of dithering again. Quantisation uses the
panel's physically measured inks (`_palette_blend(1.0)`), Floyd–Steinberg, palette index order
matching the driver constants.

S3 — Mode `oklab`: perceptual quantisation. The frame is converted to Oklab, ordered-dithered
with an 8x8 Bayer matrix, matched against the measured inks by Oklab distance, and mapped back
to the same palette index order. An unsharp mask is applied before conversion ("subir el
contraste (~1.3–1.4) y la nitidez antes de convertir"). Brightness and contrast settings still
apply; `saturation` does not (the measured palette is used explicitly).

S4 — The panel preview uses the selected mode, so the three can be compared without spending an
e-ink refresh. Preview and render share one code path.

S5 — Timing is reported: Oklab conversion must stay vectorised (numpy) so a render does not
become minutes slow on a Pi.

## Tasks

| ID | Specs | Files | Commit |
| --- | --- | --- | --- |
| R1 | S1 | config.py, main.py, web_app.py, templates, main.js, tests | 1 |
| R2 | S2-S3 | display.py, tests | 2 |
| R3 | S4-S5 | display.py, main.py, tests, docs | 3 |

## Log

L1 (verbatim): "La librería inky aplica por defecto un dithering básico de Pillow que suele
dejar las fotos apagadas o con mucho grano. Para superarlo, aplica una de estas estrategias
según lo que vayas a mostrar: 1. Para fotografías e ilustraciones complejas • Sustituye el
algoritmo por defecto: En lugar de dejar que set_image() convierta la foto, realiza la
conversión tú mismo antes de enviarla (por ejemplo, con ImageMagick o scripts en Python) y
pasa la imagen resultante en modo paleta ("P") para que el driver la copie directamente al
búfer sin volver a aplicar dithering. • Usa una paleta perceptual (Oklab) y ajusta la curva:
Los 7 colores reales de la pantalla (negro, blanco, verde, azul, rojo, amarillo y naranja) no
son tan puros ni brillantes como el RGB teórico. Mapear el dithering usando los colores
medidos físicamente del panel--como explican en el foro de Pimoroni--y subir el contraste
(~1.3--1.4) y la nitidez antes de convertir evita los tonos lavados"
L2 (verbatim): "me gustaria tener las 3 opciones en los settings y yo elegir"

L3: Implementation notes and measured cost.
- `default` is untouched: RGB frame + `saturation`, driver dithers (verified: the driver
  receives mode=RGB and a saturation kwarg).
- `palette` and `oklab` hand the driver a **P image** with the panel's measured palette in the
  driver's own index order, so `set_image` copies indices and never dithers twice (verified
  with a fake driver that asserts the mode it receives).
- `palette` uses Pillow Floyd-Steinberg against the measured inks (8 ms for 800x480 on an
  M-series Mac). `oklab` converts to Oklab, ordered-dithers with an 8x8 Bayer matrix
  (amplitude 0.09 in Oklab units) and matches inks by Oklab distance (79-116 ms). Expect
  roughly a second or two on a Pi 4 and more on a Zero, once per render.
- Both modes were checked against a real Pillow: zero colours outside the palette, and the two
  produce different output from the same source.
- The Oklab transform round-trips white to L=1.0 and black to L=0.0.
- Saturation only affects `default`; that is stated in the UI hint.

L4: Palette override (requested after the Pimoroni forum thread).
- `panel_palette`: `driver` (default, the driver's measured inks), `pure` (theoretical primaries)
  or `custom` plus `panel_palette_custom`, seven `#rrggbb` values in driver index order
  (black, white, green, blue, red, yellow, orange).
- Validated at load and at the API: a malformed list is refused with 400; a custom mode with no
  usable list falls back to `driver` at load.
- Applies to the two custom strategies only; `default` keeps the driver's own palette blend.
- Accepted by the preview route, so a pasted palette can be compared without a refresh.
- Measured on the Oklab path: raising the chroma of the dithering targets (the forum technique)
  made the perceived Oklab error worse in our ordered dither (0.111 at x0.7 rising to 0.139 at
  x2.0), so no built-in boost was shipped; the palette is what can be tuned, by hand, on the
  panel.
