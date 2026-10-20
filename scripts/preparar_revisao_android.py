"""Prepara e aplica alterações revisáveis no cliente, preservando edições existentes."""
import hashlib
import difflib
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(r"D:\Programacao\Projetos\AssistenteCell")
STAGE = Path(__file__).resolve().parent.parent / ".artifacts" / "android-review"
SOURCE = Path("app/src/main/java/com/example/assistentecell")
FILES = [
    SOURCE / name for name in (
        "NotificationHandler.kt", "FeedbackReceiver.kt", "ListenerDeNotificacoes.kt",
        "AssistenteOverlayService.kt", "ContextSensorWorker.kt", "api/RetrofitClient.kt",
        "command/SystemCommandHandler.kt", "data/model/AlertaPayload.kt",
        "ui/screens/SettingsScreen.kt", "ui/viewmodel/AutomationViewModel.kt",
        "network/PCCommandSender.kt",
    )
] + [Path("app/src/main/AndroidManifest.xml")]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def prepare():
    manifest = {}
    for relative in FILES:
        original = PROJECT / relative
        manifest[relative.as_posix()] = digest(original)
        for directory in ("original", "revised"):
            destination = STAGE / directory / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
    (STAGE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Preparados {len(FILES)} arquivos; projeto Android ainda não alterado.")


def apply():
    manifest = json.loads((STAGE / "manifest.json").read_text(encoding="utf-8"))
    revised = STAGE / "revised"
    files = [p for p in revised.rglob("*") if p.is_file()]
    # Valida todos antes de alterar qualquer arquivo. Nenhuma edição posterior é perdida.
    for path in files:
        relative = path.relative_to(revised)
        destination = (PROJECT / relative).resolve()
        if PROJECT.resolve() not in destination.parents:
            raise RuntimeError(f"Destino fora do projeto: {destination}")
        expected = manifest.get(relative.as_posix())
        if digest(destination) != expected:
            raise RuntimeError(f"Arquivo mudou durante a revisão: {relative}")
    changed = 0
    for path in files:
        destination = PROJECT / path.relative_to(revised)
        if digest(destination) != digest(path):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            changed += 1
    print(f"Aplicados {changed} arquivos no cliente Android.")


def diff():
    patches = []
    revised = STAGE / "revised"
    for path in sorted(p for p in revised.rglob("*") if p.is_file()):
        relative = path.relative_to(revised)
        original = STAGE / "original" / relative
        before = original.read_text(encoding="utf-8").splitlines(keepends=True) if original.exists() else []
        after = path.read_text(encoding="utf-8").splitlines(keepends=True)
        patches.extend(difflib.unified_diff(before, after, fromfile="a/" + relative.as_posix(),
                                          tofile="b/" + relative.as_posix()))
    target = Path(__file__).resolve().parent.parent / "docs" / "patches" / "android-rotinas.patch"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(patches), encoding="utf-8")
    print(f"Patch pronto para revisão: {target}")


def checkpoint():
    """Atualiza a base de aplicação somente se o cliente corresponde à revisão anterior."""
    revised = STAGE / "revised"
    manifest = {}
    for path in (p for p in revised.rglob("*") if p.is_file()):
        relative = path.relative_to(revised)
        current = PROJECT / relative
        if digest(current) != digest(path):
            raise RuntimeError(f"Alteração externa detectada: {relative}")
        manifest[relative.as_posix()] = digest(current)
    (STAGE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    {"prepare": prepare, "apply": apply, "diff": diff, "checkpoint": checkpoint}[sys.argv[1]]()
