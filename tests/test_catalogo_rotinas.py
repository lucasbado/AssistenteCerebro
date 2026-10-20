import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock
import httpx
from fastapi import FastAPI
import pytest

from servicos.catalogo_rotinas import CatalogoRotinas
from servicos.contrato_rotinas import apresentar_rotina, validar_rotina
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento


def rotina(nome="Editor / trabalho → agenda"):
    return {"nome": nome, "ativa": False,
            "gatilho": {"tipo": "APP_OPENED", "pacote": "com.trabalho"},
            "acoes": [{"alvo": "IA", "comando": "NOTIFICAR", "parametro": "Abrir agenda?",
                       "acao_tipo": "OPEN_APP", "acao_parametro": "com.agenda", "acao_texto": "Abrir agenda"}],
            "justificativa": "Observado em dias distintos", "evidencia": {"amostras": 6, "dias_distintos": 3}}


async def test_importacao_unica_nao_ressuscita_excluidas(banco_teste, tmp_path):
    path = tmp_path / "descobertas.json"
    path.write_text(json.dumps([rotina()]), encoding="utf-8")
    primeiro = CatalogoRotinas({"descobertas": path})
    assert len(await primeiro.listar("descobertas")) == 1
    await primeiro.rejeitar(rotina()["nome"])
    # Novo processo/versão do código ainda encontra o mesmo arquivo inicial.
    segundo = CatalogoRotinas({"descobertas": path})
    assert await segundo.listar("descobertas") == []
    assert await segundo.adicionar_sugestoes([rotina("Outro nome para a mesma regra")]) == 0


async def test_snapshot_do_render_prevalece_sobre_arquivos_do_codigo(banco_teste, tmp_path):
    antigo = tmp_path / "antigas.json"
    antigo.write_text(json.dumps([rotina("Antiga do código")]), encoding="utf-8")
    snapshot = tmp_path / "migracao.json"
    snapshot.write_text(json.dumps({"ativas": [], "descobertas": [rotina("Atual do servidor")], "rejeitadas": []}), encoding="utf-8")
    catalogo = CatalogoRotinas({"descobertas": antigo})
    catalogo.snapshot = snapshot
    assert [r["nome"] for r in await catalogo.listar("descobertas")] == ["Atual do servidor"]


