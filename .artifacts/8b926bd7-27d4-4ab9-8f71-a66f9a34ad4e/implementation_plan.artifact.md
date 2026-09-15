# Plano de Implementação: Otimização de Tokens e Memória Comprimida

Este plano visa resolver os erros de "429 Too Many Requests" (Limite de Tokens por Dia) na API do Groq, implementando técnicas de compressão de contexto, poda de histórico e otimização de prompts para maximizar o uso do cache e reduzir o consumo de tokens em até 60%.

## User Review Required

> [!IMPORTANT]
> Para economizar tokens, a Ollie passará a "esquecer" detalhes irrelevantes de conversas antigas, mantendo apenas um resumo das intenções. Além disso, o contexto do Obsidian será injetado de forma seletiva (apenas o que for relevante para a pergunta atual), em vez de enviar todo o conhecimento básico em cada requisição.

## Proposed Changes

### [Core] Otimização de Tokens e Cache
Reorganizaremos o prompt para colocar partes estáticas no topo, permitindo que o Groq utilize **Prompt Caching**.

#### [MODIFY] [servicos/llm.py](file:///D:/Programacao/AssistenteCell/servicos/llm.py)
- Reordenar o prompt: `System Prompt (Estático)` -> `Docs/Capabilities` -> `Contexto Obsidian Selecionado` -> `Hábitos` -> `Histórico` -> `Evento Atual`.
- Condensar as instruções do sistema: remover verbosidade, usar listas densas e abreviações técnicas.
- Implementar um mecanismo de "Backoff" inteligente que lê o tempo de espera no erro 429 e pausa a execução corretamente.
- Adicionar suporte a modelos "leves" (Llama 3 8B) para tarefas de classificação simples, reservando o GPT-OSS 120B para raciocínio complexo.

### [Memória] Memória de Trabalho Comprimida
Implementaremos um sistema de compressão rolante para o histórico de conversas.

#### [MODIFY] [servicos/memoria_trabalho.py](file:///D:/Programacao/AssistenteCell/servicos/memoria_trabalho.py)
- Se o histórico exceder 5 mensagens, as 4 primeiras serão resumidas em uma única sentença "Contexto Anterior".
- Limitar o buffer de mensagens brutas para as 3 mais recentes.

### [Obsidian] Injeção Seletiva de Contexto
Em vez de carregar 3-6 notas completas, usaremos uma busca por palavras-chave para injetar apenas a nota necessária.

#### [MODIFY] [servicos/obsidian_service.py](file:///D:/Programacao/AssistenteCell/servicos/obsidian_service.py)
- Adicionar o método `buscar_nota_relevante(texto_usuario)`.
- Reduzir o tamanho dos "Gists" de notas essenciais de 800 para 300 caracteres.

## Verification Plan

### Monitoramento de Tokens
- Observar os cabeçalhos de resposta do Groq (`x-ratelimit-remaining-tokens`) para validar a redução no consumo.
- Verificar o log `logs/cognitivo.log` para garantir que o contexto comprimido ainda permite que a Ollie tome decisões corretas.

### Testes de Estresse
- Realizar múltiplas perguntas rápidas seguidas e verificar se o sistema gerencia o limite 429 sem crashar, apenas pausando e retomando conforme a orientação da API.
