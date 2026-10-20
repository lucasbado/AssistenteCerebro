# Botões, cenários Python e conexões da Ollie

Verificação realizada em 19/10/2026, pelo app de PC aberto e pelas APIs dos serviços.

## Resultado dos testes reais

| Caminho | Resultado |
| --- | --- |
| Render HTTP e token Ollie | HTTP 200 com token; 401 sem token |
| WebSocket do Render | Conexão autenticada como observador, sem substituir PC/celular |
| App desktop → Render | Telemetria de CPU/RAM recebida ao vivo |
| Render → app desktop → Python | `snapshot` concluído, confirmado na telemetria do app |
| Cenário `diagnostico` | Python local executado e conclusão confirmada pelo app |
| App desktop → Home Assistant | `ha_status` concluído, com autenticação aceita |
| Wake do desktop | Janela ativada e chat focado; comando confirmado |
| Abertura de aplicativo | Calculadora aberta pelo caminho exato e processo encontrado |
| Comando inexistente | Rejeitado pelo app, com resultado `erro` confirmado |
| Voz no servidor | HTTP 200, `audio/mpeg`, 12.384 bytes para frase de teste; sem teste de reprodução |
| Home Assistant local | HTTP 200 em `http://192.168.15.179`; porta 8123 recusou conexão |
| Integrações no HA | Sensores GPIO13/14, relé do PC e luz do quarto encontrados na API |
| Ponte de mídia existente | `/health` do serviço local na porta 8765 respondeu 200, sem enviar credenciais do HA |
| HASS.Agent | Cliente e Satellite Service ativos; conexão TCP estabelecida com `192.168.15.179:1883` |
| Android | Processo ativo; consulta dos logs recentes sem crash fatal. Chat/abertura de apps no celular não foram exercitados nesta rodada |

O `.env` local foi corrigido para `HA_URL=http://192.168.15.179`, preservando as
chaves. O teste `ha_status` pelo próprio app comprova que a ponte Python também
consegue chegar ao HA com essa configuração.

Não foram acionados relé, suspensão/desligamento do PC ou mudança de luz/mídia.
Os botões novos ainda não estão instalados. Os testes reais acima usam comandos
determinísticos, sem inferência de LLM.

O Render ainda executa a versão anterior: `/api/v1/pc/conexoes` retornou 404.
As confirmações reais foram observadas em `STATUS_PC.stats.ultimo_comando`, que
o app atualizado transmite. Os novos endpoints e o webhook corrigido precisam
de deploy do backend para ficarem disponíveis nesse servidor.

## Correções

Atualização: o controle por conversa foi separado em `AgenteCasa`, com catálogo,
confirmação de estado e ponte alternativa no celular. Ver [Central da casa](central-da-casa.md).

- O webhook antigo referenciava `SISTEMA_COMANDO_IOT`, categoria inexistente;
  um POST autenticado com JSON válido falhava antes de publicar o evento.
- O novo webhook valida dispositivo, botão, gesto e ID; publica `BOTAO_ACIONADO`.
  `AgenteBotoes` deriva uma intenção para o executor do PC, preservando correlação.
  O kernel continua apenas despachando eventos.
- Respostas de `pc.chat` voltam ao desktop mesmo com celular conectado.
- As rotas de luz, no Render, enfileiram comandos para a ponte do PC. Não tentam
  acessar o IP privado do quarto a partir da nuvem. PC desconectado resulta em 503.
- A heurística de luz exige uma ordem simples explícita. Uma pergunta como
  “como está a luz?” ou uma menção isolada não vira mais um `toggle` automático.
  Ordens simples para a luz do quarto usam a ponte do PC, independentemente do celular.
- Macros sem controle de teclado, mudo sem Voicemeeter e falhas explícitas de
  abertura/volume não geram mais confirmação positiva pela ponte Python.

## Caminho dos dois botões novos

