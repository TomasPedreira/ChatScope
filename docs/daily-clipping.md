# Rotina diária de clipping para revisão privada

Instrução do utilizador: trabalhar todos os dias em que o PC e o ambiente local estiverem disponíveis, em dois blocos, 09:00–14:00 e 14:00–19:00, no fuso Europe/Lisbon. Usar apenas as streams e os vídeos indicados pelo utilizador para a data em questão. O limite operacional é dez novos uploads no conjunto do dia, somando as duas sessões. Este é um teto definido pelo utilizador, não uma afirmação sobre um limite universal do YouTube.

## Autorização e resultados

- A rotina está autorizada a analisar, selecionar, editar e carregar Shorts como privados no canal que o utilizador ligar e confirmar.
- Nunca tornar vídeos públicos, agendar publicação pública, executar `shorts.py publicar` ou retomar uma publicação pública como parte desta rotina. Estas instruções substituem prompts antigos de publicação automática.
- A decisão de tornar um clip público pertence ao utilizador, depois de rever os privados. Pedidos posteriores de publicação devem identificar os vídeos escolhidos.
- A ausência de uma lista de fontes para o dia não autoriza usar listas de dias anteriores nem a rotação predefinida de canais. Uma recolha deve corresponder às fontes expressamente escolhidas.
- Sem canal confirmado, OAuth ou um caminho de edição funcional, registar a dependência em falta. Não apresentar a rotina como tendo produzido ou carregado clips.

## Execução dos blocos

As automações Codex retomam a mesma conversa de meia em meia hora durante 09:00–19:00. Cada ronda determina o bloco atual e respeita a respetiva hora de fim. Usar recolha em segundo plano quando disponível; evitar recolhas duplicadas. Às 14:00, terminar ou transferir o trabalho em curso para a segunda sessão sem duplicar uploads. Às 19:00, parar nova produção e preparar a revisão. Não recuperar horas perdidas fora destas janelas.

No início do dia, guardar as fontes que o utilizador fornecer em `media/daily/YYYY-MM-DD/sources.json`, incluindo URLs, intervalos pedidos e perfil de clip. Registar o fuso Europe/Lisbon. Se ainda não houver fontes ou estiverem ambíguas, pedir a informação em falta uma vez e aguardar. Os formatos de mensagem do chat podem ser convertidos para este manifesto; o utilizador não tem de escrever JSON.

Manter `media/daily/YYYY-MM-DD/state.json` com o progresso, bloqueios, candidatos, hashes dos ficheiros, uploads reservados/em curso e IDs YouTube concluídos. Atribuir uma data operacional local a cada upload. Contar as reservas e uploads iniciados para impedir ultrapassar dez mesmo com retomas. Retomar um upload existente pelo mesmo identificador, sem criar cópias. Não ultrapassar limites devolvidos pelo serviço; conservar o excedente como drafts locais.

Os intervalos e o perfil de clip orientam as propostas; rever vídeo e áudio antes de os aceitar. Preservar contexto, ação e desfecho, ajustar enquadramento e legendas e evitar duplicados. A duração pretendida não justifica cortar uma frase ou ocultar o desfecho. Não inventar títulos, transcrições ou qualidade de fonte.

## Revisão diária

Às 19:00 produzir `media/daily/YYYY-MM-DD/review.md`, com cada Short privado, título, origem, duração, motivo de seleção, link para o YouTube Studio e eventuais problemas. Incluir a contagem total de uploads e os drafts que ficaram locais. Se não houve produção, indicar a razão. A revisão é humana; nenhuma seleção automática autoriza publicação pública.

## Estado atual de preparação

A análise de chat Twitch, heatmaps YouTube e perfis de clip está implementada. Há scripts separados para edição e uploads privados, mas o canal ainda não está ligado nesta instalação e falta unificar a aquisição/renderização de candidatos provenientes das várias origens. Kick e YouTube Live não estão integrados nesta versão. Não executar a rotação Twitch fixa como substituto da lista diária do utilizador. A existência de uma automação agendada não elimina estas dependências.
