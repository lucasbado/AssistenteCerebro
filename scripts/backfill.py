import os
import sys
import asyncio
import hashlib
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

# Adiciona o diretório raiz ao path para imports relativos funcionarem
sys.path.append(str(Path(__file__).resolve().parent.parent))

from banco.database import AsyncSessionLocal
from banco.models import FactDB, TaskQueueDB, MetaDB
from servicos.obsidian_parser import ObsidianParser
from servicos.llm import ServicoLLM

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("BackfillCLI")

EXTRACTION_SYSTEM_PROMPT = """You are an expert knowledge extractor. Extract atomic facts from the given text chunk.
Rules:
- Each fact must be self-contained and understandable without external context.
- Be atomic (one single idea per fact).
- State only what is explicitly written in the text. Do not infer or hallucinate.
- Maximum 20 words per fact.
- Return STRICTLY a JSON object with a single key "facts" containing a list of strings. Example: {"facts": ["User uses Python 3.12", "User prefers ruff over flake8"]}
- If no facts can be extracted, return {"facts": []}.
"""

EXTRACTION_FEW_SHOT = """
Example Input:
"## Setup\nUser configured Python 3.12 with poetry. Prefers ruff over flake8. Uses VS Code."
Example Output:
{"facts": ["User uses Python 3.12", "User uses poetry for dependency management", "User prefers ruff over other linters", "User uses VS Code"]}
"""

