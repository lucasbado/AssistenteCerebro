"""
agentes/agente_inferencia.py
"""
from collections import defaultdict, deque, namedtuple
from datetime import datetime, timedelta, timezone
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento
from modelos.catalogo import EntidadeSemantica
from servicos.catalogo_semantico import catalogo
from servicos.memoria_perfil import memoria_perfil
import logging

logger = logging.getLogger(__name__)
Coocorrencia = namedtuple('Coocorrencia', ['pacote_app', 'programa_pc', 'timestamp'])

class AgenteInferencia:
    def __init__(self):
        self.eventos_recentes: deque[EventoCanonico] = deque(maxlen=500)
        self.uso_apps: defaultdict[str, deque[datetime]] = defaultdict(lambda: deque(maxlen=20))
        # NOVO: Histórico de coocorrências para aprender associações
        self.coocorrencias: deque[Coocorrencia] = deque(maxlen=100)
        self.associacoes_pc_aprendidas: dict[str, str] = {} # Cache para evitar escritas repetidas no DB

    async def processar(self, evento: EventoCanonico):
        self.eventos_recentes.append(evento)
        self._atualizar_frequencias(evento)

        # NOVO: Processa eventos de atividade do PC para aprender rotinas
        if evento.categoria == CategoriaEvento.PC_ACTIVITY:
            await self._registrar_coocorrencia_pc(evento)

        await self._inferir_padroes(evento)

    def _atualizar_frequencias(self, evento: EventoCanonico):
        if evento.categoria == CategoriaEvento.APP_FOREGROUND:
            self.uso_apps[evento.pacote].append(evento.timestamp)

    async def _inferir_padroes(self, evento: EventoCanonico):
        # 🌟 NOVO: Monitoramento de coocorrência Celular -> Celular
        if evento.categoria == CategoriaEvento.APP_FOREGROUND:
            await self._registrar_coocorrencia_mobile(evento)

        await self._padrao_app_mais_usado()
        await self._inferir_contato_favorito(evento)
        await self._inferir_rotina_musical(evento)
        await self._padrao_rotina_noturna()
        await self._inferir_associacao_pc()
        await self._inferir_associacao_mobile()

    async def _registrar_coocorrencia_mobile(self, evento_atual: EventoCanonico):
        """Registra quando dois apps diferentes são abertos em sequência rápida."""
        pacote_atual = evento_atual.pacote
        if "assistentecell" in pacote_atual: return

        agora = evento_atual.timestamp
        for ev in reversed(self.eventos_recentes):
            # Procura o penúltimo app aberto nos últimos 60s
            if (agora - ev.timestamp) > timedelta(seconds=60): break
            if ev.id == evento_atual.id: continue

            if ev.categoria == CategoriaEvento.APP_FOREGROUND and ev.pacote != pacote_atual:
                if "assistentecell" in ev.pacote: continue
                
                # Registra como uma coocorrência mobile (usamos o campo programa_pc para o segundo app)
                nova = Coocorrencia(ev.pacote, pacote_atual, agora)
                self.coocorrencias.append(nova)
                logger.info(f"🧠 [INFERENCIA] Coocorrência registrada (Mobile): '{ev.pacote}' -> '{pacote_atual}'")
                return

    async def _inferir_associacao_mobile(self):
        """Aprende padrões de abertura de apps sequenciais no celular."""
        if len(self.coocorrencias) < 2: return

        contador = defaultdict(int)
        for co in self.coocorrencias:
            # Identifica mobile-mobile pelo ponto no nome do "programa"
            if "." in co.programa_pc:
                contador[(co.pacote_app, co.programa_pc)] += 1

        for (p1, p2), contagem in contador.items():
            if contagem >= 2:
                logger.info(f"✨ [INFERENCIA] Novo hábito mobile detectado: '{p1}' ➔ '{p2}'")
                entidade = await catalogo.obter_app(p1)
                if entidade:
                    entidade.atributos.setdefault("associacoes", {})
                    entidade.atributos["associacoes"]["mobile_next"] = { "pacote": p2 }
                    await catalogo.memoria.salvar(entidade)

    async def _inferir_contato_favorito(self, evento: EventoCanonico):
        if evento.categoria != CategoriaEvento.NOTIFICACAO:
            return

        remetente = evento.payload.get("titulo")
        if not remetente:
            return

        perfil_contato = await memoria_perfil.obter_perfil_contato(remetente)
        if not perfil_contato:
            return

        # Regra de inferência: score alto e confiança alta indicam um contato favorito.
        if perfil_contato.score > 10 and perfil_contato.confianca > 0.7:
            entidade = await catalogo.obter_contato(remetente) or EntidadeSemantica(tipo="CONTATO", chave=remetente)
            entidade.atributos.setdefault("insights", {})
            if not entidade.atributos["insights"].get("contato_favorito"):
                entidade.atributos["insights"]["contato_favorito"] = True
                await catalogo.memoria.salvar(entidade)

    async def _inferir_rotina_musical(self, evento: EventoCanonico):
        if evento.categoria != CategoriaEvento.MEDIA:
            return

        artista = evento.payload.get("artista")
        if not artista:
            return

        # 1. Busca os perfis de interação com o artista em todos os horários
        perfis = await memoria_perfil.obter_perfis_artista(artista)
        if not perfis:
            return

        # 2. Encontra o horário com maior interação (maior score)
        perfil_rotina = max(perfis, key=lambda p: p.score)

        # 3. Regra de inferência: só considera uma rotina se a interação for significativa
        if perfil_rotina.score > 5:
            # Extrai o horário do nome da categoria (ex: ARTISTA_PREFERENCIA_MANHA)
            horario_rotina = perfil_rotina.categoria.split('_')[-1]

            # 4. Salva o insight na memória semântica para o AgenteReflexo usar
            entidade = await catalogo.obter_artista(artista)
            if entidade:
                entidade.atributos.setdefault("insights", {})
                # Só atualiza se for uma nova rotina ou uma rotina diferente
                if entidade.atributos["insights"].get("rotina_musical") != horario_rotina:
                    entidade.atributos["insights"]["rotina_musical"] = horario_rotina
                    await catalogo.memoria.salvar(entidade)

    async def _padrao_app_mais_usado(self):
        if not self.uso_apps:
            return

        app_scores = {}
        agora = datetime.now(timezone.utc)
        for pacote, timestamps in self.uso_apps.items():
            score = 0
            for ts in timestamps:
                # Pontua mais alto por uso recente. O score decai linearmente ao longo de 24h.
                horas_atras = (agora - ts).total_seconds() / 3600
                score += max(0, 1 - (horas_atras / 24))
            app_scores[pacote] = score

        if not app_scores:
            return

        pacote_top, score_top = max(app_scores.items(), key=lambda item: item[1])

        # Um novo limiar baseado em score, não em contagem bruta.
        # Ex: equivale a ~3 usos muito recentes ou mais usos antigos.
        if score_top < 3.0:
            return

        entidade = await catalogo.obter_app(pacote_top) or EntidadeSemantica(tipo="APP", chave=pacote_top)
        entidade.atributos.setdefault("insights", {})
        entidade.atributos["insights"]["app_favorito"] = True
        entidade.atributos["insights"]["score"] = round(score_top, 2)
        await catalogo.memoria.salvar(entidade)

    async def _padrao_rotina_noturna(self):
        agora = datetime.now(timezone.utc)
        ultimos_15min = [e for e in self.eventos_recentes if agora - e.timestamp < timedelta(minutes=15)]
        apps_noturnos = defaultdict(int)
        for e in ultimos_15min:
            if e.categoria == CategoriaEvento.APP_FOREGROUND:
                apps_noturnos[e.pacote] += 1
        if not apps_noturnos:
            return
        app_top = max(apps_noturnos.items(), key=lambda x: x[1])
        pacote, uso = app_top
        # 🌟 AJUSTE: Limiar baixado para 2 para aprendizado mais rápido no início
        if uso < 2:
            return
        entidade = await catalogo.obter_app(pacote) or EntidadeSemantica(tipo="APP", chave=pacote)
        entidade.atributos.setdefault("insights", {})
        entidade.atributos["insights"]["uso_noturno"] = True
        await catalogo.memoria.salvar(entidade)

    async def _registrar_coocorrencia_pc(self, evento_pc: EventoCanonico):
        """
        Chamado quando uma atividade no PC é detectada (via UDP listener). 
        Procura por um evento de app no celular que tenha ocorrido um pouco antes.
        """
        # 🌟 CORREÇÃO: Pega o processo dentro do sub-payload enviado pelo Client PC
        inner_payload = evento_pc.payload.get("payload", {})
        programa_pc = inner_payload.get("processo")
        
        if not programa_pc:
            return

        agora = evento_pc.timestamp
        # Procura por um APP_FOREGROUND nos últimos 60 segundos
        for ev in reversed(self.eventos_recentes):
            if (agora - ev.timestamp) > timedelta(seconds=60):
                break

            if ev.categoria == CategoriaEvento.APP_FOREGROUND:
                pacote_app = ev.pacote
                if "assistentecell" in pacote_app: continue

                nova_coocorrencia = Coocorrencia(pacote_app, programa_pc, agora)
                self.coocorrencias.append(nova_coocorrencia)
                logger.info(f"🧠 [INFERENCIA] Coocorrência registrada (PC): App '{pacote_app}' -> PC '{programa_pc}'")
                return

    async def _inferir_associacao_pc(self):
        """
        Analisa as coocorrências registradas e, se encontrar um padrão forte,
        salva a associação na memória semântica.
        """
        # 🌟 AJUSTE: Limiar baixado para 2 interações para proatividade inicial
        if len(self.coocorrencias) < 2: 
            return

        contador = defaultdict(int)
        for co in self.coocorrencias:
            # Filtra o que NÃO parece mobile-mobile (não tem pontos no nome do programa)
            if "." not in co.programa_pc:
                contador[(co.pacote_app, co.programa_pc)] += 1

        for (pacote, programa), contagem in contador.items():
            if contagem >= 2 and self.associacoes_pc_aprendidas.get(pacote) != programa:
                logger.info(f"✨ [INFERENCIA] Nova associação aprendida! App '{pacote}' -> PC '{programa}'")
                
                entidade_app = await catalogo.obter_app(pacote)
                if entidade_app:
                    entidade_app.atributos.setdefault("associacoes", {})
                    entidade_app.atributos["associacoes"]["pc_default"] = { "programa": programa }
                    await catalogo.memoria.salvar(entidade_app)
                    self.associacoes_pc_aprendidas[pacote] = programa
