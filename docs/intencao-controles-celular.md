# Intenção e controles do celular sem depender da memória

Atualização de 26/10/2026. A cota esgotada da Neon pausa agenda, tarefas e aprendizado;
não precisa impedir conversa, despertadores, timers ou execução no celular.

Pedidos locais conhecidos continuam rápidos. Os demais passam por interpretação
semântica: a IA decide intenção, ação e parâmetros; o servidor valida o plano e
aguarda o executor Android. Não há confirmação de execução produzida pela IA.

## Conversa e relógio

“Me acorde amanhã às sete”, “coloca pra despertar às 7h30” e pedidos mais livres
podem virar `alarm.create`. Se faltar horário, a Ollie pergunta. A continuação
fica somente em RAM por até três minutos, separada por origem PC/celular.
Não cria uma agenda paralela e desaparece ao reiniciar. Pedidos novos não são
tratados automaticamente como respostas à pergunta anterior.

O relógio entende números falados, horários como “sete e meia” e períodos; aceita repetição diária
ou de segunda a sexta quando explicitamente solicitada. O horário e a data são
conferidos com o fuso do dispositivo/usuário. Uma data que não corresponde à próxima
ocorrência do horário abre o Relógio para ajuste, em vez de criar silenciosamente
um despertador para o dia errado. O estado `encaminhado` significa entrega ao
Relógio, não comprovação de um alarme salvo.

Perguntas de conhecimento também recebem uma resposta nesse modo. Pedidos para
salvar compromisso, tarefa ou memória continuam recusados enquanto a persistência
estiver indisponível. Não anunciar armazenamento é obrigatório.

## Aplicativos reais e interação

O celular registra `APPS_MOBILE` e envia nomes/pacotes de aplicativos instalados
que podem ser abertos. O catálogo é transitório, pertence ao socket registrado e
é descartado na desconexão. Um pacote inexistente não é inventado pela IA.
Aberturas simples de app/site e buscas reconhecidas evitam inferência adicional.
O destino explícito prevalece sobre a origem; um pedido para PC não abre no celular.

`app.task` acrescenta navegação por elementos acessíveis, com até cinco etapas e
50 segundos por tarefa. **A interpretação de telas é opcional e desligada por padrão.**
Em Configurações → Controles do celular, a opção explica que textos visíveis podem
conter mensagens/dados pessoais e serão enviados ao servidor e à IA do PC ou Cloudflare.
O executor verifica a autorização antes de consultar elementos ou agir. Não é
habilitada por instalação, ADB ou autorização prévia de acessibilidade.

Com autorização e acessibilidade, cada consulta produz referências de elementos
com validade de 15 segundos. Antes de agir, o cliente confere aplicativo, elemento,
posição e propriedades atuais. A referência só permite uma ação. Tela alterada,
elemento ausente, login ou permissão interrompem o fluxo. Campos de senha são
omitidos, digitação genérica é restrita à busca, e telas de permissões/configurações
do sistema não são operadas por esse caminho. Rótulos comuns de envio, compra,
pagamento, exclusão ou concessão de permissão são bloqueados também no cliente.
Isso não torna toda interface de terceiros controlável; apps sem elementos acessíveis
ou com etapas ambíguas pedem intervenção do usuário.

Mensagens usam o fluxo dedicado de revisão existente. Não há envio autônomo de
mensagem por um plano genérico de tela. Neste trabalho nenhuma mensagem foi enviada.
Capturas textuais não são gravadas nos recibos do Android. São usadas durante a
tarefa e podem ser processadas remotamente somente após a autorização descrita acima.

## IA e orçamento sem SQL

O interpretador tenta a IA do PC conectado; se indisponível, usa o Workers AI já
configurado. Essa ponte dispensa a gravação de métricas SQL. Nenhum polling de
banco é criado para interpretação e nenhuma notificação dispara esse fluxo.

O orçamento temporário da Cloudflare é conservador: até 40 mil tokens estimados
e 300 reservas em 24 horas, seis por minuto, sem perder reservas em falhas de rede.
Cooldown do provedor é respeitado. Ele existe somente no processo, reinicia junto
com ele e não representa o saldo real de neurons da conta nem o orçamento de
outros consumidores. Planos de interface também têm limites de tempo e etapas.

## Entrega e validação

- Backend e APK precisam ser atualizados. Clientes antigos continuam com controles
  anteriores e recebem orientação de atualização para ações novas.
- Suíte Python: 604 passaram, dois ignorados; teste adicional de atualização do catálogo também passou.
- Android: 69 testes passaram; APK debug compilado.
- Teste real da IA, sem executar comandos: pedido livre de despertar às 6h30,
  timer de três minutos, pergunta de horário ausente e explicação de pareidolia.
- Integração simulada autenticada: modo limitado sem sessão SQL, catálogo Android,
  pergunta e continuação do horário, execução e resposta correlacionada.
- APK instalado por depuração Wi-Fi em 26/10/2026, após o usuário disponibilizar o
  aparelho e publicar o backend `85c7ed4` no Render. API online em modo limitado;
  PC, celular e pontes da casa conectados.
- Pedido real pela API → kernel → interpretação semântica → executor Android:
  “Preciso levantar às 21:28. Faz o celular me acordar nesse horário?”. O Relógio
  Samsung mostrou o alarme `Ollie`, às 21h28 de 26/10, ativado. Depois foi excluído
  somente esse alarme, com verificação de nome, horário e seleção única. Os estados
  dos outros alarmes visíveis foram preservados.
- “Quero usar a calculadora no celular agora, abre ela pra mim” retornou
  `app.open/concluido`; a Calculadora Samsung veio para o primeiro plano.
- A autorização de leitura de telas por IA permaneceu desligada. O serviço da
  assistente permaneceu vinculado (`mBound=true`), e wake word/listener estavam
  ativos após a instalação. Esses testes reais usaram texto pela API; não são
  uma nova medição de reconhecimento de voz ou de interação dentro de outros apps.

As alterações Android estão em `patches/android-intencoes-celular.patch` e no
manifesto de hashes correspondente, sobre a base de `android-controles-celular.patch`.
Aplicar apenas quando os hashes anteriores coincidirem. O deploy no Render é manual.

Referências: [AlarmClock](https://developer.android.com/reference/android/provider/AlarmClock),
[intents comuns](https://developer.android.com/guide/components/intents-common) e
[AccessibilityService](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService).
