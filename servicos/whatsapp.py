"""Reconhece pedidos de rascunho sem interpretar o corpo como outro comando."""
import re
from dataclasses import dataclass


COMANDO_WHATSAPP_PC = 'preparar_whatsapp_pc'
_PEDIDO = re.compile(
    r'(?:\s*(?:ei\s+)?ollie[,!\s]+)?(?:por favor[,\s]+)?(?:pode\s+)?'
    r'(?:mande|manda|envie|envia|enviar|prepare|prepara|preparar)\s+(?:uma\s+)?'
    r'mensagem\s+(?:para|pra|pro)\s+(?P<destinatario>.+?)\s+(?:no|pelo)\s+whatsapp'
    r'(?:\s+(?:do|no|pelo)\s+(?P<dispositivo>pc|computador|desktop|notebook|celular|android|telefone))?'
    r'\s+(?:dizendo|falando|com o texto)\s*[:,]?\s*(?P<texto>.+)',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RascunhoWhatsApp:
    destinatario: str
    texto: str
    destino: str


def interpretar_rascunho_whatsapp(texto):
    pedido = _PEDIDO.fullmatch(str(texto).strip())
    if pedido is None:
        return None
    dispositivo = (pedido['dispositivo'] or '').lower()
    destino = 'PC' if dispositivo in {'pc', 'computador', 'desktop', 'notebook'} else 'MOBILE'
    return RascunhoWhatsApp(pedido['destinatario'].strip(), pedido['texto'].strip(), destino)


def numero_whatsapp_pc(destinatario):
    telefone = re.sub(r'[ ()-]', '', destinatario)
    if re.fullmatch(r'\+[1-9][0-9]{7,14}', telefone):
        return telefone[1:]
    if re.fullmatch(r'55[1-9][0-9]{9,10}', telefone):
        return telefone
    raise ValueError('No PC, indique um número internacional com o código do país e o DDD. Você também pode pedir pelo WhatsApp do celular usando um contato.')
