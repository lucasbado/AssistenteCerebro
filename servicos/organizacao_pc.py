"""Organização local com prévia persistente e volta dos arquivos sem sobrescrita."""
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from servicos.arquivos_pc import LIMITE_ITENS, _caminho_operacao, _resultado, _seguro, parametros_arquivo


CATEGORIAS = {
    **dict.fromkeys(('.pdf', '.txt', '.doc', '.docx', '.md', '.odt'), 'Textos'),
    **dict.fromkeys(('.csv', '.xls', '.xlsx', '.ods'), 'Planilhas'),
    **dict.fromkeys(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'), 'Imagens'),
    **dict.fromkeys(('.mp4', '.mov', '.mkv', '.webm', '.avi'), 'Vídeos'),
    **dict.fromkeys(('.mp3', '.wav', '.m4a', '.ogg', '.flac'), 'Áudios'),
    **dict.fromkeys(('.zip', '.rar', '.7z', '.gz'), 'Compactados'),
    **dict.fromkeys(('.exe', '.msi', '.msix'), 'Instaladores'),
}


@contextmanager
def _bloquear(diario):
    import msvcrt

    diario.parent.mkdir(parents=True, exist_ok=True)
    with diario.with_suffix('.lock').open('a+b') as trava:
        trava.seek(0)
        msvcrt.locking(trava.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            trava.seek(0)
            msvcrt.locking(trava.fileno(), msvcrt.LK_UNLCK, 1)


def _salvar(diario, estado):
    temporario = diario.with_suffix('.tmp')
    with temporario.open('w', encoding='utf-8') as arquivo:
        json.dump(estado, arquivo, ensure_ascii=False)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    temporario.replace(diario)


def _identidade(caminho):
    try:
        info = caminho.lstat()
    except FileNotFoundError:
        return None
    if not _seguro(info) or not stat.S_ISREG(info.st_mode):
        return None
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def _movimentos(pasta, plano):
    for item in plano:
        nome, categoria, identidade = item['nome'], item['categoria'], item['identidade']
        validado, _, _ = parametros_arquivo('abrir_arquivo', {'nome': nome})
        if nome != validado or '/' in nome or categoria != CATEGORIAS.get(Path(nome).suffix.casefold()):
            raise ValueError('O registro da organização contém um caminho inválido.')
        origem = _caminho_operacao(pasta, nome)
        subpasta = _caminho_operacao(pasta, categoria)
        destino = _caminho_operacao(pasta, f'{categoria}/{nome}') if subpasta.exists() else subpasta / nome
        yield item, origem, destino, identidade


@contextmanager
def diario_da_pasta(pasta, rotulo, diario_dir=None):
    if os.name != 'nt':
        raise ValueError('Esta operação exige o executor Windows.')
    pasta = pasta.resolve(strict=True)
    if diario_dir is None:
        diario_dir = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'Ollie' / 'arquivos'
    diario = diario_dir / f'{rotulo}.json'
    with _bloquear(diario):
        estado = json.loads(diario.read_text(encoding='utf-8')) if diario.is_file() else {}
        if estado.get('raiz') != str(pasta):
            estado = {'raiz': str(pasta)}
        yield diario, estado


def executar_organizacao(comando, pasta, rotulo, diario_dir=None):
    pasta = pasta.resolve(strict=True)
    with diario_da_pasta(pasta, rotulo, diario_dir) as (diario, estado):
        if comando == 'prever_organizacao':
            plano = []
            with os.scandir(pasta) as itens:
                for indice, item in enumerate(itens):
                    if indice >= 25_000 or len(plano) == LIMITE_ITENS:
                        break
                    categoria = CATEGORIAS.get(Path(item.name).suffix.casefold())
                    if not categoria or item.name.startswith('.'):
                        continue
                    try:
                        parametros_arquivo('abrir_arquivo', {'nome': item.name})
                        origem = _caminho_operacao(pasta, item.name)
                        identidade = _identidade(origem)
                        subpasta = _caminho_operacao(pasta, categoria)
                        destino = subpasta / item.name
                        if identidade and (not subpasta.exists() or subpasta.is_dir()) and not os.path.lexists(destino):
                            plano.append({'nome': item.name, 'categoria': categoria, 'identidade': identidade})
                    except (OSError, ValueError):
                        continue
            estado['previa'] = plano
            _salvar(diario, estado)
            return _resultado('previa_organizacao' if plano else 'organizacao_sem_itens',
                              [f'{rotulo}/{i["categoria"]}/{i["nome"]}' for i in plano])

        if comando == 'organizar_pasta':
            plano = estado.get('previa', [])
            if not plano:
                return _resultado('organizacao_sem_previa')
            movimentos = list(_movimentos(pasta, plano))
            if any(_identidade(origem) != identidade or os.path.lexists(destino)
                   for _, origem, destino, identidade in movimentos):
                estado.pop('previa')
                _salvar(diario, estado)
                return _resultado('previa_desatualizada')
            # Grave a intenção antes da primeira movimentação. Após interrupção, desfazer verifica cada arquivo.
            estado['ultima'] = plano
            estado.pop('previa')
            _salvar(diario, estado)
            movidos = []
            for item, origem, destino, identidade in movimentos:
                try:
                    destino.parent.mkdir(exist_ok=True)
                    _caminho_operacao(pasta, f'{item["categoria"]}/{item["nome"]}')
                    if _identidade(origem) != identidade:
                        break
                    os.rename(origem, destino)
                except (OSError, ValueError):
                    break
                movidos.append(f'{rotulo}/{item["categoria"]}/{item["nome"]}')
            return _resultado('organizado' if len(movidos) == len(plano) else 'organizacao_parcial', movidos)

        plano = estado.get('ultima', [])
        if not plano:
            return _resultado('sem_organizacao')
        pendentes, restaurados = [], []
        for item in plano:
            try:
                _, origem, destino, identidade = next(_movimentos(pasta, [item]))
                if _identidade(origem) == identidade and not os.path.lexists(destino):
                    continue
                if os.path.lexists(origem) or _identidade(destino) != identidade:
                    pendentes.append(item)
                    continue
                os.rename(destino, origem)
            except (OSError, ValueError):
                pendentes.append(item)
                continue
            restaurados.append(f'{rotulo}/{item["nome"]}')
        estado['ultima'] = pendentes
        _salvar(diario, estado)
        return _resultado('desfeito_parcial' if pendentes else 'desfeito', restaurados)
