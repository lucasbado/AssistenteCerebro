# Plano de Implementação: Motor de Descoberta de Rotinas (Ollie Discovery)

Este plano descreve a criação de um serviço de processamento em lote que analisa os mais de 1100 padrões históricos na base de dados para gerar sugestões de rotinas inteligentes e orquestradas.

## Objetivos
- Analisar a `memoria_perfil` e `memoria_semantica` em busca de hábitos consolidados.
- Cruzar dados de **Tempo**, **Aplicativos Mobile** e **Atividade PC**.
- Apresentar sugestões "prontas para aprovação" na tela inicial do usuário.

## Mudanças Propostas

### 1. Serviço de Descoberta
#### [NEW] [routine_discovery_service.py](file:///D:/Programacao/AssistenteCell/servicos/routine_discovery_service.py)
- Implementar o `RoutineDiscoveryService` com os seguintes scanners:
    - **Scanner Temporal**: Identifica apps e programas que dominam faixas de horário (ex: "Notepad na Manhã").
    - **Scanner de Sinergia (Cross-Device)**: Usa as associações aprendidas (ex: "Instagram no Celular -> abrir Instagram no PC").
    - **Scanner de Fluxo (Sequencial)**: Identifica apps abertos em sequência no celular.
- Método `gerar_sugestoes_em_lote()`: Retorna uma lista de cards de sugestão formatados.

### 2. API de Descoberta
#### [MODIFY] [router_capabilities.py](file:///D:/Programacao/AssistenteCell/api/router_capabilities.py)
- Adicionar endpoint `GET /api/v1/capabilities/discover`.
- Este endpoint permitirá ao app forçar uma varredura completa da base de 1165 registros.

### 3. Integração com a Tela Inicial
#### [MODIFY] [api/servico.py](file:///D:/Programacao/AssistenteCell/api/servico.py)
- Integrar o `RoutineDiscoveryService` no `ServicoHome`.
- Se o sistema detectar padrões de alta confiança que ainda não são rotinas, eles aparecerão automaticamente como cards na Home.

### 4. Agente de Rotinas
#### [MODIFY] [agentes/agente_rotina.py](file:///D:/Programacao/AssistenteCell/agentes/agente_rotina.py)
- Melhorar a capacidade de auto-reflexão para que ele use o novo serviço de descoberta durante o ciclo `REFLEXAO_ROTINA`.

## Plano de Verificação

### Teste de Lote
1. Chamar `GET /api/v1/capabilities/discover`.
2. Verificar se o sistema sugere rotinas baseadas nos dados reais (ex: a associação `com.android.chrome` -> `opera.exe` encontrada na pesquisa).

### Teste de Aceitação
1. "Aceitar" uma sugestão descoberta via interface (ou API).
2. Confirmar que a regra foi gravada no `config/routines.json`.

## User Review Required
> [!IMPORTANT]
> Com 1165 padrões, a Ollie pode gerar muitas sugestões de uma vez. Vou implementar um filtro de **Confiança Mínima (0.8)** para mostrar apenas o que é realmente um hábito sólido. Você concorda com esse filtro inicial?
