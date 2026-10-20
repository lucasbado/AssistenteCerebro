import pytest
from httpx import AsyncClient, ASGITransport

# Importamos a app da API que queremos testar
from api.main_api import app_api as app

# Marca todos os testes neste módulo para serem executados com asyncio
pytestmark = pytest.mark.asyncio

@pytest.fixture
async def async_client(banco_teste):
    """Cria um cliente de teste assíncrono para a nossa API."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True,
                           headers={"Authorization": "Bearer token-de-teste"}) as client:
        yield client

async def test_get_home_endpoint(async_client: AsyncClient):
    """Testa se o endpoint /home responde corretamente e com a estrutura de cards."""
    response = await async_client.get("/api/v1/home")
    assert response.status_code == 200
    data = response.json()
    assert "saudacao" in data
    assert "cards" in data
    assert isinstance(data["cards"], list)
    
    # Verifica a estrutura do primeiro card, se existir
    if data["cards"]:
        card = data["cards"][0]
        assert "tipo" in card
        assert "conteudo" in card

async def test_get_status_endpoint(async_client: AsyncClient):
    """Testa o endpoint de status, verificando a estrutura e dados básicos."""
    response = await async_client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status_geral"] == "OPERACIONAL"
    assert "kernel" in data
    assert "llm" in data
    assert "memorias" in data
    assert "modelo_carregado" in data["llm"]

async def test_get_timeline_endpoint(async_client: AsyncClient):
    """Testa o endpoint de timeline, garantindo que a estrutura de eventos está correta."""
    response = await async_client.get("/api/v1/timeline")
    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    assert isinstance(data["events"], list)
    
    # Verifica a estrutura do primeiro evento, se existir
    if data["events"]:
        evento = data["events"][0]
        assert "id" in evento
        assert "timestamp" in evento
        assert "resumo" in evento
        assert "icone" in evento

async def test_get_perfil_endpoint(async_client: AsyncClient):
    """
    Testa o endpoint de perfil.
    Nota: Este é um teste de integração. Para testes de unidade, precisaríamos
    mocar as chamadas ao banco de dados e à LLM.
    """
    response = await async_client.get("/api/v1/perfil")
    assert response.status_code == 200
    data = response.json()
    assert "resumo_comportamental" in data
    assert "habitos_aplicativos" in data
    assert "preferencias_musicais" in data
    assert isinstance(data["habitos_aplicativos"], list)
    assert isinstance(data["preferencias_musicais"], list)
