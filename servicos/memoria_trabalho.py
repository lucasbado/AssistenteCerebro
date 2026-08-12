from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy.future import select
from sqlalchemy import delete
from banco.database import AsyncSessionLocal
from banco.models import MemoriaTrabalhoDB

# A relevância de uma conversa decai 1.0 ponto a cada 24 horas.
# Uma conversa com relevância 7.0 será esquecida em 7 dias se não houver interação.
DECAY_RATE_PER_HOUR = 1.0 / 24.0

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

            if conversa:
                # Conversa existente: atualiza
                contexto_atual = conversa.resumo_contexto if isinstance(conversa.resumo_contexto, list) else []
                contexto_atual.extend(novas_mensagens)
                # Mantém apenas as últimas 10 mensagens para não sobrecarregar
                conversa.resumo_contexto = contexto_atual[-10:]
                
                conversa.relevancia += incremento_relevancia
                conversa.ultima_interacao = now
            else:
                # Nova conversa: cria
                conversa = MemoriaTrabalhoDB(
                    chave_conversa=chave_conversa,
                    resumo_contexto=novas_mensagens[-10:], # Salva apenas as últimas
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