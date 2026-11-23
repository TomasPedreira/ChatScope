# Piloto de triagem de clips ao vivo

O chat serve para escolher **que trechos vale a pena ver**. A revisão decide se o momento funciona como clip e onde começa e acaba. O objetivo do estudo é obter mais clips aproveitáveis por minuto de revisão.

## Linha de base da recolha atual

Começa na sessão `20261121-231028-36bec715`. Manter as regras do detetor e o modelo de montagem durante duas sessões terminadas. Usar uma terceira se uma das duas tiver pouco material ou faltarem controlos revistos.

- Classificar as prévias de `revisao.md` antes de consultar o tipo ou o sinal do chat. Usar os mesmos critérios editoriais para qualquer criador. Registar o motivo e, quando medido, o tempo efetivo de revisão. Se uma falha de imagem, áudio ou contexto puder vir da nossa captura, pôr o trecho em reserva e confirmar na fonte antes de o classificar.
- Para publicar, identificar na edição final o acontecimento e o que muda a seguir. Dar tempo para perceber ambos. Uma pergunta, um comentário ou uma reação pode fechar o Short quando constitui por si um remate que se sustenta isolado. Anotar em reserva os casos em que o título ou a explicação externa fazem o trabalho do vídeo. Guardar as revisões anteriores quando chegar feedback.
- Comparar os candidatos do chat com os trechos sorteados. Mostrar quantos foram selecionados, renderizados, revistos e aproveitados, com numeradores e denominadores. Comparar também clips aproveitáveis por minuto cronometrado. Tratar diferenças por criador ou jogo como exploratórias quando houver poucos exemplos.
- Primeiro teste de edição, dentro do mesmo momento. Comparar terminar no impacto com deixar a primeira reação aproveitável do streamer. Manter o mesmo início, enquadramento, estilo das legendas e nível de áudio. A duração adicional faz parte da variável em teste. Sortear a ordem e mostrar as versões com nomes neutros a quem avalia. Registar qual fecha melhor antes de consultar o tratamento e publicar no máximo uma versão por momento.
- Se repetirmos o teste com publicação pública, sortear entre clips de origem diferente dentro de pares do mesmo criador e categoria, com horários comparáveis. Guardar a atribuição antes de publicar e medir resultados à mesma idade, por exemplo 48 horas. Manter o intervalo mínimo de 30 minutos. Guardar métricas de audiência e qualidade como observações distintas.

```powershell
python docs/triagem/avaliar.py registar $sessao $id reserva --motivo 'O remate é pouco claro'
python docs/triagem/avaliar.py comparar 20261121-231028-36bec715 --sessoes 3
python docs/triagem/avaliar.py sortear 20261121-231028-36bec715 --seed 1321
```

Usar `--reacao-final` quando houver uma reação final aproveitável para o primeiro teste. Fixar a semente antes de ver as comparações.

## Revisão cruzada dos diretos, 22/11/2026

Passei 49 minutos de vídeo original de oito canais pela amostragem de imagem e pela
transcrição. Os 15 blocos incluem janelas de chat, trechos antes e depois do pico
e amostras escolhidas sem usar o chat. A segunda sessão ao vivo permitiu comparar
dois cortes capturados a 1080p com os casos que a primeira fila deixou de fora.

