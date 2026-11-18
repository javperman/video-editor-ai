---
name: Video QC
description: Usar al comprobar un render o un proyecto de vídeo en video-editor-ai antes de darlo por válido.
---

# Video QC

## Comandos

```bash
ffprobe -v error -show_entries format=duration,size,bit_rate \
  -show_entries stream=index,codec_type,codec_name,width,height,avg_frame_rate,nb_frames,sample_rate,channels \
  -of json salida.mp4

ffmpeg -hide_banner -nostats -i salida.mp4 -vf blackdetect=d=0.5:pix_th=0.10 -an -f null -
ffmpeg -hide_banner -nostats -i salida.mp4 -vf freezedetect=n=-60dB:d=2 -an -f null -
ffmpeg -hide_banner -nostats -i salida.mp4 -af ebur128=peak=true -f null - 2>&1 | tail -n 14
```

## Criterios

- Resolución y FPS exactos al plan.
- Duración coherente con la timeline.
- H.264 + audio AAC.
- Sin clipping; objetivo inicial −16 LUFS y true peak ≤ −1,5 dBTP.
- Sin negros ni congelados no intencionados.
- Difuminado sensible verificado en todos los frames de su aparición.
- Subtítulos sincronizados con error medio < 250 ms.

## Regla

Un render no está terminado porque el comando devuelva 0. Hay que comprobar
FFprobe, QC y que el proyecto siga reabriéndose.
