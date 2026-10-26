# Controles do celular

## Estado desta rodada

Backend e APK implementados em 26/10/2026. A conversa usa uma rota própria de
controle Android, sem gastar LLM para reconhecer as ordens abaixo. O kernel
continua apenas distribuindo eventos. O servidor aguarda o resultado do executor
antes de responder; encaminhar um pedido não equivale a confirmar sua execução.

É necessário publicar o backend no Render e atualizar o APK juntos. Um celular
com versão antiga retorna uma orientação de atualização, sem usar os controles
antigos com parâmetros implícitos.

## Pedidos disponíveis

| Pedido de exemplo | Comportamento |
| --- | --- |
| “Ligue a lanterna” / “Desligue o flash” | Aguarda a câmera informar o estado solicitado. Exige permissão de câmera. |
| “Coloque o volume de mídia em 40%” | Ajusta e consulta o volume real; o aparelho pode arredondar conforme seus níveis. Também aceita toque, alarme e notificações. |
| “Ajuste o brilho para 30%” | Ajusta o brilho manual e consulta o valor. Exige autorização para alterar configurações do sistema. |
| “Coloque o celular no modo vibrar” | Confirma o modo de toque. Também aceita silencioso e normal. |
| “Ative o Não perturbe” / “Desative o Não perturbe” | Solicita o filtro e consulta o estado global. Se o Android restringir essa mudança, informa o limite. |
| “Ative o GPS” / “Desative o Wi-Fi” / “Ative o Bluetooth” | Encaminha ao painel correspondente para sua interação. Não anuncia que mudou o estado dessas conexões. |
| “Crie um timer de 5 minutos” | Encaminha ao aplicativo Relógio; confira por lá. Entre um segundo e 24 horas. |
| “Coloque um despertador para 7:30” | Encaminha ao Relógio para a próxima ocorrência do horário. Não promete um alarme em uma data arbitrária. |
| “Volte uma tela” / “Abra a tela inicial” / “Abra os aplicativos recentes” / “Abra as notificações” | Usa as ações globais da acessibilidade e verifica se o Android aceitou. |
| “Abra os controles do celular” | Abre a tela de permissões e orientações da Ollie. |

Em **Configurações → Controles do celular**, o usuário autoriza individualmente
câmera, contatos, ajustes do sistema, Não perturbe e acessibilidade. Nenhuma
permissão é concedida por ADB. Nem toda autorização é necessária para todo pedido.

Pedidos de volume, brilho e navegação feitos no PC continuam pertencendo ao PC.
Diga “no celular” para trocar o destino. Recursos específicos do telefone, como
lanterna e timer, podem ser solicitados pelo PC. Um destino explícito “no PC”
nunca aciona o executor Android.

É possível combinar controles reconhecidos, por exemplo “ligue a lanterna e
coloque o brilho em 50%”. O plano inteiro precisa ser reconhecido antes do primeiro
envio. Até seis controles são executados sequencialmente. Permissão, revisão,
encaminhamento a outro app ou erro interrompem as próximas etapas.

## WhatsApp e Instagram

Exemplos:

- “Mande mensagem para Ana no WhatsApp dizendo chego às oito”.
- “Envie uma mensagem para João no Instagram dizendo obrigado pelo convite”.

A Ollie preserva o corpo original, inclusive negações, nomes, URLs e frases que
pareçam comandos. Ela abre uma **revisão no celular**. O recebimento do comando
não envia a mensagem.

Se houver exatamente uma notificação individual com título correspondente e uma
ação de resposta livre, o usuário pode tocar em **Confirmar e responder**. Antes
do envio, o cliente verifica novamente aplicativo, destinatário, chave e horário
da notificação. Grupos, títulos aproximados, notificações alteradas ou nomes
ambíguos não são escolhidos automaticamente. A resposta usa o `RemoteInput` do
próprio aplicativo; aceitação do `PendingIntent` não comprova entrega ao contato.

Sem essa notificação, o WhatsApp pode receber um texto preparado por link. O
cliente aceita um telefone explícito ou um contato com nome exato e um número
único, mediante permissão de contatos. A revisão final e o toque em Enviar ficam
no WhatsApp. Números salvos em formato internacional são preferíveis; números
locais usam a região do aparelho para formatação.

