# Estudo ao vivo da ChatScope

O coletor corre em segundo plano no Windows com Python, FFmpeg e FFprobe. A app Tauri pode ficar fechada. O estudo só arranca quando se chama o lançador e termina após oito horas ou às 22:00 de Lisboa, o que chegar primeiro. Corre durante o dia com o PC ligado. Uma segunda sessão pode arrancar noutro dia e guarda os resultados numa pasta própria.

Instala `tzdata` no Python usado pelo lançador para o horário de Lisboa.
Instala também `faster-whisper` nesse Python para gerar os rascunhos com legendas.

```powershell
python -m pip install tzdata faster-whisper
```

Na raiz do workspace:

```powershell
# Verificar a disponibilidade de fontes com um teste pontual de vídeo
.\apps\chatscope\study\Start-Estudo.ps1 -Check

# Iniciar o estudo quando for autorizado
.\apps\chatscope\study\Start-Estudo.ps1 -Hours 8

# Sessão pontual de 45 minutos a pedido, mesmo fora do horário diurno
.\apps\chatscope\study\Start-Estudo.ps1 -Hours 0.75 -ForaDoHorario

# Ver a atividade ou pedir a paragem
.\apps\chatscope\study\Start-Estudo.ps1 -Status
.\apps\chatscope\study\Start-Estudo.ps1 -Stop
```

## Rotina diária

A rotina atual é local-first e usa as automações Codex de 09:00–14:00 e
14:00–19:00. Não instalar Start-Rotina.ps1: esse lançador é legado e contém
um fluxo antigo de publicação. As fontes diárias são apenas as indicadas pelo
utilizador; a rotação abaixo pertence ao estudo histórico, não à rotina diária.
Consultar docs/daily-clipping.md e docs/media-pipeline.md na raiz do projeto.

## Amostra

O coletor verifica a rotação da Twitch a cada 45 s e acompanha até oito emissões em inglês orientadas ao público dos EUA ao mesmo tempo.

| Prioridade | Alternativas por ordem |
| --- | --- |
| TheBurntPeanut | summit1g, TimTheTatman |
| LIRIK | tarik |
| Sodapoppin | Nmplol |
| Kai Cenat | RDCgaming |
| IShowSpeed | Adin Ross |
| Jynxzi | — |
| CaseOh | — |
| Agent00 | erobb221, fanfan |

Cada vaga exige pelo menos 1 000 espectadores na entrada. O canal prioritário assume a vaga quando entra em direto e os cortes pendentes da alternativa terminam. Uma vaga pode ficar livre até haver um direto adequado. Títulos marcados como retransmissão são excluídos.

Cada janela de chat tem 10 s. Registam-se mensagens, participantes distintos, pessoas a reagir e os sinais detetados sem guardar nomes ou mensagens completas. A comparação usa até três minutos anteriores e espera pelo menos um minuto depois de entrar ou voltar a ligar ao chat. A regra base usa 0,20% da audiência simultânea, com um mínimo de quatro pessoas, e compara a atividade com o chat recente. A amostra de audiência pode ter até dois minutos.

Em diretos a partir de 15 000 espectadores, um pico também pode passar se tiver pelo menos três vezes a mediana recente de pessoas a reagir e cumprir o mínimo de audiência `ceil(sqrt(espectadores)/8.5)`. Exige ainda pelo menos 1,5× o ritmo habitual, reações de pelo menos 22% dos participantes e um produto dos dois rácios de pelo menos 0,75. O relatório regista a regra que disparou o corte.

A amostra tem um teto de seis candidatos mais dois controlos por hora para o conjunto dos canais. Cada vaga pode gastar um candidato na primeira meia hora e até dois no total. Controlo significa um trecho escolhido numa altura sorteada, sem usar os sinais de chat dessa janela. O vídeo é pedido nesses intervalos e guardado como prévia local de 73 s a 360p. A prévia parte de 55 s antes do fim da janela de chat e termina 18 s depois. O contexto anterior dá margem ao atraso entre a ação em vídeo e a reação escrita. São até 9m44s de material por hora para revisão e corte.

Os candidatos guardam também a faixa original do direto, até 1080p, sem recompressão. O coletor acompanha as playlists dos canais e descarrega vídeo apenas nas janelas escolhidas. A categoria do direto vai no registo do candidato e qualquer jogo pode gerar um corte. Se a faixa original falhar ou não atingir 720p, a prévia continua disponível para análise.

O chat chega por IRC sobre TLS. A audiência simultânea e o vídeo público vêm das interfaces usadas pelo site. Estas podem mudar, e algumas streams podem não disponibilizar vídeo alinhado por timestamps. A captura verifica que os segmentos cobrem o intervalo e regista as falhas. O sincronismo entre os relógios do chat e do vídeo é aproximado. A audiência é uma contagem simultânea, não uma medida de quantas das mesmas pessoas ficaram. O coletor guarda tudo localmente e não cria clips na conta Twitch.

## Resultado

Cada sessão fica em `media/twitch/estudo-ao-vivo/`. O ficheiro `ultima-sessao.txt` identifica a mais recente.

- `resultado.md` lista canais, candidatos, controlos, links para os ficheiros locais e medianas de audiência em torno do pico.
- `revisao.md` mistura candidatos e controlos sem as respetivas pontuações. É a fila para ver e classificar. Guardar as classificações numa cópia desse ficheiro, porque a fila é atualizada durante a recolha.
- `masters/` guarda as fontes dos candidatos e `drafts/` guarda os rascunhos verticais e a transcrição com tempos. O ficheiro `drafts.log` mostra o progresso da primeira edição. [Edição e publicação](SHORTS.md)
- `estado.json` e `eventos.jsonl` permitem confirmar se a sessão progrediu, reconstituir as decisões e medir as falhas.
- `vigia.jsonl` regista a verificação ao arranque, a cada 30 minutos e quando o coletor termina. `vigia.json` mostra a mais recente. O vigia verifica o estado do processo, a idade do relatório, novas janelas de chat, clips prontos e falhas. O registo distingue uma vaga sem canal de uma recolha que deixou de avançar.

O vigia corre em segundo plano com o coletor. Regista saídas inesperadas sem reiniciar o estudo. A revisão do conteúdo e o acerto do corte final são feitos depois de ver as prévias. O ensaio anterior e o protocolo de classificação estão em [docs/triagem](../../../docs/triagem/README.md).

Na revisão, usar como referência o corte de 20 s do RicFazeres em que o carro fica preso na água. Confirmar que se percebe a situação antes da ação e que se vê a consequência e a reação. Cortar na primeira saída natural, antes de reinícios, menus ou repetições. A pontuação do chat ajuda a localizar o trecho para rever.
