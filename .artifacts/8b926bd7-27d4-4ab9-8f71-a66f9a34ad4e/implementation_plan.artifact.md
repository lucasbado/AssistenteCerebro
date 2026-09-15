# Plano de Implementação: Ollie Automação Ativa (Auto-Geração de Rotinas)

Este plano descreve como a Ollie passará a criar rotinas automaticamente no sistema a partir dos padrões aprendidos, permitindo uma revisão rápida antes da ativação final.

## Mudanças Propostas

### 1. Motor de Geração Automática
#### [NEW] [routine_generator_service.py](file:///D:/Programacao/AssistenteCell/servicos/routine_generator_service.py)
- Criar o `RoutineGeneratorService` que:
    - Lê os Top 50 padrões de sinergia e temporalidade.
    - Usa a LLM para converter esses padrões em **Rotinas Completas** (Gatilho + Múltiplas Ações).
    - **Nomes Criativos**: A LLM gerará nomes como "Madrugada Produtiva" ou "Sinergia Gamer".
    - **Justificativa**: Incluirá um campo `justificativa` que servirá como sub-explicação para o usuário entender o porquê daquela rotina.

### 2. Área de Verificação (Staging)
#### [NEW] [discovered_routines.json](file:///D:/Programacao/AssistenteCell/config/discovered_routines.json)
- Um novo arquivo JSON que servirá como a "caixa de entrada" para rotinas criadas pela Ollie.
- As rotinas aqui **não** são executadas até serem verificadas pelo usuário.

### 3. API de Verificação e Promoção
#### [MODIFY] [api/router_capabilities.py](file:///D:/Programacao/AssistenteCell/api/router_capabilities.py)
- Adicionar endpoints:
    - `GET /discovered`: Lista as rotinas criadas pela Ollie.
    - `POST /approve/{nome}`: Move a rotina de `discovered_routines.json` para `routines.json` (ativando-a).
    - `DELETE /discovered/{nome}`: Descarta a rotina sugerida.

### 4. Ciclo de Auto-Geração
#### [MODIFY] [main.py](file:///D:/Programacao/AssistenteCell/main.py)
- Adicionar um loop de fundo (`loop_descoberta`) que roda a cada 12 horas para processar novos padrões e popular a fila de verificação.

## Plano de Verificação

### Fluxo de Trabalho
1. **Ollie**: Varre os 1165 padrões e encontra o hábito de "Notepad na Manhã".
2. **Sistema**: Cria a rotina em `discovered_routines.json`.
3. **Usuário**: Abre o App -> Seção "Rotinas Descobertas" -> Clica em "Verificar".
4. **App**: Mostra o que a rotina faz. Você clica em "Confirmar e Ativar".
5. **Resultado**: A rotina é movida para `routines.json` e passa a funcionar instantaneamente.

## User Review Required
> [!IMPORTANT]
> Você prefere que a Ollie crie as rotinas com um nome sugerido por ela (ex: "Sinergia Noturna: Chrome") ou quer que ela use um formato fixo (ex: "Descoberta #42")?
