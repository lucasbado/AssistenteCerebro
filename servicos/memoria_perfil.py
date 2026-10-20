from __future__ import annotations
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import PerfilUsuarioDB
from datetime import datetime, timezone
import math
from servicos.tempo import periodo_do_dia

# Categorias para o perfil de usuário
CATEGORIA_CONTATO = "CONTATO_INTERACAO"
CATEGORIA_APP = "APP_USO"
CATEGORIA_ARTISTA = "ARTISTA_PREFERENCIA"
CATEGORIA_WIFI = "WIFI_CONEXAO"


def _get_time_slot(timestamp: datetime) -> str:
    """Determina o período do dia com base no timestamp."""
    return periodo_do_dia(timestamp)


class MemoriaPerfil:
    async def _registrar_interacao(
        self, categoria: str, valor: str, score_increment: int = 1
    ):
        """
        Método genérico para registrar uma interação, incrementando seu score e confiança.
        Este é o núcleo do aprendizado.
        """
        if not valor:
            return

        async with AsyncSessionLocal() as session:
            stmt = select(PerfilUsuarioDB).where(
                PerfilUsuarioDB.categoria == categoria, PerfilUsuarioDB.valor == valor
            )
            resultado = await session.execute(stmt)
            perfil_db = resultado.scalars().first()

            if perfil_db:
                perfil_db.score = max(0, perfil_db.score + score_increment)
            else:
                perfil_db = PerfilUsuarioDB(
                    categoria=categoria,
                    valor=valor,
                    score=max(0, score_increment),
                    confianca=0.1,  # Começa com uma confiança baixa
                )
                session.add(perfil_db)

            # Lógica para atualizar a confiança baseada no número de interações
            # A base do log (20) define quão rápido a confiança cresce.
            # log20(1) ~= 0, log20(20) = 1. São necessárias ~19 interações para atingir 1.0.
            perfil_db.confianca = min(
                round(math.log(perfil_db.score + 1) / math.log(20), 2), 1.0
            )
            perfil_db.ultima_atualizacao = datetime.now(timezone.utc)

            await session.commit()

    async def registrar_interacao_contato(self, remetente: str):
        """Registra uma interação com um contato."""
        await self._registrar_interacao(CATEGORIA_CONTATO, remetente)

    async def registrar_conexao_wifi(self, ssid: str):
        """Registra uma conexão a uma rede Wi-Fi."""
        await self._registrar_interacao(CATEGORIA_WIFI, ssid)

    async def registrar_uso_app(self, pacote: str):
        """Registra o uso de um aplicativo."""
        await self._registrar_interacao(CATEGORIA_APP, pacote)

    async def registrar_uso_por_periodo(self, categoria: str, valor: str, timestamp: datetime):
        await self._registrar_interacao(f"{categoria}_{_get_time_slot(timestamp)}", valor)

    async def registrar_escuta_artista(self, artista: str, timestamp: datetime):
        """Registra a escuta de um artista musical, associando ao horário."""
        time_slot = _get_time_slot(timestamp)
        categoria = f"{CATEGORIA_ARTISTA}_{time_slot}"
        await self._registrar_interacao(categoria, artista)

    async def registrar_feedback_negativo(self, categoria_base: str, valor: str):
        """Aplica um feedback negativo, diminuindo o score e a confiança com uma penalidade forte."""
        # Para artistas, o feedback negativo deve afetar todos os perfis de horário.
        if categoria_base == CATEGORIA_ARTISTA:
            perfis = await self.obter_perfis_artista(valor)
            for perfil in perfis:
                # Penalidade forte para desincentivar rapidamente.
                await self._registrar_interacao(
                    perfil.categoria, valor, score_increment=-5
                )
        else:
            await self._registrar_interacao(categoria_base, valor, score_increment=-5)

    async def registrar_feedback_positivo(self, categoria_base: str, valor: str):
        """Aplica um feedback positivo, aumentando o score e a confiança com um bônus."""
        # Para artistas, reforça todos os perfis de horário.
        if categoria_base == CATEGORIA_ARTISTA:
            perfis = await self.obter_perfis_artista(valor)
            if perfis:
                for perfil in perfis:
                    await self._registrar_interacao(
                        perfil.categoria, valor, score_increment=2
                    )
            else:
                # Se não há perfil, cria um para o horário atual como ponto de partida.
                await self.registrar_escuta_artista(valor, datetime.now(timezone.utc))
        else:
            await self._registrar_interacao(categoria_base, valor, score_increment=2)

    async def _obter_perfil(self, categoria: str, valor: str) -> PerfilUsuarioDB | None:
        """Método genérico para obter dados de perfil."""
        async with AsyncSessionLocal() as session:
            stmt = select(PerfilUsuarioDB).where(
                PerfilUsuarioDB.categoria == categoria, PerfilUsuarioDB.valor == valor
            )
            resultado = await session.execute(stmt)
            return resultado.scalars().first()

    async def obter_perfil_contato(self, nome_contato: str) -> PerfilUsuarioDB | None:
        """
        Obtém os dados de perfil (score, confiança) para um dado contato.
        """
        return await self._obter_perfil(CATEGORIA_CONTATO, nome_contato)

    async def obter_perfil_app(self, pacote: str) -> PerfilUsuarioDB | None:
        """
        Obtém os dados de perfil (score, confiança) para um dado app.
        """
        return await self._obter_perfil(CATEGORIA_APP, pacote)

    async def obter_perfil_artista(self, nome_artista: str) -> PerfilUsuarioDB | None:
        """
        Obtém os dados de perfil (score, confiança) para um dado artista.
        """
        return await self._obter_perfil(CATEGORIA_ARTISTA, nome_artista)

    async def obter_perfis_artista(self, nome_artista: str) -> list[PerfilUsuarioDB]:
        """Obtém todos os perfis de um artista, divididos por horário."""
        async with AsyncSessionLocal() as session:
            stmt = select(PerfilUsuarioDB).where(
                PerfilUsuarioDB.categoria.like(f"{CATEGORIA_ARTISTA}_%"),
                PerfilUsuarioDB.valor == nome_artista,
            )
            resultado = await session.execute(stmt)
            return resultado.scalars().all()

    async def obter_item_mais_frequente_por_periodo(
        self, categoria_base: str, periodo: str
    ) -> str | None:
        """
        Busca o item com maior score para uma dada categoria e período.
        Ex: (ARTISTA_PREFERENCIA, MANHA) -> 'Staind'
        """
        categoria_completa = f"{categoria_base}_{periodo}"
        async with AsyncSessionLocal() as session:
            stmt = (
                select(PerfilUsuarioDB)
                .where(PerfilUsuarioDB.categoria == categoria_completa)
                .order_by(PerfilUsuarioDB.score.desc())
                .limit(1)
            )
            resultado = await session.execute(stmt)
            perfil_db = resultado.scalars().first()
            return perfil_db.valor if perfil_db else None

    async def obter_perfil_completo(
        self, confianca_minima: float = 0.5
    ) -> list[PerfilUsuarioDB]:
        """Obtém todos os fatos aprendidos sobre o usuário com uma confiança mínima."""
        async with AsyncSessionLocal() as session:
            stmt = (
                select(PerfilUsuarioDB)
                .where(PerfilUsuarioDB.confianca >= confianca_minima)
                .order_by(PerfilUsuarioDB.categoria, PerfilUsuarioDB.confianca.desc())
            )
            resultado = await session.execute(stmt)
            return resultado.scalars().all()

    async def obter_top_entidades(
        self, categoria: str = None, limite: int = 5
    ) -> list[PerfilUsuarioDB]:
        """
        Obtém as entidades/hábitos com maior score geral para gerar resumos,
        podendo filtrar por uma categoria específica.
        """
        async with AsyncSessionLocal() as session:
            stmt = select(PerfilUsuarioDB)

            # Se o agregador pedir uma categoria específica, nós filtramos
            if categoria:
                # Usamos o .like() para cobrir subcategorias (ex: ARTISTA_PREFERENCIA_MANHA)
                stmt = stmt.where(PerfilUsuarioDB.categoria.like(f"{categoria}%"))

            stmt = stmt.order_by(PerfilUsuarioDB.score.desc()).limit(limite)

            resultado = await session.execute(stmt)
            return resultado.scalars().all()


memoria_perfil = MemoriaPerfil()
