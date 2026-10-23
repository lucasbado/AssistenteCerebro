"""Caixa de revisão: notificações indicam possíveis pendências, não comprovam falta de resposta."""
import asyncio
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError
from banco.database import AsyncSessionLocal
from banco.models import MensagemRevisaoDB
from servicos.controle_casa import normalizar
from servicos.datas_agenda import extrair_data, titulo_sem_data
from servicos.linguagem_tarefas import pendencia_mensagem, limpar_alvo
from servicos.tempo import horario_local, utc

PACOTES = {'com.whatsapp', 'com.whatsapp.w4b', 'org.telegram.messenger', 'com.google.android.apps.messaging',
    'com.samsung.android.messaging', 'org.thoughtcrime.securesms', 'com.instagram.android', 'com.discord'}


def pedido_mensagens(texto):
    t = normalizar(texto)
    return bool(re.match(r'^(?:ollie[, ]+)?(?:minhas mensagens|mensagens pendentes|quem precisa de resposta|quem me perguntou|(?:mostr[ae]|revis[ae]|quais|ver|listar)\b.*\bmensagens\b|prepar(?:e|a|ar) (?:uma )?resposta para\b)', t))


def referencia_conversa(valor):
    return str(valor) if re.fullmatch(r'[0-9a-f]{64}', str(valor or '')) else ''


def chave_conversa(pacote, remetente, referencia=None):
    identidade = referencia_conversa(referencia) or normalizar(remetente).strip()
    return hashlib.sha256(f'{pacote}|{identidade}'.encode()).hexdigest()


def chave_tarefa_mensagem(pacote, remetente, texto, timestamp, referencia=None):
    dia = horario_local(timestamp).date().isoformat()
    base = f'mensagem:{pacote}:{remetente}:{dia}:{normalizar(texto)}'
    return base + ':' + referencia_conversa(referencia) if referencia_conversa(referencia) else base


def origem_agenda_mensagem(pacote, referencia=None):
    return pacote + ':' + referencia_conversa(referencia) if referencia_conversa(referencia) else pacote


def sinais_mensagem(texto):
    t = normalizar(texto)
    if re.search(r'\b(?:cancelad\w*|nao precisa|nao vai|nao sera|ja foi|se der|talvez)\b', t): return []
    sinais = []
    if '?' in texto or re.search(r'\b(?:pode me|consegue me|me avisa|me confirma|preciso saber|aguardo sua resposta)\b', t): sinais.append('pergunta')
    if re.search(r'\b(?:convite|te convido|vamos|bora|topa|voce vem|voce vai|esta convidad\w*)\b', t): sinais.append('convite')
    if pendencia_mensagem(texto): sinais.append('prazo')
    return sinais


def apresentar(i):
    return {'id': i.id, 'pacote': i.pacote, 'remetente': i.remetente, 'texto': i.texto, 'sinais': list(i.sinais),
        'estado': i.estado, 'rascunho': i.rascunho, 'versao': i.versao, 'agenda_id': i.agenda_id, 'tarefa_id': i.tarefa_id,
        'recebido_em': utc(i.recebido_em).isoformat(), 'quando': horario_local(i.recebido_em).strftime('%d/%m às %H:%M'),
        'referencia_notificacao': i.referencia_notificacao}


class ConflitoMensagem(ValueError): pass


