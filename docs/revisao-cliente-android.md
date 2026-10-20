# Revisão do cliente Android e integração com o backend

Cliente localizado em `D:\Programacao\Projetos\AssistenteCell` e revisado em
19/10/2026, complementando [a revisão do backend](revisao-rotinas-notificacoes.md).
Foram aplicadas correções nos dois projetos, preservando as modificações que já
existiam no cliente. O Wear OS não foi alterado nesta revisão.

## Falhas encontradas e correções

| Problema | Correção aplicada |
| --- | --- |
| Retrofit, WebSocket e sensores não enviavam autenticação | Cliente HTTP do backend adiciona `Authorization: Bearer`; token configurável na tela do servidor. O cliente Home Assistant fica separado |
| URL local era reescrita de 8000 para 8001 | Removida a reescrita. O padrão de desenvolvimento e o botão de ambiente local usam `main:app` em 8000. Endereços previamente salvos são preservados |
| Salvar servidor chamava reconnect, mas ele saía quando já havia um socket | Reconexão fecha a conexão anterior e ignora callbacks obsoletos |
| Deduplicação tratava toda a conversa como uma mensagem | Backend envia `id`; Android deduplica por tipo e ID de evento, mantendo `correlacao_id` para rastreabilidade |
| Normalização apagava números e acentos das respostas | Identidade de entrega preserva texto e dados distintos, incluindo horários e valores |
| Filtro de hábitos escondia tudo com “costuma”, “hábito” ou “frequentemente” | Filtro limitado a mensagens decorativas antigas; sugestões com ação e respostas do chat passam |
| Sugestão enviada com o app aberto não aparecia no chat nem como notificação | `NOTIFICACAO` permanece visível e acionável; só respostas do chat já aberto dispensam aviso de sistema |
| Toda mensagem virava notificação com prioridade máxima e overlay com som | Canais separados para sugestões e urgências. Overlay exige urgência e preferência explícita; fica desligado por padrão |
| Modo foco escondia os botões | Silencia o aviso e mantém a ação escolhida pelo usuário disponível |
| Ação principal competia com resposta, voz e rejeição | Ação sugerida aparece primeiro, seguida de rejeição e resposta textual |
| Clique em “Abrir app” passava pelo mesmo bloqueio de auto-open | Caminho de clique explícito não depende da preferência de abertura automática |
| Botão de notificação executava abertura a partir de um BroadcastReceiver | Ações novas usam `PendingIntent.getActivity` para uma Activity interna |
| Nome como Spotify podia ser redirecionado ao PC antes de procurar no Android | Destino MOBILE permanece no celular; busca por pacote ou nome exato e único, sem prefixo arbitrário ou fallback silencioso para PC |
| Resposta do chat era analisada para executar comandos implícitos | Texto é apresentado; execução exige mensagem de comando ou ação explícita |
| Comando PC recebido pelo celular podia ser reinterpretado como local | Cliente ignora `COMANDO_PC`; esse comando pertence ao executor desktop |
| Sender enviava o mesmo comando por WebSocket e UDP | UDP só é usado quando o WebSocket não aceita o envio |
| Aprovar, rejeitar ou gerar rotina deixava loading preso | Loading é encerrado na atualização da lista; falhas aparecem no estado de erro |
| Monitor de uso retinha só o último app da consulta e descartava trocas dentro de três segundos | Cada transição é processada; launcher e apps excluídos continuam delimitando sessões |
| Voltar do launcher para o mesmo app não era uma nova abertura | Rastreador preserva essas transições, separando-as de navegação rápida entre Activities do mesmo app |
| Uso contínuo não tinha atualização observável | Heartbeat por minuto enquanto há app em primeiro plano e tela interativa; backend o utiliza para bem-estar, sem incrementar aberturas ou disparar rotinas |
| Feedback de clique só era logado; rejeição virava comando normal para a IA | Feedback real via WebSocket, com fallback HTTP, publicado como `FEEDBACK_USUARIO` |
| Aprendizado avaliava o primeiro sensor da conversa, em vez da sugestão | Feedback pode identificar a notificação exata; ajuste de preferência considera o app sugerido |
| Descartar notificação era punição de preferência | Descarte só registra interação; rejeição explícita ajusta a preferência |
| Resposta inline dizia “enviada” sem verificar conexão | Mostra encaminhamento apenas quando o socket aceita o envio; falha de conexão fica explícita |

