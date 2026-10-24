"""Perfil cacheado por 24h; alterações no perfil renovam no máximo uma vez por hora."""
import hashlib
from datetime import datetime, timedelta, timezone
from sqlalchemy import update
from banco.database import AsyncSessionLocal
from banco.models import CacheIADB
from servicos.consumo_ia import travar_controle, utc


async def resumo_cacheado(texto, gerar):
    agora = datetime.now(timezone.utc)
    assinatura = hashlib.sha256(texto.encode()).hexdigest()
    chave = 'resumo_perfil'
    anterior = None
    async with AsyncSessionLocal() as s, s.begin():
        await travar_controle(s, 'cache_perfil')
        item = await s.get(CacheIADB, chave)
        if item is not None:
            anterior = item.resultado
            idade = agora - utc(item.atualizado_em) if item.atualizado_em else timedelta(days=100)
            if (anterior is not None and (idade < timedelta(hours=1) or (
                item.assinatura == assinatura and idade < timedelta(hours=24)))) or utc(item.bloqueado_ate) > agora:
                return anterior or {'resumo': 'Seu perfil está sendo preparado.', 'cards': []}
            item.bloqueado_ate = agora + timedelta(minutes=2)
        else:
            s.add(CacheIADB(chave=chave, assinatura='', resultado=None, bloqueado_ate=agora + timedelta(minutes=2)))
    try:
        resultado = await gerar()
        if not isinstance(resultado, dict) or not (resultado.get('resumo') or resultado.get('cards')):
            raise ValueError('Resumo de perfil vazio.')
        async with AsyncSessionLocal() as s, s.begin():
            await s.execute(update(CacheIADB).where(CacheIADB.chave == chave).values(resultado=resultado,
                assinatura=assinatura, atualizado_em=agora, bloqueado_ate=agora))
        return resultado
    except Exception:
        # Mantém o último resumo e não repete falhas em cada abertura da página.
        async with AsyncSessionLocal() as s, s.begin():
            await s.execute(update(CacheIADB).where(CacheIADB.chave == chave).values(bloqueado_ate=agora + timedelta(minutes=10)))
        return anterior or {'resumo': 'Resumo temporariamente indisponível.', 'cards': []}