| Caso | O que desencadeou a revisão | O que confirmei na fonte | Decisão inicial |
| --- | --- | --- | --- |
| [Peanut, 24:40–25:35](https://www.twitch.tv/videos/2936706130?t=00h24m40s) | 150 pessoas a escrever, contra 37 habituais e 10 reações do léxico | O pico apanhou uma votação durante a pausa. A personagem disparou depois de retomado o jogo. A reação sobre a arma veio a seguir. | Editado para comparação. |
| [Kai, 22:40–24:10](https://www.twitch.tv/videos/2936683310?t=00h22m40s) | 112 pessoas no pico contra 35 habituais, com zero reações do léxico | Perguntava se o chat o ouvia enquanto tentava resolver o OBS. | Descartado pelo conteúdo do original. |
| [Kai, 30:35–34:40](https://www.twitch.tv/videos/2936683310?t=00h30m35s) | A captura ao vivo falhou | O arquivo mostrou a briga e o que acontece a seguir. A sequência termina em navegação no mapa, com pouco material para um corte autónomo. | Recuperado e deixado em reserva. |
| [Kai, 1:12:50–1:15:50](https://www.twitch.tv/videos/2936683310?t=01h12m50s) | Amostra contínua sem usar o chat | A descolagem, a passagem sobre a plantação e a aterragem são legíveis, mas o voo acaba de forma rotineira. | Reserva. |
| [Peanut, 1:20:06](https://www.twitch.tv/videos/2936706130?t=01h20m06s) | No direto, 26 reações de 59 participantes. A regra experimental de fluxo não marcou o pico. | O carro muda de trajetória, a personagem vai parar ao asfalto e encontra o carro preso na vegetação. O corte preserva a reação do Peanut e fecha antes da pausa. | Melhor corte da segunda recolha. |
| [Kai, 1:46:50](https://www.twitch.tv/videos/2936683310?t=01h46m50s) | No direto, 22 reações de 62 participantes, com os dois detetores a assinalar a janela | A personagem pergunta quanto ganha e despacha-o. Ele oferece-se para pagar para o deixar em paz e ela manda-o pagar mesmo. A reação de Kai aparece durante a fala. | Editado para comparação. |
| [ExtraEmily, 1:12:24](https://www.twitch.tv/videos/2936569895?t=01h12m24s) | Amostra contínua sem usar o chat | Emily tenta um salto lateral, aterra e brinca que parece um sapo. | Referência IRL encontrada sem pontuação de chat. |
| [Tarik, 4:14:00](https://www.twitch.tv/videos/2936353375?t=04h14m00s) e [Sodapoppin, 2:12:00](https://www.twitch.tv/videos/2936589818?t=02h12m00s) | Amostra de Valorant e pico de participantes em WoW | Uma remarcação de partida e uma conversa sobre equipamento, respetivamente. | Fora da edição. |

No primeiro estudo, o fluxo isolado acrescentou 169 janelas a 26 da regra original.
Votações, despedidas e falhas de áudio também apareceram nesse conjunto. O caso da
votação do Peanut tinha uma mudança forte de imagem no momento em que saiu da pausa.
O disparo aconteceu depois, e a maior subida de volume veio da fala do Peanut. Vale
a pena marcar estes segundos como pistas distintas e verificar a sequência no vídeo.
As contagens da Twitch mantiveram-se iguais durante os picos do acidente e da conversa
no clube e só subiram numa consulta posterior. São contagens simultâneas, demasiado
espaçadas para medir a retenção causada por um clip.

Alinhei também dois clips populares com os respetivos VODs em três pontos de áudio.
No clip do Kai, com 59 881 vistas na Twitch à data da consulta, a janela do momento
tinha 143 mensagens e 25 reatores. Nas três janelas anteriores, as medianas foram
157 mensagens e 16 reatores. No clip do Peanut, com 10 542 vistas, havia 150
mensagens face a 138 habituais e 27 reatores face a seis. Palavras ligadas ao
acontecimento, como `coyote` e `dog`, foram escritas por cinco pessoas cada e
não apareceram nas três amostras anteriores. As vistas são dos clips da Twitch,
e os dois casos foram escolhidos como referências já conhecidas.
[Clip do Kai](https://clips.twitch.tv/UnusualConsiderateLionGingerPower-oJF7Ao2MX9omrH0x)
[Clip do Peanut](https://clips.twitch.tv/TubularBashfulHeronShadyLulu-XAm39nSjTyF0Gwcp)

O comando de prospeção dá o mesmo orçamento a cada canal. Procura momentos que ficaram
fora da captura original pela regra em uso, pelo fluxo e por expressões ou emotes
repetidos. Acrescenta uma amostra sem pico e evita rever janelas sobrepostas.
Define a janela em UTC. Para recuperar a passagem de um VOD público, confirmar
o arquivo e converter a hora para segundos a partir do início desse arquivo. A
consulta de chat dá uma pista sobre onde procurar. O início e o fim são decididos
pela ação no vídeo.

```powershell
python docs/triagem/avaliar.py prospetar 20261121-231028-36bec715 --seed 22
python apps/chatscope/study/recover_vod.py 2936706130 1503 1525 $previa --original $fonte
python docs/triagem/rever_video.py $pastaDeRevisao $previa --intervalo 2 --transcrever
```

O índice guarda separadamente mudanças de cena, imagem negra, subidas de volume
e transcrição. Os fotogramas permitem rever também os períodos que ficaram entre
estes sinais. O comando de publicação regista o que acontece e o desfecho, com os
dois tempos confirmados dentro do MP4 vertical.

A segunda recolha terminou às 00:59. Registou 538 janelas em sete canais. Dois
dos três candidatos ficaram completos, um para cada canal em destaque. A fila de
prospeção devolveu mais 16 janelas, sete delas amostras sem pico. Nas duas sessões
terminadas, aproveitei um dos sete candidatos capturados. Os dois controlos
capturados acabaram em reserva ou descarte. Faltam mais controlos e medições de
tempo de revisão para comparar a produtividade de cada método.

Recuperei mais 6m20s em três janelas tardias assinaladas na segunda sessão.
A falha de captura do Kai cobria a saída do clube, condução e entrada noutro
local. No Peanut, 127 pessoas a escrever e uma reação do léxico coincidiram
com a avaliação de um carro estacionado. Outra janela do Peanut apanhou conversa
sobre registo do carro e a procura da opção de câmara. Nenhuma destas três
passagens entrou na edição final.

O primeiro par de edição saiu com a semente 1321. Comparei o acidente do Peanut
até 10,5 segundos com a versão de 25 segundos. As duas partilham o início, o
enquadramento, as legendas e o áudio até ao ponto de corte. A curta acaba no
asfalto. A longa mostra onde o carro ficou e fecha com a fala dos arbustos.
A decisão editorial foi pela longa. É uma comparação de montagem de um único
momento, sem teste público entre variantes.

## Calibração de texto e emotes, 22/11/2026

Usei cinco clips já vistos na Twitch para localizar momentos a rever. Em cada um, alinhei o clip com o VOD pelo áudio em três pontos, escolhi a ação pelo vídeo e consultei 20 segundos de chat a partir dela. Comparei com três amostras de 20 segundos anteriores, na mesma emissão. A Twitch devolveu amostras por tempo, pelo que as contagens descrevem as mensagens consultadas. A posição devolvida para o clip na consulta web ficou entre cerca de 7 e 58 segundos depois do início efetivo nestes cinco exemplos.

| Caso | Momento revisto | Visualizações na amostragem | Reatores do léxico atual / participantes na amostra | Sinais a investigar |
| --- | --- | ---: | ---: | --- |
| [Tarik](https://clips.twitch.tv/CredulousFurryToadNerfRedBlaster-jzbt5UsvL6CNq80m) | Demonstração da técnica no Valorant | 1 109 | 13 / 83 | Exemplo de vocabulário. `lool` teve quatro pessoas, contra zero nas três janelas anteriores. |
| [Jynxzi](https://clips.twitch.tv/VivaciousVenomousMangetoutRaccAttack-ESKcgB7b9ijG-Nkc) | Eliminação e reação no Fortnite | 10 393 | 27 / 82 | Variantes de riso e `gg` atingiram pessoas fora do léxico atual. |
| [CaseOh](https://clips.twitch.tv/LongFuriousGarlicDendiFace-C43HKo8gkc7BKTXl) | Queda em *Trees Hate You* | 16 987 | 32 / 151 | O emote Twitch `LUL` teve seis pessoas. `gg` teve sete e `dinodance` quatro. |
| [erobb221](https://clips.twitch.tv/ScaryFurtiveVanillaKappa-GAbGjChaRYo3U1Bz) | Reação à montagem da árvore de Natal | 3 945 | 8 / 124 | `jackass` teve 11 pessoas, contra 0, 0 e 1 antes. É um sinal de contexto deste chat. |
| [Sodapoppin](https://clips.twitch.tv/VenomousFairSwallowBatChest-Liy7cAcgDPt8OF66) | Comentário sobre ouro por hora em WoW | 9 332 | 17 / 153 | `sure` teve seis pessoas e `ads` teve três. A conversa sobre anúncios é um exemplo de atividade a distinguir de uma reação ao momento. |

Para testar um gatilho de captura, agrupar variantes de expressão, contar a união das pessoas a reagir e comparar o total com a audiência e com o próprio chat. Uma grafia rara pode ajudar a melhorar o léxico. O seu número isolado tem pouco peso na avaliação de um pico.

O coletor regista em `experimentalSignals` os IDs nativos da Twitch e as expressões curtas em texto, incluindo nomes de emotes que chegam como texto. Conta pessoas distintas por sinal. Com três ou mais pessoas e historial disponível, a expressão aparece se a sua proporção passar 1,5× a mediana recente do mesmo chat. O estudo recolhe estes sinais em paralelo com a regra de captura atual. A inclusão no detetor fica para o ensaio com candidatos e controlos revistos. [Tags de chat da Twitch](https://dev.twitch.tv/docs/chat/irc/#privmsg-tags)

## Fluxo do chat como sinal independente

O coletor regista `experimentalFlow` por janela. Usa o aumento de mensagens, o número de pessoas distintas, a dispersão habitual do chat e a relação entre pessoas e mensagens. Testa uma subida forte em 10 segundos e uma subida mais gradual em duas janelas consecutivas. O mínimo absoluto começa em 12 pessoas acima do habitual e sobe com a audiência e a variação normal do canal. Para contextualizar uma janela, regista quantas das pessoas que escreveram estiveram ausentes das janelas anteriores usadas como referência.

Na sessão **20261121-231028-36bec715**, das **1 506** janelas com dados e tempo para capturar, a regra atual marcou 26, a de fluxo marcou 190 e ambas marcaram 21. Houve 169 janelas marcadas só por fluxo. São picos a filtrar e agrupar antes do corte, dentro do orçamento fixo de revisão.

| Pico | Pessoas na janela / mediana habitual | Reações do léxico | O que se vê no VOD |
| --- | ---: | ---: | --- |
| [Agent00](https://www.twitch.tv/videos/2936322874?t=6h23m50s) | 42 / 3 | 0 | Anuncia que chegou ao capítulo final, descobre que ainda faltava um e muda de reação. Vale testar o corte. |
| [TheBurntPeanut](https://www.twitch.tv/videos/2936706130?t=0h24m40s) | 150 / 37 | 10 | Pára o jogo e pede ao chat que escolha. A amostra inclui 20 pessoas a escrever `do it`. A escolha e o resultado precisam de ser revistos juntos. |
| [LIRIK](https://www.twitch.tv/videos/2936297170?t=6h33m52s) | 91 / 18 | 3 | Despedida ao fechar o direto. Na amostra do replay, 34 pessoas escreveram `o7`. |
| [Sodapoppin](https://www.twitch.tv/videos/2936589818?t=2h4m54s) | 44 / 5 | 1 | Conversa sobre atributos e equipamento em WoW, sem desfecho claro no trecho revisto. |

Medir a contribuição de cada regra com o mesmo número de trechos para rever. Usar `avaliar.py fluxo` para repetir a medição sem alterar a recolha. A análise agrupa janelas próximas do mesmo canal e apresenta picos distintos dos candidatos já capturados.

```powershell
python docs/triagem/avaliar.py fluxo 20261121-231028-36bec715 --limite 6
```

### Ensaio editorial do Agent00

Recuperação do VOD original a partir da janela que o fluxo marcou na primeira sessão. A edição de oito segundos junta a celebração do capítulo final à pergunta sobre seis capítulos e termina aí. O utilizador considerou o corte demasiado curto e sem acontecimento e retirou o vídeo. O ensaio fica registado como rejeição editorial. Testei também cortes de imagem numa resolução reduzida. A mudança de plano apareceu no Agent00 e na despedida do LIRIK, pelo que serve para localizar uma passagem a rever.

### Resultados dos Shorts

A fila guarda uma medição dos Shorts públicos a cada publicação e com `shorts.py feedback`. A primeira leitura desta comparação, perto de duas horas de idade, deu 621 vistas ao Kai, 554 ao Speed e 297 ao Peanut. O comentário do Peanut reage à consequência da aterragem. O Summit tinha 38 minutos e a avaliação editorial ficou em reserva depois do feedback do utilizador. A série guarda a idade para permitir comparações em pontos equivalentes. Tratar o desempenho e a apreciação editorial como medidas separadas. [Definição de vistas na API do YouTube](https://developers.google.com/youtube/data/reference/rest/v3/videos#statistics.viewCount)

## O que testei

Usei cinco minutos de um [direto de xQc](https://www.twitch.tv/videos/2929044358?t=00h10m00s), entre 10:00 e 15:00. A captura tem 1 816 mensagens de 601 participantes, com uma mediana de 52,5 mensagens por 10 segundos. A regra atual da ChatScope devolveu oito sugestões. Neste piloto usei o VOD para simular a chegada das mensagens e verificar o contexto.

Comparei três regras com o mesmo orçamento de três candidatos por regra, separados por pelo menos 30 segundos dentro de cada regra:

| Regra | Como ordena | Janelas selecionadas |
| --- | --- | --- |
| Ritmo | Mensagens por 10 s face à mediana do minuto anterior | 12:40, 14:50, 13:10 |
| Reações | Percentagem dos participantes da janela que reagiram | 12:10, 13:20, 11:00 |
| Combinação | Ritmo relativo, com um bónus pela proporção de reações e um mínimo de cinco pessoas a reagir | 12:20, 14:50, 14:20 |

As três regras foram comparadas nas mesmas 24 janelas. O primeiro minuto serviu para estabelecer o ritmo de referência. A combinação usou `ritmo × (1 + 4 × proporção)` apenas como hipótese de trabalho. As nove escolhas deram oito janelas distintas. Juntei dois controlos sorteados entre as janelas em que o intervalo de revisão não se sobrepunha a um candidato.

Inspecionei fotogramas do VOD, normalmente de quatro em quatro segundos e com amostragem mais densa nos trechos ambíguos. Cruzei-os com uma transcrição automática local. O excerto está sem áudio até 12:00, pelo que o sentido de algumas reações anteriores fica por confirmar.

## Classificação inicial

Os horários da tabela apontam para o início da janela de chat. A classificação descreve o que consegui verificar na edição do streamer e indica quando há razão para ver mais contexto.

| Janela | Origem | Veredito | Observação |
| --- | --- | --- | --- |
| [11:00](https://www.twitch.tv/videos/2929044358?t=00h11m00s) | Reações | Inconclusivo | Há uma mudança de vídeo e depois imagens de um foguetão. O áudio está ausente. |
| [11:30](https://www.twitch.tv/videos/2929044358?t=00h11m30s) | Controlo | Inconclusivo | Continuação do vídeo do foguetão, seguida de navegação. O áudio está ausente. |
| [12:10](https://www.twitch.tv/videos/2929044358?t=00h12m10s) | Reações | Reserva | O basquetebol é visível e há uma reação do streamer. Vale rever se procurarmos clips de reação a vídeos de terceiros. |
| [12:20](https://www.twitch.tv/videos/2929044358?t=00h12m20s) | Combinação | Agrupar | É a saída do mesmo vídeo de basquetebol que alimentou a janela anterior. Rever uma vez chega. |
| [12:40](https://www.twitch.tv/videos/2929044358?t=00h12m40s) | Ritmo | Reserva | A maior subida de ritmo coincide com imagens de uma tempestade no mar. Há um acontecimento visual, mas a amostra não mostra uma reação autónoma do streamer que justifique o corte. |
| [13:10](https://www.twitch.tv/videos/2929044358?t=00h13m10s) | Ritmo | Agrupar | O streamer continua a ver e a voltar atrás no mesmo vídeo da tempestade. |
| [13:20](https://www.twitch.tv/videos/2929044358?t=00h13m20s) | Reações | Agrupar | Ainda é o mesmo vídeo, com discussão no chat sobre se é gerado por IA. |
| [13:50](https://www.twitch.tv/videos/2929044358?t=00h13m50s) | Controlo | Descartar | Navegação e discussão sobre a PlayStation. Não identifiquei um desfecho que se sustente sozinho. |
| [14:20](https://www.twitch.tv/videos/2929044358?t=00h14m20s) | Combinação | Testar corte | O vídeo dos buracos de Montreal dá origem a uma piada sobre conduzir depressa. Experimentaria **14:31–14:48**, verificando a frase de entrada e o fim pela escuta. O desfecho só apareceu ao alargar a janela. |
| [14:50](https://www.twitch.tv/videos/2929044358?t=00h14m50s) | Ritmo e combinação | Descartar | O pico coincide com a navegação no YouTube e a entrada num vídeo do MrBeast. O volume, por si só, não trouxe um excerto autónomo. |

O teste de exigir simultaneamente **1,5× o ritmo normal e cinco pessoas a reagir** teria enviado apenas 14:50 para revisão. A janela das 14:20, com 1,43× o ritmo e 11 pessoas a reagir, teria ficado de fora. Em 12:40, o ritmo subiu para 2,04× com 82 participantes, mas o léxico atual não reconheceu nenhuma reação. Havia **20 mensagens «MONKA»**. É um exemplo para testar cobertura de emotes por canal em dados novos, não um limiar validado.

Com cinco minutos de um único canal de react, sem rótulos independentes e com áudio incompleto, o piloto demonstra falhas possíveis. Não mede a precisão de cada regra nem a retenção de espectadores. O VOD não inclui a série de contagens de audiência do direto.

## Próximo ensaio com orçamento fixo

1. **Durante o direto, marcar em modo de ensaio.** Em três canais com ritmos diferentes, recolher chat e amostrar a audiência periodicamente. Guardar a hora UTC do pico, mensagens, participantes e pessoas a reagir. Comparar a evolução de espectadores de minutos antes e depois como sinal auxiliar. A Twitch fornece contagens simultâneas, pelo que uma subida não demonstra que os mesmos espectadores ficaram. [Get Streams](https://dev.twitch.tv/docs/api/reference/streams#get-streams)
2. **Limitar a fila.** Começar com um máximo de seis candidatos de 25 s por hora e dois controlos aleatórios. Juntar picos adjacentes da mesma passagem, descontar comandos e mensagens repetidas pela mesma pessoa e guardar a causa provável quando o chat está a responder a uma sondagem ou a uma raid.
3. **Fazer uma passagem barata primeiro.** Usar fotogramas de baixa resolução, cortes de cena e presença de áudio para afastar navegação sem conteúdo e problemas evidentes. Quando a decisão depende de uma fala, transcrever só a janela. Se o caso ficar ambíguo, ouvir e ver a prévia antes de descartar.
4. **Ver e classificar os sobreviventes.** Marcar como `aproveitar`, `reserva`, `descartar` ou `inconclusivo`. Registar a categoria do momento, a razão e os tempos de início, ação e fim. Confirmar a última frase ou reação visual com vídeo e áudio contínuos. Só então renderizar o corte final a partir da fonte.
5. **Avaliar sem mostrar a pontuação a quem revê.** Medir candidatos aproveitáveis por minuto de revisão, minutos de vídeo enviados para análise por hora de direto e quantidade de cortes que precisaram de mais contexto. Rever também um bloco contínuo curto por sessão para descobrir momentos que nenhuma regra propôs. Afinar numa sessão e comparar noutra.

Seis prévias de 25 s são **2m30s de vídeo por hora**; com os dois controlos são **3m20s**. Isto é um teto inicial para o ensaio, não uma poupança medida neste piloto. Quando passarmos a criar clips durante o direto, a melhor janela inicial tem de ser capturada antes de haver dados de audiência dos minutos seguintes. Esses dados podem ajudar na triagem posterior.

A separação entre proposta pelo chat e ajuste dos limites também aparece em [Lightor](https://arxiv.org/abs/1910.12201). A combinação de chat e sinais visuais foi estudada em [Video Highlight Prediction Using Audience Chat Reactions](https://arxiv.org/abs/1707.08559). São referências para desenhar a experiência; os resultados de e-sports não calibram este canal.

Reproduzir as contagens e a seleção a partir da raiz:

```powershell
python docs/triagem/piloto_chat.py --json
```