class BackfillOrchestrator:
    def __init__(self, vault_path: str, user_id: str = "default", dry_run: bool = False, skip_pattern: str = None):
        self.vault_path = Path(vault_path).resolve()
        self.user_id = user_id
        self.dry_run = dry_run
        self.skip_pattern = skip_pattern
        self.parser = ObsidianParser(self.vault_path)
        self.llm = ServicoLLM()

    def chunk_text(self, text: str, max_chars: int = 800) -> List[str]:
        """Realiza chunking semântico dividindo por headers ou blocos de tamanho máximo (~200 tokens)."""
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for p in paragraphs:
            if len(current_chunk) + len(p) + 2 <= max_chars:
                current_chunk += ("\n\n" if current_chunk else "") + p
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = p
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    async def extract_facts_from_chunk(self, chunk: str) -> List[str]:
        """Extrai fatos atômicos via LLM com retry e parsing defensivo."""
        prompt = f"{EXTRACTION_FEW_SHOT}\n\nInput Text:\n{chunk}"
        
        for attempt in range(2):
            try:
                provider = self.llm._pick_provider()
                response_str = await provider.gerar(prompt, EXTRACTION_SYSTEM_PROMPT, max_tokens=600)
                
                # Limpa marcações markdown se houver
                clean_resp = response_str.strip()
                if clean_resp.startswith("```json"):
                    clean_resp = clean_resp[7:]
                if clean_resp.endswith("```"):
                    clean_resp = clean_resp[:-3]
                clean_resp = clean_resp.strip()

                data = json.loads(clean_resp)
                facts = data.get("facts", [])
                if isinstance(facts, list):
                    # Limita a 15 fatos por chunk para evitar poluição
                    return [str(f).strip() for f in facts if f][:15]
            except Exception as e:
                logger.warning(f"⚠️ [Backfill] Tentativa {attempt + 1} falhou na extração: {e}")
                await asyncio.sleep(1)
        return []

    def calculate_importance(self, file_path: str, text: str, tags: List[str]) -> float:
        """Calcula importância inicial com base em tags, headers e recência."""
        importance = 0.5
        if "permanente" in tags or "zettel" in tags:
            importance += 0.3
        if "## Perfil" in text or "## Preferências" in text:
            importance += 0.2
        if "backlinks" in file_path.lower():
            importance += 0.1
        return min(1.0, importance)

    async def run(self):
        logger.info(f"🚀 [Backfill] Iniciando backfill para o vault: {self.vault_path} (User: {self.user_id}, DryRun: {self.dry_run})")
        
        if not self.vault_path.exists():
            logger.error(f"❌ [Backfill] Caminho do vault não encontrado: {self.vault_path}")
            return

        vault_files = set()
        error_log_path = Path("backfill_errors.log")
        errors = []

        md_files = list(self.vault_path.rglob("*.md"))
        total_facts_created = 0

        for file_path in md_files:
            if self.skip_pattern and re.search(self.skip_pattern, str(file_path)):
                logger.info(f"⏭️ [Backfill] Pulando arquivo por padrão de exclusão: {file_path.name}")
                continue

            try:
                clean_text, tags, rel_path = self.parser.parse_file(file_path)
                vault_files.add(rel_path)

                if not clean_text:
                    continue

                chunks = self.chunk_text(clean_text)
                file_facts_count = 0

                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        for chunk in chunks:
                            source_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                            
                            # Extrai fatos via LLM
                            facts = await self.extract_facts_from_chunk(chunk)
                            if not facts:
                                continue

                            importance = self.calculate_importance(rel_path, chunk, tags)

                            for fact_text in facts:
                                # Verifica idempotência via unique index (source_file + source_hash)
                                novo_fato = FactDB(
                                    user_id=self.user_id,
                                    text=fact_text,
                                    keywords=json.dumps(tags),
                                    importance=importance,
                                    source_file=rel_path,
                                    source_hash=source_hash
                                )
                                session.add(novo_fato)
                                
                                if not self.dry_run:
                                    # Enfileira embedding na task_queue
                                    task = TaskQueueDB(
                                        user_id=self.user_id,
                                        task_type="embed_fact",
                                        payload={"fact_text": fact_text, "source_file": rel_path}
                                    )
                                    session.add(task)

                                file_facts_count += 1
                        
                        await session.commit()
                
                total_facts_created += file_facts_count
                logger.info(f"✅ [Backfill] Arquivo processado: {rel_path} ({file_facts_count} fatos)")

            except Exception as e:
                err_msg = f"Erro no arquivo {file_path}: {e}\n"
                logger.error(f"❌ [Backfill] {err_msg}")
                errors.append(err_msg)

        if errors and not self.dry_run:
            with open(error_log_path, "w", encoding="utf-8") as f:
                f.writelines(errors)

        # 🌟 RECONCILIAÇÃO GLOBAL (Remoção de órfãos)
        if not self.dry_run:
            logger.info("🧹 [Backfill] Executando reconciliação global de deleções...")
            async with AsyncSessionLocal() as session:
                stmt = select(FactDB.source_file).where(FactDB.user_id == self.user_id, FactDB.source_file != None).distinct()
                result = await session.execute(stmt)
                db_files = {row[0] for row in result.all()}

                orphans = db_files - vault_files
                if orphans:
                    logger.info(f"🗑️ [Backfill] Removendo fatos órfãos de {len(orphans)} arquivos deletados...")
                    for orphan in orphans:
                        from sqlalchemy import delete
                        await session.execute(delete(FactDB).where(FactDB.user_id == self.user_id, FactDB.source_file == orphan))
                    await session.commit()

                # Bump de facts_version no meta
                meta_stmt = select(MetaDB).where(MetaDB.key == f"facts_version_{self.user_id}")
                meta_res = await session.execute(meta_stmt)
                meta = meta_res.scalar_one_or_none()
                if meta:
                    meta.value = str(int(meta.value) + 1)
                else:
                    session.add(MetaDB(key=f"facts_version_{self.user_id}", value="1"))

                # Marca backfill_complete
                backfill_meta_stmt = select(MetaDB).where(MetaDB.key == f"backfill_complete_{self.user_id}")
                bm_res = await session.execute(backfill_meta_stmt)
                bm = bm_res.scalar_one_or_none()
                if bm:
                    bm.value = "true"
                else:
                    session.add(MetaDB(key=f"backfill_complete_{self.user_id}", value="true"))

                await session.commit()
            logger.info("✨ [Backfill] Reconciliação e versionamento concluídos com sucesso!")

        logger.info(f"🎉 [Backfill] Concluído! Total de fatos criados: {total_facts_created}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill de notas do Obsidian para o FactDB")
    parser.add_argument("--vault-path", default="Ollie", help="Caminho para o vault do Obsidian")
    parser.add_argument("--user-id", default="default", help="ID do usuário")
    parser.add_argument("--dry-run", action="store_true", help="Executa sem salvar no banco")
    parser.add_argument("--skip-pattern", default=None, help="Regex de arquivos para ignorar")
    
    args = parser.parse_args()
    
    orchestrator = BackfillOrchestrator(
        vault_path=args.vault_path,
        user_id=args.user_id,
        dry_run=args.dry_run,
        skip_pattern=args.skip_pattern
    )
    asyncio.run(orchestrator.run())
