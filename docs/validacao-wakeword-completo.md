# Treino completo de Hey Ollie

Em 20/10/2026, todas as etapas terminaram com sucesso em Linux, Python 3.11.17,
PyTorch 2.5.0 e CPU. Fonte: [execucao real no GitHub Actions](https://github.com/lucasbado/AssistenteCerebro/actions/runs/39491886927),
commit `669122395e66889d1cfc1433f8119d7ac44d7c7a`.
O [relatorio completo](validacoes/wakeword-treino-completo-2026-10-20.json)
registra dados, revisoes, hash do script e hash do modelo.

## Etapas executadas

| Etapa | Resultado |
| --- | --- |
| Preparar dependencias, importar treino/Piper e carregar modelos ONNX | Passou |
| Gerar previa de `hey ollie` | WAV mono PCM16, 16 kHz, 0,575 s |
| Baixar e converter AudioSet | 685 audios de fundo preparados |
| Baixar MIT RIR | 270 respostas de ambiente |
| Baixar features negativas e de validacao | 17.280.000.128 e 184.836.608 bytes; cabecalhos conferidos |
| Gerar exemplos positivos e negativos adversariais, treino e validacao | Passou |
| Aplicar aumentacao de audio e extrair embeddings | Passou |
| Executar `auto_train` original | Tres sequencias: 10.000, 1.000 e 1.000 passos |
| Mesclar checkpoints e exportar ONNX | Passou |
| Conferir grafo ONNX, SHA256 e inferencia no ONNX Runtime | Passou |

O fluxo completo levou aproximadamente 17 minutos nesse runner. A etapa de
treino inclui geracao, aumentacao e as tres sequencias; nao foi substituida
pelo teste curto de uma atualizacao de pesos.

## Correcoes aplicadas

O AudioSet mudou de TAR para Parquet no `main`. O download usa agora a revisao
fixa que ainda possui `bal_train09.tar`. MIT e features tambem usam revisoes
fixas. Downloads sao retomaveis e os tamanhos/cabecalhos sao conferidos antes
de marcar os dados como prontos.

Uma copia derivada do CLI mantem todas as janelas de validacao em leitura
mapeada e executa inferencia em lotes de 2048, evitando materializar varios GB
na RAM. O carregador de treino usa um leitor continuo. O clone original fica
intacto. A correcao da flag TFLite impede iniciar uma conversao nao solicitada
apos exportar o ONNX. Em CPU, os lotes de sintese e aumentacao sao menores.

Uma nova tentativa remove o manifesto anterior antes de executar. Assim, uma
falha nao deixa um resultado antigo aparentando ser o resultado atual.

## Modelo e teste local

O artefato foi baixado para `.artifacts/wakeword/treino-completo/`, fora do Git.
O modelo tem **205.430 bytes**, SHA256
`42cda4d736a2d1742b5c174a3cc00157011b915057372fb21d06df231664dd2e`.

Com o mesmo avaliador local que sera usado para a voz real, limiar `0.5` e duas
janelas consecutivas:

| Entrada | Resultado |
| --- | --- |
| Previa sintetica `hey ollie` | Uma ativacao; pico 0,862416 |
| 30 segundos de silencio | Zero ativacoes; pico 0,000824 |

Os [resultados locais](validacoes/wakeword-completo-avaliacao-local-2026-10-20.json)
preservam os valores exatos. Uma amostra sintetica e silencio verificam o
caminho de inferencia, sem medir conversas, musica ou a pronuncia do usuario.

Para ouvir com o microfone, a partir da raiz do projeto:

```powershell
.\tools\wakeword\ouvir.ps1 -Modelo ".artifacts\wakeword\treino-completo\hey_ollie.onnx"
```

## Qualidade ainda experimental

O CLI original reportou accuracy **0,746**, recall **0,506** e **2,124 falsos
positivos por hora** no seu corpus de validacao. Esses valores sao registrados
como metricas do upstream; nao representam uma medicao em uso real nem a taxa
de ativacoes da regra local com duas janelas consecutivas.

O recall ainda e baixo para ativacao confiavel: cerca de metade dos positivos
da validacao foi reconhecida. A proxima etapa e avaliar varias gravacoes reais
de "Ei Ollie" e negativos com fala/ambiente, depois ajustar pronuncia, exemplos
e limiar com esses dados. CUDA/Colab e integracao Android nao foram testados
por esta execucao em CPU.

## Repetir

O workflow `wakeword-treino-completo.yml` fica disponivel para execucao manual
na aba Actions, com runner Linux padrao. O teste curto continua automatico
para mudancas nas ferramentas. O treino completo guarda modelo, previa e
relatorio por tres dias; a copia local ja baixada nao depende desse prazo.
