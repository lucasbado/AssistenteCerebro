"""Copia o catálogo do servidor antes do primeiro deploy com persistência em banco."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


async def exportar(url, token, destino):
    async with httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {token}"}) as client:
        async def ler(tipo):
            response = await client.get(url.rstrip("/") + "/api/v1/capabilities/" + tipo)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or not all(isinstance(r, dict) and r.get("nome") for r in data):
                raise ValueError("O servidor retornou um catálogo inválido.")
            return data
        for _ in range(3):
            ativas = await ler("routines")
            descobertas = await ler("discovered")
            if ativas == await ler("routines") and descobertas == await ler("discovered"):
                break
        else:
            raise ValueError("O catálogo mudou durante a cópia. Tente novamente.")
    rejeitadas_path = ROOT / "config/rejected_routines.json"
    rejeitadas = json.loads(rejeitadas_path.read_text(encoding="utf-8")) if rejeitadas_path.exists() else []
    dados = {"versao": 1, "exportado_em": datetime.now(timezone.utc).isoformat(),
             "ativas": ativas, "descobertas": descobertas, "rejeitadas": rejeitadas}
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    Path(destino).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"rotinas": len(ativas), "sugestoes": len(descobertas), "destino": str(destino)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="URL do backend atualmente publicado")
    parser.add_argument("--destino", default=str(ROOT / "config/migracao_rotinas.json"))
    args = parser.parse_args()
    token = dotenv_values(ROOT / ".env").get("OLLIE_API_TOKEN", "")
    if not token:
        parser.error("Configure OLLIE_API_TOKEN no .env antes de exportar.")
    print(json.dumps(asyncio.run(exportar(args.url, token, args.destino)), ensure_ascii=True))
