# Walkthrough: Configuração de Segurança para GitHub

Preparei ambos os projetos para o versionamento no GitHub, garantindo que nenhum dado sensível ou arquivo desnecessário seja enviado.

## Alterações Realizadas

### 1. Backend (Python/Tauri)
Atualizei o [.gitignore](file:///D:/Programacao/AssistenteCell/.gitignore) para incluir:
- **Segredos**: `config.toml` (ID/Secret do Spotify) e `.env`.
- **Logs**: Todas as pastas e arquivos de log para manter o repo limpo.
- **Estado da IA**: Arquivos temporários e descobertas como `discovered_routines.json` e a pasta `.artifacts/`.
- **Binários**: O executável do Cloudflare e pastas de build do Rust/Tauri.
- **Ambientes**: Inclusão de `.venvs/` e `venvs/`.

### 2. Mobile (Android)
Atualizei o [.gitignore](file:///D:/Programacao/Projetos/AssistenteCell/.gitignore) para incluir:
- **Bancos de Dados**: `*.db` (impede que o banco de dados de hábitos local seja versionado).
- **IA e Build**: Pasta de artefatos `.artifacts/` e cache do Kotlin `.kotlin/`.
- **IDE**: Reforcei o bloqueio da pasta `.idea/` mantendo apenas configurações essenciais de estilo e VCS.

## Como Validar

1.  Abra o terminal na raiz de cada projeto.
2.  Rode o comando:
    ```powershell
    git status
    ```
3.  Verifique se o arquivo `config.toml` (no backend) ou `agente_local.db` (no mobile) **NÃO** aparecem na lista de arquivos para serem adicionados.

> [!IMPORTANT]
> Se você já havia feito um `git add` em algum desses arquivos anteriormente, será necessário removê-los do cache com `git rm --cached <arquivo>` antes do próximo commit.

> [!TIP]
> Recomendo criar um arquivo `config.example.toml` com valores vazios para que outros desenvolvedores saibam quais chaves precisam preencher para rodar o projeto.
