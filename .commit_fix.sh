#!/bin/bash
cd /Users/mjimenez/code/inky-image
git add -A
git commit -n -m "Fix circular import: extraer Renderer a modulo propio

- Crear inky_image/renderer.py con la ABC Renderer
- main.py: importa Renderer de renderer.py (ya no lo define internamente)
- web_app.py: importa Renderer de renderer.py (ya no importa main.py)
- Rompe el ciclo: main -> web_app -> main -> import fails"
git push