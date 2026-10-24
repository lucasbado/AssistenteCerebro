from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from groq import APIStatusError

from servicos.llm_providers import GroqProvider
from servicos.consumo_ia import uso_ia


def resposta(texto='{"mensagem_dinamica":"Tudo certo"}'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=texto))])


def erro(status, codigo, mensagem="Falha simulada"):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))
    return APIStatusError(mensagem, response=response, body={"error": {"code": codigo, "message": mensagem}})


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_FALLBACK_MODELS", raising=False)
    criar = AsyncMock(return_value=resposta())
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=criar)))
    consumo = SimpleNamespace(reservar=AsyncMock(return_value='teste'), concluir=AsyncMock(), bloquear=AsyncMock())
    return GroqProvider(client=client, consumo=consumo)


async def test_groq_comeca_pelo_modelo_ativo_sem_tentar_llamas_retirados(provider):
    assert await provider.gerar("oi", "Responda brevemente", max_tokens=30)
    chamadas = provider.client.chat.completions.create.await_args_list
    assert len(chamadas) == 1
    parametros = chamadas[0].kwargs
    assert parametros["model"] == provider.modelo_atual == "openai/gpt-oss-120b"
    assert parametros["response_format"] == {"type": "json_object"}
    assert parametros["max_tokens"] == 30
    assert "json" in parametros["messages"][0]["content"].lower()


def test_modelos_configuraveis_sem_duplicatas(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", " minha-escolha ")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "alternativa, minha-escolha, ,alternativa")
    provider = GroqProvider(client=object())
    assert provider.modelos == ["minha-escolha", "alternativa"]
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "")
    assert GroqProvider(client=object()).modelos == ["minha-escolha"]


async def test_404_nao_repete_sem_json_e_modelo_fica_em_espera(provider):
    agora = [100.0]
    provider._relogio = lambda: agora[0]
    provider.modelos = ["modelo-antigo", "ativo"]
    criar = provider.client.chat.completions.create
    criar.side_effect = [erro(404, "model_not_found"), resposta(), resposta(), erro(404, "model_not_found"), resposta()]
    await provider.gerar("a", "JSON")
    await provider.gerar("b", "JSON")
    assert [c.kwargs["model"] for c in criar.await_args_list] == ["modelo-antigo", "ativo", "ativo"]
    agora[0] += 3601
    await provider.gerar("c", "JSON")
    assert [c.kwargs["model"] for c in criar.await_args_list][-2:] == ["modelo-antigo", "ativo"]
    assert all("response_format" in c.kwargs for c in criar.await_args_list)


async def test_sem_json_so_quando_api_declara_formato_nao_suportado(provider):
    criar = provider.client.chat.completions.create
    criar.side_effect = [erro(400, "invalid_request_error", "response_format json_object is not supported"), resposta(), resposta()]
    await provider.gerar("a", "Responda")
    await provider.gerar("b", "Responda")
    chamadas = criar.await_args_list
    assert "response_format" in chamadas[0].kwargs
    assert "response_format" not in chamadas[1].kwargs
    assert "response_format" not in chamadas[2].kwargs
    assert len({c.kwargs["model"] for c in chamadas}) == 1
    assert all("json" in c.kwargs["messages"][0]["content"].lower() for c in chamadas)


@pytest.mark.parametrize("status,codigo", [(429, "rate_limit_exceeded"), (400, "json_validate_failed")])
async def test_erros_sem_relacao_com_formato_nao_refazem_mesmo_modelo(provider, status, codigo):
    criar = provider.client.chat.completions.create
    criar.side_effect = [erro(status, codigo), resposta()]
    await provider.gerar("oi", "JSON")
    assert [c.kwargs["model"] for c in criar.await_args_list] == provider.modelos
    assert all("response_format" in c.kwargs for c in criar.await_args_list)


@pytest.mark.parametrize("status", [401, 403])
async def test_falha_de_autenticacao_nao_testa_todos_os_modelos(provider, status):
    criar = provider.client.chat.completions.create
    criar.side_effect = erro(status, "invalid_api_key")
    with pytest.raises(APIStatusError):
        await provider.gerar("oi", "JSON")
    criar.assert_awaited_once()


async def test_modelos_indisponiveis_nao_produzem_sucesso_falso(provider):
    criar = provider.client.chat.completions.create
    criar.side_effect = erro(404, "model_not_found")
    with pytest.raises(APIStatusError):
        await provider.gerar("oi", "JSON")
    chamadas = criar.await_count
    with pytest.raises(ValueError, match="Todos os modelos"):
        await provider.gerar("oi", "JSON")
    assert criar.await_count == chamadas


async def test_selecao_de_mensagens_limita_reasoning_sem_mudar_conversa(provider):
    with uso_ia('selecao_mensagens'):
        await provider.gerar('analise', 'JSON', 600)
    assert provider.client.chat.completions.create.call_args.kwargs['reasoning_effort'] == 'low'
    await provider.gerar('conversa', 'JSON', 900)
    assert 'reasoning_effort' not in provider.client.chat.completions.create.call_args.kwargs


async def test_json_falhou_pode_ter_consumido_tokens_e_preserva_estimativa(provider):
    provider.client.chat.completions.create.side_effect = [erro(400, 'json_validate_failed'), resposta()]
    await provider.gerar('analise', 'JSON')
    assert provider.consumo.concluir.call_args_list[0].kwargs['recusado'] is False