```mermaid
flowchart LR
  ESP[ESP32 / ESPHome] -->|esphome.ollie_botao| HA[Home Assistant]
  HA -->|POST autenticado| API[Webhook Ollie no Render]
  API --> K[Kernel]
  K --> B[AgenteBotoes]
  B --> K
  K --> EX[Executor do PC]
  EX -->|WebSocket| PC[Ollie desktop]
  PC --> W[Wake: abrir janela e focar chat]
  PC --> PY[Cenário Python local]
  PY -->|API local| HA
  PC -->|Confirmação| API
```

As automações existentes de `esphome.duplo_clique_vidro`, mídia e relé continuam
com os nomes enviados pelo usuário. Os arquivos novos usam outro evento e não
substituem `rest_command.ollie_desk_media` nem `button.lusca_pc_mute`.

### 1. Atualizar o backend e o desktop

Publicar o backend com estes arquivos no Render. Manter o mesmo `OLLIE_API_TOKEN`
no Render, no desktop e no segredo do HA usado para chamar a Ollie.

O desktop em desenvolvimento recebeu as mudanças pelo ambiente Tauri/Vite aberto.
Uma instalação empacotada precisa de nova build e acesso à pasta do backend/Python,
como a ponte já utiliza. `OLLIE_BACKEND_DIR` e `OLLIE_PYTHON` permitem configurar
essa localização quando ela difere da pasta do projeto.

### 2. Adicionar o pacote no Home Assistant

Arquivo pronto: `config/integracoes/home_assistant_ollie.yaml`.

Se usar pacotes, copiar para `/config/packages/ollie_botoes.yaml` e incluir a pasta
na configuração existente:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Mesclar com a chave `homeassistant` já existente, se houver. Em `secrets.yaml` do HA:

```yaml
ollie_authorization: "Bearer COLOQUE_AQUI_O_MESMO_OLLIE_API_TOKEN"
```

Esse segredo autentica **HA → Ollie**. O `HA_TOKEN` do `.env` autentica
**Ollie no PC → Home Assistant** e não deve ser colocado nesse campo.

Validar a configuração do HA e carregar/reiniciar conforme sua organização atual.
O pacote trata apenas `esphome.ollie_botao`, envia o ID do contexto do evento como
chave de deduplicação e registra recusas HTTP no log do HA.

