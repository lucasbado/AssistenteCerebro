"""Ferramentas de arquivos dentro das pastas pessoais do Windows."""
import json
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from servicos.controle_casa import normalizar


PASTAS = {'Downloads': 'Downloads', 'Documentos': 'Documents', 'Área de Trabalho': 'Desktop'}
PASTAS_CONHECIDAS = {'downloads': 'Downloads', 'download': 'Downloads', 'documentos': 'Documentos',
                     'documents': 'Documentos', 'area de trabalho': 'Área de Trabalho', 'desktop': 'Área de Trabalho'}
EXTENSOES = frozenset({'.pdf', '.txt', '.md', '.csv', '.docx', '.xlsx', '.pptx', '.odt', '.ods',
                       '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'})
OPERACOES_ARQUIVOS = {
    'criar_pasta': 'pasta_criada', 'copiar_arquivo': 'copiado', 'mover_arquivo': 'movido',
    'renomear_arquivo': 'renomeado', 'compactar_arquivo': 'compactado',
}
COMANDOS_ARQUIVOS = frozenset({'buscar_documentos', 'abrir_arquivo', 'listar_arquivos', 'capturar_tela'} | OPERACOES_ARQUIVOS.keys())
LIMITE_ITENS = 6
ESTADOS = {
    'buscar_documentos': {'encontrado', 'nao_encontrado', 'incompleto'},
    'abrir_arquivo': {'janela_confirmada', 'abertura_enviada', 'ambiguo', 'nao_encontrado', 'incompleto'},
    'listar_arquivos': {'listado', 'incompleto'},
    'capturar_tela': {'capturado'},
    **{comando: {estado, 'destino_existe', 'origem_ausente'} for comando, estado in OPERACOES_ARQUIVOS.items()},
}


def pastas_pessoais():
    caminhos = {nome: Path.home() / subpasta for nome, subpasta in PASTAS.items()}
    if os.name == 'nt':
        import winreg

        nomes_registro = {'Downloads': '{374DE290-123F-4565-9164-39C4925E467B}',
                          'Documentos': 'Personal', 'Área de Trabalho': 'Desktop'}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as chave:
                for nome, campo in nomes_registro.items():
                    try:
                        valor = Path(os.path.expandvars(winreg.QueryValueEx(chave, campo)[0]))
                        if valor.is_absolute():
                            caminhos[nome] = valor
                    except OSError:
                        pass
        except OSError:
            pass
    return caminhos


def parametros_arquivo(comando, parametro):
    if isinstance(parametro, str):
        parametro = parametro.strip()
        parametro = (json.loads(parametro) if parametro.startswith('{') else
                     {('pasta' if comando in {'listar_arquivos', 'capturar_tela'} else 'nome'): parametro})
    if not isinstance(parametro, dict) or set(parametro) - {'nome', 'pasta', 'extensao'}:
        raise ValueError('Pedido de arquivo inválido.')
    nome = parametro.get('nome', '')
    pasta = parametro.get('pasta', '')
    extensao = parametro.get('extensao', '')
    if not all(isinstance(valor, str) for valor in (nome, pasta, extensao)):
        raise ValueError('Informe o nome e a pasta do arquivo em texto.')
    nome = nome.strip().replace('\\', '/')
    nome_path = PurePosixPath(nome)
    if (comando in {'abrir_arquivo', 'buscar_documentos'} and not any(c.isalnum() for c in nome)
            or len(nome) > 240 or nome_path.is_absolute()
            or '..' in nome_path.parts or any(c in nome for c in ':*?<>|"')
            or any(ord(c) < 32 for c in nome)):
        raise ValueError('Use o nome do arquivo ou um caminho relativo à pasta pessoal.')
    if pasta:
        pasta = PASTAS_CONHECIDAS.get(normalizar(pasta))
        if not pasta:
            raise ValueError('As pastas disponíveis são Downloads, Documentos e Área de Trabalho.')
    if len(nome_path.parts) > 1 and (pasta_no_nome := PASTAS_CONHECIDAS.get(normalizar(nome_path.parts[0]))):
        if pasta and pasta != pasta_no_nome:
            raise ValueError('O caminho e o nome da pasta indicam lugares diferentes.')
        pasta = pasta_no_nome
        nome = PurePosixPath(*nome_path.parts[1:]).as_posix()
    if comando == 'listar_arquivos' and not pasta:
        raise ValueError('Qual pasta devo listar: Downloads, Documentos ou Área de Trabalho?')
    extensao = extensao.casefold()
    if extensao and extensao not in EXTENSOES:
        raise ValueError('Tipo de documento indisponível.')
    return nome, pasta, extensao


def _resultado(estado, itens=()):
    return {'arquivo': {'estado': estado, 'itens': list(itens)[:LIMITE_ITENS]}}


