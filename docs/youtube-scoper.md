# YouTube scoper

Implementação na branch `youtube_scoper`. A experiência permite analisar um
vídeo YouTube na aplicação desktop e selecionar momentos pelo heatmap público,
sem exigir chat ou autorização do canal.

## Arquitetura

`scope.rs` define `Source`, `Moment`, `SignalPoint` e o pedido de origem.
`providers.rs` contém o trait `SourceProvider`, as implementações concretas
`TwitchProvider` e `YouTubeProvider` e o `ProviderRegistry`. O registo escolhe
o adapter, valida/canonicaliza o URL e prepara a origem. As capabilities
identificam os modos efetivamente implementados, sem anunciar suporte a chat
ao vivo no YouTube ou a Kick nesta versão.

`detectors.rs` define o trait `MomentDetector`, `HeatmapDetector` e
`ChatActivityDetector`. A aquisição não escolhe a duração do corte: fornece
os dados normalizados ao detector. `chat.rs` conserva o transporte Twitch e
o cálculo de sinais; disponibiliza também os candidatos sem a antiga
restrição de oito para o planeador aplicar o perfil escolhido.

`clips.rs` contém `ClipProfile` e `TimeRange`. O perfil valida duração
pretendida, contexto antes do pico e máximo de candidatos. O planeamento
mantém a duração junto aos limites, deslocando o intervalo quando possível.
Os candidatos identificam sempre `signal`, `strength`, `peak`, `start`, `end`
e `reason`. A interface usa estes candidatos comuns em ambas as origens.

Fluxo YouTube:

```text
UI local -> start_capture (IPC Tauri) -> validação/canonicalização do URL
  -> subprocesso Python isolado -> providers/youtube.py -> yt-dlp -> YouTube
  -> JSON de metadados e heatmap -> validação e detector Rust
  -> Session em memória -> get_snapshot -> timeline e candidatos na UI
  -> revisão no navegador / exportação JSON ou CSV
```

O Python é executado com argumentos separados, `-I`, stdin fechado e janela
oculta. O código do adapter é incorporado em Rust com `include_str!`.
Apenas o URL canonicalizado chega ao extractor, sem parâmetros de playlists.
Há um timeout de 50 segundos; cancelar elimina o processo filho. A geração
da sessão impede que um resultado antigo substitua uma sessão nova.

O frontend carrega apenas ficheiros locais. Os metadados são inseridos como
texto, nunca HTML; abrir um momento usa o navegador do Windows com um URL
YouTube construído no backend. O CSP continua sem permitir conteúdo remoto.

## Detector e interpretação

Os intervalos são validados, ordenados e limitados à região pedida. O detector
procura máximos locais acima da mediana mais uma margem. Agrupa plateaus,
ordena por intensidade e elimina sobreposições segundo os intervalos do
perfil. Por defeito escolhe até oito sugestões de 30 s, com 20 s antes do pico.
Na UI, a duração pode ser 5–180 s e o máximo de candidatos 1–30. O JSON guarda
o perfil e os intervalos efetivos; uma região mais curta limita a duração.

`strength` é um sinal relativo normalizado, sem significado probabilístico.
Um heatmap de 100 pontos num vídeo de duas horas tem intervalos de cerca de
72 segundos: o pico é uma aproximação, não um ponto de corte editorial exato.
Picos no início, música, tutoriais ou explicações repetidas podem não dar bons
Shorts. Não existe análise semântica automática nesta primeira integração.

Estados distintos:

- `available`: heatmap válido; pode não ter picos distintos.
- `unavailable`: metadados válidos, mas nenhum heatmap devolvido pelo YouTube.
- `error` na sessão: vídeo inacessível, extração falhada, dados inválidos,
  Python/dependência ausente ou timeout.
- `stopped`: operação cancelada.

