# Composición (PiP) y transform — 2026-11-09

## Lado del plan (verificado)

`src/video_ai/layouts.py` calcula un `transform` normalizado:

- `x`, `y`: esquina superior izquierda en 0..1 del lienzo.
- `scale`: fracción del ancho del lienzo; el alto sale del aspecto.
- `max_height` (opcional): tope de alto en fracción del lienzo; si el alto natural
  lo supera, se reduce `scale`. Pensado para verticales (móvil), donde un ancho
  pequeño ya ocupa mucho alto.
- `fit_aspect` + `focus` (opcionales): recortan la capa tipo *cover* a una
  proporción de caja (alto/ancho), con anclaje vertical (`center`/`top`/`bottom`).
  Sirve para convertir un móvil vertical (9:16) en un recuadro tipo *talking head*
  (p. ej. 3:4). El render lo aplica con `crop` de FFmpeg antes de escalar.
- Presets de esquina, margen y validación de que la capa cabe.

Probado con 4 pruebas (posiciones, error si no cabe, PiP sobre la pista V2 y que
el original no se modifica).

## Lado de OpenChatCut (encontrado en su código)

En `remotion-bundle/bundle.js`, `appearanceAt` aplica:

```js
transform: translate(<x>%, <y>%) rotate(<r>deg) scale(<sx>, <sy>)
transformOrigin: 50% 50%
```

Es decir, **`x`/`y` son porcentajes del tamaño propio del elemento**, con origen
en el centro, y `scale` es un multiplicador. En el spike, `{scale:0.28, x:60,
y:-60}` significaba «escala a 28 % y desplaza a la derecha y arriba».

## Conversión propuesta (matemática probada, aplicación sin verificar)

Suponiendo que el elemento base ocupa el lienzo, la esquina visual tras escalar
alrededor del centro es `(1-s)/2`, luego:

```text
x% = x - 0.5 + s/2
y% = y - 0.5 + s/2
```

Implementada en `src/video_ai/adapters/occ_transform.py` con ida y vuelta
probadas (`tests/test_occ_transform.py`). **No se aplica todavía en el editor**
porque la suposición no está confirmada.

## Calibración por render: inconcluyente

`scripts/calibrate_transform.py` intenta medir la caja de una capa magenta sobre
fondo negro tras aplicar transforms conocidos y exportar. Resultado:

- El caso identidad `{scale:1,x:0,y:0}` salió correcto (capa a pantalla completa).
- La mayoría de los casos devolvieron caja vacía (no se detectó la capa), y el
  único caso con medidas `{scale:0.28,x:60,y:-60}` dio una caja vertical
  (0,12 × 0,35) incompatible con la suposición, lo que apunta a que el elemento
  base **no** ocupa el lienzo o a un montaje distinto del esperado.

Conclusión honesta: **la conversión no está verificada**. No se envía al editor
como si funcionase. Falta repetir la calibración con un montaje fiable (una capa
con proporción conocida y comprobando que se importa y se monta en cada caso).

## Siguiente

1. Repetir la calibración comprobando en cada caso que la capa existe y se exporta.
2. Fijar los coeficientes reales y conectarlos al adaptador (`edit_item` updates).
3. Añadir un render de comprobación al protocolo antes de dar PiP por válido.

## Resuelto por otra vía: PiP en el render local

Para no depender de la incógnita de `transform` de OpenChatCut, el **render local**
(`src/video_ai/render.py`) aplica el PiP directamente con `overlay` de FFmpeg,
usando el `transform` normalizado del plan (`x`, `y`, `scale`).

Verificado por medición: se renderiza una capa magenta sobre fondo negro y se
mide su caja en el fotograma; coincide con el `transform` pedido (x, y, ancho
dentro de ±0,03). Eso cierra la composición PiP sin tocar OpenChatCut.

También se corrigió un **bug real**: el alto del PiP se calculaba sin tener en
cuenta el aspecto del lienzo, de modo que en un lienzo 16:9 la capa se salía por
abajo. Ahora el alto en fracción es `scale * aspect_capa * aspect_lienzo`.
