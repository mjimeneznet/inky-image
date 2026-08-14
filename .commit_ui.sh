#!/bin/bash
cd /Users/mjimenez/code/inky-image
git add -A
git commit -n -m "UI: unificar sistema de feedback y mejorar responsive

El mismo mensaje de accion aparecia en 4 canales a la vez:
- ui-badge (centro de pantalla, pulsante)
- action-status-bar (barra superior con spinner)
- status-output (dump JSON en settings)
- toasts (showBadge)

Ahora hay un solo canal de busy (action-status-bar) y toasts para
resultados. Eliminados: ui-badge, status-output, chip UI del topbar,
y las funciones showMessage/showBadge/showBusyBadge/setTopUiState.

Responsive: breakpoint intermedio para tablet (2 columnas), movil
sigue en 1 columna. Limpiado CSS huerfano."
git push