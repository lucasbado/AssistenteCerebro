# Abertura automática e importância

## Causa

O celular tinha a abertura automática habilitada enquanto o servidor mostrava o
interruptor desligado. Rotinas ativas enviavam comandos diretamente, e o raciocínio
também podia mandar abrir um aplicativo ao interpretar uma notificação. A política
antiga de PC não verificava importância nem lista de permitidos e era perdida ao
reiniciar. No Android, quase toda mensagem de WhatsApp recebia importância alta.

## Comportamento corrigido

- Um pedido direto para abrir um aplicativo, por voz/chat ou pelo botão de uma
  notificação, continua independente da abertura automática.
- Inferências da IA sobre notificações externas geram sugestões com botão.
  A urgência atribuída pela IA não autoriza uma abertura.
- Rotinas aprovadas só abrem apps com o controle geral ligado, destino permitido
  e importância suficiente. Confiança estatística não representa permissão.
- Aprovar uma sugestão começa em **Só sugerir**, mesmo que a LLM tenha atribuído
  importância. Em Superpoderes, o usuário escolhe Só sugerir (0), Média (0,6) ou
  Alta (0,95). Alterar a importância mantém a rotina pausada quando já estava assim.
- Em Sistema, o usuário liga/desliga a abertura automática e escolhe os apps
  permitidos. A lista é compartilhada com o PC. Bloqueios do servidor prevalecem.
- O limite padrão do servidor é 0,85. No celular, o nível Alta exige pelo menos
  0,95; Média exige 0,6, sempre respeitando o limite maior do servidor. Só sugerir
  nunca autoriza execução, inclusive quando o limite global é zero.
- Há intervalo de dez minutos entre aberturas, uma hora para repetir o mesmo
  aplicativo/dispositivo e teto de três aberturas por hora no servidor. O celular
  também guarda intervalos e IDs processados para evitar replays.
- Sequências com várias aberturas automáticas viram sugestão antes de reservar
  a cota. Um destino PC já em primeiro plano não gasta a cota nem gera sugestão.
- O nível de importância filtra os avisos proativos entregues, além dos eventos
  coletados. Respostas solicitadas no chat continuam disponíveis. Promoções com
  termos financeiros ficam baixas; mensagens comuns ficam médias; chamadas,
  transações confirmadas e alertas de segurança podem ser altas.

A classificação é determinística por categoria e texto; mensagens pessoais
urgentes sem esses sinais ainda podem ficar médias. Não há interpretação perfeita
da importância subjetiva de cada contato.

## Persistência e atualização

`politica_intervencao` mantém política e histórico de aberturas no mesmo banco
configurado por `DATABASE_URL`. A inicialização de `main:app` cria a tabela.
Não apague nem reimporte o catálogo de rotinas já implantado.

Os endpoints `/api/v1/pc/intervention/policy` e a apresentação das rotinas retornam
`controle_abertura_version: 1`. O APK impede ativar os controles novos contra um
servidor anterior. Comandos antigos sem autorização explícita viram sugestão no
celular, mesmo se uma preferência antiga estivesse ligada.

O backend precisa do **deploy manual no Render**. Antes dele, pedidos de abertura
enviados pelo servidor antigo também podem virar sugestão com botão, pois não
contêm a identificação nova de pedido explícito. Voz e chat continuam disponíveis.
Depois do deploy, atualize a tela de Superpoderes e reabra Sistema. A abertura
automática começa desligada; escolha importância e apps antes de habilitá-la.

## Validação

145 testes Python e 40 testes Android passaram. APK compilado e instalado no
celular conectado. A build web do desktop também passou após preservar a exceção
para pedidos explícitos enviados pela voz. O executável desktop não foi reinstalado.

Testes isolados cobrem a rotina celular banco → Instagram, bloqueio geral,
importância, lista exata, persistência após reinício, intervalos, replays,
aprovação sem autorização implícita, preservação de pausa e comandos de voz.
A consulta final do celular/Render fica em `.artifacts/teste-abertura-automatica.json`,
sem tokens ou conteúdo de notificações. A execução integrada com a política nova
no Render depende do deploy manual.

## Link de vídeo recebido no WhatsApp

Receber uma mensagem com vídeo do TikTok não é um pedido para abrir o TikTok.
O serviço `links_notificacao` usa somente texto e mensagens do evento atual,
incluindo o agrupamento da memória de trabalho. Um único link compatível gera
uma sugestão com `OPEN_URL` e a URL completa, preservando caminho, identificador,
query e fragmento. Não abre o app automaticamente. Endereços de histórico e URLs
inventadas pela LLM não são usados como destino.

Quando há vários links compatíveis ou nenhum endereço verificável, o botão
**Ver mensagem** abre o aplicativo de origem para o usuário escolher. Não promete
abrir a conversa exata. A ação Android para links usa o endereço original; sua
associação com navegador ou app é feita pelo sistema.

Notificações repetidas geram a mesma chave de sugestão para o mesmo destino,
independentemente do texto produzido pela IA, e respeitam a deduplicação de uma
hora e o orçamento de avisos existente. Não se promete silenciar indefinidamente
uma mensagem ainda pendente. `SUGERIR` oferece botão sem executar; `IGNORAR` não
executa nem sugere comandos. Este complemento altera apenas o backend e entra
no mesmo deploy manual pendente; não precisa de outro APK.
