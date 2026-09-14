# Plano de Implementação: Ollie, a Orquestradora Inteligente

Este plano visa transformar a Ollie em uma assistente que realmente aprende e orquestra o ecossistema PC-Celular, resolvendo falhas de execução e adicionando "visão" profunda ao que ocorre no computador.

## Problemas Críticos Atuais
1.  **Código Corrompido**: O `AgenteRaciocinio.py` possui blocos de código duplicados que sabotam a lógica de decisão.
2.  **Bloqueio de Orquestração**: A IA está proibida de agir no PC se o gatilho vier de uma notificação de celular (uma barreira artificial que impede a sinergia).
3.  **Cegueira de Conteúdo**: A Ollie sabe que o navegador está aberto, mas não sabe se você está vendo um vídeo de culinária ou codando.
4.  **Falhas de Ponte**: Comandos enviados via nuvem não estão sendo executados localmente por falta de clareza no roteamento.

## Mudanças Propostas

### 1. Refatoração e Limpeza Total
#### [MODIFY] [agentes/agente_raciocinio.py](file:///D:/Programacao/AssistenteCell/agentes/agente_raciocinio.py)
- Remover duplicidades massivas de código.
- **Liberar Cross-Device**: Remover a restrição que impede ações de PC disparadas por eventos de Celular.
- Melhorar a extração de comandos (`Scavenger`) para lidar com diferentes formatos de resposta da LLM.

### 2. Visão Profunda (Ollie "Vê" o Conteúdo)
#### [MODIFY] [ClientPc.py](file:///D:/Programacao/AssistenteCell/ClientPc.py)
- Capturar o **Título da Janela** (ex: "Como fazer bolo - YouTube").
- Enviar o título via UDP -> Bridge -> Render.
- Isso permitirá frases como: "Ollie, fecha esse vídeo de bolo e abre meu VS Code".

### 3. Consciência de Ambiente (Memória Viva)
#### [MODIFY] [servicos/consciencia.py](file:///D:/Programacao/AssistenteCell/servicos/consciencia.py)
- Armazenar o `titulo_janela` e o `processo_ativo`.
- Adicionar um "Heartbeat" de consciência: se o PC está online, a IA deve saber disso antes de sugerir qualquer comando de hardware.

### 4. Inteligência de Aprendizado (ML-Like)
#### [MODIFY] [agentes/agente_inferencia.py](file:///D:/Programacao/AssistenteCell/agentes/agente_inferencia.py)
- **Matriz de Correlação**: Registrar não apenas app-processo, mas (Horário, AppCelular, AppPC).
- **Proatividade Temporal**: Se o usuário abre o YouTube toda segunda às 20h, a Ollie gerará um card de sugestão ou perguntará: "Bora pro YouTube? Já deu o horário!".

### 5. Correção da Ponte de Execução
#### [MODIFY] [api/websocket.py](file:///D:/Programacao/AssistenteCell/api/websocket.py)
- Garantir que mensagens do tipo `COMANDO_PC` sejam entregues com prioridade zero de erro ao `PC_MASTER`.

## Plano de Verificação

### Teste de Sinergia
1.  Abrir o Instagram no celular.
2.  A Ollie deve notar (via `AgenteFoco`) e, se houver um padrão, sugerir: "Quer que eu abra o Instagram no PC pra você ver em tela cheia?".
3.  Confirmar no chat "Sim".
4.  **Sucesso**: O PC deve abrir a URL do Instagram.

### Teste de Aprendizado
1.  Abrir o Notepad 3 vezes seguidas logo após abrir o WhatsApp.
2.  Verificar se o `AgenteInferencia` registrou a associação na memória semântica.

## User Review Required
> [!IMPORTANT]
> A captura de títulos de janelas pode expor dados sensíveis (ex: nomes de arquivos ou destinatários de chat no título). Você concorda com esse nível de captura para tornar a Ollie mais inteligente?
