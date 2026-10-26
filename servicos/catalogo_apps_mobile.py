"""Catálogo transitório enviado pelo celular registrado; não consulta o banco."""
import re
import time
from servicos.controle_casa import normalizar

PACKAGE = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+')


class CatalogoAppsMobile:
    def __init__(self):
        self.cliente = None
        self.apps = ()
        self.atualizado = 0

    def vincular(self, cliente):
        if cliente is not self.cliente:
            self.cliente, self.apps, self.atualizado = cliente, (), 0

    def receber(self, cliente, apps):
        if cliente is not self.cliente or not isinstance(apps, list) or len(apps) > 1500:
            return False
        limpos = {}
        for app in apps:
            if not isinstance(app, dict):
                continue
            nome, pacote = app.get('n'), app.get('p')
            if isinstance(nome, str) and 0 < len(nome.strip()) <= 100 and isinstance(pacote, str) and len(pacote) <= 180 and PACKAGE.fullmatch(pacote):
                limpos[pacote] = {'n': nome.strip(), 'p': pacote}
        self.apps, self.atualizado = tuple(limpos.values()), time.monotonic()
        return True

    def resolver(self, nome):
        t = normalizar(nome)
        aliases = {'relogio': 'com.sec.android.app.clockpackage', 'calculadora': 'com.sec.android.app.popupcalculator',
                   'camera': 'com.sec.android.app.camera', 'galeria': 'com.sec.android.gallery3d',
                   'configuracoes': 'com.android.settings', 'whatsapp': 'com.whatsapp', 'instagram': 'com.instagram.android',
                   'youtube': 'com.google.android.youtube', 'chrome': 'com.android.chrome'}
        exatos = [a for a in self.apps if normalizar(a['n']) == t or a['p'] == nome]
        if not exatos and t in aliases:
            exatos = [a for a in self.apps if a['p'] == aliases[t]]
        return exatos[0] if len(exatos) == 1 else None

    def candidatos(self, pedido):
        t = normalizar(pedido)
        def score(app):
            nome = normalizar(app['n'])
            return (10 if len(nome) > 2 and nome in t else 0) + sum(1 for w in nome.split() if len(w) > 3 and w in t)
        return sorted(self.apps, key=lambda a: (-score(a), a['n']))[:100]


catalogo_apps_mobile = CatalogoAppsMobile()
