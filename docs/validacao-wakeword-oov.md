# Regressao do fonemizador: hey ouh_lee

O log do Colab mostrou uma falha adicional na geracao de negativos. A frase
`hey ouh_lee` contem `ouh_lee`, ausente no CMUDict. Nesse caso, o openWakeWord
baixa o modelo DeepPhonemizer; a URL S3 original retornou HTTP403 e o downloader
externo gravou o XML de acesso negado como se fosse o checkpoint `.pt`.
A tentativa de carregar esse XML causou `invalid load key, '<'`.

O treino anterior com `hey ollie` nao exercitou esse caminho porque suas
palavras estavam no dicionario. A falha nao veio dos avisos de Torch ou CUDA.

## Correcao

O helper identifica palavras fora do dicionario antes de sintetizar os audios.
Quando necessario, prepara o checkpoint no caminho exato usado pelo upstream,
com uma [copia publica em revisao fixa](https://huggingface.co/niobures/G2P/blob/650ef1ac309a58faf82028c13492f7147e42e107/DeepPhonemizer/pretrained/en_us_cmudict_forward.pt).
O modelo tem 66.725.366 bytes e SHA256
`c2e1fb223d7e027bf7b33052540c6f71d19db6d7fd87ab8671152b8b114501c2`.

Um arquivo XML ou outro cache com hash diferente e substituido. O download vai
para um arquivo temporario e so e promovido depois da verificacao de hash.
Respostas HTTP com erro nao viram checkpoints; HTML com status200 tambem falha
na verificacao. Depois o helper carrega o modelo e verifica a geracao de fonemas.
Nao altera o clone original, o kernel, os agentes nem as dependencias do Render.

## Execucao real da regressao

[Execucao GitHub Actions](https://github.com/lucasbado/AssistenteCerebro/actions/runs/39526723368),
commit `042c3057e1fa7c74809aa1f326602c5dafeff9d7`, Linux/Python3.11/CPU.
O [relatorio JSON](validacoes/wakeword-oov-2026-10-20.json) contem os valores exatos.

| Verificacao | Resultado |
| --- | --- |
| Semear o checkpoint com o XML do erro403 | Executado |
| Substituir o arquivo invalido e validar o hash do download real | Passou |
| Carregar DeepPhonemizer e prever `ouh_lee` | `[UW][L][IY]` |
| Gerar texto negativo adversarial pelo openWakeWord | `heymann polygram's` |
| Sintetizar o negativo pelo Piper | WAV mono PCM16, 16kHz, 1,235s |
| Aumentacao, embeddings e uma atualizacao Adam | Passou |
| Exportacao ONNX e comparacao de inferencia com PyTorch | Passou |

O teste curto levou 5,886s depois da preparacao. Ele comprova o reparo do cache
e o caminho OOV real; a verificacao curta nao e uma medicao da qualidade da wake word.

## Treino completo da frase do usuario

O [treino completo com `hey ouh_lee`](https://github.com/lucasbado/AssistenteCerebro/actions/runs/39526723300)
tambem terminou com sucesso em Linux/Python3.11/CPU, com o mesmo commit.
Incluiu todos os dados reais, positivos e negativos de treino/validacao,
aumentacao, tres sequencias de 10.000/1.000/1.000 passos, mescla de checkpoints,
exportacao ONNX, verificacao do grafo, hash e inferencia ORT.
O [relatorio do treino](validacoes/wakeword-ouh-lee-treino-2026-10-20.json)
preserva a frase, os fonemas e as metricas originais.

O modelo foi baixado e conferido no PC em
`.artifacts/wakeword/treino-ouh-lee/hey_ollie.onnx`, sem substituir o modelo
anterior da outra frase. Tem 205.430 bytes e SHA256
`59d03446f5901a73efc43f29ca602f3c7564481620e846cdeecceb41889c92cd`.

No [avaliador local](validacoes/wakeword-ouh-lee-avaliacao-local-2026-10-20.json),
com limiar0.5 e duas janelas consecutivas, a previa sintetica produziu uma
ativacao, pico0,835990. Trinta segundos de silencio nao produziram ativacoes,
pico0,000887. Esses testes usam arquivos; nao capturam o microfone.

O CLI reportou accuracy0,725, recall0,454 e1,239 falsos positivos por hora no
corpus de validacao. O recall ainda e baixo para considerar a ativacao confiavel.
Essas metricas do upstream nao medem a voz/ambiente do usuario nem a taxa de
ativacoes da regra local. O modelo continua experimental. CUDA e integracao
Android nao foram validados por essa execucao em CPU.

Os251 testes locais passaram, incluindo reparo do XML, rejeicao de HTML com
status200, erro403, cache valido, inferencia OOV e falha antes de sintetizar os
positivos. O teste curto automatico passou a incluir essa regressao de OOV.

## Retomar o Colab existente

Use a celula de atualizacao em [treinar-wakeword-ollie.md](treinar-wakeword-ollie.md),
no mesmo ambiente do Colab. Depois repita a etapa4 com `frase = 'hey ouh_lee'`
e a aprovacao da pronuncia marcada. O helper corrige o arquivo invalido; nao e
necessario excluir os dados ou os positivos que ja foram gerados.
