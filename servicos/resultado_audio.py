"""Validação do retorno do executor, antes de exibi-lo na API."""
import json
import math
from servicos.controle_audio import ALVOS_MIXER, SAIDAS


def resultado_audio_valido(resultado):
    if not isinstance(resultado, dict) or set(resultado) != {'audio'}:
        return False
    audio = resultado['audio']
    if not isinstance(audio, dict):
        return False
    if not isinstance(audio.get('status'), str) or audio['status'] not in {'concluido', 'sem_alteracao', 'bloqueado', 'erro', 'parcial', 'indeterminado', 'ocupado'}:
        return False
    if not isinstance(audio.get('codigo'), str) or not 1 <= len(audio['codigo']) <= 100:
        return False
    if audio.get('perfil_audio') not in (None, 'HEADSET', 'CINEMA') or audio.get('modo_controle') not in (None, 'VOLUME', 'SINCRONIZACAO'):
        return False
    if set(audio) - {'status', 'codigo', 'alterado', 'perfil_audio', 'modo_controle', 'feedback', 'antes', 'depois', 'solicitado', 'parametros_tentados'}:
        return False
    if audio.get('alterado') is not None and type(audio['alterado']) is not bool:
        return False
    if audio.get('feedback') not in (None, 'desabilitado', 'enviado', 'falhou'):
        return False
    parametros = {'Option.delay[2]': (0, 500)}
    for alvo, prefixo in ALVOS_MIXER.items():
        parametros[f'{prefixo}.Gain'] = (-60, 12)
        parametros[f'{prefixo}.Mute'] = (0, 1)
        if alvo.startswith('ENTRADA'):
            parametros.update({f'{prefixo}.{rota}': (0, 1) for rota in SAIDAS})
    for field in ('antes', 'depois', 'solicitado'):
        values = audio.get(field, {})
        if not isinstance(values, dict) or set(values) - parametros.keys():
            return False
        for p, v in values.items():
            minimo, maximo = parametros[p]
            if type(v) not in (int, float) or not math.isfinite(v) or not minimo <= v <= maximo:
                return False
            if (minimo, maximo) == (0, 1) and v not in (0, 1):
                return False
    tentados = audio.get('parametros_tentados', [])
    if not isinstance(tentados, list) or len(tentados) > 2 or any(not isinstance(p, str) or p not in parametros for p in tentados):
        return False
    return len(json.dumps(audio, ensure_ascii=False)) <= 4096
