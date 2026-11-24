# ChatScope

Aplicação Windows em Rust e Tauri para capturar chat de diretos, VODs e clips
da Twitch e localizar momentos em vídeos YouTube através do heatmap público
de repetição. Exporta chat ou candidatos em JSON e CSV.
Abre `Start-ChatScope.ps1` na raiz para compilar e lançar a aplicação.

```text
apps/chatscope/
  src-tauri/        backend Rust e configuração Tauri
  ui/               interface
  providers/        adapter de metadados YouTube, sem download de vídeo
  study/            recolha, edição e publicação de Shorts
  tests/fixtures/   dados de teste necessários
docs/triagem/       ferramentas e registos do piloto de triagem
```

Para compilar ou testar, segue o [README da app](apps/chatscope/README.md).
Para preparar o YouTube, executa `apps/chatscope/Setup-YouTube.ps1` uma vez.
A [prova do heatmap e arquitetura](docs/youtube-scoper.md) descreve a integração.
A [recolha em segundo plano](apps/chatscope/study/README.md) e a
[edição de Shorts](apps/chatscope/study/SHORTS.md) têm instruções próprias.
As gravações e os resultados ficam em `media/`, e as credenciais pessoais
ficam no perfil do Windows.
