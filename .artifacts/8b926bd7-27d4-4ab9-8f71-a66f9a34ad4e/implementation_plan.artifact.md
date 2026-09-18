# Plano de Implementação: Aprendizado de Identidade e Naturalidade

Este plano visa transformar a Ollie em uma assistente que evolui sua percepção sobre o usuário (**Lucas**) organicamente através do uso, além de tornar sua fala mais humana e estratégica, eliminando vícios de linguagem.

## User Review Required

> [!IMPORTANT]
> A Ollie passará a atuar como um "Scavenger de Fatos". Toda conversa será analisada para extrair preferências, profissão e detalhes pessoais que serão salvos no Obsidian automaticamente. A fala será ajustada para ser informal e parceira, sem o uso forçado de gírias.

## Proposed Changes

### 1. Refinamento do Motor de Pensamento (Backend)
#### [MODIFY] [llm.py](file:///D:/Programacao/AssistenteCell/servicos/llm.py)
- **Personalidade**: Redefinir o tom para "Parceira estratégica, informal e inteligente". Instruir explicitamente a evitar o vício de iniciar frases com "Vish" ou "Bora".
- **Protocolo de Aprendizado**: Adicionar instruções para que a IA identifique fatos sobre o usuário (nome, gostos, trabalho, família) e os retorne no campo `memoria_obsidian`.
- **Esquema de Resposta**: Incluir `memoria_obsidian` no exemplo do prompt de sistema para que a LLM saiba que pode registrar fatos permanentemente.

### 2. Orquestração de Memória (Agentes)
#### [MODIFY] [agente_raciocinio.py](file:///D:/Programacao/AssistenteCell/agentes/agente_raciocinio.py)
- Refinar a lógica de registro no Obsidian: se o fato captado for sobre a identidade do usuário, garantir que ele seja rotulado para ser salvo em notas relevantes.

### 3. Base de Conhecimento Inicial
#### [MODIFY] [Identidade.md](file:///D:/Programacao/AssistenteCell/Ollie/Identidade.md)
- Limpar as diretrizes rígidas de "falar com gírias" para permitir que a Ollie defina o tom ideal conforme aprende com o Lucas.

## Verification Plan

### Testes de Conversa e Aprendizado
1. Dizer: "Ollie, eu trabalho como programador e gosto muito de café forte."
2. Verificar se ela responde naturalmente (sem gírias forçadas).
3. Abrir o Obsidian e verificar se um novo fato foi registrado na pasta `Agente/` ou na nota de `Gostos.md` / `Identidade.md`.
4. Perguntar logo em seguida: "O que você sabe sobre meu trabalho?" para validar se ela já usa o conhecimento recém-adquirido.
