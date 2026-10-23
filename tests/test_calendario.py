from datetime import datetime, timedelta, timezone
from servicos.calendario import itens_calendario
from servicos.agenda import agenda
from servicos.tarefas import tarefas


async def test_calendario_so_copia_confirmados_com_data_sem_alarmes(banco_teste):
    inicio = datetime.now(timezone.utc) + timedelta(days=1)
    compromisso = await agenda.salvar('compromisso', 'Consulta', inicio, confirmar=True)
    await agenda.salvar('compromisso', 'Sugestão', inicio)
    await agenda.salvar('alarme', 'Acordar', inicio, confirmar=True)
    tarefa = await tarefas.salvar('Pagar conta', inicio)
    await tarefas.salvar('Comprar pão')
    await tarefas.salvar('Sugestão de mensagem', inicio, confirmar=False)
    itens = (await itens_calendario())['itens']
    assert {i['id'] for i in itens} == {compromisso['id'], tarefa['id']}
    assert all(i['ativo'] for i in itens)
    assert next(i for i in itens if i['dominio'] == 'tarefa')['duracao_minutos'] == 1


async def test_calendario_retorna_cancelamento_e_conclusao_de_copias_conhecidas(banco_teste):
    inicio = datetime.now(timezone.utc) + timedelta(days=1)
    compromisso = await agenda.salvar('compromisso', 'Consulta', inicio, confirmar=True)
    tarefa = await tarefas.salvar('Pagar conta', inicio)
    await agenda.alterar_estado(compromisso['id'], 'cancelado')
    await tarefas.alterar(tarefa['id'], 'concluir')
    itens = (await itens_calendario([{'dominio': 'agenda', 'id': compromisso['id']}, {'dominio': 'tarefa', 'id': tarefa['id']}]))['itens']
    assert len(itens) == 2 and all(not i['ativo'] for i in itens)


async def test_calendario_adiar_atualiza_mesmo_id_e_data_local_preserva_dia(banco_teste, monkeypatch):
    monkeypatch.setenv('OLLIE_TIMEZONE', 'America/Sao_Paulo')
    inicio = datetime(2030, 10, 23, 3, tzinfo=timezone.utc)
    tarefa = await tarefas.salvar('Pagar conta', inicio, dia_inteiro=True)
    copia = (await itens_calendario())['itens'][0]
    assert copia['data_local'] == '2030-10-23'
    await tarefas.alterar(tarefa['id'], 'adiar', inicio + timedelta(days=1), True)
    nova = (await itens_calendario())['itens'][0]
    assert nova['id'] == copia['id'] and nova['data_local'] == '2030-10-24'


async def test_api_tarefa_atualiza_projecao_e_avisa_celular_so_apos_salvar(banco_teste, monkeypatch):
    from unittest.mock import AsyncMock
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from api.auth import AuthMiddleware
    from api.calendario import router as calendar_router
    from api.tarefas import router as task_router
    from api.websocket import central_alertas
    aviso = AsyncMock(return_value=True)
    monkeypatch.setattr(central_alertas, 'solicitar_sincronizacao_calendario', aviso)
    app = FastAPI()
    app.include_router(calendar_router, prefix='/calendario')
    app.include_router(task_router, prefix='/tarefas')
    app.add_middleware(AuthMiddleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        assert (await client.post('/calendario/sincronizar', json={})).status_code == 401
        client.headers['Authorization'] = 'Bearer token-de-teste'
        prazo = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        item = (await client.post('/tarefas', json={'titulo': 'Pagar conta', 'prazo': prazo})).json()
        aviso.assert_awaited_once()
        feed = (await client.post('/calendario/sincronizar', json={})).json()['itens']
        assert feed[0]['id'] == item['id'] and feed[0]['ativo']
        await client.patch('/tarefas/' + item['id'], json={'acao': 'concluir', 'versao': 1})
        final = (await client.post('/calendario/sincronizar', json={'conhecidos': [{'dominio': 'tarefa', 'id': item['id']}]})).json()['itens']
        assert not final[0]['ativo']
        invalid = await client.post('/calendario/sincronizar', json={'conhecidos': [{'dominio': 'tarefa', 'id': 'invalido'}]})
        assert invalid.status_code == 422
