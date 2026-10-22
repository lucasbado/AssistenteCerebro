# Comandos por origem e respostas no PC

## Como usar

| Onde você fez o pedido | Pedido | Onde executar | Onde responder |
| --- | --- | --- | --- |
| PC | Abrir YouTube | PC, no navegador | PC, com voz habilitada |
| Celular | Abrir YouTube | Aplicativo do celular | Celular |
| PC | Abrir YouTube no celular | Celular | PC |
| Celular | Abrir YouTube no PC | PC, no navegador | Celular |

O destino explícito prevalece; sem ele, aberturas de apps, URLs e buscas usam o
dispositivo de origem. A escolha da LLM não altera essa regra. Pedidos simples
para YouTube, Spotify, WhatsApp, Telegram, Instagram, TikTok e Chrome podem ser
interpretados sem LLM. A mesma capacidade recebe um comando apropriado ao destino:
YouTube vira URL no PC e pacote Android no celular. URLs completas continuam intactas.

Se o destino estiver offline, a Ollie responde na origem e não executa no outro
aparelho. Se a mesma etapa mencionar PC e celular como destinos, pede esclarecimento.
Pedidos compostos podem indicar um aparelho diferente em cada etapa:
[buscas e execução em sequência](pedidos-compostos-e-foco.md).
Aplicativos exclusivos de PC não são enviados ao Android como se estivessem
instalados nele. Recursos como Voicemeeter e cenários Python continuam específicos
do PC; luzes continuam usando o controlador da casa e uma ponte local disponível.

Abrir um app não muda o local da resposta. A confirmação da luz também volta ao
dispositivo que fez a pergunta, mesmo quando a ponte física foi o outro aparelho.
Mensagens de encaminhamento dizem que o pedido foi enviado; não afirmam que o
aplicativo foi visto na tela. Falhas locais retornam uma resposta de erro.

## Voz do PC

O app de PC lê respostas de seus próprios pedidos com **Thalita Neural**, em
português, pelo endpoint de voz que já atende o Android. O download usa o cliente
autenticado, sem token na URL. Quando o servidor não responde, devolve conteúdo
sem áudio ou a reprodução falha, usa a voz portuguesa instalada no Windows.
Não foi acrescentada API paga ou download de modelo. O botão de alto-falante no
cabeçalho do chat ativa/silencia a leitura e guarda a escolha. Silenciar interrompe
a leitura atual. A voz funciona também para respostas a mensagens digitadas.
O botão **Testar voz** permite ouvir uma frase sem enviar um comando à Ollie.
Silenciar também cancela downloads pendentes, para evitar uma fala atrasada.

A leitura exige correlação com um pedido recente desse desktop. Notificações
proativas, conversas iniciadas no celular e replays da mesma resposta não são
lidos pelo PC. Falha de voz mantém a resposta escrita e mostra aviso. Esta etapa
adiciona saída de voz; a entrada de comandos no desktop continua pelo chat. O
microfone e a sessão de assistente do Android continuam disponíveis.

## Implementação

`servicos/roteamento_pedidos.py` resolve origem, destino e tradução de comando.
As entradas HTTP/WebSocket registram `dispositivo_origem`, `canal_origem` e a
correlação nos eventos. O WebSocket usa a identidade do cliente registrado. Esses
metadados acompanham as derivações, incluindo respostas e erros.

`AgenteRaciocinio` aplica o destino antes de emitir comandos; `AgentePcExecutor`
continua executando o lado PC. O transporte móvel passa a enviar diretamente ao
celular, sem broadcast de comandos. Respostas de chat têm destino exclusivo e
não caem em outro dispositivo quando o cliente de origem desconecta. O kernel
permanece apenas como barramento, sem regras de roteamento.

No desktop, `DesktopReplies` verifica correlação e replays. `DesktopVoice` gerencia
download, reprodução MP3, cancelamento e fallback. Arquivos em memória são
liberados quando a fala termina ou é cancelada. Uma nova resposta cancela a
anterior. O módulo nativo `desktop_voice.rs` oferece SAPI do Windows como
alternativa em processo oculto. O texto
é JSON na entrada do processo, nunca código interpolado. A leitura usa texto
simples; marcações não são executadas como SSML ou comandos.

## Publicação e validação

O backend precisa do **deploy manual no Render** para usar as regras novas.
O app de PC em desenvolvimento recarregou com a implementação nativa; o APK
Android foi recompilado e atualizado com a identificação de voz/texto. Nenhuma
automação pessoal de HA/ESPHome foi alterada e nenhum deploy remoto foi executado.

Validação: 168 testes Python, 40 testes Android e oito testes do desktop.
TypeScript/Vite e `cargo check --offline` passaram. Os testes verificam os dois
sentidos de execução, destinos offline, modelos sugerindo o aparelho errado,
respostas na origem e preservação de correlação nas entradas HTTP/WebSocket.

A reprodução nativa da frase de teste terminou com código zero em 6,3 segundos;
relatório sem conteúdo pessoal: `.artifacts/teste-voz-pc.json`. O usuário confirmou
que ouviu a frase no PC. O fluxo integrado contra o backend novo no Render ainda
depende do deploy manual. Os testes de roteamento
usam transportes simulados e não abriram apps pessoais no PC ou celular.

A melhoria para voz neural usa o endpoint já publicado; não depende de outro
deploy para gerar áudio. O teste real recebeu MP3 de 29.232 bytes e reproduziu
4,872 segundos de Thalita Neural. O usuário confirmou que ouviu e gostou mais.
Relatório: `.artifacts/teste-voz-natural-pc.json`. Testes adicionais cobrem voz
neural, fallback local, cancelamento durante download/reprodução e troca de
resposta sem fala atrasada. TypeScript/Vite passaram com essa alteração.
O executável do desktop foi recompilado com os arquivos novos incorporados e
reaberto; a melhoria não depende de manter um servidor Vite em execução.
