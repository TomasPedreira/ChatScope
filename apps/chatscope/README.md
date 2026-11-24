# ChatScope

## Vídeos YouTube

Além do chat Twitch, a app aceita URLs `youtube.com/watch`, `youtu.be`,
`youtube.com/shorts`, `youtube.com/embed` e `youtube.com/live` de vídeos já
publicados/processados. Canais e playlists não são entradas de análise.

Prepara a dependência isolada uma vez (Python 3.10+):

```powershell
.\Setup-YouTube.ps1
```

O lançador cria `.venv-youtube` nesta pasta e instala a versão fixada em
`requirements-youtube.txt`. A app procura esse ambiente junto do projeto ou
do executável e usa o Python do PATH como alternativa. O adapter é incorporado
no executável; não é necessário distribuir o script Python separadamente.

1. Cola o URL ou clica no exemplo **YouTube** e escolhe **Analisar YouTube**.
2. Opcionalmente indica início/fim dentro da duração do vídeo.
3. Consulta a timeline e os candidatos ordenados por intensidade relativa.
4. Seleciona um candidato ou um segmento e usa **Abrir no YouTube** para rever
   o vídeo no navegador a partir do início do intervalo.
5. Exporta JSON (metadados, heatmap e candidatos) ou CSV (candidatos e links).

Em **Perfil do clip**, escolhe a duração pretendida (5–180 s), o contexto antes
do pico e o máximo de candidatos (1–30). O restante tempo fica depois do pico.
O planeador desloca o intervalo nos limites do vídeo para manter a duração;
se a origem ou região for mais curta, usa apenas o tempo disponível. O mesmo
perfil aplica-se aos candidatos Twitch e é preservado no JSON. Estes valores
definem propostas para revisão, sem iniciar renderização ou publicação.

O adapter consulta apenas metadados públicos, sem descarregar vídeo ou usar
cookies pessoais. O perfil inicial usa 30 s, com 20 s antes do pico, e oito
candidatos no máximo. Os picos não interpretam a história do vídeo.
Sem heatmap, a consulta termina normalmente e informa que o sinal está ausente;
uma falha de rede, dependência ou extractor aparece como erro. Heatmaps planos
podem não produzir candidatos. **Parar** cancela o subprocesso de extração.

