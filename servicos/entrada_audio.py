"""Contrato autenticado HA → comando fixo do desktop; nunca recebe parâmetros arbitrários do mixer."""
import asyncio
import hashlib
import json
from collections import OrderedDict
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EntradaAudio(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    evento_id: str = Field(min_length=1, max_length=128, pattern=r'^[\w.:-]+$')
    action_name: Literal['media.next_track', 'media.previous_track', 'media.play_pause', 'audio.profile', 'audio.status']
    gesture: Literal['single_click', 'double_click', 'triple_click'] | None = None
    perfil_audio: Literal['HEADSET', 'CINEMA'] | None = None

    @model_validator(mode='after')
    def validar(self):
        if (self.action_name == 'audio.profile') != (self.perfil_audio is not None):
            raise ValueError('audio.profile exige perfil_audio e somente essa ação aceita perfil_audio')
        esperado = {'media.next_track': 'double_click', 'media.previous_track': 'triple_click', 'media.play_pause': 'single_click'}
        if self.gesture is not None and self.gesture != esperado.get(self.action_name):
            raise ValueError('Gesto não corresponde à ação')
        return self

    def comando(self):
        return {'id_comando': 'audio-' + hashlib.sha256(self.evento_id.encode()).hexdigest(),
                'operacao': {'media.next_track': 'avancar', 'media.previous_track': 'voltar',
                             'media.play_pause': 'alternar_modo', 'audio.profile': 'selecionar_perfil',
                             'audio.status': 'consultar'}[self.action_name],
                **({'perfil_audio': self.perfil_audio} if self.perfil_audio else {})}


class EntradaAudioService:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.recentes = OrderedDict()

    async def enviar(self, pedido, central):
        comando = pedido.comando()
        signature = json.dumps(comando, sort_keys=True)
        async with self.lock:
            old = self.recentes.get(comando['id_comando'])
            if old and old != signature:
                raise ValueError('evento_id já usado para outro pedido')
            self.recentes[comando['id_comando']] = signature
            while len(self.recentes) > 2000:
                self.recentes.popitem(last=False)
            return await central.enviar_comando_pc({'tipo_ws': 'COMANDO_PC', 'comando': 'audio_controle',
                'id_comando': comando['id_comando'], 'parametro': json.dumps(comando)})


entrada_audio = EntradaAudioService()
