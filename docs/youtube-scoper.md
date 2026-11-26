# YouTube scoper

A branch `youtube_scoper` suporta heatmaps, captura YouTube Live e produção
de MP4 locais. A [arquitetura completa](media-pipeline.md) descreve os contratos,
adapters, detectors, rendering, persistência e limites.

O heatmap é opcional, consultado sem OAuth e sem download de media. É um sinal
relativo de repetição, sem contagens de cliques ou garantia de qualidade.
O detector Rust procura máximos acima da mediana, agrupa plateaus e evita
intervalos sobrepostos usando o ClipProfile comum.

Sem heatmap, a aplicação adquire um intervalo até dez minutos e analisa energia
do áudio. Num direto, grava 30–600 segundos; os tempos pertencem a essa gravação.
Não há captura de chat YouTube nesta versão nem heatmap durante o direto.
Sem picos distintos, pode definir-se um corte manual.

**Criar este MP4** ou **Criar todos os sugeridos** inicia aquisição e rendering
FFmpeg. A análise pelo heatmap, por si só, continua sem descarregar vídeo.
Ficheiros finais, masters e manifests ficam locais, sem uploads automáticos.

## Disponibilidade

O YouTube não publica um prazo ou limiar universal garantido para disponibilizar
o gráfico. A ausência do campo não revela a causa concreta.
[Elegibilidade](https://support.google.com/youtube/answer/12825599?hl=en).
Os prazos de retenção no Studio não garantem o heatmap público.

Um gráfico de 100 pontos num vídeo de duas horas tem segmentos de cerca de
72 segundos: o pico é aproximado. Música, ruído ou explicações repetidas podem
produzir picos sem dar bons Shorts. Os candidatos precisam de revisão.

## Provas de rede

Em 24/11/2026, a extração devolveu 100 intervalos em Big Buck Bunny
(`YE7VzlLtp-4`), Never Gonna Give You Up (`dQw4w9WgXcQ`) e Me at the zoo
(`jNQXAC9IVRw`). A fixture de Big Buck Bunny conserva os pontos reais para testes.
O vídeo `BaW_jenozKc` estava indisponível; não foi confundido com ausência de sinal.

Em 25/11/2026, um download limitado de Big Buck Bunny produziu cinco segundos,
1920×1080 e áudio. Uma captura do direto público NASA (`ROboUHfPUrU`)
produziu um master de 30,01 s, 1280×720 e áudio. O URL anterior da NASA estava
em processamento e foi corretamente rejeitado.

São provas dos caminhos testados, sem garantia de cobertura universal.
As interfaces, formatos e requisitos de JavaScript podem mudar.
[yt-dlp](https://github.com/yt-dlp/yt-dlp),
[EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

## Extensão

Uma origem implementa `SourceProvider` em Rust e `MediaSource` em Python;
devolve sinais normalizados e ficheiros locais. Um sinal novo implementa
`MomentDetector`. `ClipProfile`, `Moment`, `VideoAnalysis` e `FFmpegRenderer`
são comuns. Kick fica na branch separada `kick_scoper`.

`study/` conserva o coletor Twitch avançado e edições históricas. O desktop
usa o pipeline comum para produzir MP4. A fila de uploads é separada e opcional.
