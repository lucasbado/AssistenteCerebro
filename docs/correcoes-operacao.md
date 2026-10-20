# Configuração e validação das correções

## Autenticação

Configure `OLLIE_API_TOKEN` com o mesmo segredo no ambiente do servidor e no
arquivo `.env` do backend usado pelo desktop. Gere um valor hexadecimal com:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Não existe token padrão. Sem configuração, endpoints protegidos retornam 503;
tokens incorretos retornam 401. WebSockets não autorizados são recusados.
A raiz e o health check permanecem públicos.

Clientes HTTP, incluindo Android, devem enviar `Authorization: Bearer <token>`.
O desktop envia o segredo no subprotocolo WebSocket `bearer.<token>` junto de
`ollie`; clientes nativos também podem usar o header Authorization.
A query `?token=<token>` é aceita para compatibilidade, mas pode aparecer nos
logs de acesso do servidor. Não coloque tokens no código ou no controle de versão.
O código Android não está neste repositório e deve ser adaptado antes do uso
com este servidor autenticado.

## Desktop e comandos

O Tauri chama `scripts/pc_command.py` com argumentos separados, sem interpolar
parâmetros em código e sem executar comandos desconhecidos no shell.
Falhas no processo Python são retornadas à interface.
O chat usa `tipo_ws: CHAT_MESSAGE`, `texto` e `pacote: pc.chat`.
O botão de reconexão reutiliza o ciclo de vida da conexão atual.

`OLLIE_BACKEND_DIR` permite escolher a pasta do backend e `OLLIE_PYTHON` permite
escolher o interpretador. Em desenvolvimento, a pasta é inferida a partir do
projeto Rust. Em outra máquina, configure essas variáveis e disponibilize o
backend, suas dependências e o script da ponte.

## Banco, eventos e fila

O banco usa somente a URL configurada. Falhas de conexão interrompem o startup
em vez de trocar silenciosamente o banco remoto por um SQLite vazio.
Na ausência de DATABASE_URL, o SQLite fica na raiz do projeto.
As colunas source_file, source_hash e locked_until são verificadas e adicionadas
antes da criação das tabelas. A inicialização é repetível.
FTS5 é inicializado pela conexão assíncrona; sqlite-vec é opcional e sua ausência
é registrada. Tarefas de embedding usam Ollama (`nomic-embed-text`, 768 dimensões).
Configure `OLLAMA_EMBED_URL` e `OLLAMA_EMBED_MODEL` para mudar esse serviço.
Sem o modelo/serviço disponível, as tarefas recebem tentativas e podem chegar a
`dead`, sem serem marcadas indevidamente como concluídas.

O worker usa uma reserva de cinco minutos e limita cada execução a dois minutos.
Reservas expiradas são recuperadas. O processamento admite repetição após falhas;
ações de tarefas devem permanecer idempotentes.

Eventos e suas coleções JSON são imutáveis. Use `clonar()` para produzir um novo
evento. O kernel respeita a prioridade definida pelo produtor, limita eventos
concorrentes e contabiliza erros dos listeners separadamente. O encerramento
cancela e aguarda as tarefas antes de fechar o banco.

## Modelos da Groq e respostas do chat

O backend começa por `openai/gpt-oss-120b`, com fallback para
`openai/gpt-oss-20b`. Os modelos Llama antigos deixaram de estar disponíveis para
planos free/developer em 16/08/2026, conforme o
[aviso oficial da Groq](https://console.groq.com/docs/deprecations).

Para escolher a ordem no ambiente do Render, configure opcionalmente:

```dotenv
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODELS=openai/gpt-oss-20b
```

O segundo campo aceita modelos separados por vírgula. Vazio desativa fallbacks.
Os valores padrão já são usados quando essas variáveis não existem. Não altere
`GROQ_API_KEY` nem `OLLIE_API_TOKEN` para resolver um `model_not_found`.

Erros 404/modelo indisponível não são repetidos sem `response_format`; o modelo
fica fora das tentativas por uma hora naquela instância. Só uma recusa explícita
do formato `json_object` permite nova tentativa sem esse parâmetro, mantendo a
instrução JSON no prompt. Erros de chave/autenticação não percorrem a lista inteira.
Retentativas automáticas do SDK foram desativadas para não multiplicar a cadeia.

O chat Android agora usa `RetrofitClient.backendHttpClient`, assim como os sensores
e o WebSocket. Antes, seu cliente separado não enviava o token em `POST /eventos`,
mesmo quando o listener já estava conectado. A interface passa a diferenciar
mensagem aceita de respostas 401/403 e outros erros HTTP, encerrando o indicador
de espera na recusa. O envio inclui um pacote de chat e usa a URL atual do servidor.

Foram executados 52 testes Python e 13 testes unitários Android. Os testes de
modelos simulam a Groq; não fizeram inferências pagas nem comprovam disponibilidade
futura de um modelo na conta. O APK corrigido foi compilado e atualizado no celular
conectado. A mudança de modelos precisa de um novo deploy do backend no Render.

## Verificação local

```powershell
.\.venvs\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

```powershell
cd ollie-master-next
npm.cmd run build
cd src-tauri
cargo check --offline
```

Os testes usam SQLite temporário e simulam LLM e hardware. Eles não executam
comandos reais no PC nem alteram o banco pessoal. O contrato externo da timeline
mantém o campo `events` já definido no DTO.
