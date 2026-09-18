# Plano de Implementação: Correção de Erros de Validação e Chamada de IA

Este plano visa corrigir dois erros críticos detectados nos logs do Render após o último deploy: um erro de validação de dados (Pydantic) ao gerar a tela inicial e um erro de tipagem na chamada do serviço de Inteligência Artificial.

## User Review Required

> [!IMPORTANT]
> As correções são puramente de lógica interna e não alteram o comportamento esperado do sistema, apenas restauram a funcionalidade que estava quebrada por incompatibilidade de nomes de parâmetros e estruturas de dados.

## Proposed Changes

### 1. Correção de Validação na Home (API)
#### [MODIFY] [servico.py](file:///D:/Programacao/AssistenteCell/api/servico.py)
- No loop de `sugestoes_descubertas`, garantir que o conteúdo do card de regra seja envolvido pelo `SugestaoRegraWrapper`, conforme exigido pelo DTO `SugestaoRegraCard`. Isso resolve o `ValidationError`.

### 2. Sincronização de Parâmetros da IA (Agentes)
#### [MODIFY] [agente_raciocinio.py](file:///D:/Programacao/AssistenteCell/agentes/agente_raciocinio.py)
- Ajustar os nomes dos argumentos na chamada `self.llm.classificar_evento`:
  - `conhecimento` -> `knowledge`
  - `habitos` -> `habits`
- Isso resolve o erro `TypeError: got an unexpected keyword argument 'conhecimento'`.

## Verification Plan

### Testes de Estabilidade
1. Monitorar o log do Render após o novo deploy.
2. Confirmar que as mensagens de `ERROR:api.servico` e `ERROR:AgenteRaciocinio` pararam de aparecer.
3. Verificar no aplicativo se os cards de "Sugestão de Rotina" voltaram a aparecer na Home.
