# Plano de Implementação: Ollie Cloud Bridge (PC -> GUI -> Render)

Este plano descreve como fazer o monitoramento do PC chegar à Ollie no Render, usando a GUI local como uma ponte WebSocket, já que o Render não suporta UDP.

## Mudanças Propostas

### 1. GUI Local como Ponte (Bridge)
#### [MODIFY] [ollie_master_gui.py](file:///D:/Programacao/AssistenteCell/ollie_master_gui.py)
- Implementar um listener UDP em background na porta 5005.
- Ao receber atividade do `ClientPc.py`, enviar via WebSocket para o Render com o tipo `PC_ACTIVITY`.
- Adicionar logs na interface para confirmar que a ponte está funcionando.

### 2. Receptor de Atividade no Servidor
#### [MODIFY] [api/websocket.py](file:///D:/Programacao/AssistenteCell/api/websocket.py)
- Adicionar suporte ao tipo `PC_ACTIVITY` vindo do WebSocket.
- Ao receber, converter em `EventoCanonico(categoria=PC_ACTIVITY)` e publicar no Kernel.
- Isso permitirá que o `AgenteRotina` (no Render) dispare as automações.

### 3. Ajuste de Inicialização no Servidor
#### [MODIFY] [main.py](file:///D:/Programacao/AssistenteCell/main.py)
- Adicionar verificação `if not os.getenv("RENDER")` ao iniciar o `pc_listener_service`.
- Isso evita erros de bind de porta no ambiente do Render.

### 4. Configuração de Rotina
#### [MODIFY] [config/routines.json](file:///D:/Programacao/AssistenteCell/config/routines.json)
- Manter/Ajustar a rotina "Sincronização Ollie: Notepad" para garantir que ela use os campos corretos recebidos via ponte.

## Plano de Verificação

### Fluxo de Teste (Nuvem)
1. Iniciar a Ollie no Render.
2. Iniciar `ollie_master_gui.py` no PC (Conectado ao Render).
3. Iniciar `ClientPc.py` no PC.
4. Abrir o Notepad no PC.
5. **Verificar GUI**: Log deve dizer "Retransmitindo atividade: notepad.exe".
6. **Verificar Celular**: Deve receber a notificação enviada pela Ollie do Render.

## User Review Required
> [!IMPORTANT]
> A porta 5005 deve estar livre no seu PC para a GUI conseguir escutar o ClientPc.
