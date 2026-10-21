import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.notificacoes import PoliticaNotificacoes


@pytest.mark.parametrize("decision,expected", [(True, True), (False, False), ("true", False), (1, False)])
def test_indicador_de_escuta_exige_booleano_real(decision, expected):
    event = EventoCanonico(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
        origem=OrigemEvento.IA, pacote="com.example.assistentecell.voice",
        payload={"texto": "Qual luz?", "tipo_ws": "CHAT_RESPONSE", "aguarda_resposta": decision})
    payload, _ = PoliticaNotificacoes().preparar(event)
    assert payload["aguarda_resposta"] is expected
    assert event.payload["aguarda_resposta"] == decision


def test_notificacao_externa_nao_pede_abertura_do_microfone():
    event = EventoCanonico(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
        origem=OrigemEvento.IA, pacote="com.whatsapp",
        payload={"texto": "Quer responder?", "aguarda_resposta": True})
    payload, _ = PoliticaNotificacoes().preparar(event)
    assert "aguarda_resposta" not in payload


@pytest.mark.parametrize("decision", [True, False])
async def test_raciocinio_envia_decisao_junto_da_resposta(monkeypatch, decision):
    import agentes.agente_raciocinio as module
    agent = module.AgenteRaciocinio()
    agent._harvest_current_habits = AsyncMock(return_value=[])
    agent._registrar_log_cognitivo = lambda *args: None
    agent._tentar_heuristica_local = lambda _: None
    agent.memoria_trabalho = SimpleNamespace(atualizar_conversa=AsyncMock(), obter_contexto=AsyncMock(return_value=[]))
    agent.llm = SimpleNamespace(classificar_evento=AsyncMock(return_value={
        "mensagem_dinamica": "Qual luz?" if decision else "Tudo certo.",
        "tipo_interacao": "NOTIFICAR", "execucao_direta": [], "aguarda_resposta": decision}))
    publish = AsyncMock()
    monkeypatch.setattr(module.kernel, "publicar", publish)
    event = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
        acao=TipoAcao.INTENCAO_RACIOCINIO, origem=OrigemEvento.USUARIO,
        pacote="com.example.assistentecell.voice", payload={"texto": "oi"})
    await agent.processar(event)
    replies = [call.args[0] for call in publish.call_args_list if call.args[0].payload.get("tipo_ws") == "CHAT_RESPONSE"]
    assert len(replies) == 1
    assert replies[0].payload["aguarda_resposta"] is decision


async def test_llm_recebe_historico_para_entender_resposta_curta(monkeypatch):
    import servicos.llm as module
    monkeypatch.setattr(module.context_builder, "construir_contexto", AsyncMock(return_value={
        "global_summary": "", "session_summary": "", "fatos_relevantes": "- O usuário prefere o quarto."}))
    monkeypatch.setattr(module.consciencia, "obter_resumo_para_llm", Mock(return_value="ambiente"))
    monkeypatch.setattr(module.semantic_cache_service, "buscar", AsyncMock(return_value=None))
    monkeypatch.setattr(module.semantic_cache_service, "inserir", AsyncMock())
    provider = Mock(gerar=AsyncMock(return_value=json.dumps({"mensagem_dinamica": "Certo.", "aguarda_resposta": False})))
    service = object.__new__(module.ServicoLLM)
    service._consecutive_failures = 0
    service._circuit_open_until = 0
    service._pick_provider = Mock(return_value=provider)
    service.ollama = provider
    await service.classificar_evento("CHAT", "com.example.assistentecell.voice", {"texto": "sim"},
        historico=["Ollie: Você prefere o quarto?", "Usuário: sim"])
    prompt, system = provider.gerar.call_args.args
    assert "Você prefere o quarto?" in prompt
    assert "aguarda_resposta" in system
    assert "O usuário prefere o quarto" in system
