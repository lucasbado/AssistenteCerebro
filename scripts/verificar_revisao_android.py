"""Verifica recursos e vocabulário da revisão; não substitui compilação ou teste no aparelho."""
import argparse
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument("--projeto", type=Path, default=Path(r"D:\Programacao\Projetos\AssistenteCell"))
args = parser.parse_args()
revision = Path(__file__).resolve().parents[1] / ".artifacts/android-review/revised"
resources = revision / "app/src/main/res"
xml_files = [resources / "layout/layout_ollie_voice_session.xml", *resources.glob("drawable/*ollie*.xml")]
for path in xml_files:
    ET.parse(path)
layout = xml_files[0].read_text(encoding="utf-8")
ids = set(re.findall(r'@\+id/(\w+)', layout))
session = (revision / "app/src/main/java/com/example/assistentecell/assistant/OllieSession.kt").read_text(encoding="utf-8")
missing = set(re.findall(r'R\.id\.(\w+)', session)) - ids
if missing:
    raise ValueError(f"IDs ausentes no dock: {sorted(missing)}")
policy = (revision / "app/src/main/java/com/example/assistentecell/voice/WakeWordPolicy.kt").read_text(encoding="utf-8")
grammar = json.loads("[" + re.search(r'val grammar = listOf\((.*?)\)', policy).group(1) + "]")
fst = (args.projeto / "app/src/main/assets/model/vosk-model-small-pt-0.3/Gr.fst").read_bytes()
words = set(" ".join(grammar).split())
unknown = [w for w in sorted(words) if struct.pack("<I", len(w.encode())) + w.encode() not in fst]
if unknown:
    raise ValueError(f"Palavras fora do vocabulário do modelo: {unknown}")
report = {"xml_validos": len(xml_files), "ids_do_dock_validados": len(ids),
          "frases_da_gramatica": len(grammar), "palavras_fora_do_modelo": unknown,
          "observacao": "Compilação Android e teste auditivo ainda são necessários."}
print(json.dumps(report, ensure_ascii=True, indent=2))
(revision.parent / "validacao-recursos-voz.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
