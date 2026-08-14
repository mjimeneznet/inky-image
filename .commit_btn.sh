#!/bin/bash
cd /Users/mjimenez/code/inky-image
git add -A
git commit -n -m "Fix boton B saltando imagenes: ejecutar callbacks en worker thread

El hilo del boton ejecutaba render_next_image sincronamente, bloqueandose
durante el render e-ink (1-2s). Los falling edges de rebote del mismo pulso
se acumulaban en el buffer del kernel y, al terminar el render, se procesaban
como pulsacion nueva (el debounce comparaba el tiempo de procesamiento, no
del evento), avanzando 2+ imagenes con 1 pulsacion.

- ButtonHandler ahora despacha callbacks a un ThreadPoolExecutor (1 worker)
- El reader thread nunca se bloquea: el debounce descarta los eventos de
  rebote correctamente (llegan a pocos ms del primer edge)
- Pulsaciones reales se encolan y ejecutan en orden tras el render
- Agregar tests de debounce y dispatch no bloqueante"
git push