O gráfico não fornece contagens de cliques, percentagens de audiência nem uma
probabilidade de qualidade. O YouTube não publica um prazo ou limiar de vistas
garantido para o heatmap público. Vídeos recentes, com poucas vistas ou não
elegíveis podem não o ter. A extração com yt-dlp depende de interfaces do site
que podem mudar. [Regras de disponibilidade](https://support.google.com/youtube/answer/12825599?hl=en).

```powershell
# Prova de rede, sem download de vídeo
.\.venv-youtube\Scripts\python.exe tests/probe_youtube.py
# Interface, dados gravados e estados de ausência/erro/cancelamento
node tests/youtube-preview.mjs
# Integração nativa real numa janela oculta; requer dist/ChatScope.exe
node tests/youtube-native.mjs
# Mesmo motor pela CLI
.\dist\ChatScope.exe --scope-youtube 'https://youtu.be/YE7VzlLtp-4' --output artifacts/youtube.json
# Com perfil de corte
.\dist\ChatScope.exe --scope-youtube 'https://youtu.be/YE7VzlLtp-4' --duration 60 --before-peak 40 --max-moments 3 --output artifacts/youtube-60s.json
```

O suporte atual termina na seleção/revisão e exportação de candidatos. A
recolha `study/`, a edição automática e a fila de publicação mantêm o seu fluxo
Twitch. A documentação da [arquitetura e prova](../../docs/youtube-scoper.md)
explica os pontos de extensão.

Aplicação desktop Windows em **Rust + Tauri 2**, criada a partir das tarefas
«twitch chat» do workspace Clipping: acesso ao chat, recolha de sinais de momentos
engraçados e processamento desses sinais.

## Abrir

Executa `Start-ChatScope.ps1` nesta pasta (ou na raiz do workspace). O script abre a versão compilada;
se ainda não existir, compila em release com Cargo. Precisas do WebView2, Rust e das
ferramentas C++ do Visual Studio para compilar no Windows.

A partir da raiz `Clipping`:

```powershell
cargo build --release --manifest-path apps/chatscope/Cargo.toml --target-dir "$env:LOCALAPPDATA/Clipping/Cache/chatscope-target"
cargo test --manifest-path apps/chatscope/Cargo.toml --target-dir "$env:LOCALAPPDATA/Clipping/Cache/chatscope-target"
```

## Utilizar

1. Cola um URL de canal (`https://www.twitch.tv/canal`), VOD
   (`https://www.twitch.tv/videos/ID`) ou clip Twitch.
2. Para VODs, podes indicar início e fim em segundos, `MM:SS` ou `HH:MM:SS`.
   Um parâmetro `?t=1h2m3s` no URL também é respeitado. O intervalo é `[início, fim)`.
   Sem fim, extrai até ao fim do VOD. Nos clips, usa o intervalo do VOD de origem.
3. Clica em **Capturar chat**. Num canal, recebe apenas novas mensagens a partir
   da ligação; num VOD, percorre o replay com paginação por cursor.
4. Pesquisa em toda a sessão por utilizador/texto ou por reações. A lista mostra
   os últimos 400 resultados; JSON e CSV incluem sempre a sessão completa.
   Clica num momento para consultar as mensagens desse intervalo, incluindo
   mensagens anteriores às últimas 400. «Voltar ao chat» repõe a vista geral.
5. **Parar captura** preserva o que já foi recebido. A exportação abre uma caixa
   de diálogo nativa e permite escolher o destino. Exportar durante a captura
   guarda uma fotografia dos dados no momento do clique.

O botão de exemplo VOD procura um VOD recente na Twitch no momento do clique,
em vez de depender de um identificador que pode expirar.

## Timestamps e sinais

- **Ao vivo:** os tempos são relativos ao início desta captura, incluindo a
  ligação. Não são o tempo decorrido da transmissão. O timestamp UTC original
  de cada mensagem também é exportado.
- **VOD/clip:** os tempos são posições absolutas no VOD, mesmo quando só se
  extrai um intervalo ou um clip.
- As janelas de análise têm 10 segundos. Reações reconhecidas incluem `LUL`,
  `KEKW`, `OMEGALUL`, `LOL`, `LMAO`, `Pog`, risos escritos e 😂/🤣.
- Um candidato exige pelo menos 4 mensagens, 2 reações e 3 participantes
  distintos na janela. O sinal combina proporção de reações, atividade face à
  média da sessão e participantes distintos. Na interface, os intervalos usam
  o perfil do clip e são selecionados sem sobreposição; o limite inicial é oito.
  A CLI de captura de chat conserva a análise legada de oito momentos.
- O valor de 0–100 exportado em JSON é um **score heurístico** usado para ordenar
  os momentos, sem interpretação probabilística. A interface mostra os horários
  e as contagens de reações/participantes em vez desse valor.
  Não há modelo treinado, classificação confirmada de humor ou análise de vídeo.
  Spam, entusiasmo e emotes podem produzir falsos positivos. É uma primeira
  ferramenta de triagem para rever o vídeo e recolher feedback humano.

## Dados e limites

O backend faz os pedidos HTTPS/WSS. O frontend local não carrega conteúdo remoto
nem executa texto do chat como HTML. Não há tokens pessoais, envio de mensagens
ou gravação automática do chat. Os dados ficam em memória até serem exportados;
fechar a app perde uma sessão não exportada. Limite de cerca de 250 mil mensagens
por sessão; ao atingir o limite, a captura para com um aviso e permite exportar.

O CSV usa UTF-8 com BOM, aspas escapadas e neutralização de células que começam
por caracteres de fórmula, para abrir no Excel. O JSON preserva o texto original,
metadados da origem e candidatos. As mensagens são deduplicadas pelo ID Twitch.

O replay de VOD utiliza o endpoint GraphQL do site Twitch, que **não é uma API
pública estável**. Pode mudar ou recusar pedidos. VODs expirados, privados,
replays desativados e clips sem VOD de origem não permitem recuperar o chat.
Não existe recuperação de mensagens já apagadas ou de mensagens perdidas durante
uma desconexão do chat ao vivo. A app tenta restabelecer a ligação e mantém o que
recebeu. Os exports anteriores do workspace e o Tailscale não foram alterados.

## Verificar sem interface

O mesmo motor Rust também aceita uma captura pela linha de comandos:

```powershell
& 'apps/chatscope/dist/ChatScope.exe' --capture 'https://www.twitch.tv/twitchplayspokemon' --seconds 30 --output 'apps/chatscope/artifacts/live.json'
& 'apps/chatscope/dist/ChatScope.exe' --capture 'https://www.twitch.tv/videos/ID' --start 600 --end 900 --output 'apps/chatscope/artifacts/vod.json' --csv 'apps/chatscope/artifacts/vod.csv'
```

A fixture local está em `tests/fixtures/vod.json`; os resultados gerados ficam em `artifacts/`.
`artifacts/verification.json` regista os resultados da demonstração desta versão.
Os testes unitários verificam URLs/tempos, parsing IRC Unicode, critérios mínimos
de vários participantes e proteção/escaping do CSV. A demonstração real verifica
a rede, a paginação, os timestamps e a interface nativa.

## Testes da interface sem controlar o desktop

```powershell
cd apps/chatscope
npm ci
npm test
npm run test:native
```

`npm test` abre Edge **headless** num perfil separado e verifica a apresentação
com dados reais gravados, filtros e layout a 1280×860 e 1020×700.
`npm run test:native` abre **outra instância Tauri oculta**, com perfil WebView2
separado e CDP temporário em loopback. Verifica que a janela está oculta, testa
o caminho completo interface → Rust → Twitch para VOD e chat ao vivo, captura
screenshots e fecha a instância. Não ativa janelas nem injeta rato ou teclado
no sistema. Precisa do executável `dist/ChatScope.exe` (o lançador prepara-o após compilar).

A app normal não abre uma porta de depuração. Os argumentos e o perfil de
depuração existem apenas no processo filho iniciado pelo teste. O atalho
`Ctrl+Enter` inicia a captura quando a app está em foco.

## Como chega o chat

O motor Rust recebe o chat ao vivo por IRC sobre WebSocket seguro em
`wss://irc-ws.chat.twitch.tv:443`. Nesta versão usa leitura anónima; não pede
uma conta ao utilizador nem envia mensagens. Os VODs são lidos com pedidos
HTTPS ao GraphQL do site, paginados por cursor. Um clip é resolvido para um
intervalo do seu VOD de origem. Estes caminhos já foram verificados com
mensagens reais, mas não substituem uma integração oficial autenticada.

A interface consulta o estado do Rust uma vez por segundo através de IPC
Tauri. Essa consulta é local; não é polling HTTP do chat ao vivo da Twitch.

Para uma integração oficial de chat ao vivo, a Twitch recomenda EventSub:
OAuth com `user:read:chat`, ligação WebSocket, subscrição de
`channel.chat.message` criada por REST e mensagens JSON recebidas nessa ligação.
EventSub não fornece o replay do chat de VODs. Referências oficiais:
[autenticação e subscrições](https://dev.twitch.tv/docs/chat/authenticating/),
[eventos de chat](https://dev.twitch.tv/docs/eventsub/reference/chat),
[WebSockets](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/).

## Referências de implementação

- [Tauri: comandos entre frontend e Rust](https://v2.tauri.app/develop/calling-rust/).
- [Twitch: protocolo IRC](https://dev.twitch.tv/docs/chat/irc/).
- [TwitchDownloader: implementação de referência para replay de chat](https://github.com/lay295/TwitchDownloader/blob/master/TwitchDownloaderCore/ChatDownloader.cs).


## Pastas locais

`dist/` contém o executável e `artifacts/` contém resultados de testes.
Ambas são ignoradas pelo Git. Os caches Cargo ficam em
`%LOCALAPPDATA%/Clipping/Cache/chatscope-target`.
Para recompilar e abrir: `./Start-ChatScope.ps1 -Build`.
A pasta de media War of Rights está em `../../media/war-of-rights/`, separada da app.
