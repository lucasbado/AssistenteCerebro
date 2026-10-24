# Perguntas gerais e falhas da IA

Em 24/10/2026 foi investigado o caso “o que era pareidolia?”, que terminou em
um recibo sem explicação. Um teste com a Groq reproduziu HTTP 429 nos dois modelos
configurados: a cota diária estava próxima do limite. O servidor transformava a
falha em “Processando comando...”, mas não havia trabalho posterior àquela frase.
O transporte também tinha um retorno genérico de sucesso para chats vazios.
Os logs locais não tinham a interação original; a causa observada no teste não
comprova qual resposta exata o Render gerou naquela interação.

## Comportamento corrigido

- A Ollie responde perguntas, explicações e comparações sem precisar de uma ação
  de dispositivo. A correção não contém uma resposta fixa para pareidolia.
- Perguntas claramente informativas usam um prompt mais curto, com personalidade,
  histórico recente e conhecimento pessoal selecionado, sem o catálogo completo
  de comandos. Esse caminho só produz texto e a decisão de aguardar uma resposta;
  comandos e gravações permanentes sugeridos pelo modelo são descartados.
- Perguntas pessoais, consultas de estado e pedidos mistos mantêm o fluxo completo.
  O prompt geral também exige responder ao assunto. Se ele retorna apenas um
  recibo, silêncio ou IGNORAR sem ações, o serviço tenta uma resposta conversacional.
- Uma explicação nova não é consumida como preenchimento de rascunho pendente de
  tarefa/agenda. Perguntar “o que é mutar microfone?” não silencia o microfone.
- Respostas sem conteúdo e recibos sem resposta não são aceitos como conclusão
  nem reutilizados do cache. Há no máximo uma correção de formato/recibo por
  provedor no caminho de conversa. Erros de rede ou cota não entram nesse laço.
- Falta de cota, falha do provedor e chat vazio têm mensagens honestas. Não há
  confirmação de sucesso ou promessa de trabalho em segundo plano.

`servicos/conversa.py` concentra reconhecimento e contrato; `ServicoLLM` mantém
os provedores existentes. Reflexo e raciocínio seguem publicando eventos pelo
kernel, sem chamadas diretas entre agentes. A resposta preserva a correlação,
o dispositivo de origem, o canal de voz e `aguarda_resposta`.

## Validação e limites

Testes reais com a Groq responderam sobre pareidolia, céu azul e fotossíntese.
Outros testes reais encontraram novamente HTTP 429 e devolveram o aviso correto,
confirmando que a cota continua sendo um limite externo. Prompts menores reduzem
consumo, mas não tornam a cota gratuita ilimitada. Não foi contratado outro serviço.

Os testes isolados cobrem perguntas de assuntos diferentes, continuidade,
recibos, JSON inválido, limite de tentativas, cache, comandos indevidos e o fluxo
API → kernel → raciocínio → política de notificações → WebSocket, tanto para
PC quanto celular, com resposta normal e com erro de cota. Não executam ações
reais nem usam o histórico pessoal.

Suíte completa: **449 testes passaram e dois foram pulados**. Os fluxos existentes
de luzes, aberturas, agenda, tarefas, mensagens e rotinas continuaram aprovados.

O fluxo responde com o conhecimento do modelo e contexto disponível; não ganhou
busca automática na web nesta alteração. Informação atual não verificada deve ser
apresentada com essa limitação. Qualidade factual ainda depende do modelo.

Publicação: **deploy manual do backend no Render**. Não é necessário reinstalar
o Android nem recompilar o desktop para esta correção.
