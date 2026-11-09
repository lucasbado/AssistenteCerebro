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
from contextlib import contextmanager
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
    'prever_organizacao': 'previa_organizacao', 'organizar_pasta': 'organizado',
    'desfazer_organizacao': 'desfeito', 'lixeira_arquivo': 'na_lixeira', 'restaurar_lixeira': 'restaurado',
    'criar_arquivo': 'arquivo_criado', 'ler_arquivo': 'lido', 'acrescentar_texto': 'texto_acrescentado',
}
COMANDOS_ORGANIZACAO = {'prever_organizacao', 'organizar_pasta', 'desfazer_organizacao'}
COMANDOS_TEXTO = {'criar_arquivo', 'ler_arquivo', 'acrescentar_texto'}
EXTENSOES_TEXTO = {'.txt', '.md', '.csv'}
LIMITE_TEXTO = 1200
LIMITE_EDICAO = 256 * 1024
COMANDOS_ARQUIVOS = frozenset({'buscar_documentos', 'abrir_arquivo', 'listar_arquivos', 'capturar_tela'} | OPERACOES_ARQUIVOS.keys())
LIMITE_ITENS = 6
ESTADOS = {
    'buscar_documentos': {'encontrado', 'nao_encontrado', 'incompleto'},
    'abrir_arquivo': {'janela_confirmada', 'abertura_enviada', 'ambiguo', 'nao_encontrado', 'incompleto'},
    'listar_arquivos': {'listado', 'incompleto'},
    'capturar_tela': {'capturado'},
    **{comando: {estado, 'destino_existe', 'origem_ausente'} for comando, estado in OPERACOES_ARQUIVOS.items()},
    'prever_organizacao': {'previa_organizacao', 'organizacao_sem_itens'},
    'organizar_pasta': {'organizado', 'organizacao_parcial', 'organizacao_sem_previa', 'previa_desatualizada'},
    'desfazer_organizacao': {'desfeito', 'desfeito_parcial', 'sem_organizacao'},
    'restaurar_lixeira': {'restaurado', 'destino_existe', 'sem_item_lixeira', 'restauro_nao_confirmado'},
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
    if not isinstance(arquivo, dict):
        return False
    campos = {'estado', 'itens'}
    if comando == 'ler_arquivo' and arquivo.get('estado') == 'lido':
        campos |= {'texto', 'parcial'}
        if (not isinstance(arquivo.get('texto'), str) or not isinstance(arquivo.get('parcial'), bool)
                or len(arquivo['texto']) > LIMITE_TEXTO or '\x00' in arquivo['texto']):
            return False
    if set(arquivo) != campos:
        return False
    estado, itens = arquivo['estado'], arquivo['itens']
    if (not isinstance(estado, str) or estado not in ESTADOS[comando] or not isinstance(itens, list)
            or len(itens) > LIMITE_ITENS):
        return False
    estados_unicos = {estado for cmd, estado in OPERACOES_ARQUIVOS.items() if cmd not in COMANDOS_ORGANIZACAO}
    if estado in {'abertura_enviada', 'janela_confirmada', 'capturado', 'destino_existe', *estados_unicos} and len(itens) != 1:
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
    if comando in COMANDOS_ORGANIZACAO:
        if not isinstance(dados, dict) or set(dados) != {'pasta'}:
            raise ValueError('Indique a pasta da organização.')
        return parametros_arquivo('listar_arquivos', dados)
    if comando in COMANDOS_TEXTO:
        return _parametros_texto(comando, dados)
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
    return PurePosixPath(nome).as_posix(), pasta, novo_nome, pasta_destino


def _parametros_texto(comando, dados):
    campos = {'nome', 'pasta'} if comando == 'ler_arquivo' else {'nome', 'pasta', 'texto'}
    if not isinstance(dados, dict) or set(dados) != campos:
        raise ValueError('Indique o nome do arquivo e a pasta.')
    nome, pasta, _ = parametros_arquivo('abrir_arquivo', {'nome': dados['nome'], 'pasta': dados['pasta']})
    texto = dados.get('texto', '')
    if not pasta or PurePosixPath(nome).suffix.casefold() not in EXTENSOES_TEXTO:
        raise ValueError('Indique Downloads, Documentos ou Área de Trabalho e um arquivo .txt, .md ou .csv.')
    if (not isinstance(texto, str) or len(texto) > LIMITE_TEXTO or '\x00' in texto
            or (comando == 'acrescentar_texto' and not texto.strip())):
        raise ValueError('Informe o texto a gravar com até 1200 caracteres.')
    return PurePosixPath(nome).as_posix(), pasta, texto


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


@contextmanager
def _travar_texto(arquivo):
    if os.name == 'nt':
        import msvcrt

        msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, LIMITE_EDICAO + 1)
    else:
        import fcntl

        fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    yield  # Fechar o arquivo libera a trava.


