# Ajuda com mensagens e rotinas de revisão

Segunda etapa da sequência de funções de assistente, após
[tarefas e calendário](tarefas-e-calendario.md). A próxima etapa é o resumo do dia;
depois vêm memória pessoal editável, cenários entre dispositivos e continuidade.

## O que já está disponível

A caixa **Mensagens** no PC e o ícone de mensagens na conversa do celular reúnem
pedidos concretos, decisões, convites definidos e prazos encontrados nas notificações dos
aplicativos de mensagens compatíveis. Também é possível pedir **“minhas mensagens”**
ou **“prepare resposta para Ana dizendo que vou conferir o horário”**.
Quando houver mais de uma mensagem daquele nome, a Ollie pede para escolher.

### Seleção pelo contexto

Ter `?` deixou de ser critério para entrar na caixa. Perguntas como “tudo bem?”,
“já almoçou?” e “viu aquele vídeo?” ficam fora. Pedidos como “pode enviar o
relatório até sexta?” e confirmações com data definida entram. Um relato do
remetente sobre sua própria obrigação não vira uma pendência do usuário.

O serviço `selecao_mensagens` mantém até seis trechos recebidos por conversa,
com até 1.500 caracteres por trecho. Usa somente os últimos 30 minutos como
contexto e remove esse armazenamento auxiliar após 24 horas. Referências opacas
do Android isolam conversas, inclusive contatos com o mesmo nome. Mensagens
de grupo identificadas pelo remetente diferente do título não são atribuídas
automaticamente ao dono do celular.

Casos claros são decididos localmente. Só candidatos ambíguos com assunto
concreto ou continuação de contexto relevante passam por análise semântica.
“Você vem?” depois de uma entrevista definida pode ser uma confirmação;
a mesma frase sem contexto não basta. O modelo precisa apontar trechos reais
da mensagem atual e, quando necessário, do contexto para justificar a seleção.
Não pode criar tarefas, compromissos ou enviar respostas nessa etapa.

