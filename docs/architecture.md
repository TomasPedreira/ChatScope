# Arquitetura e organização do código

A desktop app usa HTML/JavaScript e Tauri IPC para falar com Rust. Rust coordena
a análise, os detectors e a produção. Um worker Python local integra yt-dlp,
FFmpeg e, opcionalmente, Whisper. A CLI usa os mesmos serviços do desktop.

## Rust: responsabilidades explícitas

```text
apps/chatscope/src-tauri/src/
  main.rs                    arranque, configuração e registo dos comandos
  cli.rs                     modos --capture, --scope-youtube e --media-job
  commands/
    analysis.rs              comandos de aquisição/análise e snapshots
    production.rs            criar, cancelar, retomar e abrir clips
    exports.rs               exportação JSON/CSV
  analysis_session.rs        AnalysisSession em memória e SessionSnapshot
  domain_models.rs           MediaSource, SourceInput, SignalPoint, ClipCandidate
  clip_profiles.rs           ClipProfile, RenderProfile e TimeRange
  source_providers.rs        SourceProvider e ProviderRegistry
  kick_provider.rs           validação/routing específico Kick
  twitch_chat.rs             transportes e sinais específicos Twitch
  moment_detectors.rs        detectors de chat, heatmap e áudio
  media_analysis.rs          normalização e deteção dos sinais devolvidos pelo worker
  media_worker_client.rs     runtime Python, stdin/stdout, timeout e processos filhos
  clip_production.rs         ClipProductionManager e lifecycle dos lotes
  production_paths.rs        diretório de saída e geração de job IDs
  production_store.rs        leitura/escrita atómica de manifests e estado
  session_exports.rs         serialização/exportação de candidatos e análises
  source_links.rs            construção de links por timestamp
  youtube_heatmap_tests.rs   fixtures e regressões de heatmaps
```

Os candidatos chamam-se `ClipCandidate`: ainda não são MP4. `ClipProfile` usa
`duration_seconds` e `seconds_before_peak`. `RenderProfile` usa `aspect_ratio`,
`framing_mode` e `include_captions`. `master_source_offset_seconds` identifica
a posição do início do master na timeline da fonte.

`AnalysisSession` guarda uma única `video_analysis`. O campo antigo YouTube é
derivado apenas no snapshot de compatibilidade, evitando duas cópias mutáveis
da mesma análise dentro da sessão.

## Python: aquisição, rendering e storage separados

```text
apps/chatscope/pipeline/
  worker.py                  dispatcher fino do protocolo JSON
  source_analysis.py         aquisição de metadados e sinais
  media_sources.py           MediaSource, YtDlpSource, LocalSource, MediaSourceRegistry
  kick_source.py             integração Kick sobre o adapter comum
  audio_signals.py           extração de energia de áudio por segundo
  video_renderer.py          Renderer e FFmpegRenderer
  speech_transcriber.py      Transcriber e WhisperTranscriber para legendas de saída
  caption_models.py          CaptionProfile, SubtitleCue e TimedTranscript
  caption_service.py         áudio limitado, legendas inglesas, SRT e proveniência
  transcript_translation.py  contrato para futuras direções, incluindo EN → PT
  clip_production.py         execução dos intervalos escolhidos e verificação do MP4
  request_validation.py      validação de perfis e dados do heatmap
  job_storage.py             escrita atómica, manifests e data Europe/Lisbon
  review_index.py            índice gerado dos ficheiros locais
  media_tools.py             FFmpeg, execução de comandos e probe de vídeo
```

Rust `ProviderRegistry` escolhe o fluxo da app e valida a origem. Python
`MediaSourceRegistry` escolhe o adapter que obtém metadados e media. O renderer
recebe ficheiros locais e intervalos, sem conhecer a plataforma.

## Interface

`ui/app.js` coordena a sessão, a seleção e as views de chat/vídeo. Os nomes
genéricos são `renderVideoAnalysis`, `selectedVideoCandidate` e `isVideoAnalysis`.
`clip_production_view.js` mantém os controlos e progresso de produção;
`dom_helpers.js` mantém helpers de apresentação e `tauri_client.js` a fronteira
IPC. Os módulos são ES modules locais, sem framework ou conteúdo remoto.

## Compatibilidade e naming

As alterações de nomes internos não mudam os comandos públicos Tauri, os modos
CLI nem o JSON já guardado. Mapeamentos serde mantêm `duration`, `beforePeak`,
`aspect`, `fit`, `captions`, `moments`, `mediaOrigin` e os campos dos snapshots.
Os pedidos existentes podem continuar a ser retomados. Os aliases legados
ficam na fronteira de serialização; o código interno usa nomes do domínio.

Usa-se snake_case em Rust/Python, camelCase em JavaScript e PascalCase nos tipos.
Funções devem descrever ações; nomes temporais novos devem indicar unidades e,
quando necessário, a timeline de referência. Variáveis locais curtas continuam
adequadas quando o contexto é pequeno e inequívoco.

## Onde ficam as sugestões e os clips

Antes de produzir vídeo, os ClipCandidate aparecem na interface e nos exports
JSON/CSV escolhidos pelo utilizador. A cache contém evidência de aquisição;
não deve ser confundida com MP4 já preparados.

```text
media/daily/
  requests/ID.json             candidatos e perfis de um lote pedido
  current.json                 estado do último lote
  cache/ID/                    sinais e masters usados na análise
  YYYY-MM-DD/
    clips/TEMA/ID-NN.mp4        potenciais clips renderizados para revisão
    jobs/ID/job.json            origem, cortes, estado, hashes e caminhos
    jobs/ID/N/master/           trechos adquiridos para o rendering
    clips-index.md              índice automático; preserva review.md humano
```

Na instalação atual, a raiz é `C:\Users\joaoa\REPOS\ChatScope\media\daily`.
Não é necessário um canal YouTube para guardar/rever os ficheiros locais.

A [geração de legendas inglesas](english-captions.md) separa a língua falada da
língua de saída e permite substituir o provider sem alterar origens ou rendering.

## Próximo sinal: texto do vídeo

A [issue #3](https://github.com/TomasPedreira/ChatScope/issues/3) acompanha
legendas/transcrições como sinais de deteção, começando por YouTube. É diferente
de usar Whisper para legendar um clip já selecionado. Os sinais atualmente
implementados são chat, heatmap e energia de áudio.
