import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from servicos.controle_audio import ArquivoEstadoAudio, ConfigAudio, ControleAudio, MixerBanana


class MixerFake:
    def __init__(self):
        self.valores = {**{f'Bus[{i}].Gain': v for i, v in enumerate([-3., 3., 6.])},
                        **{f'Bus[{i}].Mute': 0 for i in range(3)}, 'Option.delay[1]': 0, 'Option.delay[2]': 100}
        self.escritas = []
        self.falhar = None

    def ler(self, p): return self.valores[p]
    def escrever(self, p, v):
        self.escritas.append((p, v))
        if p == self.falhar: raise RuntimeError('Falha simulada')
        self.valores[p] = v
    def confirmar(self, valores):
        assert all(self.valores[p] == v for p, v in valores.items())


@pytest.fixture
def controle(tmp_path):
    mixer = MixerFake()
    return ControleAudio(mixer, ArquivoEstadoAudio(tmp_path), ConfigAudio()), mixer


def pedir(c, op, ident=None, **kwargs):
    from uuid import uuid4
    return c.executar({'id_comando': ident or str(uuid4()), 'operacao': op, **kwargs})


def perfil(c, nome): return pedir(c, 'selecionar_perfil', perfil_audio=nome)


def test_sem_perfil_nunca_inferir_pelo_mute(controle):
    c, m = controle
    assert pedir(c, 'avancar')['codigo'] == 'perfil_nao_selecionado'
    assert m.escritas == []


def test_headset_altera_somente_a1_e_passo_configuravel(controle):
    c, m = controle
    c.config = ConfigAudio(passo_volume_db=1.5)
    perfil(c, 'HEADSET')
    assert pedir(c, 'avancar')['depois'] == {'Bus[0].Gain': -1.5}
    pedir(c, 'voltar')
    assert m.valores['Bus[0].Gain'] == -3
    assert {p for p, _ in m.escritas} == {'Bus[0].Gain'}


def test_cinema_diferenca_e_limites_do_par(controle):
    c, m = controle; perfil(c, 'CINEMA')
    pedir(c, 'avancar')
    assert (m.valores['Bus[1].Gain'], m.valores['Bus[2].Gain']) == (5, 8)
    m.valores.update({'Bus[1].Gain': 10, 'Bus[2].Gain': 11})
    pedir(c, 'avancar')
    assert (m.valores['Bus[1].Gain'], m.valores['Bus[2].Gain']) == (11, 12)
    assert pedir(c, 'avancar')['codigo'] == 'limite_atingido'
    m.valores.update({'Bus[1].Gain': -59, 'Bus[2].Gain': -56})
    pedir(c, 'voltar')
    assert (m.valores['Bus[1].Gain'], m.valores['Bus[2].Gain']) == (-60, -57)


@pytest.mark.parametrize('mutada,ativa', [(1, 2), (2, 1)])
def test_cinema_com_uma_mutada_ajusta_so_a_outra(controle, mutada, ativa):
    c, m = controle; perfil(c, 'CINEMA')
    m.valores[f'Bus[{mutada}].Mute'] = 1
    pedir(c, 'avancar')
    assert [p for p, _ in m.escritas] == [f'Bus[{ativa}].Gain']
    assert m.valores[f'Bus[{mutada}].Mute'] == 1


def test_todas_mutadas_nao_recebem_escritas(controle):
    c, m = controle; perfil(c, 'CINEMA')
    m.valores.update({'Bus[1].Mute': 1, 'Bus[2].Mute': 1})
    assert pedir(c, 'avancar')['codigo'] == 'saidas_mutadas'
    assert not m.escritas


def test_perfil_modo_independentes_persistem_em_novas_instancias(controle):
    c, m = controle
    perfil(c, 'HEADSET'); pedir(c, 'alternar_modo')
    outro = ControleAudio(m, ArquivoEstadoAudio(c.estado.pasta), ConfigAudio())
    bloqueado = pedir(outro, 'avancar')
    assert bloqueado['codigo'] == 'sincronizacao_exige_cinema'
    assert not m.escritas
    perfil(outro, 'CINEMA')
    assert pedir(outro, 'consultar')['modo_controle'] == 'SINCRONIZACAO'
    assert pedir(outro, 'avancar')['depois'] == {'Option.delay[2]': 110}
    pedir(outro, 'voltar')
    assert m.valores['Option.delay[2]'] == 100 and m.valores['Option.delay[1]'] == 0


def test_delay_limites_e_mute(controle):
    c, m = controle; perfil(c, 'CINEMA'); pedir(c, 'alternar_modo')
    m.valores['Option.delay[2]'] = 495
    pedir(c, 'avancar'); assert m.valores['Option.delay[2]'] == 500
    m.valores['Option.delay[2]'] = 5
    pedir(c, 'voltar'); assert m.valores['Option.delay[2]'] == 0
    m.valores['Bus[2].Mute'] = 1
    antes = list(m.escritas)
    assert pedir(c, 'avancar')['codigo'] == 'a3_mutada'
    assert m.escritas == antes


