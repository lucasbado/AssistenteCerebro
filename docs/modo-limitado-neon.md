# Ollie com a cota de banco esgotada

Em 26/10/2026, a Neon informou `You've used all of your monthly compute allowance
for this project`. O deploy falhava antes de iniciar a API, em `inicializar_banco`.
É a cota de processamento do PostgreSQL, independente dos limites de Groq ou
Cloudflare Workers AI. O usuário escolheu manter os controles em modo limitado.

## Recuperação sem trocar a memória

O servidor tenta inicializar o banco configurado uma vez. Se o provedor retornar
a recusa explícita `Your account or project has exceeded the quota`, inicia a
composição de controles. Erros de senha, conexão comum, schema ou migração continuam
interrompendo o startup; não são escondidos como problema de cota.

Também é possível usar `OLLIE_MODO_LIMITADO=true` no Render. Nesse caso, nem a
conexão inicial é tentada. Isso permite manter o serviço funcionando sem acordar
o banco enquanto a cota não renova. Não é necessário definir essa variável para
a recuperação automática da recusa de cota mostrada nos logs.

O modo usa a mesma autenticação HTTP/WebSocket. Não substitui `DATABASE_URL`,
não cria SQLite alternativo, não apaga tabelas e não altera o banco remoto.
Os controles em andamento e suas confirmações são transitórios, como antes.
Novos pedidos não passam a formar uma memória paralela.

## O que continua disponível

- Comandos explícitos para lanterna, volume, brilho, som, painéis, navegação,
  despertador, timer e revisão de mensagem no celular.
- Abrir apps, sites e buscas conhecidas, respeitando o dispositivo de origem
  e o destino dito pelo usuário; planos de abertura/iluminação já reconhecidos.
- Consultar e controlar a iluminação pela ponte do PC ou celular com HA configurado.
- Controles diretos do PC via HTTP/WebSocket e vínculos já configurados dos botões.
- Reconhecimento de voz no cliente e síntese da resposta pelo endpoint de voz.

Exemplos: “ligue a lanterna”, “apague a luz”, “abra HBO Max no PC” e “crie um timer
de 5 minutos”. Não há interpretação livre por LLM nesse modo. Um pedido que precise
de IA ou persistência recebe uma explicação da indisponibilidade, sem anunciar
que foi salvo ou executado.

## O que fica pausado

Agenda da Ollie, tarefas, memória, histórico, revisão persistente de mensagens,
aprendizado, rotinas aprendidas, consultas de IA e verificadores periódicos do
banco não são iniciados. A criação de um despertador no Relógio Android continua
separada da agenda persistente da Ollie.

A tela inicial informa o modo limitado. Leituras de agenda e memória retornam
HTTP 503 com `codigo=persistencia_indisponivel`, em vez de listas vazias que
pareçam perda de dados. Gravações nesses recursos e feedback persistente também
são recusados. Sensores e notificações recebidos por `/eventos` não recebem
confirmação de armazenamento: retornam 503. Somente ordens diretas do usuário
seguem para o kernel nesse endpoint enquanto o modo está ativo.

`GET /health` retorna HTTP 200 para indicar que o serviço de controles está vivo,
com `modo=limitado`, `persistencia_disponivel=false` e o motivo. A rota de status
também informa `LIMITADO`. A política de abertura automática exposta ao cliente
é temporariamente restritiva; sua política salva no banco não é sobrescrita.

## Redução de desperdício no modo completo

- Fila de fatos: sondagem com espera progressiva de 5 segundos até 15 minutos
  quando vazia; falhas usam espera de 15 minutos. Uma fila com trabalho é drenada
  sem uma espera fixa entre cada tarefa. Inserções externas depois de uma longa
  ociosidade podem aguardar até o próximo ciclo; essa fila não é a de alarmes
  nem de lembretes pessoais.
- Sondagem vazia faz uma leitura, sem os dois UPDATEs e COMMIT anteriores.
- Limpeza de mensagens antigas passa de cada 30 segundos para uma vez por hora.
- Batidas internas `TICK_*` de agenda/tarefas/mensagens/rotinas deixam de gerar
  registros episódicos. Seus resultados e acontecimentos pessoais continuam
  arquivados. Nenhum registro antigo é apagado por esta alteração.

Esses cortes reduzem consultas e gravações; não garantem que a Neon durma no modo
completo. Os relógios de lembretes e rotinas ainda precisam de uma revisão de
agendamento por próximo vencimento para eliminar suas sondagens frequentes.
No modo limitado, nenhum desses verificadores de banco é executado.

## Voltar ao modo completo

Quando o painel da Neon informar a renovação da cota, remova ou desative
`OLLIE_MODO_LIMITADO`, caso a tenha definido, e reinicie/republique o serviço no
Render. Se a inicialização do mesmo banco for bem-sucedida, a composição completa
é iniciada. Não há tentativa periódica de reconexão, mudança automática de plano
nem promessa de renovação em uma data que o painel ainda não confirmou.

O Neon documenta a cota mensal e a suspensão por consumo em
[planos](https://neon.com/docs/introduction/plans). A documentação sobre
[computes](https://neon.com/docs/manage/computes) explica como conexões e processos
de fundo frequentes podem impedir a suspensão por ociosidade.

## Validação

Os testes simulam a recusa de cota e proíbem qualquer criação de sessão SQL depois
do startup limitado. Cobrem autenticação, estado de saúde, home, recusas de
gravação, feedback e conversa completa com confirmações simuladas de celular, PC
e luzes. A validação contra o Render depende do deploy desta correção.