O mecanismo utiliza [RESTful Command do HA](https://www.home-assistant.io/integrations/rest_command/),
com cabeçalho de autorização, JSON e resposta HTTP acessível à automação.

### 3. Acrescentar os dois sensores no ESPHome

Trecho pronto: `config/integracoes/esphome_botoes_novos.yaml`.

GPIO25 e GPIO26 são sugestões para os dois TTP223 ainda não instalados. Confirmar
a ligação antes de compilar/gravar. Acrescentar os dois itens à lista `binary_sensor`
existente; não criar uma segunda chave nem substituir os sensores atuais.
O trecho não contém Wi-Fi ou outras credenciais.

O botão `ollie` envia wake e o botão `cenarios` envia o cenário cadastrado.
A integração usa a ação [homeassistant.event do ESPHome](https://esphome.io/components/api/#homeassistantevent-action).
Os eventos precisam começar com `esphome.` e a integração ESPHome do HA precisa
permitir ações do dispositivo, como já ocorre nos eventos dos botões existentes.

Este wake apenas mostra/foca o chat do desktop. Ainda não inicia gravação,
reconhecimento de fala ou conversa de voz. Essa próxima etapa poderá usar o mesmo
evento depois que a captura/reprodução tiver seu ciclo de início, cancelamento e fim.

### 4. Cadastrar cenários Python

`config/botoes.json` contém o vínculo exato entre dispositivo/botão/gesto e ação.
`config/cenarios.json` contém os cenários disponíveis **neste PC**.
O cenário inicial `diagnostico` só verifica a execução do interpretador.

Para uma sequência maior, colocar o script em `scripts/cenarios/preparar_estudo.py`
e cadastrar, por exemplo, um novo item no objeto de `config/cenarios.json`:

```json
{
  "estudo": {
    "ativo": true,
    "passos": [
      {"comando": "python", "script": "preparar_estudo.py", "timeout_segundos": 60},
      {"comando": "abrir_app", "parametro": "vscode"},
      {"comando": "ligar_luz", "parametro": "light.yeelink_color5_027d_light"}
    ]
  }
}
```

O script do exemplo deve ser escrito antes de usar esse cenário. Alterar o vínculo
do botão `cenarios` de `diagnostico` para `estudo` no arquivo do backend/Render.
Configurações são lidas a cada acionamento, sem edição remota de código.

Os passos rodam em ordem, interrompendo em caso de falha; não há desfazimento
automático dos passos anteriores. Há no máximo 30 passos, orçamento configurado
de até 300 segundos e timeout individual para cada processo Python.
Um cenário por vez é aceito pelo desktop. Arquivos Python precisam estar dentro
de `scripts/cenarios`; argumentos são fixados na configuração local.
O webhook não recebe código, caminho de script ou comando de shell.

## Simulação e diagnóstico

Após o deploy, enviar o JSON abaixo para `POST /api/v1/ha/buttons/preview`, usando
o cabeçalho `Authorization: Bearer <OLLIE_API_TOKEN>`:

```json
{
  "dispositivo": "esphome-web-903934",
  "botao": "cenarios",
  "gesto": "toque",
  "evento_id": "simulacao-001"
}
```

A simulação não publica eventos nem consome cooldown. O mesmo corpo em
`POST /api/v1/ha/webhook` aciona o vínculo. IDs devem ser novos para cada toque
e preservados em uma retentativa do mesmo evento.

`202 aceito` significa enfileirado. Consultar `GET /api/v1/pc/comando/{id}` para
ver `enviado`, `concluido`, `erro`, `pc_offline` ou `sem_confirmacao`.
A rota pode retornar 404 enquanto o evento ainda aguarda o executor.
Somente o WebSocket do PC registrado pode confirmar conclusão.

Confirmações guardam os últimos 200 comandos em memória. Deduplicação do webhook
usa os últimos 10 minutos, com limite de 2.000 IDs, e cooldown padrão de 1 segundo.
São proteções locais à instância: reinício/redeploy perde esse histórico.
Não há garantia de execução exatamente uma vez entre reinícios ou múltiplos workers;
evitar retentar automaticamente cenários com efeitos se faltar confirmação.

```powershell
.\.venvs\Scripts\python.exe scripts/diagnosticar_conexoes.py
.\.venvs\Scripts\python.exe scripts/diagnosticar_conexoes.py --testar-pc --wake
```

A primeira forma consulta conexões; a segunda executa os quatro testes seguros
descritos na tabela. O relatório sem tokens/mensagens pessoais fica em
`.artifacts/diagnostico-conexoes.json`. O script permanece como observador e não
registra outro `PC_MASTER` ou `MOBILE`.

## Validação automatizada

Os testes de regressão cobrem autenticação e validação do webhook, simulação sem
efeitos, deduplicação/cooldown, falha de fila, correlação entre eventos, sequência
de cenário, limites de caminho/timeout, confirmação exclusiva do PC, ausência de
hardware, encaminhamento de luz e retorno do chat ao desktop. Usam dados
temporários e hardware/rede simulados; um teste executa um script temporário local.

Resultado: **80 testes Python passaram**, build TypeScript/Vite passou e
`cargo check --offline` passou para o código Tauri. O teste real de wake confirmou
que o app aberto já dispõe do novo comando nativo.

Os YAMLs tiveram a sintaxe verificada; ESPHome não está instalado para compilar
o firmware neste ambiente. São exemplos preparados para aplicação. Não foram gravados no ESP32 nem
instalados no Home Assistant nesta rodada.