def test_evento_duplicado_ou_interrompido_nao_repete_efeito(controle):
    c, m = controle; perfil(c, 'HEADSET')
    r = pedir(c, 'avancar', 'mesmo-id')
    assert pedir(c, 'avancar', 'mesmo-id') == r
    assert len(m.escritas) == 1
    assert pedir(c, 'voltar', 'mesmo-id')['codigo'] == 'id_reutilizado'
    state = c.estado.ler(); state.recibos['mesmo-id'].pop('resultado'); c.estado.salvar(state)
    assert pedir(c, 'avancar', 'mesmo-id')['status'] == 'indeterminado'
    assert len(m.escritas) == 1


def test_corrupcao_de_estado_nao_reinicializa_perfil(controle):
    c, m = controle
    c.estado.path.write_text('{corrompido', encoding='utf-8')
    with pytest.raises(ValueError): pedir(c, 'avancar')
    assert not m.escritas


def test_falha_de_escrita_atomica_preserva_arquivo_anterior(controle, monkeypatch):
    import servicos.controle_audio as modulo
    c, _ = controle; perfil(c, 'HEADSET')
    antes = c.estado.path.read_bytes()
    monkeypatch.setattr(modulo.os, 'replace', Mock(side_effect=OSError('Disco simulado')))
    with pytest.raises(OSError): pedir(c, 'alternar_modo')
    assert c.estado.path.read_bytes() == antes
    assert not list(c.estado.pasta.glob('*.tmp'))


def test_comandos_concorrentes_nao_perdem_incrementos(controle):
    c, m = controle; perfil(c, 'HEADSET')
    m.valores['Bus[0].Gain'] = -40
    def run(i):
        return pedir(ControleAudio(m, ArquivoEstadoAudio(c.estado.pasta), ConfigAudio()), 'avancar', f'concorrente-{i}')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(12)))
    assert all(r['status'] == 'concluido' for r in results)
    assert m.valores['Bus[0].Gain'] == -16
    assert len(c.estado.ler().recibos) == 13


def test_falha_parcial_nao_anuncia_sucesso_nem_repete(controle):
    c, m = controle; perfil(c, 'CINEMA'); m.falhar = 'Bus[2].Gain'
    r = pedir(c, 'avancar', 'falha')
    assert r['status'] == 'parcial' and r['alterado'] is None
    assert pedir(c, 'avancar', 'falha') == r
    assert len(m.escritas) == 2


def test_feedback_falha_nao_desfaz_nem_repete_mudanca_de_modo(controle):
    c, _ = controle
    c.config = ConfigAudio(feedback_habilitado=True)
    c.feedback = Mock(side_effect=TimeoutError())
    r = pedir(c, 'alternar_modo', 'modo')
    assert r['status'] == 'concluido' and r['feedback'] == 'falhou'
    assert pedir(c, 'alternar_modo', 'modo') == r
    c.feedback.assert_called_once_with('SINCRONIZACAO')


def test_adaptador_descarta_cache_e_confirma_leitura_real():
    class ApiComSnapshot:
        def __init__(self):
            self.cache = {'Bus[0].Gain': 12}
            self.real = 0
            self.snapshot = -3
            self.atualizacoes = 0

        @property
        def pdirty(self):
            self.snapshot = self.real
            self.atualizacoes += 1
            return True

        def get(self, p):
            return self.cache.pop(p, self.snapshot)

        def set(self, p, v):
            self.cache[p] = v
            self.real = v

    vm = ApiComSnapshot()
    a = MixerBanana(lambda: vm)
    assert a.ler('Bus[0].Gain') == 0
    assert not vm.cache
    a.escrever('Bus[0].Gain', 2)
    a.confirmar({'Bus[0].Gain': 2})
    assert vm.atualizacoes == 2


def test_estado_serializado_entre_processos_reais(tmp_path):
    import os, subprocess, sys
    codigo = '''
import sys
from servicos.controle_audio import ControleAudio, ArquivoEstadoAudio, ConfigAudio
c=ControleAudio(None, ArquivoEstadoAudio(sys.argv[1],timeout=10), ConfigAudio())
r=c.executar({'id_comando':sys.argv[2],'operacao':'alternar_modo'})
assert r['status']=='concluido',r
'''
    ambiente = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    jobs = [subprocess.Popen([sys.executable, '-c', codigo, str(tmp_path), f'processo-{i}'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ambiente) for i in range(6)]
    for job in jobs:
        _, err = job.communicate(timeout=20)
        assert job.returncode == 0, err.decode(errors='replace')
    estado = ArquivoEstadoAudio(tmp_path).ler()
    assert estado.modo_controle == 'VOLUME'
    assert len(estado.recibos) == 6
