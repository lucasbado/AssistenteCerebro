from fastapi import APIRouter
from servicos.consumo_ia import consumo_ia
from servicos.ponte_ia_pc import ponte_ia_pc
from servicos.cloudflare_ia import CloudflareProvider

router = APIRouter()


@router.get('/consumo')
async def consumo():
    dados = await consumo_ia.resumo()
    return {**dados, 'pc_disponivel': ponte_ia_pc.disponivel(),
            'cloudflare_configurada': CloudflareProvider().disponivel()}
