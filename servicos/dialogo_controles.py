"""Continuação curta de horário; não é uma memória pessoal nem substitui o banco."""
import time
from servicos.linguagem_relogio import resposta_de_horario
from servicos.controle_casa import normalizar


class DialogoControles:
    def __init__(self, relogio=time.monotonic):
        self.relogio = relogio
        self.pendentes = {}
        self.semanticos = {}

    def resolver(self, chave, texto):
        item = self.pendentes.get(chave)
        if item and item[1] > self.relogio() and resposta_de_horario(texto):
            from servicos.datas_agenda import DATA, HORA
            from servicos.linguagem_relogio import numeros_falados
            base = HORA.sub('', numeros_falados(item[0]))
            if DATA.search(texto):
                base = DATA.sub('', base)
            resposta = numeros_falados(texto)
            if not HORA.search(resposta):
                resposta = 'as ' + resposta
            return base + ' ' + resposta
        anterior = self.semanticos.get(chave)
        if anterior and anterior[1] > self.relogio() and self._resposta_curta(texto):
            return anterior[0] + ' Complemento do usuário: ' + texto
        return texto

    @staticmethod
    def _resposta_curta(texto):
        import re
        return len(texto) < 150 and not re.match(r'^(?:ei |ollie|abra|abre|ligue|liga|desligue|desliga|crie|cria|me acorde|me lembre|o que|qual|como|quem|pesquise|procure)\b', normalizar(texto))

    def guardar_semantico(self, chave, texto, plano):
        self.semanticos = {k: v for k, v in self.semanticos.items() if v[1] > self.relogio()}
        if plano.get('pergunta') and not plano.get('continuacao_relogio'):
            self.semanticos[chave] = (texto[:2000], self.relogio() + 180)
        else:
            self.semanticos.pop(chave, None)

    def continua(self, chave, texto):
        item = self.pendentes.get(chave)
        anterior = self.semanticos.get(chave)
        return bool((anterior and anterior[1] > self.relogio() and self._resposta_curta(texto)) or
                    (item and item[1] > self.relogio() and (resposta_de_horario(texto) or normalizar(texto) in {'cancelar', 'cancela', 'nao', 'esquece', 'deixa pra la'})))

    def guardar(self, chave, plano):
        self.pendentes = {k: v for k, v in self.pendentes.items() if v[1] > self.relogio()}
        if plano.get('continuacao_relogio'):
            self.pendentes[chave] = (plano['continuacao_relogio'], self.relogio() + 180)
        else:
            self.pendentes.pop(chave, None)

    def cancelar(self, chave, texto):
        if (chave in self.pendentes or chave in self.semanticos) and normalizar(texto) in {'cancelar', 'cancela', 'nao', 'esquece', 'deixa pra la'}:
            self.pendentes.pop(chave, None)
            self.semanticos.pop(chave, None)
            return True
        return False


dialogo_controles = DialogoControles()
