# Plano de Implementação: Atualização de Segurança (.gitignore)

Este plano visa preparar os projetos para subida no GitHub, garantindo que arquivos sensíveis (tokens, bancos de dados locais, binários e segredos) não sejam versionados.

## User Review Required

> [!CAUTION]
> Arquivos como `config.toml` e `.env` contêm chaves do Spotify e outros segredos. Eles serão ignorados. Certifique-se de ter um backup desses arquivos ou crie arquivos `.example` se desejar compartilhar a estrutura.

## Proposed Changes

### 1. Backend & Server
#### [MODIFY] [.gitignore](file:///D:/Programacao/AssistenteCell/.gitignore)
- Adicionar `config.toml` e `config.example.toml`.
- Adicionar pastas de log e artefatos: `logs/`, `.artifacts/`.
- Adicionar arquivos de ferramentas: `.aider.*`, `cloudflared-windows-amd64.exe`.
- Adicionar arquivos de estado: `config/discovered_routines.json`.
- Adicionar ambientes virtuais extras: `venvs/`, `.venvs/`.

### 2. Mobile (Android)
#### [MODIFY] [.gitignore](file:///D:/Programacao/Projetos/AssistenteCell/.gitignore)
- Adicionar proteção para banco de dados local: `*.db`.
- Adicionar pastas de sistema e artefatos: `.artifacts/`, `.kotlin/`, `.idea/`.

## Verification Plan

1. **Check Git Status**: Rodar `git status` nos dois repositórios e verificar se arquivos como `config.toml` ou `agente_local.db` sumiram da lista de "Untracked files".
