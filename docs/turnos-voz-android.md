# Ilha e continuidade da conversa no celular

A memória semântica fornece fatos relevantes e a memória de trabalho fornece
o histórico recente. O raciocínio usa esse contexto para informar, em cada
resposta, se espera uma resposta do usuário. O estado do microfone pertence ao
turno atual e não é salvo como um fato permanente.

## Comportamento

- Se a Ollie apenas responder ou concluir um pedido, termina a fala e volta a
  ouvir **“Ei Ollie”**, mesmo com a ilha ainda visível.
- Se fizer uma pergunta dirigida ao usuário, termina de falar e reabre o
  reconhecimento em português para receber a resposta sem outra chamada.
- Se não houver fala, encerra essa captura e volta a ouvir a chamada. Não mantém
  o reconhecedor de comandos em um ciclo de tentativas durante o silêncio.
- Perguntas citadas, retóricas e notificações de terceiros não autorizam abrir
  esse turno interativo.

## Contrato

O JSON do raciocínio inclui `aguarda_resposta`, um booleano. A decisão é
transmitida com a `CHAT_RESPONSE` e seu `correlacao_id`. O celular só aplica a
decisão à resposta correspondente ao pedido de voz ativo, após a reprodução
da fala terminar. Um `false` explícito prevalece mesmo se o texto tiver `?`.
Strings como `"true"` não são aceitas como autorização.

O prompt agora recebe o histórico recente da conversa, além dos fatos e
resumos já recuperados. Assim, uma resposta curta como “sim” chega ao modelo
junto da pergunta anterior. Isso não concede permissões adicionais para executar
ações: os controles existentes de origem e autorização continuam aplicados.

Para receber a decisão baseada no contexto, publique a atualização do backend
no Render. Até esse deploy, o APK reconhece de forma conservadora algumas
perguntas diretas no final da resposta, como “Qual aplicativo?” e “Quer que eu
acenda?”. Essa compatibilidade não equivale à classificação semântica completa.

No Android, a visibilidade da ilha (`isAssistantSessionActive`) continua
controlando a apresentação de respostas e notificações. A ocupação do turno
(`isAssistantSessionBusy`) pausa o detector somente durante preparação,
reconhecimento, raciocínio e fala. Os estados de espera e erro liberam a chamada.

Código incremental: [android-turnos-voz.patch](patches/android-turnos-voz.patch).

## Vínculo do Android com a assistente

Em 21/10/2026, o aparelho mantinha a Ollie como assistente padrão, mas o
gerenciador de voz mostrava `mBound=true mService=null` e uma conexão encerrada.
A detecção vibrava e chegava ao serviço do app, que aguardava a liberação do
Android para abrir a sessão. O vínculo foi restabelecido preservando a seleção
da Ollie. O usuário confirmou abertura e resposta fora do app.

Uma compilação, um processo vivo ou testes de interface passando não comprovam
que esse vínculo está ativo. Depois de instalar um APK ou executar testes
instrumentados, execute:

```powershell
.venvs/Scripts/python.exe tools/android/verificar_assistente.py
```

A verificação é somente leitura. Retorna sucesso apenas quando a Ollie está
selecionada e o serviço principal possui uma conexão viva. Não confunde o binder
da sessão com o do serviço principal, nem imprime preferências ou tokens.
Se estiver desconectado, reabra a seleção de assistente digital nas configurações
do Android e selecione novamente a Ollie; confira o resultado e teste a chamada.

## Verificações automatizadas

Passaram 48 testes unitários Android e 70 testes focados do backend. Os novos
casos cobrem perguntas e respostas concluídas, decisão explícita com precedência
sobre pontuação, perguntas citadas, liberação da chamada com a ilha visível,
tipo booleano do contrato, notificações externas e histórico enviado ao modelo.

No APK instalado, o usuário confirmou os dois caminhos fora do app: chamar de
novo sem fechar a ilha depois de uma resposta concluída e receber escuta direta
após pedir uma pergunta curta. O vínculo principal com o Android permaneceu
conectado após a instalação e os testes de voz.

Registro: [turnos-voz-android-2026-10-21.json](validacoes/turnos-voz-android-2026-10-21.json).