def _executar_texto(comando, parametro, raizes):
    nome, pasta, texto = parametros_operacao(comando, parametro)
    caminho = _caminho_operacao(raizes[pasta], nome)
    exibido = [f'{pasta}/{nome}']
    if comando == 'criar_arquivo':
        try:
            with tempfile.NamedTemporaryFile(dir=caminho.parent, prefix='.ollie-', delete=False) as arquivo:
                provisoria = Path(arquivo.name)
            try:
                provisoria.write_bytes(texto.encode('utf-8'))
                os.link(provisoria, caminho)
            finally:
                provisoria.unlink(missing_ok=True)
        except FileExistsError:
            return _resultado('destino_existe', exibido)
        return _resultado('arquivo_criado', exibido)
    try:
        info = caminho.lstat()
    except FileNotFoundError:
        return _resultado('origem_ausente')
    if not stat.S_ISREG(info.st_mode) or not _seguro(info):
        raise ValueError('Selecione um arquivo de texto comum.')
    with caminho.open('rb' if comando == 'ler_arquivo' else 'r+b', buffering=0) as arquivo:
        if not os.path.samestat(info, os.fstat(arquivo.fileno())):
            raise ValueError('O arquivo mudou durante a operação.')
        if comando == 'ler_arquivo':
            # O decodificador incremental ignora somente um caractere cortado no limite de bytes.
            import codecs

            dados = arquivo.read(4 * (LIMITE_TEXTO + 1) + 3)
            trecho = codecs.getincrementaldecoder('utf-8-sig')().decode(dados, final=len(dados) < 4 * (LIMITE_TEXTO + 1) + 3)
            if '\x00' in trecho:
                raise ValueError('O arquivo não contém texto UTF-8.')
            resultado = _resultado('lido', exibido)
            resultado['arquivo'].update(texto=trecho[:LIMITE_TEXTO], parcial=len(trecho) > LIMITE_TEXTO)
            return resultado
        with _travar_texto(arquivo):
            dados = arquivo.read(LIMITE_EDICAO + 1)
            if len(dados) > LIMITE_EDICAO or b'\x00' in dados:
                raise ValueError('A edição exige um arquivo de texto de até 256 KB.')
            dados.decode('utf-8-sig')
            quebra = '\r\n' if b'\r\n' in dados else '\n'
            separador = quebra if dados.removeprefix(b'\xef\xbb\xbf') and not dados.endswith((b'\n', b'\r')) else ''
            acrescimo = (separador + texto).encode('utf-8')
            if len(dados) + len(acrescimo) > LIMITE_EDICAO:
                raise ValueError('O arquivo ultrapassaria 256 KB.')
            if arquivo.write(acrescimo) != len(acrescimo):
                arquivo.truncate(len(dados))
                raise OSError('O texto foi gravado apenas em parte.')
    return _resultado('texto_acrescentado', exibido)


def _executar_operacao(comando, parametro, raizes):
    if comando in COMANDOS_TEXTO:
        return _executar_texto(comando, parametro, raizes)
    if comando in COMANDOS_ORGANIZACAO:
        from servicos.organizacao_pc import executar_organizacao

        _, pasta, _ = parametros_operacao(comando, parametro)
        return executar_organizacao(comando, raizes[pasta], pasta)
    nome, pasta, novo_nome, pasta_destino = parametros_operacao(comando, parametro)
    if comando in {'lixeira_arquivo', 'restaurar_lixeira'}:
        from servicos.lixeira_pc import executar_lixeira

        return executar_lixeira(comando, raizes[pasta], pasta, nome)
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