Não é possível concluir, pela ausência do campo, por que razão um vídeo não tem
heatmap. A UI apresenta possibilidades, sem inventar um limiar de vistas ou
uma previsão de disponibilização. [Elegibilidade segundo o YouTube](https://support.google.com/youtube/answer/12825599?hl=en).
Os prazos do [relatório de retenção no Studio](https://support.google.com/youtube/answer/9314415?hl=en)
não garantem a disponibilidade do gráfico público.

## Prova real

Teste inicial em 24 de novembro de 2026, com yt-dlp `2026.11.23`, sem cookies,
login ou download de media:

| Vídeo | Duração | Heatmap |
| --- | ---: | --- |
| Big Buck Bunny, `YE7VzlLtp-4` | 597 s | 100 intervalos |
| Never Gonna Give You Up, `dQw4w9WgXcQ` | 213 s | 100 intervalos |
| Me at the zoo, `jNQXAC9IVRw` | 19 s | 100 intervalos |
| Antigo vídeo de teste, `BaW_jenozKc` | indisponível | erro de metadados, sem classificar como ausência de heatmap |

Estes casos demonstram a viabilidade técnica, sem estabelecer cobertura de
todos os vídeos. O caso de heatmap ausente é também coberto por fixture
determinística; não foi inferido a partir de um vídeo inacessível.

`tests/probe_youtube.py` repete a prova e guarda `artifacts/youtube-probe.json`.
A fixture `tests/fixtures/youtube.json` preserva os 100 pontos da primeira
consulta de Big Buck Bunny para testes Rust e de interface sem rede.

Os testes Rust verificam validação de URL, dados inválidos, ausência, curvas
planas, plateaus, ordenação, sobreposição, limites do intervalo e escaping do
CSV. O teste headless verifica timeline, navegação, abertura por timestamp,
exportação sem chat, metadados não confiáveis, estados de ausência/erro,
cancelamento, mudança para Twitch e layout compacto. O teste nativo consulta
o YouTube pelo caminho real UI -> IPC -> Rust -> Python e verifica intervalo,
cancelamento e preservação da sessão perante URLs inválidos.

Validação final: 14 testes Rust, três testes Python e ambos os testes de
interface headless passaram. A instância nativa oculta recebeu 100 intervalos
reais, gerou três candidatos de 60 s, respeitou um intervalo de 60–180 s e
validou cancelamento. O adapter usa apenas o cliente web e evita manifests
de media/formatos JavaScript; repete uma resposta de metadados incompleta uma
vez. Durante o desenvolvimento ocorreram respostas incompletas/timeouts,
pelo que a disponibilidade em rede continua a exigir estados de erro claros.

A regressão nativa Twitch também passou: 1 816 mensagens reais do VOD,
navegação pelos intervalos planeados, pesquisa/filtros e captura/paragem de
chat ao vivo. A CLI YouTube exportou 100 intervalos e três sugestões de 60 s.

## Fontes seguintes e trabalho em falta

| Origem / modo | Estado atual | Caminho de integração |
| --- | --- | --- |
| Twitch live, VOD e clip | Implementado | Chat normalizado -> ChatActivityDetector |
| YouTube gravado / direto já processado | Implementado | Heatmap público opcional -> HeatmapDetector |
| YouTube live | Planeado, sem captura nesta versão | API oficial de live chat -> mensagens normalizadas -> ChatActivityDetector |
| Kick live | Investigado, sem captura nesta versão | Eventos oficiais de chat -> receiver de webhooks -> mensagens normalizadas |
| Kick VOD / ficheiro sem sinais de público | Investigação necessária | Transcrição, áudio e imagem -> novos detectors |

O [YouTube streamList](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList)
recebe chat em tempo real e permite retomar por token. Exige tratar permissões,
quota, reconexão, chat desativado e fim do direto. A API documenta que não
recupera chat de um direto já terminado; replay requer uma integração própria.
Não se deve prometer um heatmap durante o direto.

A [API de eventos Kick](https://github.com/KickEngineering/KickDevDocs/blob/main/events/introduction.md)
disponibiliza `chat.message.sent` por webhooks, incluindo subscrição com app
tokens a canais identificados. O receiver exige um URL público e validação
das assinaturas. Uma app apenas em localhost não recebe esses eventos sem
um serviço acessível. Os [payloads](https://github.com/KickEngineering/KickDevDocs/blob/main/events/event-types.md)
permitem normalizar mensagem, autor e timestamp para reutilizar o detector.
Não encontrei nos recursos oficiais consultados uma API de heatmap ou de
replay histórico de chat para VODs Kick; isso não demonstra que o site não
tenha outros mecanismos, mas não permite prometer suporte estável.

Sem chat nem heatmap, um detector futuro pode combinar transcrição (mudanças
de tema, frases completas e conclusões), áudio (risos, excitação e pausas) e
imagem (mudanças de cena ou acontecimentos). Estes são sinais para propor
candidatos, que precisam de avaliação com clips revistos. Picos de volume
isolados não demonstram relevância. Convém guardar a origem e razão de cada
sinal e avaliar qualidade separadamente da intensidade de público.

Para acrescentar uma origem, implementar `SourceProvider`, registar o adapter
e devolver dados normalizados. Reutilizar um detector existente quando os
sinais forem compatíveis, ou implementar `MomentDetector` para um novo sinal.
O perfil e os contratos dos candidatos continuam comuns. Rust usa structs e
traits para estes blocos, equivalentes ao papel de classes e interfaces.

Os contratos comuns permitem acrescentar um adapter de ficheiros locais ou
detectors baseados em transcrição/áudio sem exigir `ChatMessage` aos vídeos.
Uma integração futura com YouTube Analytics poderá acrescentar retenção de
canais autorizados. A implementação atual não pede essas permissões.

A captura e edição automática em `study/` continuam separadas. Ainda falta
uma camada comum de media acquisition/rendering que receba os planos de corte
de qualquer origem e os ligue a FFmpeg e à fila de publicação. A UI define o
perfil para propostas, mas não aplica esse perfil aos antigos scripts de
drafts nem renderiza vídeo YouTube. Legendas, aspect ratio, resolução e presets
persistentes são extensões editoriais futuras, sem controlos fictícios na UI.
Não se inicia download de vídeo, edição ou publicação ao analisar um URL.