A análise automática respeita o orçamento compartilhado de IA. Não gasta os
fallbacks reservados aos pedidos diretos. Cota esgotada, falha ou evidência
insuficiente resultam em não destacar o caso ambíguo; pedidos claros ainda são
selecionados localmente. Decisões são cacheadas por conteúdo e contexto. Uma
renovação da notificação não repete o trabalho; contexto novo permite reavaliar.
O GPT-OSS usa esforço baixo somente nessa classificação, com espaço de saída
para concluir o JSON, conforme a [API Groq](https://console.groq.com/docs/reasoning).

A lista ordena importância antes da recência. A API acrescenta `prioridade` e
`motivo`; o app do PC exibe o motivo e clientes Android existentes já recebem
a lista na nova ordem. Perguntas antigas são reavaliadas localmente na consulta
e retiradas do destaque, sem apagar registros nem marcá-los como resolvidos.
Rascunhos e vínculos que o usuário já criou são preservados na revisão.
Essa reavaliação examina até 2.000 candidatos por consulta e apresenta até 100.

Teste real com mensagens sintéticas confirmou três casos: confirmação de
entrevista selecionada; papo sobre contrato numa série descartado; pedido de
assinatura por uma continuação com “isso” selecionado. Relatório privado em
`.artifacts/teste-selecao-mensagens-real.json`. Não foram enviadas mensagens.

Cada item permite guardar um compromisso, criar uma tarefa, preparar e editar um
rascunho, copiá-lo, marcar como resolvido ou ignorar. Os vínculos reaproveitam as
sugestões anteriores para evitar duplicação. Guardar compromisso exige uma data
reconhecida no texto; um prazo relativo usa o momento em que a mensagem chegou.
O compromisso confirmado segue a sincronização já configurada com o calendário
Samsung. A tarefa pode ficar sem prazo.

Preparar uma resposta usa o provedor de IA já configurado e só ocorre por pedido
do usuário. A mensagem recebida é tratada como contexto, e não como uma instrução
para a Ollie executar ações. O rascunho deve ser conferido: o envio continua sendo
feito pelo usuário na conversa do aplicativo.

No celular, **Abrir conversa original** usa a ação da notificação recebida, com
verificação do aplicativo, remetente e versão da notificação. Se ela foi removida,
mudou, expirou ou o serviço reiniciou, a Ollie avisa para abrir a conversa
manualmente. Não escolhe um contato parecido como alternativa.

## Ligação com o aprendizado de rotinas

Abrir explicitamente a revisão gera um evento de uso da habilidade `mensagens`,
com dispositivo e horário. Atualizações em segundo plano não contam como uso.
O evento de aprendizado não leva o texto nem o remetente da mensagem.

O descobridor considera os últimos 21 dias, exige pelo menos cinco dias distintos
de uso no mesmo período/dispositivo, confiança mínima de 80% dos dias ativos
observados e uso nos últimos sete dias. Várias visitas no mesmo dia não aumentam
essa evidência. Dias ativos sem revisão entram no denominador.

O resultado aparece no catálogo existente de sugestões como **Revisar mensagens**,
com evidência e justificativa. Nasce desativado. Depois de aprovado, pode oferecer
uma revisão no período aprendido, no dispositivo correspondente, no máximo uma
vez por dia e respeitando a política geral de notificações. Só há oferta quando
existem itens e o cliente está conectado. A rotina não prepara respostas, envia
mensagens ou abre aplicativos automaticamente. Pausa, rejeição e exclusão usam os
controles existentes das rotinas.

## Contexto e limites

O histórico de trabalho foi separado por conversa, em vez de juntar todos os
contatos de um aplicativo. O cliente Android atualizado fornece uma referência
opaca da conversa; clientes antigos usam aplicativo e nome do remetente, que não
distinguem homônimos com segurança. A caixa elimina repetições da mesma mensagem
na mesma conversa/dia e não reabre revisões encerradas quando a notificação reaparece.

Notificações não comprovam que uma mensagem continua sem resposta. A tela mostra
possíveis pendências para revisão; não lê o histórico completo do WhatsApp nem
acompanha o envio feito fora da Ollie. A caixa guarda até 14 dias e apresenta no
máximo 100 itens por filtro. O usuário pode encerrar cada revisão, e rascunhos usam
controle de versão para não sobrescrever uma alteração concorrente.

## Implementação e publicação

`servicos/mensagens.py` concentra captura, revisão, rascunhos e vínculos;
`AgenteMensagens` recebe eventos pelo kernel. A API autenticada está em
`/api/v1/mensagens`; não há operação de envio. O banco cria a tabela aditiva
`mensagens_revisao` na inicialização, preservando tarefas e compromissos existentes.
A seleção atual acrescenta a coluna JSON `analise` por migração aditiva e a
tabela `conversas_revisao`. Tarefas já confirmadas não são reclassificadas.
O catálogo e o executor de rotinas existentes materializam e executam a ação
`IA / REVISAR_MENSAGENS`.

Na integração inicial, o APK foi compilado e instalado no celular conectado,
e o serviço de assistente foi reconectado. Nesta revisão da seleção, o app do
PC foi compilado e reaberto; o celular continua usando a API compatível.
**É necessário fazer o deploy manual do backend no Render** para os clientes
encontrarem as novas rotas e começarem a capturar as próximas notificações.

As alterações Android desta etapa estão arquivadas em
[android-assistencia-mensagens.patch](patches/android-assistencia-mensagens.patch)
e seu manifesto de hashes. A base é a cópia local após a integração de tarefas e
calendário; o patch não substitui todas as alterações anteriores do projeto Android.

Validação atual: 516 testes Python passaram, dois foram pulados; 21 testes do
desktop passaram. TypeScript/Vite e Rust compilaram. Os 61 testes Android e o
teste de interface que confirmou a abertura da caixa pertencem à integração
anterior; a seleção atual é validada no backend, com contrato compatível.
Os testes Python cobrem isolamento por conversa, repetição de notificações,
rascunhos, autenticação, conflitos de versão, reaproveitamento de tarefa/agenda,
descoberta e aprovação de rotina, limite diário e destino da notificação.
Nenhuma mensagem real foi enviada nos testes. O fluxo com notificações reais no
Render ainda depende do deploy manual e de novas mensagens recebidas.
