# Tarefas: Ecossistema Ollie - Teste Integrado PC-Celular

- [x] Criar o serviço de escuta UDP `servicos/pc_listener_service.py`
- [x] Integrar o serviço no ciclo de vida em `main.py` (com trava para Render)
- [x] Implementar Ponte UDP -> WebSocket em `ollie_master_gui.py`
- [x] Implementar Receptor de Atividade em `api/websocket.py`
- [x] Atualizar o motor de rotinas em `agentes/agente_rotina.py` para suportar `PC_ACTIVITY`
- [x] Adicionar a rotina de teste em `config/routines.json`
- [ ] Verificar a retransmissão GUI -> Render nos logs (Aguardando ação do usuário)
- [ ] Verificar o disparo da rotina e notificação no celular (Aguardando ação do usuário)
