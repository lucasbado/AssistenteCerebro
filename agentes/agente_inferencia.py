"""Atualiza o perfil por observação; padrões de automação são apurados no histórico."""
from collections import defaultdict, deque
from datetime import timedelta

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from modelos.catalogo import EntidadeSemantica
from servicos.catalogo_semantico import catalogo
from servicos.memoria_perfil import memoria_perfil
from servicos.atividade import processo_pc
from servicos.tempo import periodo_do_dia, utc


class AgenteInferencia:
    def __init__(self):
        self.uso_apps = defaultdict(lambda: deque(maxlen=20))
        self._ultima_atividade = {}

    async def processar(self, evento: EventoCanonico):
        if evento.origem not in {OrigemEvento.ANDROID, OrigemEvento.PC}:
            return
        if evento.categoria in {CategoriaEvento.APP_FOREGROUND, CategoriaEvento.PC_ACTIVITY}:
            if evento.payload.get("heartbeat"):
                return
            pc = evento.categoria == CategoriaEvento.PC_ACTIVITY
            valor = processo_pc(evento.payload) if pc else evento.pacote
            if not valor or "assistentecell" in valor.lower():
                return
            dispositivo = "pc" if pc else "mobile"
            ts = utc(evento.timestamp)
            anterior = self._ultima_atividade.get(dispositivo)
            if anterior and (ts <= anterior[1] or
                    (valor == anterior[0] and ts - anterior[1] < timedelta(minutes=30))):
                return
            self._ultima_atividade[dispositivo] = (valor, ts)
            await memoria_perfil.registrar_uso_por_periodo("PC_ROUTINE" if pc else "APP_USO", valor, ts)
            if not pc:
                self.uso_apps[valor].append(ts)
                await self._atualizar_insights_app(valor, ts)
        elif evento.categoria == CategoriaEvento.NOTIFICACAO:
            await self._inferir_contato_favorito(evento)
        elif evento.categoria == CategoriaEvento.MEDIA:
            await self._inferir_rotina_musical(evento)

    async def _atualizar_insights_app(self, pacote, timestamp):
        recentes = [ts for ts in self.uso_apps[pacote] if timestamp - ts <= timedelta(hours=24)]
        if len(recentes) < 3:
            return
        entidade = await catalogo.obter_app(pacote)
        if not entidade:
            return
        insights = entidade.atributos.setdefault("insights", {})
        insights["app_favorito"] = True
        insights["score"] = len(recentes)
        if periodo_do_dia(timestamp) in {"NOITE", "MADRUGADA"}:
            insights["uso_noturno"] = True
        await catalogo.memoria.salvar(entidade)

    async def _inferir_contato_favorito(self, evento):
        remetente = evento.payload.get("titulo")
        if not remetente:
            return
        perfil = await memoria_perfil.obter_perfil_contato(remetente)
        if perfil and perfil.score > 10 and perfil.confianca > 0.7:
            entidade = await catalogo.obter_contato(remetente) or EntidadeSemantica(tipo="CONTATO", chave=remetente)
            insights = entidade.atributos.setdefault("insights", {})
            if not insights.get("contato_favorito"):
                insights["contato_favorito"] = True
                await catalogo.memoria.salvar(entidade)

    async def _inferir_rotina_musical(self, evento):
        artista = evento.payload.get("artista")
        if not artista:
            return
        perfis = await memoria_perfil.obter_perfis_artista(artista)
        if not perfis:
            return
        perfil = max(perfis, key=lambda p: p.score)
        if perfil.score > 5 and perfil.confianca >= 0.7:
            entidade = await catalogo.obter_artista(artista)
            if entidade:
                horario = perfil.categoria.split("_")[-1]
                insights = entidade.atributos.setdefault("insights", {})
                if insights.get("rotina_musical") != horario:
                    insights["rotina_musical"] = horario
                    await catalogo.memoria.salvar(entidade)