async def test_ciclo_api_com_nome_unicode_e_barra(catalogo_teste):
    from api.router_capabilities import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/capabilities")
    await catalogo_teste.adicionar_sugestoes([rotina()])
    name = {"nome": rotina()["nome"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test/api/v1/capabilities/") as c:
        assert (await c.post("approve", json=name)).status_code == 200
        data = (await c.get("routines")).json()
        assert data[0]["ativa"] and data[0]["pode_ativar"]
        assert data[0]["evidencia"]["amostras"] == 6
        assert (await c.patch("routines", json={**name, "ativa": False})).status_code == 200
        assert not (await c.get("routines")).json()[0]["ativa"]
        assert (await c.patch("routines", json={**name, "ativa": True})).status_code == 200
        assert (await c.request("DELETE", "routines", json=name)).status_code == 200
        assert (await c.get("routines")).json() == []
        assert (await c.request("DELETE", "routines", json=name)).status_code == 404
    assert await catalogo_teste.adicionar_sugestoes([rotina()]) == 0


async def test_aprovacao_invalida_nao_perde_sugestao(catalogo_teste):
    r = rotina()
    r["acoes"][0] = {"alvo": "PC", "comando": "inventado", "parametro": ""}
    await catalogo_teste.adicionar_sugestoes([r])
    with pytest.raises(ValueError, match="não é suportado"):
        await catalogo_teste.aprovar(r["nome"])
    assert len(await catalogo_teste.listar("descobertas")) == 1
    assert await catalogo_teste.listar("ativas") == []
    presented = apresentar_rotina(r, "descobertas")
    assert presented["problemas"] and not presented["pode_ativar"]


async def test_rejeicao_do_proximo_app_nao_volta_com_outro_nome_ou_texto(catalogo_teste):
    antiga = rotina("Nome criado pela LLM")
    antiga["acoes"] = [{"alvo": "MOBILE", "comando": "launch_app", "parametro": "com.agenda"}]
    await catalogo_teste.adicionar_sugestoes([antiga])
    await catalogo_teste.rejeitar(antiga["nome"])
    nova = rotina("Fluxo: trabalho para agenda")
    assert await catalogo_teste.adicionar_sugestoes([nova]) == 0


def test_contratos_legados_normalizados_sem_inventar_comandos():
    r = rotina()
    r["acoes"] = [{"alvo": "PC", "comando": "opera.exe", "parametro": ""},
                  {"alvo": "MOBILE", "comando": "launch_app", "parametro": "com.agenda"}]
    original = deepcopy(r)
    valid = validar_rotina(r)
    assert valid["acoes"][0] == {"alvo": "PC", "comando": "abrir_app", "parametro": "opera.exe"}
    assert valid["acoes"][1]["comando"] == "OPEN_APP"
    assert r == original


def test_gatilho_sem_produtor_e_explicado():
    r = rotina()
    r["gatilho"] = {"tipo": "TIME_RANGE", "inicio": "08:00", "fim": "10:00", "evento": "PC_LOGIN"}
    with pytest.raises(ValueError, match="não produz"):
        validar_rotina(r)


async def test_geracao_e_aprovacao_concorrentes_nao_perdem_dados(catalogo_teste):
    a = rotina("Primeira")
    b = rotina("Segunda")
    b["gatilho"]["pacote"] = "com.outro"
    await catalogo_teste.adicionar_sugestoes([a])
    await asyncio.gather(catalogo_teste.aprovar(a["nome"]), catalogo_teste.adicionar_sugestoes([b]))
    assert [r["nome"] for r in await catalogo_teste.listar("ativas")] == [a["nome"]]
    assert [r["nome"] for r in await catalogo_teste.listar("descobertas")] == [b["nome"]]


async def test_pausa_exclusao_e_cooldown_sobrevivem_a_novo_executor(catalogo_teste, monkeypatch):
    import agentes.agente_rotina as modulo
    r = rotina()
    r["cooldown_segundos"] = 60
    await catalogo_teste.adicionar_sugestoes([r])
    await catalogo_teste.aprovar(r["nome"])
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    def evento():
        return EventoCanonico(categoria=CategoriaEvento.APP_FOREGROUND, origem=OrigemEvento.ANDROID,
                              pacote="com.trabalho", payload={})
    await modulo.AgenteRotina().processar(evento())
    await modulo.AgenteRotina().processar(evento())
    publicar.assert_awaited_once()
    await catalogo_teste.definir_ativa(r["nome"], False)
    await modulo.AgenteRotina().processar(evento())
    publicar.assert_awaited_once()
    await catalogo_teste.rejeitar(r["nome"], "ativas")
    await modulo.AgenteRotina().processar(evento())
    publicar.assert_awaited_once()


async def test_reserva_revalida_pausa_e_libera_se_nao_encaminhou(catalogo_teste):
    r = {**rotina(), "ativa": True}
    await catalogo_teste.adicionar(r)
    now = datetime.now(timezone.utc)
    reservation = await catalogo_teste.reservar_execucao(r, now)
    assert reservation
    await catalogo_teste.concluir_reserva(reservation, False)
    assert await catalogo_teste.reservar_execucao(r, now)
    await catalogo_teste.definir_ativa(r["nome"], False)
    assert await catalogo_teste.reservar_execucao(r, now + timedelta(hours=2)) is None


async def test_rotina_da_casa_usa_eventos_e_responde_como_notificacao(catalogo_teste, monkeypatch):
    import agentes.agente_rotina as modulo
    from agentes.agente_casa import AgenteCasa
    from api.websocket import central_alertas
    r = {**rotina(), "ativa": True, "acoes": [{"alvo": "CASA", "comando": "desligar_luz", "parametro": "luz_quarto"}]}
    await catalogo_teste.adicionar(r)
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    evento = EventoCanonico(categoria=CategoriaEvento.APP_FOREGROUND, origem=OrigemEvento.ANDROID,
                            pacote="com.trabalho", payload={})
    await modulo.AgenteRotina().processar(evento)
    acao = publicar.call_args.args[0]
    assert acao.categoria == CategoriaEvento.CASA_ACAO_SOLICITADA
    monkeypatch.setattr(central_alertas, "executar_casa", AsyncMock(return_value={"status": "concluido", "resultado": {"state": "off"}}))
    await AgenteCasa().processar(acao)
    resposta = publicar.call_args.args[0]
    assert resposta.payload["tipo_ws"] == "NOTIFICACAO"
    assert resposta.metadados["tipo_destino"] == "NOTIFICACAO"


async def test_pc_offline_nao_executa_metade_da_rotina_nem_consume_intervalo(catalogo_teste, monkeypatch):
    import agentes.agente_rotina as modulo
    from api.websocket import central_alertas
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(central_alertas, "pc_master", None)
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    r = {**rotina(), "ativa": True}
    r["acoes"].append({"alvo": "PC", "comando": "abrir_app", "parametro": "code.exe"})
    await catalogo_teste.adicionar(r)
    evento = EventoCanonico(categoria=CategoriaEvento.APP_FOREGROUND, origem=OrigemEvento.ANDROID,
                            pacote="com.trabalho", payload={})
    executor = modulo.AgenteRotina()
    await executor.processar(evento)
    publicar.assert_not_awaited()
    monkeypatch.setattr(central_alertas, "pc_master", object())
    await executor.processar(evento)
    assert publicar.await_count == 2
