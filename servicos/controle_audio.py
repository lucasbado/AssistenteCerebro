"""Controle explícito dos buses Banana. Estado local, atômico e protegido entre processos."""
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from servicos.nomes_mixer import ALVOS_MIXER, SAIDAS, SAIDAS_FISICAS, VIRTUAIS, apelido_valido, localizar_nome

logger = logging.getLogger(__name__)
CONFIG = Path(__file__).resolve().parents[1] / 'config/audio.json'
DELAY_A3 = 'Option.delay[2]'
OPERACOES_MIXER = frozenset({'ler_mixer', 'ganho_mixer', 'ajustar_ganho_mixer', 'mudo_mixer', 'rota_mixer',
                             'catalogo_mixer', 'apelidar_mixer', 'mover_rota_mixer'})


class ComandoAudio(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id_comando: str = Field(min_length=1, max_length=128, pattern=r'^[\w.:-]+$')
    operacao: Literal['avancar', 'voltar', 'alternar_modo', 'selecionar_perfil', 'consultar',
                      'aumentar_atraso', 'zerar_atraso',
                      'ler_mixer', 'ganho_mixer', 'ajustar_ganho_mixer', 'mudo_mixer', 'rota_mixer',
                      'catalogo_mixer', 'apelidar_mixer', 'mover_rota_mixer']
    perfil_audio: Literal['HEADSET', 'CINEMA'] | None = None
    alvo: str | None = Field(default=None, pattern=r'^(?:A[1-3]|B[12]|ENTRADA[1-5])$')
    rota: Literal['A1', 'A2', 'A3', 'B1', 'B2'] | None = None
    valor: float | None = Field(default=None, allow_inf_nan=False)
    nome: str | None = Field(default=None, max_length=32)

    @model_validator(mode='after')
    def perfil_obrigatorio(self):
        if (self.operacao == 'selecionar_perfil') != (self.perfil_audio is not None):
            raise ValueError('Somente selecionar_perfil exige perfil_audio')
        if self.operacao not in OPERACOES_MIXER:
            if any(v is not None for v in (self.alvo, self.rota, self.valor, self.nome)):
                raise ValueError('Parâmetros de mixer fora da operação')
            return self
        if self.operacao == 'apelidar_mixer':
            if not self.alvo or not apelido_valido(self.nome) or self.rota is not None or self.valor is not None:
                raise ValueError('Indique um canal e um apelido de até 32 caracteres.')
            return self
        if self.nome is not None:
            raise ValueError('Apelido fora da operação')
        if self.operacao == 'catalogo_mixer':
            if any(v is not None for v in (self.alvo, self.rota, self.valor)):
                raise ValueError('A listagem não aceita ajustes')
            return self
        if self.operacao == 'mover_rota_mixer':
            if not self.alvo or self.alvo in SAIDAS or self.rota not in SAIDAS_FISICAS or self.valor is not None:
                raise ValueError('Indique uma entrada e uma saída física A1, A2 ou A3.')
            return self
        if self.operacao == 'ler_mixer':
            if self.rota is not None or self.valor is not None:
                raise ValueError('A leitura do mixer aceita apenas o canal')
            return self
        if self.alvo is None or self.valor is None:
            raise ValueError('Indique o canal e o valor do ajuste')
        if (self.operacao == 'rota_mixer') != (self.rota is not None):
            raise ValueError('Indique a saída somente ao alterar uma rota')
        if self.operacao == 'rota_mixer' and self.alvo in SAIDAS:
            raise ValueError('A rota parte de uma entrada do mixer')
        limites = {'ganho_mixer': (-60, 12), 'ajustar_ganho_mixer': (-60, 60)}
        if self.operacao in limites:
            minimo, maximo = limites[self.operacao]
            if not minimo <= self.valor <= maximo:
                raise ValueError('Ganho fora dos limites do mixer')
        elif self.valor not in (0, 1):
            raise ValueError('O estado deve ser zero ou um')
        return self


class ConfigAudio(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    passo_volume_db: float = Field(default=2.0, gt=0, le=6, allow_inf_nan=False)
    passo_delay_ms: Literal[10] = 10
    feedback_habilitado: bool = False


class EstadoAudio(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    versao: Literal[1] = 1
    perfil_audio: Literal['HEADSET', 'CINEMA'] | None = None
    modo_controle: Literal['VOLUME', 'SINCRONIZACAO'] = 'VOLUME'
    recibos: dict = Field(default_factory=dict)
    apelidos_mixer: dict[str, str] = Field(default_factory=dict, max_length=10)


class EstadoOcupado(RuntimeError):
    pass


class ArquivoEstadoAudio:
    def __init__(self, pasta=None, timeout=3):
        if pasta is None:
            pasta = os.getenv('OLLIE_AUDIO_STATE_DIR') or Path(os.getenv('LOCALAPPDATA') or Path.home()) / 'Ollie/audio'
        self.pasta = Path(pasta)
        self.path = self.pasta / 'estado.json'
        self.timeout = timeout

    @contextmanager
    def travar(self):
        self.pasta.mkdir(parents=True, exist_ok=True)
        with (self.pasta / 'estado.lock').open('a+b') as arquivo:
            if arquivo.seek(0, os.SEEK_END) == 0:
                arquivo.write(b'0'); arquivo.flush()
            limite = time.monotonic() + self.timeout
            while True:
                try:
                    arquivo.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= limite:
                        raise EstadoOcupado('Outro comando de áudio está em execução')
                    time.sleep(.025)
            try:
                yield
            finally:
                arquivo.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)

    def ler(self):
        if not self.path.exists():
            return EstadoAudio()
        return EstadoAudio.model_validate_json(self.path.read_text(encoding='utf-8'))

    def salvar(self, estado):
        temporario = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='.estado-', suffix='.tmp', dir=self.pasta, delete=False) as arquivo:
                temporario = Path(arquivo.name)
                arquivo.write(estado.model_dump_json())
                arquivo.flush()
                os.fsync(arquivo.fileno())
            os.replace(temporario, self.path)
        finally:
            if temporario is not None:
                temporario.unlink(missing_ok=True)


class MixerBanana:
    """Usa a conexão existente e evita confirmar uma escrita com seu próprio cache."""
    def __init__(self, obter_vm):
        self.obter_vm = obter_vm

    def ler(self, parametro):
        vm = self.obter_vm()
        if parametro == DELAY_A3:
            return self._ler_delay_a3(vm)
        vm.cache.pop(parametro, None)
        # A API nativa mantém outro snapshot além do cache Python. Consultar
        # IsParametersDirty atualiza esse snapshot, inclusive após vm.set().
        _ = vm.pdirty
        valor = float(vm.get(parametro))
        if not math.isfinite(valor):
            raise RuntimeError('VoiceMeeter devolveu valor inválido')
        return valor

    @staticmethod
    def _ler_delay_a3(vm):
        # No Banana 2.1.2.2, GetParameterFloat devolve um valor antigo
        # mesmo quando System Settings já mostra o ajuste aplicado.
        with tempfile.TemporaryDirectory(prefix='ollie-vm-') as pasta:
            arquivo = Path(pasta) / 'mixer.xml'
            vm.set('Command.Save', str(arquivo))
            vm.cache.pop('Command.Save', None)
            limite = time.monotonic() + 1
            while time.monotonic() < limite:
                try:
                    dados = arquivo.read_bytes()
                    opcoes = re.search(rb'<OptionDev\b[^>]*?/>', dados)
                    if opcoes:
                        valor = float(ET.fromstring(opcoes.group()).attrib['msA3'])
                        if 0 <= valor <= 500:
                            return valor
                        raise ValueError('Delay da A3 fora dos limites')
                except (FileNotFoundError, PermissionError):
                    pass
                time.sleep(.025)
        raise RuntimeError('VoiceMeeter não exportou o atraso da A3')

    def escrever(self, parametro, valor):
        self.obter_vm().set(parametro, valor)

    def ler_texto(self, parametro):
        vm = self.obter_vm()
        vm.cache.pop(parametro, None)
        _ = vm.pdirty
        valor = vm.get(parametro, is_string=True)
        return ''.join(c for c in valor if c.isprintable()).strip()[:160]

    def confirmar(self, valores):
        limite = time.monotonic() + .5
        while True:
            if all(self.ler_texto(p) == v if isinstance(v, str) else abs(self.ler(p) - v) < .05
                   for p, v in valores.items()):
                return
            if time.monotonic() >= limite:
                raise RuntimeError('VoiceMeeter não confirmou a alteração')
            time.sleep(.025)


class ControleAudio:
    def __init__(self, mixer, estado=None, config=None, feedback=None):
        self.mixer = mixer
        self.estado = estado or ArquivoEstadoAudio()
        self.config = config or ConfigAudio.model_validate_json(CONFIG.read_text(encoding='utf-8'))
        self.feedback = feedback

    def executar(self, comando):
        pedido = ComandoAudio.model_validate(comando)
        dados = pedido.model_dump(exclude={'id_comando'})
        if pedido.nome is None:
            dados.pop('nome')
        if pedido.operacao not in OPERACOES_MIXER:
            # Preserva recibos já gravados para os comandos do botão/HA.
            dados = {k: dados[k] for k in ('operacao', 'perfil_audio')}
        assinatura = hashlib.sha256(json.dumps(dados, sort_keys=True).encode()).hexdigest()
        try:
            with self.estado.travar():
                estado = self.estado.ler()  # Corrupção nunca vira reset silencioso.
                if pedido.operacao == 'catalogo_mixer':
                    try:
                        return self._resultado(estado, 'concluido', 'catalogo_mixer', False,
                                               catalogo=self._catalogo(estado))
                    except Exception as erro:
                        logger.warning('Catálogo do mixer indisponível (%s).', type(erro).__name__)
                        return self._resultado(estado, 'erro', 'executor_indisponivel', False)
                anterior = estado.recibos.get(pedido.id_comando)
                if anterior:
                    if anterior.get('assinatura') != assinatura:
                        return self._resultado(estado, 'erro', 'id_reutilizado', False)
                    return anterior.get('resultado') or self._resultado(estado, 'indeterminado', 'execucao_interrompida_nao_repetida', None)
                while len(estado.recibos) >= 200:
                    del estado.recibos[next(iter(estado.recibos))]
                estado.recibos[pedido.id_comando] = {'assinatura': assinatura}
                self.estado.salvar(estado)  # Reserva durável antes de qualquer efeito.
                try:
                    resultado = self._aplicar(estado, pedido)
                except Exception as erro:
                    logger.error('Áudio %s falhou: %s', pedido.id_comando, type(erro).__name__)
                    resultado = self._resultado(estado, 'erro', 'executor_indisponivel', None)
                estado.recibos[pedido.id_comando]['resultado'] = resultado
                self.estado.salvar(estado)
                logger.info('Áudio id=%s operação=%s perfil=%s modo=%s resultado=%s', pedido.id_comando, pedido.operacao, estado.perfil_audio, estado.modo_controle, resultado['codigo'])
                return resultado
        except EstadoOcupado:
            return {'status': 'ocupado', 'codigo': 'controle_ocupado', 'alterado': False}

    @staticmethod
    def _resultado(estado, status, codigo, alterado, **extra):
        return dict(status=status, codigo=codigo, alterado=alterado,
                    perfil_audio=estado.perfil_audio, modo_controle=estado.modo_controle, **extra)

    def _aplicar(self, estado, pedido):
        if pedido.operacao in OPERACOES_MIXER:
            return self._aplicar_mixer(estado, pedido)
        if pedido.operacao == 'consultar':
            return self._resultado(estado, 'concluido', 'estado_consultado', False)
        if pedido.operacao == 'selecionar_perfil':
            mudou = estado.perfil_audio != pedido.perfil_audio
            estado.perfil_audio = pedido.perfil_audio
            return self._resultado(estado, 'concluido', 'perfil_selecionado', mudou)
        if pedido.operacao == 'alternar_modo':
            estado.modo_controle = 'SINCRONIZACAO' if estado.modo_controle == 'VOLUME' else 'VOLUME'
            self.estado.salvar(estado)
            feedback = 'desabilitado'
            if self.config.feedback_habilitado:
                try:
                    feedback = 'enviado' if self.feedback and self.feedback(estado.modo_controle) else 'falhou'
                except Exception as erro:
                    logger.warning('Feedback de áudio falhou: %s', type(erro).__name__)
                    feedback = 'falhou'
            return self._resultado(estado, 'concluido', 'modo_alterado', True, feedback=feedback)
        if estado.perfil_audio is None:
            return self._resultado(estado, 'bloqueado', 'perfil_nao_selecionado', False)
        direcao = 1 if pedido.operacao == 'avancar' else -1
        if pedido.operacao in ('aumentar_atraso', 'zerar_atraso') or estado.modo_controle == 'SINCRONIZACAO':
            return self._ajustar_atraso(estado, pedido.operacao)
        indices = [0] if estado.perfil_audio == 'HEADSET' else [1, 2]
        ativos = [i for i in indices if not self._mute(i)]
        if not ativos:
            return self._resultado(estado, 'sem_alteracao', 'saidas_mutadas', False)
        antes = {f'Bus[{i}].Gain': self.mixer.ler(f'Bus[{i}].Gain') for i in ativos}
        if any(not -60 <= v <= 12 for v in antes.values()):
            raise RuntimeError('Ganho fora dos limites')
        passo = self.config.passo_volume_db
        delta = min(passo, 12 - max(antes.values())) if direcao > 0 else -min(passo, min(antes.values()) + 60)
        depois = {p: round(v + delta, 4) for p, v in antes.items()}
        return self._escrever(estado, antes, depois, {f'Bus[{i}].Gain': i for i in ativos})

    def _ajustar_atraso(self, estado, operacao):
        if estado.perfil_audio != 'CINEMA':
            return self._resultado(estado, 'bloqueado', 'sincronizacao_exige_cinema', False)
        if self._mute(2):
            return self._resultado(estado, 'sem_alteracao', 'a3_mutada', False)
        antes = self.mixer.ler(DELAY_A3)
        if not 0 <= antes <= 500:
            raise RuntimeError('Delay fora dos limites')
        direcao = -1 if operacao == 'voltar' else 1
        depois = 0 if operacao == 'zerar_atraso' else max(0, min(500, antes + direcao * self.config.passo_delay_ms))
        return self._escrever(estado, {DELAY_A3: antes}, {DELAY_A3: depois}, {DELAY_A3: 2})

    def _aplicar_mixer(self, estado, pedido):
        if pedido.operacao == 'apelidar_mixer':
            return self._apelidar(estado, pedido)
        if pedido.operacao == 'mover_rota_mixer':
            return self._mover_rota(estado, pedido)
        if pedido.operacao == 'ler_mixer':
            alvos = (pedido.alvo,) if pedido.alvo else SAIDAS
            campos = ['Gain', 'Mute']
            if pedido.alvo and pedido.alvo.startswith('ENTRADA'):
                campos.extend(SAIDAS)
            valores = {f'{ALVOS_MIXER[alvo]}.{campo}': self.mixer.ler(f'{ALVOS_MIXER[alvo]}.{campo}')
                       for alvo in alvos for campo in campos}
            return self._resultado(estado, 'concluido', 'mixer_consultado', False, depois=valores)
        campo = pedido.rota or ('Mute' if pedido.operacao == 'mudo_mixer' else 'Gain')
        parametro = f'{ALVOS_MIXER[pedido.alvo]}.{campo}'
        anterior = self.mixer.ler(parametro)
        valor = pedido.valor
        if pedido.operacao == 'ajustar_ganho_mixer':
            valor = max(-60, min(12, anterior + valor))
        antes, depois = {parametro: anterior}, {parametro: valor}
        if abs(anterior - valor) < .05:
            return self._resultado(estado, 'sem_alteracao', 'mixer_ja_ajustado', False, depois=antes)
        try:
            self.mixer.escrever(parametro, valor)
            self.mixer.confirmar(depois)
        except Exception as erro:
            logger.warning('Não consegui confirmar o ajuste do mixer (%s).', type(erro).__name__)
            return self._resultado(estado, 'parcial', 'alteracao_nao_confirmada', None,
                                   antes=antes, solicitado=depois, parametros_tentados=[parametro])
        return self._resultado(estado, 'concluido', 'ajuste_confirmado', True, antes=antes, depois=depois)

    def _catalogo(self, estado):
        return {alvo: {'rotulo': self.mixer.ler_texto(f'{prefixo}.Label'),
                       'dispositivo': self.mixer.ler_texto(f'{prefixo}.device.name') if alvo in SAIDAS_FISICAS else '',
                       'apelido': estado.apelidos_mixer.get(alvo, ''),
                       'rotas': [saida for saida in SAIDAS if self.mixer.ler(f'{prefixo}.{saida}') == 1]
                       if alvo in VIRTUAIS else []}
                for alvo, prefixo in ALVOS_MIXER.items()}

    def _apelidar(self, estado, pedido):
        catalogo = self._catalogo(estado)
        dono = localizar_nome(pedido.nome, catalogo)
        if dono is not None and dono != pedido.alvo:
            return self._resultado(estado, 'bloqueado', 'apelido_em_uso', False)
        parametro = f'{ALVOS_MIXER[pedido.alvo]}.Label'
        mudou = catalogo[pedido.alvo]['rotulo'] != pedido.nome or estado.apelidos_mixer.get(pedido.alvo) != pedido.nome
        if catalogo[pedido.alvo]['rotulo'] != pedido.nome:
            try:
                self.mixer.escrever(parametro, pedido.nome)
                self.mixer.confirmar({parametro: pedido.nome})
            except Exception:
                return self._resultado(estado, 'parcial', 'apelido_nao_confirmado', None)
        estado.apelidos_mixer[pedido.alvo] = pedido.nome
        return self._resultado(estado, 'concluido', 'mixer_apelidado', mudou, nome=pedido.nome)

    def _mover_rota(self, estado, pedido):
        prefixo = ALVOS_MIXER[pedido.alvo]
        # Liga a nova saída antes de desligar as antigas. B1 e B2 são rotas de gravação/stream.
        saidas = (pedido.rota, *(s for s in SAIDAS_FISICAS if s != pedido.rota))
        depois = {f'{prefixo}.{saida}': int(saida == pedido.rota) for saida in saidas}
        antes = {parametro: self.mixer.ler(parametro) for parametro in depois}
        if any(valor not in (0, 1) for valor in antes.values()):
            raise RuntimeError('Rota anterior inválida')
        if antes == depois:
            return self._resultado(estado, 'sem_alteracao', 'mixer_ja_ajustado', False, depois=depois)
        tentados = []
        try:
            for parametro, valor in depois.items():
                if antes[parametro] != valor:
                    tentados.append(parametro)
                    self.mixer.escrever(parametro, valor)
            self.mixer.confirmar(depois)
        except Exception:
            return self._resultado(estado, 'parcial', 'alteracao_nao_confirmada', None, antes=antes,
                                   solicitado=depois, parametros_tentados=tentados)
        return self._resultado(estado, 'concluido', 'rotas_confirmadas', True, antes=antes, depois=depois)

    def _mute(self, indice):
        value = self.mixer.ler(f'Bus[{indice}].Mute')
        if value not in (0, 1):
            raise RuntimeError('Mute inválido')
        return value == 1

    def _escrever(self, estado, antes, depois, buses):
        if antes == depois:
            return self._resultado(estado, 'sem_alteracao', 'limite_atingido', False, antes=antes, depois=depois)
        alterados = []
        try:
            for p in depois:
                if self._mute(buses[p]):
                    raise RuntimeError('Mute mudou durante o comando')
            for p, v in depois.items():
                if self._mute(buses[p]):
                    raise RuntimeError('Mute mudou durante o comando')
                alterados.append(p)  # Uma escrita que lança erro também pode ter ocorrido.
                self.mixer.escrever(p, v)
            self.mixer.confirmar(depois)
        except Exception as erro:
            logger.error('Falha ao confirmar áudio: %s', type(erro).__name__)
            return self._resultado(estado, 'parcial' if alterados else 'erro', 'alteracao_nao_confirmada', None if alterados else False,
                                   antes=antes, solicitado=depois, parametros_tentados=alterados)
        return self._resultado(estado, 'concluido', 'ajuste_confirmado', True, antes=antes, depois=depois)


def executar_audio(comando, service=None):
    if service is None:
        from servicos.pc_control_service import pc_control_service
        service = pc_control_service
    def feedback(modo):
        import asyncio
        from servicos.home_assistant_service import home_assistant_service
        return asyncio.run(home_assistant_service.feedback_audio(modo))
    return ControleAudio(MixerBanana(service.obter_vm_audio), feedback=feedback).executar(comando)
