# Chamada com a pronuncia real no PC

O modelo sintetico `hey ouh_lee` nao reconheceu nenhuma das seis chamadas reais
da primeira coleta de 20/10/2026, apesar de o microfone B1 receber fala com
volume suficiente. Uma amostra Piper reconhecida nao comprovava compatibilidade
com o jeito de o usuario dizer **Ei Ollie**.

O laboratorio agora tem `tools/wakeword/personalizar.py`. Ele usa os embeddings
de audio do openWakeWord e treina um classificador pessoal de regressao logistica
em CPU. Isso cria outro classificador; nao altera os pesos dos modelos
compartilhados nem depende do STT transcrever o nome. O Vosk continua sendo usado
somente para o pedido depois da ativacao.

## Preparar um candidato

Gravacoes devem ficar em `.artifacts/wakeword`, ignorado pelo Git. Nenhum audio
e enviado pelo helper. Feche ou desative a escuta da Ollie durante a coleta,
para nao executar pedidos de teste.

Use WAV mono, PCM16, 16 kHz: pelo menos seis arquivos em `positivo/`, com uma
chamada curta isolada por arquivo e pausas antes/depois, e seis em `negativo/`,
com frases comuns. Inclua frases parecidas, como **Ei, olha aqui**, **Eu vou
ali** e **Hoje eu li**. Varie tom, distancia e volume. Fundos adicionais devem
ficar em outra pasta; gravacoes de validacao nao podem ser reutilizadas nela.

```powershell
$ollieLocal = '.\.artifacts\wakeword\venv\Scripts\python.exe'
& $ollieLocal -m pip install -r tools\wakeword\requirements-personalizar.txt
& $ollieLocal tools\wakeword\personalizar.py --pasta .artifacts\wakeword\minha-coleta --modelo-base .artifacts\wakeword\modelos\hey_ollie.onnx --fundos .artifacts\wakeword\fundos --saida .artifacts\wakeword\meu-candidato --calibrar
```

O ambiente local precisa estar preparado por `tools/wakeword/preparar_pc.ps1`.
O treino acrescenta variacoes pequenas de velocidade as chamadas. A separacao
da validacao cruzada acontece por **gravacao inteira**, antes das variacoes;
assim uma versao acelerada da chamada avaliada nao entra no treino daquele
fold. Gravacoes identicas renomeadas tambem sao rejeitadas. O relatorio inclui
resultados, hashes e limites.

Com `--calibrar`, o corte e calculado no meio da margem entre a pior chamada
e a frase negativa mais parecida, em escala de logits, usando a validacao do
treino. Se as classes se sobrepoem, o helper recusa a calibracao. O corte so
pode ficar mais restritivo que o inicial. Ele e incorporado ao intercepto do
ONNX: o worker continua exigindo score 0,5 e duas janelas consecutivas. Os
resultados usados para escolher esse corte sao de calibracao, nao um benchmark
independente.

O candidato nao e instalado automaticamente. Use uma **nova coleta**, que nao
entrou no treino, para avaliar positivos e negativos com `testar.py avaliar`.
Se uma frase do teste virar exemplo de treino para corrigir uma confusao, ela
deixa de ser uma validacao independente; e preciso testar outras gravacoes.
Mesmo bons resultados em poucos segundos nao estimam ativacoes por dia, TV,
musica, outras pessoas ou mudancas no microfone.

Para instalar um candidato avaliado, feche a Ollie e use
`preparar_desktop.py --model CAMINHO_DO_CANDIDATO.onnx` no ambiente isolado.
Esse comando preserva as preferencias existentes sem `--enable`. Reabra o app.
O modelo anterior pode ser reinstalado pelo mesmo comando; seus arquivos
originais continuam na pasta de treino. Nada disso exige deploy do Render.

## Resultado no PC em 20/10/2026

O primeiro candidato reconheceu as tres chamadas de uma nova rodada, mas
confundiu **Ei, olha aqui**. Essas frases viraram negativos de treino. A rodada
seguinte revelou a necessidade de apertar o corte. O candidato final usa seis
chamadas reais, nove frases reais e cinquenta fundos sinteticos. O corte bruto
calculado apenas na validacao do treino foi 0,991709; nao foi escolhido usando
as pontuacoes da ultima coleta.

O ONNX final reconheceu as tres chamadas da ultima coleta e rejeitou suas
cinco frases negativas, incluindo **Ei, olha aqui** e **Ei, olha a luz**.
Tambem rejeitou tres arquivos de outras chamadas do upstream e sessenta
segundos de silencio. As gravacoes da ultima coleta nao entraram nos pesos nem
no calculo do corte, mas orientaram o desenvolvimento do procedimento; esses
resultados sao testes de desenvolvimento, nao um benchmark cego. Ainda falta
medir uso prolongado, musica, TV, outras pessoas e variacoes de distancia.

O candidato foi instalado localmente em `.artifacts/wakeword/modelos/hey_ollie.onnx`,
preservando a entrada B1 e a voz ativa. SHA256:
`38cacbdd4575d6618d26d704d4b7e81f087c11e6dbc1e02db4b6fd187503832f`.
O modelo sintetico anterior permanece em `.artifacts/wakeword/treino-ouh-lee`.
Gravacoes e pesos pessoais ficam fora do Git. O relatorio resumido, sem audio,
esta em [validacao da pronuncia real](validacoes/wakeword-pronuncia-real-2026-10-20.json).
