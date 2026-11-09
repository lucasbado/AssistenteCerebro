"""
Ajuste de velocidade da fala de Ollie sem alterar o tom da voz (Algoritmo SOLA).
Mantém a altura da voz natural mesmo em velocidades mais altas (ex: 1.25x, 1.5x).
"""
import numpy as np

VELOCIDADE_PADRAO = 1.0
TAXA_AMOSTRAGEM = 24_000  # 24 kHz mono PCM 16-bit


class Acelerador:
    """Acelera PCM 16-bit sem alterar o tom, aceitando áudio em blocos."""

    def __init__(self, fator: float = VELOCIDADE_PADRAO, taxa: int = TAXA_AMOSTRAGEM):
        self.fator = max(1.0, float(fator))
        self.taxa = int(taxa)
        self.janela = int(self.taxa * 0.030)  # Janela de 30ms
        self.meia = self.janela // 2
        self.passo_saida = self.janela - self.meia
        self.passo_entrada = int(round(self.passo_saida * self.fator))
        self.busca = int(self.taxa * 0.005)  # 5ms de busca de sincronia
        self._rampa = np.linspace(0.0, 1.0, self.meia, dtype=np.float32)

        self._x = np.zeros(0, dtype=np.float32)
        self._p = 0
        self._cauda = None
        self._fim_da_janela = 0
        self._meio_byte = b""

    def _melhor_deslocamento(self) -> int:
        if self._cauda is None:
            return 0
        ini = max(0, self._p - self.busca)
        fim = min(len(self._x) - self.janela, self._p + self.busca)
        if fim <= ini:
            return 0
        trecho = self._x[ini: fim + self.meia]
        if len(trecho) < self.meia:
            return 0
        semelhanca = np.correlate(trecho, self._cauda, mode="valid")
        energia = np.sqrt(
            np.convolve(trecho * trecho, np.ones(self.meia, dtype=np.float32), mode="valid")
        ) + 1e-6
        n = min(len(semelhanca), len(energia))
        return int(ini + int(np.argmax(semelhanca[:n] / energia[:n])) - self._p)

    def _moer(self) -> list:
        saida = []
        while True:
            k = self._melhor_deslocamento()
            inicio = self._p + k
            if inicio < 0 or inicio + self.janela > len(self._x):
                break
            f = self._x[inicio: inicio + self.janela]
            if self._cauda is None:
                saida.append(f[: self.janela - self.meia])
            else:
                cruzado = self._cauda * (1.0 - self._rampa) + f[: self.meia] * self._rampa
                saida.append(cruzado)
                if self.janela - self.meia > self.meia:
                    saida.append(f[self.meia: self.janela - self.meia])
            self._cauda = f[self.janela - self.meia:].copy()
            self._fim_da_janela = inicio + self.janela
            self._p = inicio + self.passo_entrada
            corte = max(0, min(self._p, self._fim_da_janela) - self.busca)
            if corte > self.taxa:
                self._x = self._x[corte:]
                self._p -= corte
                self._fim_da_janela -= corte
        return saida

    @staticmethod
    def _para_bytes(pedacos: list) -> bytes:
        if not pedacos:
            return b""
        arr = np.concatenate(pedacos)
        arr = np.clip(arr, -32768.0, 32767.0)
        return arr.astype(np.int16).tobytes()

    def empurrar(self, raw: bytes) -> bytes:
        if not raw or self.fator <= 1.001:
            return raw
        if self._meio_byte:
            raw = self._meio_byte + raw
            self._meio_byte = b""
        if len(raw) % 2:
            self._meio_byte = raw[-1:]
            raw = raw[:-1]
            if not raw:
                return b""
        novo = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        self._x = np.concatenate([self._x, novo]) if len(self._x) else novo
        return self._para_bytes(self._moer())

    def fim(self) -> bytes:
        if self.fator <= 1.001:
            return b""
        sobra = []
        if self._cauda is not None:
            sobra.append(self._cauda)
            self._cauda = None
        if self._fim_da_janela < len(self._x):
            sobra.append(self._x[self._fim_da_janela:])
        self._x = np.zeros(0, dtype=np.float32)
        self._p = 0
        self._fim_da_janela = 0
        self._meio_byte = b""
        return self._para_bytes(sobra)


def acelerar_pcm16(raw: bytes, fator: float = VELOCIDADE_PADRAO, taxa: int = TAXA_AMOSTRAGEM) -> bytes:
    """Acelera um buffer de áudio PCM16. Se ocorrer falha, retorna o áudio original intacto."""
    if not raw or float(fator) <= 1.001:
        return raw
    try:
        acelerador = Acelerador(fator, taxa)
        return acelerador.empurrar(raw) + acelerador.fim()
    except Exception:
        return raw
