# Shorts para revisão privada

## Candidatos dos diretos

O lançador do estudo prepara automaticamente um rascunho por candidato com fonte de 720p ou superior. Usa Faster Whisper local para transcrever em inglês, escolhe uma janela inicial à volta do pico e exporta em 9:16 com volume nivelado. O ficheiro JSON ao lado do MP4 guarda a origem, a transcrição e os pontos de corte. O FFmpeg grava as legendas no vídeo.

Depois de rever o início, a ação e a reação, ajusta o corte ou regista o motivo do descarte. Os tempos são relativos à prévia da recolha. O comando volta à fonte e reutiliza a transcrição.

```powershell
python apps/chatscope/study/drafts.py
python apps/chatscope/study/drafts.py $sessao 0001-creator --inicio 32 --fim 57
python apps/chatscope/study/drafts.py $sessao 0001-creator --descartar 'Falta o acontecimento antes da reação'
& $shortsPython apps/chatscope/study/shorts.py publicar $rascunho `
  --title 'He Pulled the Handbrake at the Worst Possible Time' `
  --motivo 'O jogo e a fala do streamer explicam por que tentou parar ali' `
  --acao 4.5 'Puxa o travão de mão a caminho do cais' `
  --desfecho 14 'O carro derrapa, salta o cais e cai no mar'
```

Usa `--remover INICIO:FIM` para saltar uma pausa dentro do corte. Podes repetir a opção. Para uma história focada no streamer, `--face-crop` sozinho centra a câmara. Quando houver os dois recortes, `--so-cara 0:4 18:24` destaca a cara durante esses segundos do MP4 final.

Vê o rascunho final de início ao fim com áudio. Indica os segundos, a partir do MP4 vertical, em que se vê ou ouve a ação e o desfecho. Confirma que o título descreve o que o espectador vai encontrar nesse corte. O envio entra privado enquanto o YouTube processa o ficheiro. A publicação confirma o canal, o processamento e a visibilidade pública, e guarda o motivo editorial e os dois momentos. Repetir o mesmo comando retoma o envio ou reconhece o mesmo ID. Os hashtags podem ser indicados por jogo ou momento. A recolha e os rascunhos funcionam com o Python do estudo, que precisa do pacote `faster-whisper`. O comando de publicação usa o Python do ambiente de Shorts.

Antes de escrever o título, confirma que o próprio corte mostra uma ação clara e
uma consequência que valha a espera. Usa a reação para fechar um momento já
compreensível. O Short do OVNI do Speed foi retirado porque a ida até ao carro,
o clarão e a fala posterior deram pouco ao espectador para ver.

A fila aplica um intervalo mínimo de 30 minutos entre publicações. Um Short processado durante esse intervalo fica privado e pode ser retomado depois da hora indicada, com o mesmo ID.

Quando o utilizador dispensar a pausa para um lote, usa `publicar --sem-intervalo` em cada corte aprovado.

Por decisão do utilizador, o LIRIK fica fora da seleção para publicação.

Para agendar uma nova tentativa após um limite de uploads, usa `shorts.py retomar ID --apos DATA_ISO_COM_FUSO` com a hora mínima registada na ronda. O comando recupera a aprovação e os tempos da revisão, verifica o ficheiro e usa a mesma fila de publicação.

Escreve títulos em inglês ao estilo dos primeiros Shorts que o utilizador
destacou. Em “IShowSpeed Stole a Scooter. He Regretted It IMMEDIATELY.”, a
scooter dá uma imagem concreta e o arrependimento deixa uma pergunta. Faz o
mesmo com uma ação específica e a viragem que torna o momento estranho,
engraçado ou arriscado. Confirma ambas no corte final e guarda para o vídeo o
que responde à pergunta.

