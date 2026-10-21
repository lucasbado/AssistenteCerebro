# Ativação por voz no Android

O celular detecta “Ei Ollie” com o modelo pessoal que já funciona no PC.
O detector usa o microfone do próprio celular e roda localmente, com ONNX Runtime
Android 1.31.0. A detecção não depende do PC nem do Render. Depois da chamada,
a sessão de assistente continua usando o reconhecedor Android em português e a
conexão habitual com a Ollie para os pedidos e respostas.

## Uso

Em **Sistema → Ativação por Voz (Beta)**, ative a opção e permita o microfone.
Aguarde **“Ouvindo Ei Ollie no celular”**, diga a chamada, espere a assistente
abrir e então faça o pedido. A Ollie deve estar selecionada como assistente
padrão. A notificação permanente informa se está ouvindo ou pausada.

A escuta libera o microfone antes de abrir o reconhecimento do comando e fica
pausada durante a conversa e a resposta falada. Ao retomar, aquece os históricos
do detector por 32 blocos de 80 ms, aproximadamente 2,56 segundos.

## Implementação

O código Android está em `D:\Programacao\Projetos\AssistenteCell`:

- `OnnxWakeDetector`: PCM16 mono a 16 kHz → mel → embeddings → modelo pessoal.
  Confere os hashes dos três modelos e fecha tensores e resultados por bloco.
- `WakeWordRecorder`: captura blocos completos de 1.280 amostras em uma thread
  própria. Registra somente score e nível de áudio, sem gravações ou transcrições.
- `WakeWordGate`: exige dois scores consecutivos de pelo menos 0,5, rearme e
  intervalo de cinco segundos entre ativações.
- `WakeWordService`: coordena carregamento, notificação, pausa, retomada e abertura
  da sessão existente. Não usa mais frases aproximadas como “ei, olha” para acordar.

O processamento reproduz a cadeia de inferência do openWakeWord 0.6.0,
incluindo amplitudes PCM sem normalização para `[-1, 1]`, histórico de mel
76 × 32 e embeddings 16 × 96.

## Preparar os modelos para outro build local

Com o ambiente e os modelos pessoais já preparados no PC:

```powershell
.artifacts/wakeword/venv/Scripts/python.exe tools/wakeword/preparar_android.py --projeto D:/Programacao/Projetos/AssistenteCell
```

O utilitário copia os três modelos para `app/src/main/assets/wakeword/` e gera
`models.properties`. Essa pasta é ignorada pelo Git. O APK contém os modelos
necessários para detecção, mas as gravações de calibração não entram no APK principal.

Para comparação instrumentada, a opção `--audios` recebe uma pasta local com
subpastas `positivo/` e `negativo/`. Os arquivos de teste também são ignorados pelo
Git e pertencem somente ao APK de testes. Remova esse APK depois da validação:

```powershell
adb uninstall com.example.assistentecell.test
```

As alterações desta integração e da navegação estão arquivadas como código-fonte
em [android-wakeword-navegacao.patch](patches/android-wakeword-navegacao.patch),
relativas aos arquivos locais anteriores ao trabalho. O patch não inclui os
modelos pessoais nem outras alterações pré-existentes do projeto Android.

## Validação em 21/10/2026

No Galaxy S23, foram comparados oito áudios locais com a execução Python:
três chamadas tiveram uma ativação cada e cinco frases negativas tiveram zero.
A maior diferença numérica de score foi aproximadamente `1,01e-6`; as medianas
de inferência ficaram entre 3,29 e 3,44 ms por bloco de 80 ms na execução final.

O usuário confirmou que a chamada abriu a assistente e recebeu resposta tanto
dentro quanto fora da tela do app. A escuta do PC, pausada temporariamente para
esse teste, foi restaurada. O teste não mede consumo de bateria, funcionamento
prolongado com a tela bloqueada nem taxa geral de falsos positivos.

Resultados numéricos: [wakeword-android-2026-10-21.json](validacoes/wakeword-android-2026-10-21.json).

## Navegação e conversa

A página `chat` agora está registrada no `NavHost`. Os pedidos para abri-la por
notificação ou sessão aguardam a primeira entrada de navegação e são consumidos
após a abertura, inclusive quando a atividade já existe. Isso corrige os dois
erros observados: destino ausente e consulta do grafo antes da inicialização.

Uma barra inferior com Base, Conversa, Controle, Poderes e Sistema substitui os
ícones sem rótulo sobrepostos ao conteúdo. Mantém o fundo escuro, bordas suaves,
roxo e ciano, destaca a página selecionada e reserva espaço para o conteúdo.
As abas restauram o estado sem acumular cópias no histórico. Páginas de detalhe
têm Voltar; o controle de mouse continua acessível pela Base, como bandeja.
Os rascunhos da Base e da Conversa sobrevivem à troca de páginas. O tema da
atividade mantém a paleta escura da Ollie mesmo quando o Android usa tema claro;
isso evita texto preto sobre o fundo preto. A conversa vazia mostra uma orientação
curta para digitar ou usar o microfone.

Passaram 44 testes unitários e cinco testes instrumentados no S23: abertura do
chat na criação da atividade, troca de abas/Voltar, rascunho com teclado, abertura
do chat por um novo intent e comparação numérica do detector com Python.

A biblioteca de benchmark fica no APK de testes, conforme a separação de
[dependências de teste do Android](https://developer.android.com/build/dependencies),
evitando carregar uma versão antiga do monitor de testes dentro do APK principal.
