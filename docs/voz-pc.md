# Ativacao por voz no app do PC

O desktop usa um modelo ONNX local para detectar a chamada. Nesta instalacao,
o modelo sintetico `hey ouh_lee` foi substituido pelo candidato pessoal descrito
em [Chamada com a pronuncia real](personalizar-wakeword-pc.md).
Depois da deteccao, o Vosk reconhece o comando em portugues, localmente. O texto
segue pelo WebSocket do chat existente, com origem `pc.chat`, canal `voz` e um
ID de correlacao proprio. A resposta correspondente usa a voz neural do app,
com fallback para a voz do Windows.

## Usar

1. Abra a Ollie Master no PC e confira a conexao com o servidor.
2. Clique em **Ativar Ei Ollie**. Selecione o canal de captura do microfone;
   a opcao Padrao mostra o dispositivo que o Windows esta usando.
3. Diga **Ei Ollie**, faca uma breve pausa e espere **Pode falar**.
4. Faca o pedido em portugues. O app mostra a transcricao e aguarda a resposta.

A deteccao traz a janela a frente mesmo quando minimizada. **Falar agora**
inicia uma captura sem exigir a chamada; o comando `wake_ollie` dos botoes
tambem usa essa captura quando a voz esta ativa. **Cancelar** encerra a
conversa atual. **Desativar Ei Ollie** libera o microfone e encerra o detector.
Minimizar mantem a chamada ativa; fechar o app encerra detector e reproducao.

No Voicemeeter, selecione um endpoint de captura como **Voicemeeter Out A2**
ou **Out B1**, conforme o roteamento do microfone. **Voicemeeter Input** e um
endpoint de reproducao. O indicador de nivel ajuda a conferir se a fala chega
ao canal selecionado. O modelo exige audio mono PCM16 a 16kHz, contrato aplicado
pelo capturador local.

## Instalar ou trocar o modelo

Na raiz do repositorio:

```powershell
.\tools\wakeword\preparar_pc.ps1 -Modelo "CAMINHO\hey_ollie.onnx"
```

O script prepara o ambiente isolado e os modelos em `.artifacts/wakeword`.
Pode receber `-ModeloPortugues "PASTA_DO_VOSK"`; sem esse parametro e sem um
modelo ja instalado, baixa o modelo portugues pequeno do site oficial Vosk.
O classificador ONNX e validado antes da instalacao. As preferencias ficam em
`.artifacts/wakeword/desktop-settings.json`. O primeiro preparo deixa a voz
desativada ate o usuario ativar no app. Nesta instalacao, o teste solicitado
foi preparado com `enabled=true` e **Voicemeeter Out B1**. A leitura do mixer
confirmou que o microfone Realtek do strip0 ja estava roteado paraB1, enquanto
o padrao do Windows apontava paraA2. A selecao no app foi ajustada para esse
canal de captura.

O modelo sintetico da primeira rodada tinha SHA256
`59d03446f5901a73efc43f29ca602f3c7564481620e846cdeecceb41889c92cd`.
Os arquivos de treino e de modelos ficam fora do Git. A preparacao nao instala
dependencias no backend nem exige deploy do Render.

## Separacao e ciclo de vida

- O processo Python possui o microfone, a deteccao e o reconhecimento local.
- O supervisor Rust inicia/encerra o processo e encaminha eventos tipados ao app.
- O controlador TypeScript coordena uma conversa por vez, transporte e reproducao.
- O backend continua recebendo texto pelo contrato existente; o kernel nao muda.

O Python recebe controle JSON por stdin e publica eventos JSON por stdout.
Antes de confirmar pausa, fecha a captura. O Rust aguarda esse ACK. O app
aguarda a pausa antes de reproduzir audio e retoma a deteccao depois da fala,
com um segundo para descartar o final da propria resposta. Enquanto aguarda
resposta, o microfone permanece liberado. A captura de comando tem limite de
12 segundos; a espera pela resposta tem limite de45 segundos.

IDs de instancia e de correlacao impedem eventos de processos antigos ou
respostas atrasadas de reabrir a captura. Desativacao e fechamento interrompem
o processo; o EOF no stdin tambem encerra o capturador. O worker nao acessa
tokens, servidor ou automacoes. Audio nao e gravado ou enviado por ele; somente
o texto reconhecido segue para o chat. O diagnostico de estado em
`.artifacts/wakeword/desktop-events.jsonl` nao inclui audio nem transcricao.

## Verificacao desta rodada

- 255 testes Python passaram; 14 testes do desktop passaram.
- TypeScript/Vite e o executavel Tauri de Windows compilaram.
- Modelo da chamada e modelo pt-BR carregaram de verdade no ambiente do PC.
- Um fluxo com audio sintetico detectou a chamada, reconheceu
  `como esta luz do quarto` e publicou um unico comando.
- A captura real abriu e confirmou pausa, retomada e encerramento. O app foi
  aberto com a captura B1 ativa, confirmada pelo evento `state=wake` do worker.

No teste ao vivo com o modelo pessoal, o usuario confirmou **Ativou e respondeu**. O
classificador sintetico tinha recall45,4% no corpus da
[validacao do treino](validacao-wakeword-oov.md) e perdeu as seis chamadas reais
iniciais. A personalizacao e sua calibracao agora sao avaliadas tambem com
gravacoes reais. Os resultados e limites atuais estao no
[relatorio da pronuncia](personalizar-wakeword-pc.md). A amostra continua pequena
e nao comprova uma taxa de erro diaria.
