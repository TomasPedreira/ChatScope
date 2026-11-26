# Rotina diária de produção local de clips

Trabalhar todos os dias em que o PC e o ambiente local estiverem disponíveis, em dois blocos, 09:00–14:00 e 14:00–19:00, no fuso Europe/Lisbon. Usar apenas as streams e os vídeos indicados pelo utilizador para a data atual. O resultado por defeito é uma pasta local de MP4 para revisão humana. Esta versão substitui a autorização anterior de uploads privados diários.

## Entrega e autorização

- Escrever títulos propostos em inglês. As legendas usam inglês por defeito; o perfil admite EN/PT, com PT → EN implementado e EN → PT preparado para um provider futuro. Separar língua falada e língua de saída; ver [Caption languages](english-captions.md).

- Analisar, selecionar e editar os clips, guardando os MP4 em `media/daily/YYYY-MM-DD/clips/TEMA/`.
- Guardar `review.md` na pasta diária, com links para os ficheiros locais, título proposto, origem, duração e motivo de seleção.
- O utilizador revê os ficheiros e pode fazer o upload manualmente ou pedir depois o upload de clips identificados.
- Não iniciar uploads, mesmo privados, publicar ou agendar publicação automaticamente. Uma instrução posterior específica deve identificar os clips e o canal de destino e definir se ficam privados ou públicos.
- A falta de canal YouTube ou OAuth NÃO bloqueia a produção nem a revisão local. A ligação aos canais fica para uma sessão posterior, conforme pedido pelo utilizador.
- Não aplicar o antigo teto de dez uploads ao número de clips produzidos localmente. A produção depende da qualidade do material, do tempo e do espaço disponíveis.
- Não usar o YouTube como arquivo para contornar limites: privado continua a ser um upload. Qualquer envio autorizado posteriormente deve respeitar os limites efetivos do canal e da API; não assumir dez como um limite universal da plataforma.
- Não configurar autenticação, fazer push ou merge como parte da rotina.

## Fontes e execução

As automações Codex retomam a mesma conversa de meia em meia hora durante os blocos. Cada ronda determina o bloco atual e respeita a respetiva hora de fim. Usar processos em segundo plano quando disponíveis, sem duplicar recolhas. Às 14:00 transferir o estado para a segunda sessão; às 19:00 parar novo trabalho e preparar a revisão. Não recuperar horas perdidas fora destas janelas.

No início do dia, converter as fontes que o utilizador indicar no chat para `media/daily/YYYY-MM-DD/sources.json`, incluindo URLs, intervalos, temas e perfil de clip. Não reutilizar listas antigas nem a rotação Twitch predefinida. Sem fontes para a data atual, pedir a informação em falta uma vez e aguardar.

Manter `state.json` com progresso, bloqueios, candidatos, hashes e caminhos dos ficheiros. Preservar os originais, transcrições e tempos de corte quando necessários para rever ou reeditar. Não substituir nem apagar clips já preparados sem instrução. Não criar cópias duplicadas. Verificar o espaço disponível antes de iniciar capturas grandes.

Rever vídeo e áudio para preservar contexto, ação e desfecho. Ajustar enquadramento e legendas. Não inventar títulos, transcrições ou qualidade de fonte. Uma origem ainda sem aquisição/renderização funcional deve ser assinalada como bloqueada; isso não impede trabalhar noutras fontes autorizadas e suportadas.

## Revisão das 19:00

Conferir os MP4 realmente existentes e apresentar a pasta diária e o índice `review.md`. Incluir clips prontos, trabalho em curso ou incompleto e bloqueios reais. A falta de YouTube não é um bloqueio da revisão local. Não apresentar candidatos/exports de metadados como se já fossem MP4 renderizados.

## Vários canais

Uma conta Google pode gerir vários canais YouTube com identidades/temas distintos. A futura integração deve manter uma associação explícita entre tema e ID do canal, com confirmação do destino antes de cada envio. A configuração existente do uploader seleciona um canal de cada vez; a gestão de vários destinos ainda precisa de implementação. Não criar canais nem alterar OAuth nesta rotina.

## Estado de preparação

A análise de chat Twitch, heatmaps YouTube e perfis de clip está implementada. O pipeline comum cria MP4 no desktop e por --media-job, com rendering e estado persistente. YouTube Live usa capturas de 30–600 s com áudio como sinal; vídeos sem heatmap usam intervalos até dez minutos. Kick fica na branch kick_scoper. O coletor avançado study/ continua separado. A existência de uma automação agendada não elimina estas dependências. Produção local não depende da ligação ao canal; depende das fontes e das ferramentas de captura/edição efetivamente suportadas.

Referências: [uploads e publicação](https://support.google.com/youtube/answer/57407?hl=en), [limites superiores com funcionalidades avançadas](https://support.google.com/youtube/answer/9891124?hl=en), [vários canais na mesma conta Google](https://support.google.com/youtube/answer/3046356?hl=en).

Para execução, consultar [pipeline local](media-pipeline.md). A rotina deve usar --media-job, guardar o resultado JSON no estado diário e evitar repetir intervalos. clips-index.md é o índice automático de ficheiros; a revisão humana diária continua em review.md.
