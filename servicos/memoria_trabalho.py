from __future__ import annotations
import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from time import monotonic
from sqlalchemy.future import select
from sqlalchemy import delete
from banco.database import AsyncSessionLocal
from banco.models import MemoriaTrabalhoDB
from core.tipos import OrigemEvento
from servicos.roteamento_pedidos import dispositivo_origem

# A relevância de uma conversa decai 1.0 ponto a cada 24 horas.
# Uma conversa com relevância 7.0 será esquecida em 7 dias se não houver interação.
DECAY_RATE_PER_HOUR = 1.0 / 24.0
CHAVE_CHAT = 'br.com.assistentecell.chat'
LIMITE_CHAT = 24
logger = logging.getLogger(__name__)


def historico_para_prompt(historico):
    """Conserva o assunto sem tornar cada pedido mais caro indefinidamente."""
    if not isinstance(historico, list):
        return []
    mensagens = [item for item in historico if isinstance(item, str)][-LIMITE_CHAT:]
    if not mensagens:
        return []
    cota = min(800, 5300 // len(mensagens))
    return [item.encode('utf-8')[:cota].decode('utf-8', errors='ignore') for item in mensagens]

class MemoriaDeTrabalho:
    async def obter_contexto(self, chave_conversa: str) -> list[str] | None:
        """Recupera o contexto de uma conversa da memória de trabalho."""
        async with AsyncSessionLocal() as session:
            stmt = select(MemoriaTrabalhoDB).where(MemoriaTrabalhoDB.chave_conversa == chave_conversa)
            resultado = await session.execute(stmt)
            conversa = resultado.scalars().first()
            if conversa:
                return conversa.resumo_contexto
            return None

    async def atualizar_conversa(self, chave_conversa: str, novas_mensagens: list[str], incremento_relevancia: float = 1.0):
        """
        Atualiza uma conversa na memória de trabalho, adicionando novas mensagens
        e aumentando sua relevância.
        """
        async with AsyncSessionLocal() as session:
            stmt = select(MemoriaTrabalhoDB).where(MemoriaTrabalhoDB.chave_conversa == chave_conversa)
            resultado = await session.execute(stmt)
            conversa = resultado.scalars().first()

            now = datetime.now(timezone.utc)
            limite = LIMITE_CHAT if chave_conversa == CHAVE_CHAT else 5

            if conversa:
                contexto_atual = conversa.resumo_contexto if isinstance(conversa.resumo_contexto, list) else []
                conversa.resumo_contexto = (contexto_atual + novas_mensagens)[-limite:]
                conversa.relevancia += incremento_relevancia
                conversa.ultima_interacao = now
            else:
                conversa = MemoriaTrabalhoDB(
                    chave_conversa=chave_conversa,
                    resumo_contexto=novas_mensagens[-limite:],
                    relevancia=incremento_relevancia,
                    ultima_interacao=now
                )
                session.add(conversa)
            
            await session.commit()

    async def esquecer_conversas_irrelevantes(self) -> int:
        """
        Implementa a mecânica de esquecimento.
        Calcula um 'score de sobrevivência' para cada conversa e remove as que
        caem abaixo de zero. Retorna o número de conversas esquecidas.
        """
        async with AsyncSessionLocal() as session:
            # Mecanismo simplificado para funcionar tanto em SQLite quanto Postgres
            # Deleta conversas que não foram acessadas há mais de 7 dias ou têm relevância 0
            limite_esquecimento = datetime.now(timezone.utc) - timedelta(days=7)
            
            delete_stmt = delete(MemoriaTrabalhoDB).where(
                (MemoriaTrabalhoDB.ultima_interacao < limite_esquecimento) |
                (MemoriaTrabalhoDB.relevancia <= 0)
            )
            
            result = await session.execute(delete_stmt)
            await session.commit()
            
            return result.rowcount

memoria_trabalho = MemoriaDeTrabalho()


class RegistroTurnosChat:
    """Une o pedido original à resposta real, inclusive respostas de ferramentas."""
    def __init__(self, memoria=memoria_trabalho):
        self.memoria = memoria
        self.pendentes = OrderedDict()
        self.lock = asyncio.Lock()

    def registrar(self, evento):
        texto = evento.payload.get('texto')
        if (evento.origem not in {OrigemEvento.USUARIO, OrigemEvento.PC, OrigemEvento.ANDROID}
                or not isinstance(texto, str) or not texto.strip()):
            return
        chave = (dispositivo_origem(evento), evento.correlacao_id)
        self.pendentes.setdefault(chave, (monotonic(), texto.strip()[:2000]))
        while len(self.pendentes) > 200:
            self.pendentes.popitem(last=False)

    async def concluir(self, evento, resposta):
        chave = (dispositivo_origem(evento), evento.correlacao_id)
        pedido = self.pendentes.pop(chave, None)
        if pedido is None or monotonic() - pedido[0] > 300:
            return
        try:
            async with asyncio.timeout(2), self.lock:
                await self.memoria.atualizar_conversa(CHAVE_CHAT, [
                    f'Usuário: {pedido[1]}', f'Ollie: {resposta[:2000]}',
                ])
        except Exception as erro:
            logger.warning('Não foi possível gravar o turno de chat (%s).', type(erro).__name__)
