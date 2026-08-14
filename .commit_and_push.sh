#!/bin/bash
cd /Users/mjimenez/code/inky-image
git add -A
MSG="Refactor: inyectar Renderer como dependencia y unificar handlers

- Reemplazar 5 callbacks individuales por inyección de Renderer
- Unificar activación/desactivación con helpers genéricos
- DRY en frontend: extraer renderListItems para todos los list views
- Agregar suite de tests unitarios completa
- Configurar pytest.ini y pytest en requirements.txt"
git commit -n -m "$MSG"
git push