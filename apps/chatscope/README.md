# ChatScope

Desktop Windows em Rust + Tauri 2 para encontrar momentos e criar MP4 locais
de Twitch, YouTube (incluindo diretos) e ficheiros locais. A integração Kick
fica na branch `kick_scoper`. [Arquitetura](../../docs/media-pipeline.md).

## Preparar e produzir clips

Executa `Setup-Media.ps1` nesta pasta uma vez (Python 3.10+). Reutiliza
`.venv-youtube`, instala yt-dlp/EJS, FFmpeg e tzdata. Node no PATH é usado
para JavaScript do YouTube. Para legendas: `Setup-Media.ps1 -Captions`.

1. Cola um URL ou escolhe vídeo local em **Perfil do clip**.
2. Define duração, contexto e máximo de candidatos. Sem heatmap, escolhe um
   intervalo até dez minutos. Em diretos, deixa início/fim vazios e define
   a captura (30–600 s). Para vídeo de Twitch live, ativa o modo vídeo/áudio.
3. Analisa o heatmap ou áudio; Twitch em modo chat mantém as reações de público.
4. Seleciona um momento e ajusta o corte, formato, enquadramento, tema e legendas.
5. Escolhe **Criar este MP4** ou **Criar todos os sugeridos**.
6. Revê os ficheiros em `media/daily/YYYY-MM-DD/clips/TEMA/` e `clips-index.md`.

A produção guarda progresso, masters, perfis e hashes. Pode ser cancelada;
**Retomar incompletos** preserva os MP4 prontos. Fechar a app termina os processos
filhos e permite retomar no arranque seguinte. Nada é publicado automaticamente.

Os tempos de diretos referem-se à gravação local. A captura termina após o bloco
escolhido; ainda não há buffer contínuo. Volume/repetição são sugestões heurísticas,
sem compreensão semântica da história. Confirmar vídeo e áudio antes de publicar.

`ChatScope.exe --media-job pedido.json` usa o mesmo pipeline; formato e exemplos
em [media-pipeline.md](../../docs/media-pipeline.md). A CLI de análise
`--scope-youtube` permanece disponível.

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