Para Instagram sem resposta por notificação, há abertura manual do aplicativo.
Não há automação de conversa nova, seleção arbitrária de destinatário ou clique
cego em “Enviar”. Acessibilidade nesta rodada cobre navegação global, não o
controle completo de toda interface de terceiros. Também não há confirmação
conversacional persistente para “sim, envie”: a confirmação é na tela.

## Contrato e confiabilidade

- Evento de domínio: `CELULAR_ACAO_SOLICITADA`, derivado de ordem direta do usuário.
- WebSocket autenticado: `CELULAR_EXECUTAR` com UUID, ação e parâmetros de contrato fechado.
- Registro Android: capacidade `CONTROLE_MOBILE`; resultados apenas do socket selecionado.
- Resposta: `CELULAR_RESULTADO`, com o mesmo ID e ação. Estados: `concluido`,
  `encaminhado`, `revisao`, `permissao`, `indisponivel` ou `erro`.
- Servidor: até 16 pedidos pendentes e timeout de 12 segundos, sem retransmissão
  automática em timeout ou desconexão. Uma execução sem confirmação pode ter ocorrido.
  O agente também descarta replays das últimas 200 correlações de pedido, inclusive
  pedidos que ficaram sem confirmação, para não criar outro timer por repetição do evento.
- Cliente: valida tipos, limites e chaves; serializa efeitos e reserva o ID em
  disco antes de executar. Mantém até 200 recibos recentes sem corpo de mensagem.
  Pedido interrompido não é repetido ao receber o mesmo ID ainda retido.
- Revisão de mensagem consumida antes de entregar a resposta ao aplicativo,
  evitando dois envios por toque repetido ou recriação da tela.
- Controles legados inferidos pela LLM são recusados, em vez de executar valores
  padrão como lanterna ligada ou volume em 50%. Notificações não autorizam controles.

## Luzes e pontes

Nesta rodada, o HA respondeu na porta 80 e a entidade da lâmpada estava disponível.
O desktop estava desconectado. Após reabrir a Ollie no PC, a consulta enviada
pelo WebSocket da nuvem foi concluída, e o usuário informou que o acesso à luz
reapareceu. Não foi feito um novo teste físico de ligar/desligar nesta rodada.

`GET /api/v1/pc/conexoes` inclui agora a disponibilidade da ponte da casa e os
clientes conectados/configurados para ela. Isso indica disponibilidade de executor,
não garante que o HA ou cada lâmpada estejam alcançáveis naquele instante.

## Validação

- Python: **568 passaram, 2 ignorados**.
- Android: **66 testes unitários passaram**, APK debug compilado.
- Integração simulada: API autenticada → kernel → Android → resultado → resposta
  no PC, incluindo recusa de confirmação vinda de outro socket.
- Cobertura de negações, origem/destino, parâmetros inválidos, limites numéricos,
  mensagem literal, nomes ambíguos, timeout, cancelamento e interrupção de planos.
- Nenhuma mensagem real foi enviada durante os testes.
- APK instalado por depuração Wi-Fi após pareamento autorizado pelo usuário.
- No aparelho real, o executor confirmou lanterna ligada e desligada. A câmera
  foi autorizada pelo próprio usuário na interface.
- Volume de mídia consultado antes e depois: mantido em 6/15 (40%); executor
  retornou `concluido` para esse valor.
- Revisão fictícia de WhatsApp aberta e conferida na tela, sem envio de mensagem.
- Serviço de assistente permaneceu vinculado (`mBound=true`); wake word e listener
  de notificações estavam ativos após a instalação.
- Esses testes do executor usaram o relé WebSocket já publicado e os recibos
  locais dos pedidos. Não substituem o teste da nova conversa contra o Render:
  ela exige deploy manual do backend atualizado.

As alterações do projeto Android externo estão preservadas em
`docs/patches/android-controles-celular.patch`, com hashes de origem e destino no
manifesto JSON correspondente. Aplicar apenas na base indicada pelo manifesto.

Referências de plataforma: [AlarmClock](https://developer.android.com/reference/android/provider/AlarmClock),
[configurações de localização](https://developer.android.com/reference/android/provider/Settings#ACTION_LOCATION_SOURCE_SETTINGS)
e [RemoteInput](https://developer.android.com/reference/android/app/RemoteInput).
