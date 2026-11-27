# ChatScope

Aplicação Windows em Rust e Tauri para encontrar momentos em Twitch, YouTube,
Kick e ficheiros locais. Usa chat Twitch, heatmap público de repetição YouTube
e energia de áudio; permite capturar blocos de diretos para análise e clipping.
Cria MP4 locais, com perfis de corte/rendering e recuperação de trabalhos.
Abre `Start-ChatScope.ps1` na raiz para compilar e lançar a aplicação.

```text
apps/chatscope/
  src-tauri/        backend Rust e configuração Tauri
  ui/               interface
  providers/        adapter histórico de metadados YouTube
  pipeline/         aquisição multi-source, áudio, legendas e rendering local
  study/            recolha, edição e publicação de Shorts
  tests/fixtures/   dados de teste necessários
docs/triagem/       ferramentas e registos do piloto de triagem
```

Para compilar ou testar, segue o [README da app](apps/chatscope/README.md).
Para preparar a produção, executa `apps/chatscope/Setup-Media.ps1` uma vez.
A [arquitetura do pipeline](docs/media-pipeline.md) inclui diagrama, modos e limites.
A [prova do heatmap e arquitetura](docs/youtube-scoper.md) descreve a integração.
A [recolha em segundo plano](apps/chatscope/study/README.md) e a
[edição de Shorts](apps/chatscope/study/SHORTS.md) têm instruções próprias.
As gravações e os resultados ficam em `media/`, e as credenciais pessoais
ficam no perfil do Windows.

A [arquitetura e convenções de naming](docs/architecture.md) descreve os módulos atuais e onde ficam os candidatos e MP4.

O [guia da arquitetura e do clipping por plataforma](docs/guia-arquitetura-e-clipping.md) explica o fluxo end to end, os sinais de relevância e os pontos de extensão.
