import json
from unittest.mock import AsyncMock

from agentes.agente_reflexo import AgenteReflexo
from api.websocket import central_alertas
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from servicos import ordens_audio
from servicos.controle_audio import ArquivoEstadoAudio, ControleAudio, ConfigAudio
from servicos.resultado_audio import resultado_audio_valido


class Mixer:
    def __init__(self):
        self.parametros = {'Bus[0].Gain': -3, 'Strip[1].Mute': 0}
        self.escritas = []

    def ler(self, parametro):
        return self.parametros[parametro]

    def escrever(self, parametro, valor):
        self.escritas.append((parametro, valor))
        self.parametros[parametro] = valor

    def confirmar(self, valores):
        assert all(self.parametros[p] == v for p, v in valores.items())


def comando(texto):
    return EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO, origem=OrigemEvento.PC,
                          pacote='pc.chat', payload={'texto': texto})


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
