import json
from unittest.mock import AsyncMock
import pytest

from agentes.agente_reflexo import AgenteReflexo
from api.websocket import central_alertas
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from servicos import ordens_audio
from servicos.controle_audio import ArquivoEstadoAudio, ControleAudio, ConfigAudio
from servicos.resultado_audio import resultado_audio_valido


class Mixer:
    def __init__(self):
        self.parametros = {'Bus[0].Gain': -3, 'Strip[1].Mute': 0,
                           'Strip[3].A3': 1, 'Strip[3].B1': 1, 'Strip[4].A1': 1}
        self.escritas = []

    def ler(self, parametro):
        return self.parametros.get(parametro, 0)

    def ler_texto(self, parametro):
        return self.parametros.get(parametro, '')

    def escrever(self, parametro, valor):
        self.escritas.append((parametro, valor))
        self.parametros[parametro] = valor

    def confirmar(self, valores):
        assert all((self.ler_texto(p) if isinstance(v, str) else self.ler(p)) == v for p, v in valores.items())


def comando(texto):
    return EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO, origem=OrigemEvento.PC,
                          pacote='pc.chat', payload={'texto': texto})


@pytest.fixture(autouse=True)
def isolar_dialogo(monkeypatch):
    for atributo in ('_PENDENTES', '_ULTIMO_PEDIDO', '_ULTIMO_ALVO'):
        monkeypatch.setattr(ordens_audio, atributo, {})


@pytest.fixture
def desk_audio(monkeypatch, tmp_path):
    mixer = Mixer()
    estado = ArquivoEstadoAudio(tmp_path)
    executor = ControleAudio(mixer, estado=estado, config=ConfigAudio())

    async def enviar(mensagem, *, mixer_explicito):
        assert mixer_explicito
        retorno = {'audio': executor.executar(json.loads(mensagem['parametro']))}
        assert resultado_audio_valido(retorno)
        return {'status': 'concluido', 'resultado': retorno}

    responder = AsyncMock()
    monkeypatch.setattr(central_alertas, 'enviar_comando_pc', enviar)
    monkeypatch.setattr(ordens_audio, 'responder_pedido', responder)
    return mixer, estado, responder


async def test_comando_composto_e_continuacao_chegam_ao_mixer_sem_repetir_ajuste(monkeypatch, tmp_path):
    mixer = Mixer()
    executor = ControleAudio(mixer, estado=ArquivoEstadoAudio(tmp_path), config=ConfigAudio())

    async def enviar(mensagem, *, mixer_explicito):
        assert mixer_explicito and mensagem['comando'] == 'audio_controle'
        retorno = {'audio': executor.executar(json.loads(mensagem['parametro']))}
        assert resultado_audio_valido(retorno)
        return {'status': 'concluido', 'resultado': retorno}

    monkeypatch.setattr(central_alertas, 'enviar_comando_pc', enviar)
    responder = AsyncMock()
    monkeypatch.setattr(ordens_audio, 'responder_pedido', responder)
    monkeypatch.setattr(ordens_audio, '_ULTIMO_ALVO', {})
    reflexo = AgenteReflexo()
    evento = comando('Mute o canal dois e abaixe a saída A1 em três dB no Voicemeeter')
    await reflexo.processar(evento)
    await reflexo.processar(evento)
    assert mixer.escritas == [('Strip[1].Mute', 1), ('Bus[0].Gain', -6)]
    await reflexo.processar(comando('Agora sobe mais dois dB'))
    assert mixer.escritas[-1] == ('Bus[0].Gain', -4)
    assert 'saída A1 ficou em -4 dB' in responder.await_args.args[1]


async def test_mixer_nao_executa_primeira_etapa_se_segunda_e_invalida(monkeypatch):
    enviar = AsyncMock()
    monkeypatch.setattr(central_alertas, 'enviar_comando_pc', enviar)
    monkeypatch.setattr(ordens_audio, 'responder_pedido', AsyncMock())
    assert await ordens_audio.encaminhar_audio(comando('Mute o canal dois e defina A1 para 90 dB no Voicemeeter'))
    enviar.assert_not_awaited()


async def test_mixer_estruturado_exige_fluxo_explicito_de_voz_ou_chat():
    resultado = await central_alertas.enviar_comando_pc({'comando': 'audio_controle',
        'parametro': json.dumps({'id_comando': 'teste', 'operacao': 'mudo_mixer', 'alvo': 'A1', 'valor': 1})})
    assert resultado['status'] == 'erro'


def test_consulta_entende_ordinais_comuns_na_transcricao():
    assert ordens_audio.interpretar_audio('Mostre a primeira saída do Voicemeeter') == {
        'operacao': 'ler_mixer', 'alvo': 'A1'}
    assert ordens_audio.interpretar_audio('mostre também o estado da segunda saída do Voicemeeter') == {
        'operacao': 'ler_mixer', 'alvo': 'A2'}


async def test_pedido_da_imagem_troca_so_a_saida_fisica_e_preserva_rotas_virtuais(desk_audio):
    mixer, _, responder = desk_audio
    await AgenteReflexo().processar(comando('O Voiceemeter input coloque ele para sair no A1 que é o fone'))
    assert mixer.escritas == [('Strip[3].A1', 1), ('Strip[3].A3', 0)]
    assert mixer.ler('Strip[3].B1') == mixer.ler('Strip[4].A1') == 1
    assert 'Principal está saindo por Fone (A1)' in responder.await_args.args[1]


async def test_falta_de_saida_pede_nome_e_sim_nao_confirma_rota(desk_audio):
    mixer, _, responder = desk_audio
    reflexo = AgenteReflexo()
    await reflexo.processar(comando('Mude onde sai o Principal'))
    await reflexo.processar(comando('Sim'))
    assert not mixer.escritas
    assert 'Qual saída' in responder.await_args.args[1] and responder.await_args.kwargs['pergunta']
    await reflexo.processar(comando('fone'))
    assert mixer.escritas == [('Strip[3].A1', 1), ('Strip[3].A3', 0)]


async def test_apelido_e_confirmado_no_mixer_e_resolvido_do_catalogo(desk_audio):
    mixer, estado, responder = desk_audio
    reflexo = AgenteReflexo()
    await reflexo.processar(comando('Apelide o Voicemeeter AUX de Áudio Jogo'))
    assert mixer.ler_texto('Strip[4].Label') == 'Áudio Jogo'
    assert estado.ler().apelidos_mixer == {'ENTRADA5': 'Áudio Jogo'}
    mixer.parametros['Strip[4].Label'] = ''  # O mixer pode recarregar o perfil antigo.
    await reflexo.processar(comando('Mova o Áudio Jogo para o Echo Dot'))
    await reflexo.processar(comando('Ligue o Áudio Jogo também no fone'))
    assert mixer.ler('Strip[4].A1') == mixer.ler('Strip[4].A2') == 1
    assert mixer.ler('Strip[3].A3') == 1
    await reflexo.processar(comando('Quais são os canais do Voicemeeter?'))
    assert 'Áudio Jogo (Voicemeeter AUX Input)' in responder.await_args.args[1]
