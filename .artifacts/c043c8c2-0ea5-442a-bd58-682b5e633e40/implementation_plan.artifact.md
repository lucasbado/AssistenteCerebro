# Evolução Cognitiva: Antecipação e Roteamento Inteligente (Call Shooter)

Este plano visa transformar a Ollie em um assistente preditivo e altamente assertivo, garantindo que ela utilize os padrões aprendidos para antecipar necessidades e execute ferramentas de forma imediata (Call Shooter), com total transparência via logs cognitivos.

## User Review Required

> [!IMPORTANT]
> 1. **Foco na Execução (Call Shooter)**: A Ollie será instruída a priorizar o uso de ferramentas (`execucao_direta`) sempre que a intenção do usuário exigir dados (clima, arquivos, pesquisa) ou quando um padrão de hábito for detectado. Ela agirá primeiro e conversará depois.
> 2. **Novo Schema de IA**: A Ollie passará a retornar o campo `intencao_captada`, permitindo que o sistema registre exatamente o que ela entendeu.
> 3. **Log de Pensamento (Caixa Preta)**: Implementaremos o `logs/cognitivo.log` de forma segura para ambiente Cloud (Render), para que possamos auditar cada decisão da IA, incluindo a pergunta original, hábitos detectados, intenção e resposta.

## Proposed Changes

### [Backend: Inteligência Preditiva]

#### [MODIFY] [servicos/llm.py](file:///D:/Programacao/AssistenteCell/servicos/llm.py)
- **Prompt de Antecipação**: Adicionar seção `### PRIORIDADE DE EXECUÇÃO (CALL SHOOTER)` instruindo a IA a ser executora por padrão.
- **Injeção de Recorrências**: Criar um slot dinâmico para receber os padrões aprendidos do banco de dados (habitos).
- **Schema JSON**: Adicionar `intencao_captada` ao formato de saída.

#### [MODIFY] [agentes/agente_raciocinio.py](file:///D:/Programacao/AssistenteCell/agentes/agente_raciocinio.py)
- **Motor de Antecipação**: Antes de chamar a IA, buscar na `MemoriaPerfil` e `CatalogoSemantico` as associações do contexto atual (ex: app em foco, horário).
- **Injeção de Contexto**: Passar os hábitos detectados para o serviço de LLM.
- **Log Cognitivo Dinâmico**: Implementar gravação estruturada em `logs/cognitivo.log`, com suporte a caminhos relativos para compatibilidade com Render.
- **Correção de Travamento**: Substituir a trava de segurança baseada em texto por uma baseada em ID de evento para evitar bloqueios indevidos.

### [Backend: Observabilidade]

#### [NEW] [logs/cognitivo.log](file:///D:/Programacao/AssistenteCell/logs/cognitivo.log)
- Arquivo de rastreio para depuração da inteligência adaptativa.

## Verification Plan

### Manual Verification
1. **Teste de Ação**: Perguntar "Como está o tempo?". Confirmar se ela responde o clima real ou dispara pesquisa em vez de apenas confirmar a intenção.
2. **Teste de Hábito**: Abrir um app com associação conhecida e verificar se a Ollie sugere a ação do PC proativamente.
3. **Auditoria**: Abrir o log cognitivo e validar se a `intencao_captada` e os `habitos_detectados` estão sendo registrados corretamente.
