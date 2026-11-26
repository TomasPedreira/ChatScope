# ChatScope

Aplicação Windows em Rust e Tauri para capturar chat de diretos, VODs e clips
da Twitch e localizar momentos em vídeos YouTube através do heatmap público
de repetição. Captura YouTube Live e analisa áudio quando faltam sinais de público.
Cria MP4 locais, com perfis de corte/rendering e recuperação de trabalhos.
Abre `Start-ChatScope.ps1` na raiz para compilar e lançar a aplicação.

```text
apps/chatscope/
  src-tauri/        backend Rust e configuração Tauri
  ui/               interface
  providers/        adapter de metadados YouTube, sem download de vídeo
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