Depois de tornar um Short público, o comando guarda as vistas, gostos, comentários e hora de publicação de todos os Shorts públicos da fila. `shorts.py feedback` faz outra medição e mostra a idade de cada vídeo junto dos resultados. Comparar idades semelhantes e cruzar estes números com as classificações editoriais. O contador público de vistas do YouTube mede inícios de reprodução. [Métricas disponíveis na API](https://developers.google.com/youtube/data/reference/rest/v3/videos#statistics.viewCount)

## Outros cortes para revisão privada

Escolhe um corte revisto antes de o meter na fila. A duração e os pontos de corte vêm do ficheiro escolhido. A versão vertical mantém o enquadramento inteiro por defeito. Quando a cara e o jogo precisam de mais espaço, indica os dois recortes em pixels no formato `largura:altura:x:y`.

Para repetir o estilo do clip da água, usa um corte a 1080p sempre que a fonte o permitir e passa os recortes do jogo e da cara. Em `--legendas`, usa um JSON com as frases revistas. A lista de tempos de cada frase contém um início para cada palavra e termina com a hora de saída da legenda, em segundos a partir do início do corte.

```json
[
  { "text": "Dei cabo do carro!", "times": [1.2, 1.43, 1.61, 1.72, 2.38] }
]
```

```powershell
python apps/chatscope/study/shorts.py preparar 'C:\caminho\corte.mp4' `
  --title 'O Ric meteu o carro na água | GTA VI' `
  --game-crop '1392:936:0:18' --face-crop '396:216:1442:120' `
  --legendas 'C:\caminho\legendas.json' `
  --twitch-url 'https://www.twitch.tv/ricfazeres' --youtube-url 'https://www.youtube.com/@RicFazeres' `
  --hashtags GTA6 GTA6FunnyMoments GamingPortugal TwitchClips RicFazeres
```

O modelo põe a cara em cima, o jogo ao meio e a palavra ativa a amarelo por baixo. Escolhe os recortes adequados ao direto. A descrição inclui os links indicados e uma linha de hashtags. `#Shorts` é acrescentada automaticamente, e as restantes mudam com o jogo e o criador.

```powershell
python apps/chatscope/study/shorts.py preparar 'C:\caminho\corte.mp4' --title 'Título do Short'
python apps/chatscope/study/shorts.py estado
```

1. Cria um [canal separado no YouTube](https://support.google.com/youtube/answer/1646861) para revisão. Se souberes o ID do canal, começado por `UC`, passa-o em `--channel`. Também podes confirmar o canal que a aplicação encontra após a autorização.
2. Ativa a YouTube Data API no projeto Google Cloud e descarrega o JSON de um cliente OAuth de tipo **Aplicação para computador**. Usa o ficheiro no próprio PC. Autoriza a aplicação na conta e no canal de revisão quando o terminal mostrar o endereço do Google. [Configuração OAuth](https://developers.google.com/youtube/data/guides/auth/installed-apps)
3. Subscreve no telemóvel um tópico privado no ntfy. Configura o mesmo tópico e um token com acesso de escrita no PC. O alerta abre a edição do vídeo no YouTube Studio. [Configuração ntfy](https://docs.ntfy.sh/subscribe/phone/)

```powershell
$shortsVenv = Join-Path $env:LOCALAPPDATA 'ChatScope/Shorts/venv'
python -m venv $shortsVenv
$shortsPython = Join-Path $shortsVenv 'Scripts/python.exe'
& $shortsPython -m pip install -r apps/chatscope/study/requirements-shorts.txt
& $shortsPython apps/chatscope/study/shorts.py ligar --client 'C:\caminho\cliente-oauth.json' --channel 'UC…'
& $shortsPython apps/chatscope/study/shorts.py avisos --topic 'https://servidor.example/topico'
.\apps\chatscope\study\Start-Shorts.ps1
```

O trabalhador processa a fila a cada minuto enquanto o PC estiver ligado. Podes voltar a arrancá-lo pelo mesmo lançador. Os dados do canal, da fila e dos avisos ficam no perfil local do Windows. Os vídeos verticais ficam em `media/twitch/shorts/`.

Se a autorização chegar e a verificação do canal falhar, resolve o erro no Google e corre `shorts.py ligar --retomar` para continuar com a mesma autorização.

Para corrigir um título, usa `shorts.py titulo 'C:\caminho\short.mp4' --title 'Novo título'` com o MP4 que entrou na fila. O trabalhador aplica o título antes do upload. Para um vídeo que já tem ID, aplica a alteração ao mesmo vídeo quando a conta autorizar edição no YouTube. As ligações antigas continuam a servir para uploads e a alteração fica guardada na fila à espera dessa permissão.

Cada upload pede explicitamente visibilidade privada. O trabalhador confirma o ID do canal e aguarda que o YouTube confirme o processamento e a visibilidade antes de mandar o aviso. Faz a revisão no Studio com a conta dona do canal. [Uploads privados](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)

Se a rede cair durante um upload, o trabalhador retoma a sessão do YouTube. Se o YouTube indicar que a sessão expirou, confirma no Studio se já existe um vídeo para esse corte. O caminho e o estado da fila continuam disponíveis em `shorts.py estado`. [Protocolo de retoma](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol)
