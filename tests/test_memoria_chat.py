import json
from unittest.mock import AsyncMock

from agentes.agente_notificacoes import AgenteNotificacoes
from api.websocket import central_alertas
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from servicos import llm
from servicos.memoria_trabalho import CHAVE_CHAT, LIMITE_CHAT, RegistroTurnosChat, memoria_trabalho


async def test_contexto_retem_turnos_distantes_e_respostas_de_ferramentas(banco_teste, monkeypatch):
    turnos = RegistroTurnosChat()
    notificacoes = AgenteNotificacoes(turnos)
    monkeypatch.setattr(central_alertas, 'enviar_alerta', AsyncMock())
    monkeypatch.setattr('agentes.agente_notificacoes.kernel.publicar', AsyncMock())
    for i in range(14):
        texto = 'Use o nome Projeto Marfim.' if i == 3 else f'Mensagem {i}'
        evento = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO, origem=OrigemEvento.PC,
                                pacote='pc.chat', payload={'texto': texto})
        turnos.registrar(evento)
        await notificacoes.processar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
            payload={'tipo_ws': 'CHAT_RESPONSE', 'texto': f'Resultado confirmado {i}'}))
    historico = await memoria_trabalho.obter_contexto(CHAVE_CHAT)
    assert len(historico) == LIMITE_CHAT and historico[-1] == 'Ollie: Resultado confirmado 13'
    assert 'Usuário: Mensagem 0' not in historico

    modelo = object.__new__(llm.ServicoLLM)
    modelo._gerar = AsyncMock(return_value='{"resposta":"Uma alternativa para Projeto Marfim."}')
    await modelo.responder_conversa('Me dê outra ideia', historico)
    prompt = json.loads(modelo._gerar.await_args.args[0])
    assert 'Usuário: Use o nome Projeto Marfim.' in prompt['historico']
    assert 'Ollie: Resultado confirmado 3' in prompt['historico']
