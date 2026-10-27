"""Controle explícito dos buses Banana. Estado local, atômico e protegido entre processos."""
import hashlib
import json
import logging
import math
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)
CONFIG = Path(__file__).resolve().parents[1] / 'config/audio.json'


class ComandoAudio(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id_comando: str = Field(min_length=1, max_length=128, pattern=r'^[\w.:-]+$')
    operacao: Literal['avancar', 'voltar', 'alternar_modo', 'selecionar_perfil', 'consultar']
    perfil_audio: Literal['HEADSET', 'CINEMA'] | None = None

    @model_validator(mode='after')
    def perfil_obrigatorio(self):
        if (self.operacao == 'selecionar_perfil') != (self.perfil_audio is not None):
            raise ValueError('Somente selecionar_perfil exige perfil_audio')
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
        vm.cache.pop(parametro, None)
        # A API nativa mantém outro snapshot além do cache Python. Consultar
        # IsParametersDirty atualiza esse snapshot, inclusive após vm.set().
        _ = vm.pdirty
        valor = float(vm.get(parametro))
        if not math.isfinite(valor):
            raise RuntimeError('VoiceMeeter devolveu valor inválido')
        return valor

    def escrever(self, parametro, valor):
        self.obter_vm().set(parametro, valor)

    def confirmar(self, valores):
        limite = time.monotonic() + .5
        while True:
            if all(abs(self.ler(p) - v) < .05 for p, v in valores.items()):
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
        assinatura = hashlib.sha256(json.dumps(pedido.model_dump(exclude={'id_comando'}), sort_keys=True).encode()).hexdigest()
        try:
            with self.estado.travar():
                estado = self.estado.ler()  # Corrupção nunca vira reset silencioso.
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
        if estado.modo_controle == 'SINCRONIZACAO':
            if estado.perfil_audio != 'CINEMA':
                return self._resultado(estado, 'bloqueado', 'sincronizacao_exige_cinema', False)
            if self._mute(2):
                return self._resultado(estado, 'sem_alteracao', 'a3_mutada', False)
            parametro = 'Option.delay[2]'
            antes = self.mixer.ler(parametro)
            if not 0 <= antes <= 500:
                raise RuntimeError('Delay fora dos limites')
            depois = max(0, min(500, antes + direcao * self.config.passo_delay_ms))
            return self._escrever(estado, {parametro: antes}, {parametro: depois}, {parametro: 2})
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
