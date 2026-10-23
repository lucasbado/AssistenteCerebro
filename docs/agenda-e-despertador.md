# Agenda, datas importantes e despertador

A Ollie agora tem uma agenda compartilhada entre PC e celular. Um pedido direto
cria um item; datas encontradas em mensagens viram sugestões para revisar. O
despertador fica separado: a Ollie prepara os detalhes e oferece a abertura do
Relógio do Android, sem afirmar que o alarme foi ativado.

## Como usar

- “Me lembra de tomar remédio amanhã às 15h.”
- “Agende consulta dia 5 de novembro às 14h30.”
- “Guarda 10/11 como uma data importante.”
- “Me acorde amanhã às 7h.”
- “Qual minha agenda amanhã?”

Se faltar data, título ou horário de lembrete/despertador, ela pergunta. A resposta
seguinte completa o pedido no mesmo dispositivo por até dez minutos, inclusive
após reiniciar o servidor. “Cancelar” abandona esse pedido incompleto. Essa
continuação não transforma mensagens recebidas em confirmações do usuário.

Datas nas confirmações ganham destaque clicável e botão para abrir a agenda.
No PC, há a página **Agenda**. No celular, o ícone de agenda fica no topo da
**Conversa**. Nessas telas é possível criar itens, revisar sugestões e retirar
compromissos. O formulário permite escolher antecedência do aviso em minutos.

No celular, **Salvar no calendário** abre o aplicativo de calendário com título
e data preenchidos para conferir e salvar. Essa ação não pede acesso integral ao
calendário. É uma cópia, sem sincronização: retirar da Ollie não remove a entrada
salva no calendário.

## Mensagens e sugestões

Mensagens com data e sinais como consulta, reunião, aniversário, prazo ou
“importante” podem produzir uma sugestão. A notificação oferece **Revisar data**;
o usuário precisa salvar para ela entrar na agenda ativa. Mensagens com sinais
de cancelamento não são salvas automaticamente. As sugestões passam pelos
filtros de atenção e pelo orçamento atual de notificações, com deduplicação.
Essa extração não abre aplicativos nem configura alarmes por conta própria.

## Despertador

O estado **preparado** significa que os detalhes foram guardados na Ollie.
**Revisar no Relógio**, no celular, envia o horário e o título ao relógio instalado.
Confira o alarme nessa tela; a Ollie não recebe confirmação confiável da ativação.
Não há necessidade de instalar serviços pagos para isso.

O intent nativo representa a próxima ocorrência de um horário, não uma data
absoluta distante. O app verifica essa condição antes de encaminhar: um alarme
para semana que vem nunca pode ser convertido silenciosamente em amanhã.
Para datas distantes, mantenha o compromisso/lembrete na agenda e configure o
despertador no Relógio quando apropriado. Retirar o pedido da Ollie não desativa
alarmes já criados no Relógio.

Referências: [AlarmClock](https://developer.android.com/reference/android/provider/AlarmClock)
e [intents de calendário](https://developer.android.com/guide/components/intents-common#Calendar).

## Entrega dos lembretes

Um evento de relógio a cada 30 segundos consulta compromissos/lembretes
confirmados. O envio usa o celular conectado, com alternativa para o PC. Itens
sem conexão continuam pendentes, com janela de recuperação de uma hora após o
horário. O identificador estável evita empilhar cópias da mesma notificação no
cliente. Envio pelo WebSocket não comprova que o usuário viu ou ouviu o aviso.

Esses lembretes dependem do servidor ativo e de conexão; Render adormecido ou
rede indisponível podem atrasar ou impedir a entrega. Não substituem um
despertador local. Itens de dia inteiro não geram aviso em horário inventado.
No calendário do celular, confira também o lembrete nativo que deseja usar.

## Contrato e arquitetura

- `GET /api/v1/agenda`: próximos itens, incluindo sugestões.
- `GET /api/v1/agenda/{id}`: revisão de um item.
- `POST /api/v1/agenda`: cria compromisso, lembrete ou pedido de despertador.
- `PATCH /api/v1/agenda/{id}`: salva sugestão, conclui ou retira um item;
  aceita também `antecedencia_minutos`.
- Todas essas rotas usam a autenticação existente. Datas da API exigem fuso.
- Respostas de conversa carregam `acoes_agenda`, com ID e data de apresentação.
  Clientes mostram ações; não recebem nomes de agentes ou tabelas internas.
- `AgenteAgenda` interpreta o evento; `servicos/agenda.py` persiste; o kernel
  apenas encaminha eventos. Nenhum agente chama outro diretamente.
- As tabelas `agenda_itens` e `agenda_rascunhos` são adicionadas por `create_all`
  ao banco configurado. Os dados seguem a durabilidade desse banco.
- Não há nova chamada paga de IA. O primeiro interpretador usa regras locais
  para datas em português, horários numéricos, dias da semana e intervalos.

Ainda não há recorrência anual/semanal, sincronização bidirecional de calendário,
edição de um compromisso existente nem interpretação arbitrária de datas. Para
remarcar, retire o item e crie outro. Mais de uma data/horário no mesmo pedido
pede esclarecimento em vez de escolher um silenciosamente.

## Publicação e validação

O servidor precisa do deploy manual no Render depois do push. Sem essa
atualização, o novo cliente mostra agenda indisponível em vez de fingir que salvou.
O APK usa o servidor e token que já estão configurados; não altera o token nem
o vínculo com o Home Assistant.

Validação desta entrega: 358 testes Python passaram, dois foram ignorados;
14 testes do PC passaram e o frontend e executável Tauri compilaram. No Android,
51 testes unitários passaram, o APK compilou e foi instalado. Um teste
instrumentado abriu a agenda e o formulário de alarme no celular conectado,
sem criar alarmes ou compromissos reais. O Gradle offline não tinha um componente
UTP em cache; o teste foi executado diretamente com o runner Android pelo ADB.
Depois do teste, o vínculo principal de voz foi restabelecido e a verificação
de somente leitura confirmou Ollie selecionada e serviço conectado. Nenhuma
permissão nova foi concedida.

O patch [android-agenda.patch](patches/android-agenda.patch) registra somente
os arquivos desta entrega do projeto Android separado, a partir dos arquivos
locais que já estavam modificados. O manifesto ao lado guarda hashes para revisão.
Não aplicar sobre um Android antigo sem as integrações de voz/navegação anteriores.
