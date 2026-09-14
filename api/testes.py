"""
api/testes.py

Este módulo contém endpoints de API destinados exclusivamente para testes
e depuração, permitindo acionar fluxos complexos do sistema de forma controlada.
"""
import logging
from fastapi import APIRouter, Query
from datetime import datetime

from core.kernel import kernel
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.memoria_perfil import memoria_perfil
from servicos.catalogo_semantico import catalogo
from modelos.catalogo import EntidadeSemantica

# Helper function para consistência com os agentes
def _get_time_slot(timestamp: datetime) -> str:
    """Determina o período do dia com base no timestamp."""
    hour = timestamp.hour
    if 6 <= hour < 12:
        return "MANHA"
    if 12 <= hour < 18:
        return "TARDE"
    if 18 <= hour < 24:
        return "NOITE"
    return "MADRUGADA"

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/testes/inferencia-cruzada", tags=["Testes"])
async def testar_inferencia_cruzada():
    """
    Simula um cenário para testar a inferência cruzada do AgenteFoco.
    1. Define 'AC/DC' como o artista preferido para o período atual.
    2. Simula que o usuário abriu um app de navegação (Waze).
    3. O resultado esperado é uma notificação sugerindo ouvir AC/DC.
    """
    logger.info(">>> INICIANDO TESTE DE INFERÊNCIA CRUZADA <<<")
    
    artista_teste = "AC/DC"
    pacote_navegacao = "com.waze"
    timestamp_atual = datetime.now()

    # CORREÇÃO: Garante que o app de navegação existe no catálogo semântico para que a inferência funcione.
    logger.info(f"1/4 - Configurando catálogo: '{pacote_navegacao}' como app de 'Navegação'.")
    app_entidade = EntidadeSemantica(
        tipo="APP",
        chave=pacote_navegacao,
        atributos={"nome": "Waze", "categoria": "Navegação"}
    )
    await catalogo.memoria.salvar(app_entidade)

    logger.info(f"2/4 - Configurando perfil: '{artista_teste}' como artista preferido para '{_get_time_slot(timestamp_atual)}'.")
    for _ in range(5):
        await memoria_perfil.registrar_escuta_artista(artista_teste, timestamp_atual)

    logger.info(f"3/4 - Disparando evento: Usuário abriu o app '{pacote_navegacao}'.")
    evento = EventoCanonico(
        categoria=CategoriaEvento.APP_FOREGROUND,
        origem=OrigemEvento.ANDROID,
        pacote=pacote_navegacao,
        payload={"pacote": pacote_navegacao}
    )
    await kernel.publicar(evento)

    logger.info("4/4 - Teste disparado. Verifique os logs ou a interface para a 'Sugestão Musical'.")
    return {"status": "Teste de inferência cruzada iniciado.", "detalhes": f"Evento para '{pacote_navegacao}' publicado. O sistema deve sugerir '{artista_teste}'.", "evento_id": evento.id}

@router.post("/testes/pesquisa-web", tags=["Testes"])
async def testar_pesquisa_web(query: str = Query(..., description="A pergunta para pesquisar na web.")):
    """
    Dispara diretamente o fluxo de pesquisa na web, desde o AgentePesquisa até a síntese no AgenteRaciocinio.
    """
    logger.info(">>> INICIANDO TESTE DE PESQUISA WEB <<<")

    logger.info(f"1/2 - Disparando evento: Intenção de pesquisar por '{query}'.")
    evento = EventoCanonico(acao=TipoAcao.INTENCAO_PESQUISA, origem=OrigemEvento.SISTEMA, payload={"query": query})
    await kernel.publicar(evento)

    logger.info("2/2 - Teste disparado. Verifique os logs para o fluxo de pesquisa e síntese.")
    return {"status": "Teste de pesquisa web iniciado.", "detalhes": f"Intenção de pesquisa por '{query}' publicada.", "evento_id": evento.id}

@router.post("/testes/reflexao-rotina", tags=["Testes"])
async def testar_reflexao_rotina():
    """
    Força o sistema a analisar os padrões de uso e sugerir novas rotinas (Build Routines).
    """
    logger.info(">>> INICIANDO TESTE DE REFLEXÃO DE ROTINA <<<")
    
    evento = EventoCanonico(
        categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO,
        acao=TipoAcao.NORMAL,
        origem=OrigemEvento.SISTEMA,
        pacote="sistema.rotina",
        payload={"tipo": "REFLEXAO_ROTINA"}
    )
    await kernel.publicar(evento)
    
    return {"status": "Reflexão de rotina iniciada.", "detalhes": "O sistema está analisando os padrões para sugerir novas rotinas."}
