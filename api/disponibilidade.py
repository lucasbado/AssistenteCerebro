"""Respostas honestas para recursos que exigem persistência no modo limitado."""
from starlette.responses import JSONResponse
from servicos.disponibilidade import AVISO_LIMITADO, modo_limitado


class DisponibilidadeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not modo_limitado(scope.get('app')):
            return await self.app(scope, receive, send)
        path = scope['path'].rstrip('/') or '/'
        method = scope['method']
        # As leituras abaixo têm DTOs próprios e não fingem listas pessoais vazias.
        if method == 'GET' and path == '/api/v1/home':
            payload = {'saudacao': 'Ollie em modo limitado', 'clima': None, 'cards': [
                {'tipo': 'boas_vindas', 'conteudo': {'titulo': 'Controles disponíveis', 'texto': AVISO_LIMITADO}},
            ]}
        elif method == 'GET' and path == '/api/v1/status':
            from core.kernel import kernel
            payload = {'status_geral': 'LIMITADO', 'kernel': kernel.estatisticas(),
                'llm': {'modelo_carregado': 'Pausado: banco indisponível'}, 'memorias': {'disponivel': False}}
        elif method == 'GET' and path == '/api/v1/pc/intervention/policy':
            payload = {'auto_open_enabled': False, 'min_priority_score': 1.0, 'whitelist': [],
                       'blacklist': [], 'controle_abertura_version': 1, 'modo_limitado': True}
        else:
            # Somente caminhos que não consultam a persistência. Rotas novas falham fechadas.
            allowed = (path in {'/', '/health', '/docs', '/openapi.json', '/redoc', '/eventos'}
                or path == '/api/v1/voice/speak'
                or path in {'/api/v1/pc/conexoes', '/api/v1/pc/pc-apps', '/api/v1/pc/mobile-apps', '/api/v1/pc/comando'}
                or path.startswith('/api/v1/pc/comando/')
                or path in {'/api/v1/ha/webhook', '/api/v1/ha/buttons/preview', '/api/v1/ha/light/on', '/api/v1/ha/light/off', '/api/v1/ha/light/toggle'})
            if allowed:
                return await self.app(scope, receive, send)
            await JSONResponse({'detail': AVISO_LIMITADO, 'codigo': 'persistencia_indisponivel', 'modo': 'limitado'}, status_code=503)(scope, receive, send)
            return
        await JSONResponse(payload, headers={'Cache-Control': 'no-store'})(scope, receive, send)
