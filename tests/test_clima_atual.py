from unittest.mock import AsyncMock

import httpx
import pytest

from agentes.agente_modo_limitado import AgenteModoLimitado
from agentes.agente_reflexo import AgenteReflexo
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos import clima_atual


@pytest.mark.parametrize('agente', [AgenteReflexo, AgenteModoLimitado])
async def test_temperatura_atual_responde_sem_enviar_comando_ao_llm(agente, monkeypatch):
    responder = AsyncMock()
    monkeypatch.setattr(clima_atual, 'responder_pedido', responder)
    monkeypatch.setattr(clima_atual, 'consultar_clima_atual',
                        AsyncMock(return_value={'temperatura': '23.4', 'condicao': 'Céu limpo'}))
    evento = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
                            acao=TipoAcao.NORMAL, origem=OrigemEvento.PC, pacote='teste.pc',
                            payload={'texto': 'Como está a temperatura?'})
    await agente().processar(evento)
    responder.assert_awaited_once_with(evento, 'Em São Paulo, está fazendo 23,4 °C agora. Céu limpo.')


@pytest.mark.parametrize('texto', ['Qual é a temperatura da CPU?', 'Temperatura amanhã?',
                                 'Como está o tempo em Recife?', 'Ajuste a temperatura para 22 graus'])
def test_clima_nao_intercepta_sensores_previsoes_e_controles(texto):
    assert not clima_atual.pedido_clima_atual(texto)


async def test_clima_sem_rede_nao_inventa_temperatura(monkeypatch):
    responder = AsyncMock()
    monkeypatch.setattr(clima_atual, 'responder_pedido', responder)
    monkeypatch.setattr(clima_atual, 'consultar_clima_atual', AsyncMock(side_effect=httpx.ConnectError('offline')))
    evento = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
                            acao=TipoAcao.NORMAL, origem=OrigemEvento.ANDROID, pacote='teste.android',
                            payload={'texto': 'Qual a temperatura agora?'})
    assert await clima_atual.responder_clima_atual(evento)
    responder.assert_awaited_once_with(evento, 'Não consegui consultar a temperatura atual em São Paulo agora.')
