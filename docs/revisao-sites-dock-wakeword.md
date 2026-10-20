# Sites no PC, notificações e ativação por voz

## Sites e apps

O destino padrão continua sendo o dispositivo de origem, e o destino explícito
continua prevalecendo. `config/sites_pc.json` diferencia serviços web de programas
instalados: HBO Max/Max, Netflix, Prime Video e Disney+ usam o navegador no PC.
Apelidos antigos e erros como `max.exe` também resolvem o serviço cadastrado.
A referência para o domínio da HBO é o [centro de ajuda oficial](https://help.hbomax.com/br/Answer/Detail/000002543).

Domínios digitados, como `github.com`, recebem HTTPS. URLs completas preservam
maiúsculas no caminho e na query. Nomes sem domínio não geram endereços adivinhados.
Pacotes Android e arquivos `.exe` não são classificados como domínios.

O caminho simples de abertura também aceita nomes fora da lista antiga de sete
apps. Pedidos com múltiplas instruções seguem para a interpretação existente.
Programas instalados continuam usando o executor do PC. O celular mantém suas
regras de app/site e não recebe comandos destinados ao computador.

A ponte Python do desktop resolve o catálogo novamente antes de executar. Isso
permite corrigir um comando antigo como `abrir_app("HBO Max")` sem substituir o
executável do desktop. O backend atualizado precisa do deploy manual para que
essa distinção também aconteça antes do encaminhamento.

## Notificações e dock

A notificação usa apresentação nativa com texto expandido, ícone próprio e uma
categoria visual de Conversa, Sugestão ou Importante. Os botões de ação, rejeição
e resposta mantêm os mesmos contratos. O objetivo é evitar cortes e contraste
inconsistente dos layouts customizados; o Android limita bastante a área compacta
de [notificações customizadas](https://developer.android.com/develop/ui/views/notifications/custom-notification).

O dock agora tem cabeçalho, fechar, transcrição separada da resposta, área de
resposta com rolagem, botão de microfone e atalho para a conversa completa. Os
estados são preparar, ouvir, pensar, responder, pronta e erro. O microfone fica
desabilitado durante o envio e permite parar a escuta. Margens usam dp e respeitam
a área de navegação do sistema.

Essa apresentação está preparada em código. **Ainda não houve verificação visual
do novo APK no aparelho.** O teste instrumentado `AssistantPresentationTest` cria
uma notificação de demonstração e verifica título, texto expandido e botão Falar.

## Wake word

A consulta ao celular encontrou `wakeword_enabled=false`. Além disso, a mensagem
da interface dizia “Ei Ollie”, mas o detector só aceitava variantes de “E aí Ollie”.
O modelo português embarcado não contém `ollie`, `oli` ou `[unknown]` no vocabulário.
Ele contém aproximações fonéticas como `olhe` e `olha`, além do token `[unk]`.

A nova gramática usa palavras existentes no modelo e reconhece essas aproximações
da chamada “Ei Ollie”. O gate rejeita nome isolado, evita ativações repetidas e
respeita a sessão/microfone ocupados. A validação lê o vocabulário do modelo local;
isso não comprova o reconhecimento da pronúncia de uma pessoa.

A instalação do modelo passa a acontecer em armazenamento interno e fora da
thread de interface, com versão e erros visíveis. O sincronizador anterior
[dependia de um arquivo `uuid`](https://github.com/alphacep/vosk-api/blob/master/android/lib/src/main/java/org/vosk/android/StorageService.java)
ausente nos assets e recorria a uma cópia manual. A captura é liberada ao abrir
a sessão e retomada ao terminar. Falhas de microfone usam retentativa; falha de
abertura da sessão não deixa a captura parada indefinidamente. As restrições de
[serviço de microfone em segundo plano](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
continuam se aplicando; a inicialização deve partir do app ou do assistente padrão.

O interruptor mostra o estado real da preparação/escuta e não informa sucesso
quando falta permissão. Desligar a leitura automática das respostas não desliga
mais a wake word. Depois de instalar, ative **Sistema → Ativação por voz**, diga
“Ei Ollie”, espere a sessão aparecer e faça o pedido.

**O teste auditivo da nova detecção no celular ainda está pendente.**

## Estado da revisão e conclusão local

Os 194 testes Python passaram. As verificações estruturais de XML/vocabulário
também foram executadas com sucesso.
O relatório estrutural está em `.artifacts/android-review/validacao-recursos-voz.json`.
Os testes Kotlin e o teste instrumentado foram escritos, mas não foram executados.

A tentativa de Gradle foi impedida por falha da revisão automática de aprovação:
o serviço informou limite de uso e não concluiu a revisão. Não foi uma conclusão
de que compilar seria inseguro. Nenhum APK novo foi produzido ou instalado nesta
rodada. Parte das mudanças já foi aplicada no projeto Android; os últimos ajustes
estão em staging, com validação de hash para não sobrescrever edições externas.

Para concluir no terminal local, a partir do backend:

```powershell
.\scripts\concluir_revisao_android.ps1 -Instalar
```

O script aplica os ajustes restantes, valida recursos, executa os testes unitários,
compila o APK e o APK de teste. Só instala se tudo passar e houver exatamente um
celular autorizado conectado. Não apaga dados do aplicativo. Se houver falha,
interrompe antes da instalação e apresenta o erro para correção.

A verificação visual e a escuta real continuam necessárias depois da instalação;
elas não são substituídas pelo sucesso da compilação.
