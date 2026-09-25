# Plano de Implementação: Correção de Bugs de Interface e Validação

Este plano visa corrigir o erro de referência na interface do PC (`App.tsx`) e os erros de validação de cards na API (`servico.py`), garantindo que o ecossistema funcione de forma síncrona e estável.

## User Review Required

> [!IMPORTANT]
> Realizaremos uma pequena refatoração na gestão de eventos do Tauri para garantir que os listeners sejam limpos corretamente no unmount, evitando erros de variável indefinida. Também simplificaremos a criação de cards na API para usar dicionários, o que é mais resiliente a mudanças nos modelos do Pydantic.

## Proposed Changes

### 1. Estabilidade da Interface PC (React)
#### [MODIFY] [App.tsx](file:///D:/Programacao/AssistenteCell/ollie-master-next/src/App.tsx)
- Mover a declaração dos `unlistenHardware` e `unlistenWindow` para o topo do `useEffect` usando `let`, garantindo que o escopo seja respeitado na função de limpeza (cleanup).
- Adicionar verificações de nulidade antes de tentar desinscrever os eventos.
- Corrigir a lógica de reconexão do WebSocket para usar referências estáveis.

### 2. Correção de Validação de Cards (Python)
#### [MODIFY] [servico.py](file:///D:/Programacao/AssistenteCell/api/servico.py)
- Alterar a forma como os cards são adicionados à lista: em vez de instanciar classes manualmente para a lista do `HomeDTO`, passaremos dicionários estruturados. O Pydantic converterá esses dicionários nos modelos corretos automaticamente ao instanciar o `HomeDTO`, o que resolve os erros de `model_type` e `SugestaoRegraWrapper`.

### 3. Sincronização de Status (PC Master)
#### [MODIFY] [websocket.py](file:///D:/Programacao/AssistenteCell/api/websocket.py)
- Refinar a resposta ao registro do `PC_MASTER` para garantir que o cliente saiba que foi autenticado com sucesso e pare de tentar reconectar agressivamente.

## Verification Plan

### Testes de Interface
1. Abrir o app de PC e verificar se os logs de hardware e janelas aparecem corretamente.
2. Fechar e abrir o app rapidamente para testar a limpeza (cleanup) dos listeners sem gerar erros no console.

### Testes de API
1. Acessar o endpoint `/home` via navegador ou Postman e verificar se o JSON retornado contém todos os cards (Discovery, Insights, etc) sem erros no log do servidor.
2. Confirmar no Android se a Home carrega perfeitamente.