O Android restringe abertura de Activities por serviços e receivers usados como
intermediários de notificações. A mudança para `PendingIntent.getActivity` segue
a [documentação das restrições do Android 12](https://developer.android.com/about/versions/12/behavior-changes-12#notification-trampolines)
e a [orientação para abrir uma Activity por notificação](https://developer.android.com/develop/ui/views/notifications/navigation).

## Validação executada

- Backend: **43 testes passando** em SQLite temporário, sem executar hardware.
- Android: **5 testes unitários passando**, incluindo quatro novos casos para
  deduplicação, filtro de sugestões e transições de apps.
- `:app:testDebugUnitTest :app:assembleDebug`: **BUILD SUCCESSFUL**, em modo
  offline, utilizando as dependências já presentes na máquina.
- APK: `D:\Programacao\Projetos\AssistenteCell\app\build\outputs\apk\debug\app-debug.apk`.
- Permanecem avisos de APIs e recursos de build depreciados; não impediram a
  compilação. Não houve instalação ou execução dos testes no aparelho.

O [patch do cliente](patches/android-rotinas.patch) registra somente as diferenças
em relação aos arquivos existentes no início desta revisão. A preparação e a
aplicação verificaram hashes para evitar sobrescrever edições feitas no meio
do trabalho. Os snapshots locais ficam em `.artifacts/android-review` no backend.

## Como validar no celular

1. Atualize o app com o APK compilado e reinicie o backend com `main:app`.
2. Em Configurações → Endereço do Servidor, use a URL do backend completo e o
   mesmo token configurado em `OLLIE_API_TOKEN`. O app não inventa um token.
   Para emulador local, o padrão é `http://10.0.2.2:8000/`; em um celular físico,
   utilize o endereço do PC acessível pelo aparelho ou a URL do servidor remoto.
3. Após alterar servidor/token, encerre e abra o app para recriar também os
   repositórios já guardados nos ViewModels da interface.
4. Confirme acesso às notificações, estatísticas de uso e permissão para mostrar
   notificações. Elas são necessárias para os fluxos correspondentes.
5. Abra apps, consulte as sugestões de rotinas e aprove uma com evidência.
   Teste o botão de abrir app com auto-open desligado: o clique continua válido,
   enquanto comandos autônomos continuam sujeitos à preferência.
6. Teste “Agora não”, resposta inline e uma reconexão. Confirme no backend que
   feedback chega como `FEEDBACK_USUARIO`, e não como pedido de raciocínio.

## Limites que continuam relevantes

- Teste local de compilação não demonstra entrega, abertura efetiva ou leitura
  no aparelho. Restrições do fabricante, tela bloqueada, permissões e Activities
  de outros aplicativos precisam de validação no dispositivo.
- O aceite de um envio WebSocket não é confirmação de execução remota. Ainda
  falta confirmação de resultado com ID de comando e deduplicação persistente
  para repetição após perda de conexão. O fallback UDP antigo não oferece isso.
- Feedback já chega e ajusta a preferência do alvo. Ainda falta usar histórico
  de aceitação/rejeição para calibrar a frequência de cada tipo de sugestão;
  rejeitar um aviso não desativa permanentemente uma rotina aprovada.
- Há um fluxo legado de regras manuais em `AutomationManager`, salvo em
  SharedPreferences. As chamadas de `getRulesForSkill` encontradas servem à
  interface; não foi encontrado um executor dessas regras locais. Esse fluxo
  precisa ser unificado com as rotinas do backend, evitando duas fontes de
  configuração. As rotinas aprendidas e aprovadas usam o executor do backend.
- Sugestões antigas do backend foram preservadas. Devem ser reavaliadas antes
  de aprovação, pois não recebem evidência retroativamente.
- A revisão não reativou nem validou a cadeia de voz ou o app Wear OS.