class CaixaMensagens:
    def __init__(self): self._lock = asyncio.Lock()

    async def limpar_antigas(self):
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(delete(MensagemRevisaoDB).where(MensagemRevisaoDB.recebido_em < datetime.now(timezone.utc) - timedelta(days=14)))

    async def registrar(self, pacote, payload, timestamp):
        if pacote not in PACOTES or payload.get('tipo_conteudo', 'MSG') != 'MSG': return None
        texto, remetente = str(payload.get('texto', '')).strip(), str(payload.get('titulo', '')).strip()[:150]
        sinais = sinais_mensagem(texto)
        if not texto or not remetente or not sinais or len(texto) > 4000: return None
        origem_conversa = referencia_conversa(payload.get('conversa_ref'))
        conversa = chave_conversa(pacote, remetente, origem_conversa)
        dia = horario_local(timestamp).date().isoformat()
        assinatura = hashlib.sha256(f'{conversa}|{dia}|{normalizar(texto)}'.encode()).hexdigest()
        async with self._lock:
            try:
                async with AsyncSessionLocal() as session, session.begin():
                    existente = (await session.execute(select(MensagemRevisaoDB).where(MensagemRevisaoDB.assinatura == assinatura))).scalar_one_or_none()
                    if existente:
                        referencia = str(payload.get('referencia_notificacao') or '')[:100]
                        if existente.estado == 'revisar' and referencia and referencia != existente.referencia_notificacao:
                            existente.referencia_notificacao = referencia
                            existente.versao += 1
                        return apresentar(existente)
                    item = MensagemRevisaoDB(id=str(uuid.uuid4()), assinatura=assinatura, conversa=conversa, pacote=pacote,
                        remetente=remetente, texto=texto, sinais=sinais, recebido_em=utc(timestamp), estado='revisar', rascunho='', versao=1, origem_conversa=origem_conversa,
                        referencia_notificacao=str(payload.get('referencia_notificacao') or '')[:100])
                    session.add(item)
                    await session.flush()
                    return apresentar(item)
            except IntegrityError:
                async with AsyncSessionLocal() as session:
                    return apresentar((await session.execute(select(MensagemRevisaoDB).where(MensagemRevisaoDB.assinatura == assinatura))).scalar_one())

    async def listar(self, estado='revisar'):
        if estado not in {'revisar', 'resolvida', 'ignorada'}: raise ValueError('Filtro de mensagens inválido.')
        async with AsyncSessionLocal() as session:
            itens = (await session.execute(select(MensagemRevisaoDB).where(MensagemRevisaoDB.estado == estado,
                MensagemRevisaoDB.recebido_em >= datetime.now(timezone.utc) - timedelta(days=14))
                .order_by(MensagemRevisaoDB.recebido_em.desc()).limit(100))).scalars().all()
            return [apresentar(i) for i in itens]

    async def obter(self, identificador):
        async with AsyncSessionLocal() as session:
            i = await session.get(MensagemRevisaoDB, identificador)
            if i is None or utc(i.recebido_em) < datetime.now(timezone.utc) - timedelta(days=14): raise LookupError('Essa mensagem não está mais na caixa de revisão.')
            return apresentar(i)

    async def alterar(self, identificador, versao, **mudancas):
        async with AsyncSessionLocal() as session, session.begin():
            resultado = await session.execute(update(MensagemRevisaoDB).where(MensagemRevisaoDB.id == identificador,
                MensagemRevisaoDB.versao == versao).values(**mudancas, versao=versao + 1))
            if resultado.rowcount != 1: raise ConflitoMensagem('Essa mensagem mudou. Atualize a caixa antes de tentar novamente.')
            i = await session.get(MensagemRevisaoDB, identificador)
            return apresentar(i)

    async def mudar_estado(self, identificador, versao, estado):
        if estado not in {'resolvida', 'ignorada'}: raise ValueError('Estado de mensagem inválido.')
        item = await self.obter(identificador)
        if item['estado'] == estado: return item
        if item['estado'] != 'revisar': raise ConflitoMensagem('Essa revisão já foi encerrada.')
        return await self.alterar(identificador, versao, estado=estado)

    async def salvar_rascunho(self, identificador, versao, texto):
        if not str(texto).strip() or len(texto) > 2000: raise ValueError('Escreva uma resposta com até 2.000 caracteres.')
        item = await self.obter(identificador)
        if item['estado'] != 'revisar': raise ConflitoMensagem('Essa revisão já foi encerrada.')
        return await self.alterar(identificador, versao, rascunho=texto.strip())

    async def preparar(self, identificador, versao, instrucoes=''):
        from servicos.llm import ServicoLLM
        item = await self.obter(identificador)
        if item['versao'] != versao or item['estado'] != 'revisar': raise ConflitoMensagem('Atualize a mensagem antes de preparar outra resposta.')
        texto = await ServicoLLM().preparar_resposta_mensagem(item['remetente'], item['texto'], instrucoes)
        return await self.salvar_rascunho(identificador, versao, texto)

    async def vincular(self, identificador, versao, tipo):
        from servicos.agenda import agenda
        from servicos.tarefas import tarefas
        from servicos.calendario import avisar_celular
        item = await self.obter(identificador)
        async with AsyncSessionLocal() as session:
            origem_conversa = (await session.get(MensagemRevisaoDB, identificador)).origem_conversa
        if item['versao'] != versao or item['estado'] != 'revisar': raise ConflitoMensagem('Atualize a mensagem antes de guardar esse item.')
        campo = 'agenda_id' if tipo == 'agenda' else 'tarefa_id'
        if item[campo]: return item
        referencia = datetime.fromisoformat(item['recebido_em'])
        data = extrair_data(item['texto'], referencia)
        async with self._lock:
            if tipo == 'agenda':
                if data is None: raise ValueError('Essa mensagem não tem uma data clara. Crie o compromisso pela agenda informando a data.')
                registro = await agenda.salvar('compromisso', titulo_sem_data(item['texto'])[:255], data['inicio'], data['dia_inteiro'],
                    origem=origem_agenda_mensagem(item['pacote'], origem_conversa), confirmar=True)
            elif tipo == 'tarefa':
                key = chave_tarefa_mensagem(item['pacote'], item['remetente'], item['texto'], referencia, origem_conversa)
                registro = await tarefas.salvar(limpar_alvo(item['texto'])[:255], data['inicio'] if data else None,
                    data['dia_inteiro'] if data else False, origem=item['pacote'], contexto=f'{item["remetente"]}: {item["texto"]}'[:500],
                    confirmar=False, chave_evento=key)
                if registro['estado'] == 'sugestao': registro = await tarefas.alterar(registro['id'], 'aceitar', versao=registro['versao'])
                elif registro['estado'] != 'pendente': raise ConflitoMensagem('Essa tarefa já foi encerrada. Crie outra pela lista de tarefas se precisar.')
            else: raise ValueError('Escolha agenda ou tarefa.')
            resultado = await self.alterar(identificador, versao, **{campo: registro['id']})
        await avisar_celular()
        return resultado


caixa_mensagens = CaixaMensagens()
