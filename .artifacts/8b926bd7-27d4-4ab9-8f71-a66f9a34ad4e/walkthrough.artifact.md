# Walkthrough: Ollie, a Arquiteta de Rotinas

Agora a Ollie não apenas observa, mas ativamente **constrói o ecossistema** de automações para você, sugerindo rotinas baseadas no seu comportamento real entre o PC e o celular.

## O que foi implementado

### 1. Motor de Sugestão de Rotinas
Implementei a lógica de "Reflexão" no [agente_rotina.py](file:///D:/Programacao/AssistenteCell/agentes/agente_rotina.py). Periodicamente (ou sob comando), a Ollie analisa a memória de perfil e, se notar que você usa o mesmo programa no PC repetidamente em um certo horário, ela gera uma **Sugestão de Regra**.

### 2. Gestão de Rotinas (API de Capabilities)
Criei um novo endpoint em [router_capabilities.py](file:///D:/Programacao/AssistenteCell/api/router_capabilities.py) que permite:
- Listar as rotinas atuais do `routines.json`.
- Adicionar novas rotinas (quando você aceita uma sugestão no app).
- Remover rotinas existentes.

### 3. Integração na Home (Cards de Decisão)
O [servico_home.py](file:///D:/Programacao/AssistenteCell/api/servico.py) e o [agregador_perfil.py](file:///D:/Programacao/AssistenteCell/servicos/agregador_perfil.py) foram atualizados para incluir os padrões de PC detectados. Agora, a LLM verá esses padrões e poderá criar cards de "Sugestão de Regra" que aparecem na tela inicial do seu celular com um botão para "Aceitar".

### 4. Gatilho de Teste Manual
Adicionei em [testes.py](file:///D:/Programacao/AssistenteCell/api/testes.py) o endpoint `POST /testes/reflexao-rotina`. Isso permite que você force a Ollie a pensar sobre seus hábitos agora mesmo, sem esperar o ciclo automático.

---

## Como testar a Criação de Rotinas

1.  **Gere Histórico**: Abra o Bloco de Notas (Notepad) ou o Opera GX no mesmo período do dia (ex: Manhã) por 3 a 5 vezes.
2.  **Force a Reflexão**: Chame o endpoint `POST /testes/reflexao-rotina` (via Swagger ou Postman no Render).
3.  **Verifique os Logs**: Você verá `💡 [AgenteRotina] Padrão forte detectado... Gerando sugestão`.
4.  **Verifique a Home do App**: Um card de **Sugestão de Regra** deve aparecer na tela inicial do celular com a justificativa: *"Notei que você sempre abre o Notepad na Manhã. Quer que eu faça isso automaticamente?"*.
5.  **Aceite a Rotina**: Ao clicar em aceitar no app, a Ollie salvará a regra no `routines.json` e ela passará a ser executada sempre que o gatilho ocorrer.

> [!TIP]
> Use a Ollie Master GUI para monitorar as retransmissões do `ClientPc`. Se a Ollie "ver" o processo o suficiente, ela vai te oferecer a automação.

> [!IMPORTANT]
> A Ollie agora funciona como um sistema de **Machine Learning Humano-Assistido**: ela aprende o padrão, mas pede sua permissão antes de automatizar sua vida.
