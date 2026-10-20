# Verificação real do pipeline de wake word

Execução concluída em 20/10/2026, com Python 3.11.17 no Linux, em CPU.
Fonte: [execução GitHub Actions](https://github.com/lucasbado/AssistenteCerebro/actions/runs/39487054223).
Commit executado: `fecc64baaaa792484da1d1a2826ea787efc6e2ba`.
O [relatório JSON](validacoes/wakeword-linux-2026-10-20.json) preserva versões,
origens, formas dos tensores, perdas e hashes capturados dos logs dessa execução.

## Resultado observado

| Etapa executada | Resultado |
| --- | --- |
| Preparação Linux com dependências fixadas | Passou |
| Imports individuais, incluindo Piper, TorchMetrics, SpeechBrain e DeepPhonemizer | 40 de 40 passaram |
| Variável gráfica do Colab herdada pelo processo | Substituída por Agg no ambiente isolado |
| Piper: gerar `hey ollie` | Uma amostra não silenciosa, mono PCM16, 16 kHz, 0,725 s |
| Aumentação real com ganho | Um lote, uma amostra |
| Extração de características de voz e silêncio | Tensor float32 `[2,16,96]`, valores finitos e exemplos distintos |
| Atualização real do modelo upstream | Uma chamada Adam, contador 1 e dez tensores alterados |
| Perda antes/depois | 0,858340 → 0,677068 |
| Exportação e validação ONNX | Passou; arquivo de 859.394 bytes |
| Inferência ONNX contra PyTorch | Passou; erro absoluto máximo 8,94 × 10⁻⁸ |

O verificador durou 4,198 segundos depois da preparação. Esse tempo não inclui
instalar as dependências e baixar o modelo Piper.

## Limites desta verificação

Foi executada uma atualização real com a classe, perda e otimizador do treinamento
original. O `train_model(max_steps=1)` do upstream acumula exemplos antes de
atualizar pesos; por isso o teste usa explicitamente `loss.backward()` e
`optimizer.step()` e confere o contador interno do Adam.

O positivo é uma voz sintética e o negativo é silêncio. A verificação não baixa
os grandes corpora, não executa a geração de negativos adversariais, não roda o
treino automático completo e não mede falsos positivos ou a pronúncia do usuário.
CUDA, bateria e integração Android também não foram avaliados. O modelo de uma
etapa fica na pasta de verificação e não substitui um detector real da Ollie.

## Repetir

O workflow `.github/workflows/wakeword-verificacao.yml` usa runner Linux padrão
e permissões somente de leitura. É disparado por mudanças nas ferramentas de
wake word na `main`, ou manualmente na aba Actions. Não usa tokens da Ollie,
microfone, dados pessoais ou servidor Render.

Em Linux com Python 3.11, a partir do repositório:

```bash
export OLLIE_WAKEWORD_WORK="$PWD/.artifacts/wakeword-linux"
mkdir -p "$OLLIE_WAKEWORD_WORK"
cp tools/wakeword/requirements-treino.txt "$OLLIE_WAKEWORD_WORK/requirements-treino.txt"
python tools/wakeword/colab_ollie.py preparar --workspace "$OLLIE_WAKEWORD_WORK" --cpu
python tools/wakeword/validar_pipeline.py --workspace "$OLLIE_WAKEWORD_WORK"
```

No notebook atualizado, depois de preparar o ambiente, uma célula com
`etapa('verificar')` executa o mesmo teste em CPU e grava o relatório em
`/content/ollie-wakeword/verificacao-pipeline/ultimo-relatorio.json`.

O passo seguinte para o modelo utilizável continua sendo ouvir a prévia da
chamada e executar o [treino com mais exemplos](treinar-wakeword-ollie.md).