def validar_resultado_arquivo(comando, dados):
    if comando not in ESTADOS or not isinstance(dados, dict) or set(dados) != {'arquivo'}:
        return False
    arquivo = dados['arquivo']
    if not isinstance(arquivo, dict) or set(arquivo) != {'estado', 'itens'}:
        return False
    estado, itens = arquivo['estado'], arquivo['itens']
    if (not isinstance(estado, str) or estado not in ESTADOS[comando] or not isinstance(itens, list)
            or len(itens) > LIMITE_ITENS):
        return False
    if estado in {'abertura_enviada', 'janela_confirmada', 'capturado', 'destino_existe', *OPERACOES_ARQUIVOS.values()} and len(itens) != 1:
        return False
    if estado == 'origem_ausente' and itens:
        return False
    if estado == 'ambiguo' and len(itens) < 2 or estado == 'encontrado' and not itens:
        return False
    return all(isinstance(item, str) and 0 < len(item) <= 350 and ':' not in item and '\\' not in item
               and all(ord(c) >= 32 for c in item) and '..' not in PurePosixPath(item).parts
               and item.split('/', 1)[0] in PASTAS and '/' in item for item in itens)


def _seguro(info):
    return not (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def parametros_operacao(comando, parametro):
    dados = json.loads(parametro) if isinstance(parametro, str) else parametro
    chaves = {'nome', 'pasta'}
    if comando in {'copiar_arquivo', 'mover_arquivo'}:
        chaves.add('pasta_destino')
    elif comando == 'renomear_arquivo':
        chaves.add('novo_nome')
    if not isinstance(dados, dict) or set(dados) != chaves:
        raise ValueError('Indique o nome exato e as pastas da operação.')
    nome, pasta, _ = parametros_arquivo('abrir_arquivo', {'nome': dados['nome'], 'pasta': dados['pasta']})
    if not pasta:
        raise ValueError('Indique Downloads, Documentos ou Área de Trabalho.')
    novo_nome, pasta_destino = '', ''
    if 'pasta_destino' in dados:
        _, pasta_destino, _ = parametros_arquivo('listar_arquivos', {'pasta': dados['pasta_destino']})
    if 'novo_nome' in dados:
        novo_nome, _, _ = parametros_arquivo('abrir_arquivo', {'nome': dados['novo_nome']})
        if '/' in novo_nome:
            raise ValueError('Para renomear, diga apenas o novo nome do arquivo.')
    return nome, pasta, novo_nome, pasta_destino


def _caminho_operacao(raiz, nome):
    raiz = raiz.resolve(strict=True)
    partes = PurePosixPath(nome).parts
    atual = raiz
    for indice, parte in enumerate(partes):
        if parte.endswith((' ', '.')) or re.fullmatch(r'(?:con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(?:\..*)?', parte, re.I):
            raise ValueError('O nome contém um componente reservado pelo Windows.')
        atual /= parte
        try:
            info = atual.lstat()
        except FileNotFoundError:
            if indice != len(partes) - 1:
                raise
        else:
            if not _seguro(info):
                raise ValueError('A operação não segue atalhos ou links de arquivos.')
    return atual


def _gravar_sem_sobrescrever(origem, destino, compactar, info):
    # Publique somente um arquivo completo. O link falha se outro processo já criou o destino.
    with tempfile.NamedTemporaryFile(dir=destino.parent, prefix='.ollie-', delete=False) as temporario:
        provisoria = Path(temporario.name)
    try:
        with origem.open('rb') as entrada:
            atual = os.fstat(entrada.fileno())
            if not os.path.samestat(info, atual) or atual.st_size != info.st_size:
                raise ValueError('O arquivo de origem mudou durante a operação.')
            if compactar:
                with zipfile.ZipFile(provisoria, 'w', compression=zipfile.ZIP_DEFLATED) as arquivo:
                    with arquivo.open(origem.name, 'w') as saida:
                        shutil.copyfileobj(entrada, saida)
            else:
                with provisoria.open('wb') as saida:
                    shutil.copyfileobj(entrada, saida)
            if entrada.tell() != info.st_size or os.fstat(entrada.fileno()).st_mtime_ns != info.st_mtime_ns:
                raise ValueError('O arquivo de origem mudou durante a operação.')
        os.link(provisoria, destino)
    finally:
        provisoria.unlink(missing_ok=True)


def _executar_operacao(comando, parametro, raizes):
    nome, pasta, novo_nome, pasta_destino = parametros_operacao(comando, parametro)
    origem = _caminho_operacao(raizes[pasta], nome)
    if comando == 'criar_pasta':
        destino, rotulo, relativo = origem, pasta, nome
    else:
        try:
            info = origem.lstat()
        except FileNotFoundError:
            return _resultado('origem_ausente')
        if not stat.S_ISREG(info.st_mode) or not _seguro(info):
            raise ValueError('Selecione um arquivo comum para esta operação.')
        rotulo = pasta_destino or pasta
        base = PurePosixPath(nome)
        if pasta_destino:
            relativo = base.name
        elif comando == 'compactar_arquivo':
            relativo = base.with_name(base.name + '.zip').as_posix()
        else:
            relativo = base.with_name(novo_nome).as_posix()
        destino = _caminho_operacao(raizes[rotulo], relativo)
    exibido = f'{rotulo}/{relativo}'
    try:
        if comando == 'criar_pasta':
            destino.mkdir()
        elif comando in {'copiar_arquivo', 'compactar_arquivo'}:
            if info.st_size > 64 * 1024 * 1024:
                raise ValueError('Esta operação aceita arquivos de até 64 MB.')
            _gravar_sem_sobrescrever(origem, destino, comando == 'compactar_arquivo', info)
        else:
            if os.name != 'nt':
                raise ValueError('Mover e renomear são operações do executor Windows.')
            if origem == destino:
                raise FileExistsError(destino)
            os.rename(origem, destino)  # No Windows, falha se o destino existir.
    except FileExistsError:
        return _resultado('destino_existe', [exibido])
    return _resultado(OPERACOES_ARQUIVOS[comando], [exibido])


def _pontuar(nome, relativo):
    consulta = normalizar(nome)
    if '/' in nome:
        return 3 if normalizar(relativo.as_posix()) == consulta else 0
    if normalizar(relativo.name) == consulta:
        return 3
    if normalizar(relativo.stem) == consulta:
        return 2
    palavras = set(re.findall(r'[^\W_]+', normalizar(relativo.stem)))
    termos = set(re.findall(r'[^\W_]+', consulta)) - {'o', 'a', 'os', 'as', 'de', 'do', 'da', 'dos', 'das'}
    return 1 if termos and termos <= palavras else 0


def executar_arquivo(comando, parametro, service, pastas=None):
    raizes = pastas if pastas is not None else pastas_pessoais()
    if comando in OPERACOES_ARQUIVOS:
        return _executar_operacao(comando, parametro, raizes)
    nome, pasta, extensao = parametros_arquivo(comando, parametro)
    if comando == 'capturar_tela':
        pasta = pasta or 'Downloads'
        destino = raizes[pasta].resolve(strict=True) / f'Ollie-captura-{uuid.uuid4().hex[:12]}.png'
        imagem = service.capturar_tela()
        with destino.open('xb') as saida:
            try:
                imagem.save(saida, format='PNG')
            except Exception:
                saida.close()
                destino.unlink(missing_ok=True)
                raise
        return _resultado('capturado', [f'{pasta}/{destino.name}'])
    limite = time.monotonic() + 3.0
    visitados, melhores, pontuacao = 0, [], 0
    lista = comando == 'listar_arquivos'
    completo = True
    for rotulo in ([pasta] if pasta else PASTAS):
        raiz = raizes[rotulo]
        try:
            raiz = raiz.resolve(strict=True)
        except (OSError, RuntimeError):
            completo = False if pasta else completo
            continue
        pendentes = [raiz]
        while pendentes:
            diretorio = pendentes.pop()
            try:
                with os.scandir(diretorio) as entradas:
                    for entrada in entradas:
                        visitados += 1
                        if visitados > 25_000 or time.monotonic() >= limite:
                            return _resultado('incompleto', [item[0] for item in melhores])
                        info = entrada.stat(follow_symlinks=False)
                        if not _seguro(info):
                            continue
                        caminho = Path(entrada.path)
                        if stat.S_ISDIR(info.st_mode) and not lista:
                            pendentes.append(caminho)
                        if not stat.S_ISREG(info.st_mode) and not (comando == 'buscar_documentos' and stat.S_ISDIR(info.st_mode)):
                            continue
                        if comando == 'abrir_arquivo' and caminho.suffix.casefold() not in EXTENSOES:
                            continue
                        if extensao and caminho.suffix.casefold() != extensao:
                            continue
                        relativo = caminho.relative_to(raiz)
                        nota = 1 if lista else _pontuar(nome, relativo)
                        exibido = f'{rotulo}/{relativo.as_posix()}'
                        if nota and len(exibido) <= 350 and all(ord(c) >= 32 for c in exibido):
                            if nota > pontuacao:
                                melhores, pontuacao = [], nota
                            if nota == pontuacao and len(melhores) < LIMITE_ITENS:
                                melhores.append((exibido, caminho))
                            if lista and len(melhores) == LIMITE_ITENS:
                                return _resultado('listado', sorted(item[0] for item in melhores))
            except OSError:
                completo = False
    itens = sorted(item[0] for item in melhores)
    if not completo:
        return _resultado('incompleto', itens)
    if lista:
        return _resultado('listado', itens)
    if not itens:
        return _resultado('nao_encontrado')
    if comando == 'buscar_documentos':
        return _resultado('encontrado', itens)
    if len(itens) > 1:
        return _resultado('ambiguo', itens)
    caminho = melhores[0][1]
    info = caminho.lstat()
    if caminho.resolve(strict=True) != caminho or not _seguro(info) or not stat.S_ISREG(info.st_mode):
        raise ValueError('O arquivo mudou durante a busca.')
    confirmado = service.abrir_documento_verificado(caminho)
    return _resultado('janela_confirmada' if confirmado else 'abertura_enviada', itens)
