# Começar o detector “Hey Ollie”

A chamada e o comando usam componentes separados. O novo detector vai identificar
o som de “Hey Ollie”/“Ei Ollie”; a sessão de conversa existente continuará usando
`pt-BR`. Esta etapa prepara e avalia o modelo no PC. Ainda não instala um detector
novo no Android e não muda o backend, o kernel ou os agentes.

## 1. Abrir o treinamento guiado

Use o [notebook guiado da Ollie no Colab](https://colab.research.google.com/github/lucasbado/AssistenteCerebro/blob/main/tools/wakeword/treinar_ollie.ipynb).
Ele mantém o Python padrão do Colab e cria um ambiente separado com Python 3.11.
Isso resolve a incompatibilidade encontrada no notebook simplificado original:
o ambiente Python 3.13 não conseguiu instalar `piper-phonemize-cross` e
`torchvision==0.20.0`. O notebook da Ollie usa `piper-phonemize==1.1.0`, que tem
wheel Linux para Python 3.11, e versões fixas do PyTorch e do código de treinamento.
O treino completo nesse novo ambiente ainda precisa ser executado no Colab.

1. Entre na sua conta Google se for solicitado. Pode usar **Salvar uma cópia no Drive**
   para guardar suas alterações.
2. Em **Ambiente de execução → Alterar tipo de ambiente de execução**, escolha uma
   GPU T4 se estiver disponível na modalidade gratuita. Não é preciso contratar
   plano ou comprar unidades de computação. A disponibilidade gratuita depende do Colab.
3. Execute **1. Preparar ambiente compatível**. Instalações e preparação podem levar minutos.
4. Em **2. Ouvir a chamada antes de treinar**, mantenha o campo `frase` como
   **`hey ollie`** e clique no ▶ dessa etapa.
5. Ouça o player de áudio que aparecer. A amostra deve soar como a chamada que você
   pretende falar. Se a pronúncia do nome estiver diferente, experimente
   `hey_oh_lee`, execute a etapa de prévia novamente e compare. A grafia é somente
   uma instrução para gerar o som: não muda o nome da assistente.

Confira o áudio antes de iniciar o treino completo. Não assuma que a grafia inglesa
produziu automaticamente a sua pronúncia brasileira.

## 2. Treinar o primeiro modelo

Depois de aprovar a pronúncia, execute **3. Baixar dados**. Depois, em
**4. Treinar Hey Ollie**, marque `ouvi_e_aprovei_a_pronuncia` e mantenha os valores iniciais:

| Campo | Valor inicial |
| --- | --- |
| `exemplos` | `1000` |
| `passos` | `10000` |

São os valores do primeiro experimento, não uma meta de qualidade para produção.
O peso inicial para ativações indevidas permanece em `1500`, como no treino original.
Mantenha a aba aberta enquanto processa. O ambiente isolado evita trocar os pacotes
que o kernel do Colab já importou. Não é necessário reiniciá-lo por esse motivo.
Se houver erro, pare nesse ponto e guarde o texto do erro; não execute as próximas
etapas com dados ou dependências incompletos.

Se uma versão antiga mostrar somente `CalledProcessError`, reabra a versão atual
do notebook e execute a preparação novamente. A execução atual captura a saída
do processo e inclui as últimas linhas da causa no erro final. Também salva os
logs completos em `/content/ollie-wakeword/logs`, acessível pela lateral Arquivos
do Colab. Reabrir o notebook não exige apagar o ambiente já preparado.

Ao terminar, execute **5. Baixar modelo ONNX** para baixar `hey_ollie.onnx` e
`ultimo_modelo.json`. A versão guiada exporta somente ONNX e não instala conversores
TensorFlow/TFLite. O manifesto registra frase, parâmetros e hash do modelo.

O notebook usa dados com restrições de uso, assim como a referência original;
trate o modelo como destinado ao uso pessoal não comercial. Não é preciso enviar suas gravações
ou tokens da Ollie para fazer esse primeiro treino sintético.

## 3. Testar no PC

As ferramentas locais ficam em `tools/wakeword`. O ambiente, modelos, gravações e
relatórios ficam em `.artifacts/wakeword`, ignorado pelo Git. As dependências não
entram no `requirements.txt` do servidor e não vão para o Render.

A partir de `D:\Programacao\AssistenteCell`:

```powershell
# Só é necessário preparar uma vez (já executado nesta revisão).
.\tools\wakeword\preparar.ps1

# Troque pelo caminho real do arquivo baixado no Colab.
.\tools\wakeword\ouvir.ps1 -Modelo "$env:USERPROFILE\Downloads\hey_ollie.onnx"
```

Diga “Ei Ollie”, faça uma pausa e observe a mensagem **Chamada detectada!**.
Esse teste somente mostra detecções; não abre aplicativos nem aciona a casa.
Encerre com **Ctrl+C**. Não grava nem transmite o áudio nesse modo.

Se o microfone padrão estiver errado, liste os dispositivos e informe o número
de uma entrada com canais de captura:

```powershell
.\.artifacts\wakeword\venv\Scripts\python.exe tools\wakeword\testar.py microfones
.\tools\wakeword\ouvir.ps1 -Modelo "CAMINHO_DO_MODELO.onnx" -Dispositivo 1
```

## 4. Medir sua pronúncia e ativações indevidas

Grave uma chamada por arquivo positivo, com pequena pausa antes/depois. Varie
distância e volume entre gravações. Os negativos devem ter fala e ambiente sem
a chamada. Cada captura só começa depois de você pressionar Enter.

```powershell
$ollieTeste = '.\.artifacts\wakeword\venv\Scripts\python.exe'
& $ollieTeste tools\wakeword\testar.py gravar --tipo positivo --quantidade 10 --segundos 4
& $ollieTeste tools\wakeword\testar.py gravar --tipo negativo --quantidade 3 --segundos 20
& $ollieTeste tools\wakeword\testar.py avaliar --modelo "CAMINHO_DO_MODELO.onnx" --pasta .artifacts\wakeword\audios\positivo --tipo positivo
& $ollieTeste tools\wakeword\testar.py avaliar --modelo "CAMINHO_DO_MODELO.onnx" --pasta .artifacts\wakeword\audios\negativo --tipo negativo
```

O avaliador processa WAV mono, PCM 16 bits e 16 kHz, reinicia o detector entre
arquivos e exige duas janelas consecutivas acima do limiar inicial `0.5`. Aplica
intervalo de cinco segundos e exige que o score caia antes de aceitar outra
ativação. Isso evita contar o mesmo som muitas vezes.

O score não é uma porcentagem calibrada de certeza. Ajustar `--limiar` troca
sensibilidade por ativações indevidas; baixar o limiar sem testar negativos pode
produzir um detector que ativa com qualquer fala. Testes curtos servem para
comparar modelos e pronúncias, mas não comprovam uma taxa de erro diária.

## Estado atual e próximo passo

O ambiente local foi instalado e os modelos compartilhados foram baixados. Uma
inferência técnica com o modelo pronto Hey Jarvis e três segundos de silêncio
foi concluída sem erro e sem ativações. Isso valida o carregamento e o caminho
de áudio, mas não valida “Ei Ollie”. O modelo personalizado depende do treino
no Colab e do teste da pronúncia pelo usuário.

O novo notebook foi validado estruturalmente; o treino completo no Linux e a
pronúncia da prévia continuam pendentes. Não há um modelo Hey Ollie pronto nesta
revisão. Se o helper ou as dependências do treino forem alterados, regenere o
notebook com `python tools/wakeword/gerar_notebook.py` para atualizar seus hashes.
Os 20 testes locais passaram, cobrindo intervalo de ativação, rejeição de scores
inválidos, formato de áudio, reinício entre gravações, integridade do notebook e
propagação de erros reais dos processos para a saída visível.

Depois dessa validação, a integração Android deverá reproduzir o processamento
de áudio, executar os modelos no aparelho, abrir a sessão existente e pausar a
captura durante conversa e resposta. Também será necessário testar bateria e
retomada com tela apagada. O treino no Colab não faz essa integração sozinho.

Fontes: [treinamento oficial](https://github.com/dscripka/openWakeWord#training-new-models),
[formato de áudio e inferência](https://github.com/dscripka/openWakeWord#usage),
[ONNX Runtime no Android](https://onnxruntime.ai/docs/tutorials/mobile/).
