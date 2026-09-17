# Plano de Implementação: Otimização de Latência e Correção de Repetição (Ollie Assist)

Este plano visa reduzir drasticamente a latência das respostas por voz, corrigir o problema de comandos ignorados via botão de assistência e eliminar a repetição de fala/notificações.

## User Review Required

> [!IMPORTANT]
> Mudaremos a comunicação da sessão de voz de **HTTP** para **WebSocket**. Isso eliminará o tempo de abertura de conexão em cada frase. Também sincronizaremos o estado da sessão para que o serviço de background não "atropele" a fala da tela ativa.

## Proposed Changes

### 1. Estado de Sessão (Android)
#### [MODIFY] [ChatBridge.kt](file:///D:/Programacao/Projetos/AssistenteCell/app/src/main/java/com/example/assistentecell/websocket/ChatBridge.kt)
- Adicionar um `MutableStateFlow` chamado `isAssistantSessionActive` para que o App saiba quando a interface de voz está aberta.

### 2. Redução de Latência e Fix de Comandos (Android)
#### [MODIFY] [OllieSession.kt](file:///D:/Programacao/Projetos/AssistenteCell/app/src/main/java/com/example/assistentecell/assistant/OllieSession.kt)
- Alterar `sendToBrain` para usar `ListenerDeNotificacoes.enviarMensagemWebSocket` em vez de OkHttp.
- Enviar com o tipo `CHAT_MESSAGE`, garantindo que o servidor processe como comando de voz.
- Atualizar `isAssistantSessionActive` no `onShow` e `onHide`.

### 3. Fim da Repetição (Android)
#### [MODIFY] [ListenerDeNotificacoes.kt](file:///D:/Programacao/Projetos/AssistenteCell/app/src/main/java/com/example/assistentecell/ListenerDeNotificacoes.kt)
- Antes de executar `voiceManager?.speak`, verificar se `ChatBridge.isAssistantSessionActive` é falso.
- Se a sessão estiver ativa, o serviço de background apenas posta a mensagem no bridge (para aparecer na tela), mas **não fala e não cria notificação**, deixando essa tarefa para a `OllieSession`.

### 4. Refinamento de Comandos (Backend)
#### [MODIFY] [agente_pc_executor.py](file:///D:/Programacao/AssistenteCell/agentes/agente_pc_executor.py)
- Garantir que a origem `ANDROID_VOICE_ASSIST` (e agora `ANDROID` via WS) seja aceita para todos os comandos de sistema e hardware.

## Verification Plan

### Testes de Latência
1. Acionar a Ollie por voz e verificar se o log do servidor mostra o recebimento instantâneo (via WS).
2. Medir o tempo de resposta percebido.

### Testes de Fluxo
1. Confirmar que a Ollie fala apenas UMA vez quando a tela está aberta.
2. Confirmar que comandos como "abrir vscode" funcionam via botão de assistência.
