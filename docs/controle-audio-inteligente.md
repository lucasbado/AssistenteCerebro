# Controle inteligente de áudio da Mesa Touch

Implementação Python e ponte de comunicação: 26/10/2026. **YAML abaixo é uma proposta para aprovação: não foi aplicado ao Home Assistant.** O feedback está desabilitado em `config/audio.json`; os botões continuam com o comportamento anterior.

## Arquitetura e arquivos

O caminho reutilizado é **ESPHome → automação HA → HTTPS autenticado do backend existente → WebSocket existente → Ollie Desk/Tauri → helper Python → integração VoiceMeeter existente**. Não há servidor ou biblioteca adicional. Funciona também com o backend em modo limitado, sem depender da Neon.

| Arquivos | Responsabilidade |
| --- | --- |
| `servicos/controle_audio.py`, `config/audio.json` | Controlador, passos, limites, mute, persistência e adaptador Banana |
| `servicos/pc_control_service.py` | Conexão com o mixer já aberto, sem inicializar Spotify, abrir GUI ou reiniciar o áudio |
| `servicos/entrada_audio.py`, `api/router_ha.py`, `api/disponibilidade.py` | Contrato fechado e rota autenticada `/api/v1/ha/audio` |
| `scripts/pc_command.py` | Operação adicional `audio_controle`; comandos antigos preservados |
| `servicos/resultado_audio.py`, `servicos/confirmacao_pc.py` | Validação e transporte da confirmação estruturada |
| `servicos/home_assistant_service.py` | Chamada autenticada ao script real `script.ollie_feedback_visual` |
| `ollie-master-next/src/audioControl.ts`, `ollie-master-next/src/App.tsx` | Fila dos gestos e transporte do resultado pelo desktop, sem mudanças de layout |
| `scripts/backup_audio_ha.py` | Backup somente por GET, sem modificar o HA |
| `tests/test_controle_audio.py`, `tests/test_audio_ha.py`, `ollie-master-next/tests/audioControl.test.mjs` | Testes simulados do controlador e das pontes |

Não foi encontrado um seletor persistente HEADSET/CINEMA. O comando antigo `ciclar_saida` muda rotas individuais de strips; ele não representa esses perfis e permanece independente.

## Regras de operação

`perfil_audio` e `modo_controle` são independentes. Selecionar CINEMA não liga, desmuta nem redireciona saídas. Ao iniciar sem perfil salvo, ajustes retornam `perfil_nao_selecionado`; o sistema não deduz utilização a partir do mute. A seleção explícita é feita pela operação `audio.profile` abaixo.

| Perfil/modo | Avançar | Voltar |
| --- | --- | --- |
| HEADSET / VOLUME | A1 + passo | A1 − passo |
| CINEMA / VOLUME | A2/A3 + mesmo delta | A2/A3 − mesmo delta |
| HEADSET / SINCRONIZACAO | Bloqueado, sem escrita | Bloqueado, sem escrita |
| CINEMA / SINCRONIZACAO | A3 +10 ms | A3 −10 ms |

Play/Pause alterna apenas o modo. O passo inicial de volume é 2 dB, configurável em `config/audio.json` entre valores maiores que zero e até 6 dB. O passo de delay é 10 ms.

Saídas mutadas não recebem escrita. Se apenas uma saída do Cinema estiver desmutada, somente ela muda. Ao desmutar a outra, não há compensação automática: os próximos passos preservam a diferença que existir naquele momento. A2 nunca recebe alteração de delay.

**Limites do Cinema:** com duas saídas desmutadas, o mesmo delta é reduzido para caber em ambas. Exemplo: A2=10 dB, A3=11 dB, passo=2 dB → A2=11, A3=12. Outro avanço não altera nenhuma delas. No limite inferior ocorre o equivalente. Assim a diferença é preservada; o sistema não continua aumentando somente uma saída. Os limites utilizados são −60…+12 dB e 0…500 ms, conforme a [API oficial da VB-Audio](https://download.vb-audio.com/Download_CABLE/VoicemeeterRemoteAPI.pdf).

As leituras descartam o cache Python e consultam `pdirty` para atualizar o snapshot da API nativa. Cada escrita precisa ser confirmada por leitura real. Uma falha após uma escrita retorna `parcial`, `alterado: null`, valores anteriores e parâmetros tentados; não é repetida nem revertida automaticamente sobre possíveis ajustes do usuário.

## Estado e concorrência

Estado padrão: `%LOCALAPPDATA%\Ollie\audio\estado.json`. `OLLIE_AUDIO_STATE_DIR` permite escolher outro diretório local. Perfil e modo ficam nesse arquivo, não no Git.

Um lock de arquivo protege toda a operação entre threads/processos; a ponte desktop também preserva a ordem dos gestos. A gravação usa temporário no mesmo diretório, `flush`, `fsync` e substituição atômica. Se o estado estiver corrompido, a operação falha sem escolher outro perfil silenciosamente.

Os últimos 200 IDs são reservados antes dos efeitos e persistidos com seus resultados. Repetir um desses IDs não repete o ajuste. Se um processo morrer depois da reserva, a repetição retorna `indeterminado`, exigindo consulta antes de um novo pedido. IDs antigos além da janela não têm garantia de deduplicação; não reutilize IDs de eventos diferentes. O bloqueio coordena os novos comandos da Ollie; não impede ajustes manuais ou de outros programas no mixer.

## API e ativação por etapas

Reutiliza o `Authorization: Bearer <OLLIE_API_TOKEN>` já usado no backend; nenhum segredo deve ir no YAML público. PC desconectado retorna HTTP 503, dados inválidos 422, ID reutilizado para outro pedido 409. HTTP 202 significa enfileiramento, não execução. Consulte a URL `consulta` devolvida na resposta para verificar `resultado.audio`.

Exemplos de corpos para `POST https://assistentecellfront.onrender.com/api/v1/ha/audio`:

```json
{"evento_id":"perfil-headset-001","action_name":"audio.profile","perfil_audio":"HEADSET"}
```

```json
{"evento_id":"perfil-cinema-001","action_name":"audio.profile","perfil_audio":"CINEMA"}
```

```json
{"evento_id":"consulta-001","action_name":"audio.status"}
```

```json
{"evento_id":"evento-esp-001","action_name":"media.next_track","gesture":"double_click"}
```

Escolha explicitamente um perfil antes de operar os botões. Não foi criado um seletor visual nesta etapa de componentes Python. Os antigos comandos `media_next`, `media_prev`, `media_play_pause`, `voicemeeter`, `volume_canal` e suas rotas não foram substituídos.

Sequência de ativação: publicar o backend no Render manualmente, reconstruir/reabrir a Ollie Desk, consultar a nova rota autenticada, selecionar o perfil, aprovar/aplicar o YAML abaixo e só então habilitar o feedback em `config/audio.json`. A alteração de modo/volume passa a valer para os botões apenas depois da atualização do `rest_command` no HA.

**Pendência real:** volume validado no hardware; delay A3 ainda não confirmado. Não considerar a sincronização pronta para uso físico até resolver essa confirmação. O controlador não força reinício do motor para contornar a falha.

## Backup existente

Backup local concluído antes de qualquer mudança de configuração:

`D:\Programacao\AssistenteCell\.artifacts\backup-audio-ha-20261027-000836`

- `mesa-touch.json`: automação `automation.controle_de_midia_mesa_touch_esp32`, ID `1792384092779`.
- `feedback-visual.json`: script `script.ollie_feedback_visual`.
- `manifesto.json`: hashes SHA-256 e rotas de origem.

O nome da pasta usa UTC, portanto 27/10; a execução foi em 26/10 no horário local. Os arquivos ficam fora do Git. Para um novo backup antes da futura aplicação:

```powershell
.venvs/Scripts/python.exe scripts/backup_audio_ha.py
```

A definição completa original do `rest_command.ollie_desk_media` não foi recuperada pela API de estados; ela também deverá ser copiada antes de editar sua URL/payload.

## Proposta de YAML — aguardando confirmação

### 1. Serviço REST existente

Manter o nome `rest_command.ollie_desk_media`; alterar somente seu destino/payload e preservar o segredo de autenticação que já estiver configurado. `ollie_authorization` abaixo é o nome usado no exemplo do repositório; confirmar o nome real no HA antes da aplicação. Seu valor deve conter `Bearer ` seguido do token atual.

```yaml
rest_command:
  ollie_desk_media:
    url: https://assistentecellfront.onrender.com/api/v1/ha/audio
    method: POST
    headers:
      authorization: !secret ollie_authorization
    content_type: application/json
    verify_ssl: true
    timeout: 10
    payload: >-
      {{ {'evento_id': evento_id, 'action_name': action_name,
          'gesture': gesture} | to_json }}
```

Esse serviço continuará recebendo os três nomes de ação existentes, mas os enviará ao novo controlador. Outros clientes que usam os comandos antigos da Ollie permanecem com os contratos anteriores. Verificar outros chamadores desse `rest_command` antes de exigir `evento_id`.

### 2. Automação Mesa Touch

Preservar triggers, `choose`, modo `queued` e ação de toque longo. Acrescentar **somente** o ID do evento nos três ramos que já chamam o REST:

```yaml
# Ramo play_pause
- action: rest_command.ollie_desk_media
  data:
    action_name: media.play_pause
    gesture: single_click
    evento_id: "{{ trigger.event.context.id }}"

# Ramo avancar
- action: rest_command.ollie_desk_media
  data:
    action_name: media.next_track
    gesture: double_click
    evento_id: "{{ trigger.event.context.id }}"

# Ramo voltar
- action: rest_command.ollie_desk_media
  data:
    action_name: media.previous_track
    gesture: triple_click
    evento_id: "{{ trigger.event.context.id }}"
```

O ramo `mutar` continua chamando `button.press` em `button.lusca_pc_mute`. Não há mudança no firmware ESPHome ou na automação da luz pelo outro botão.

### 3. Script de feedback existente

Corpo proposto no editor do script `script.ollie_feedback_visual`:

```yaml
alias: Ollie - Feedback Visual
mode: queued
max: 10
fields:
  modo_controle:
    name: Modo de controle
    default: VOLUME
    selector:
      select:
        options:
          - VOLUME
          - SINCRONIZACAO
sequence:
  - variables:
      modo: "{{ modo_controle | default('VOLUME', true) }}"
  - condition: template
    value_template: >-
      {{ modo in ['VOLUME', 'SINCRONIZACAO'] and
         states('light.yeelink_color5_027d_light') in ['on', 'off'] }}
  - variables:
      estado_anterior: "{{ states('light.yeelink_color5_027d_light') }}"
      brilho_anterior: "{{ state_attr('light.yeelink_color5_027d_light', 'brightness') }}"
      modo_cor_anterior: "{{ state_attr('light.yeelink_color5_027d_light', 'color_mode') }}"
      cor_anterior: >-
        {% set m = state_attr('light.yeelink_color5_027d_light', 'color_mode') %}
        {% set atributo = {'hs':'hs_color', 'xy':'xy_color', 'rgb':'rgb_color',
          'rgbw':'rgbw_color', 'rgbww':'rgbww_color', 'color_temp':'color_temp_kelvin'}.get(m) %}
        {{ state_attr('light.yeelink_color5_027d_light', atributo) if atributo else none }}
  - action: scene.create
    data:
      scene_id: ollie_luz_anterior
      snapshot_entities:
        - light.yeelink_color5_027d_light
  - action: light.turn_on
    continue_on_error: true
    target:
      entity_id: light.yeelink_color5_027d_light
    data:
      rgb_color: "{{ [160, 32, 240] if modo == 'SINCRONIZACAO' else [0, 100, 255] }}"
      brightness_pct: 70
  - delay:
      milliseconds: 500
  - action: scene.turn_on
    continue_on_error: true
    target:
      entity_id: scene.ollie_luz_anterior
  - wait_template: >-
      {% set m = state_attr('light.yeelink_color5_027d_light', 'color_mode') %}
      {% set atributo = {'hs':'hs_color', 'xy':'xy_color', 'rgb':'rgb_color',
        'rgbw':'rgbw_color', 'rgbww':'rgbww_color', 'color_temp':'color_temp_kelvin'}.get(m) %}
      {{ states('light.yeelink_color5_027d_light') == estado_anterior and
         (estado_anterior == 'off' or
          (state_attr('light.yeelink_color5_027d_light', 'brightness') == brilho_anterior and
           m == modo_cor_anterior and
           (state_attr('light.yeelink_color5_027d_light', atributo) if atributo else none) == cor_anterior)) }}
```

`queued` serializa **snapshot → flash → restauração confirmada**. A espera final é deliberadamente sem timeout: se a lâmpada não confirmar a restauração, a fila fica parada, preservando a cena original em vez de capturar uma cor temporária no próximo flash. Até dez chamadas ficam na fila; excedentes não geram novos snapshots. Isso não bloqueia o áudio, pois a ponte chama `script.turn_on`, que inicia o script sem aguardar sua conclusão.

Se a restauração falhar, usar a cena `scene.ollie_luz_anterior` para recuperar o estado antes de cancelar/recarregar esse script. Não reutilizar esse mesmo nome de cena em outra automação concorrente. A proteção é para chamadas rápidas durante a execução do HA; cenas dinâmicas não substituem backup persistente em caso de reinício do Home Assistant. Chamadas antigas sem `modo_controle` continuam azuis. Referências: [modos de script](https://www.home-assistant.io/integrations/script/), [espera em scripts](https://www.home-assistant.io/docs/scripts/#wait), [cenas](https://www.home-assistant.io/integrations/scene/).

O Python já envia `variables: {modo_controle: ...}` ao script real, mas só fará essa chamada depois de `feedback_habilitado: true` no JSON. A proposta de YAML ainda precisa de validação na instância do HA e do seu aceite antes de aplicação.

## Testes e evidências

- Python específico: **22 testes aprovados**, incluindo A1, Cinema, mute em ambas as orientações, limites, delay simulado, bloqueio HEADSET, persistência, escrita atômica, corrupção, seis processos concorrentes, deduplicação, resultado parcial e feedback indisponível.
- Python: **623 aprovados, 2 ignorados** em `tests/`, mais **4 aprovados** em `api/test_api_v1_endpoints.py` (**627 aprovados no total**). Há um aviso preexistente de depreciação Starlette/httpx.
- Desktop: **23 testes aprovados**, incluindo ordem dos gestos e recuperação da fila após falha. Build `tsc && vite build` aprovado.
- Comunicação simulada: HTTP sem token rejeitado; contrato HTTPS no ASGI; WebSocket registrado → comando → resultado estruturado → consulta; PC offline; validação; duplicatas; feedback HA por transporte HTTP simulado autenticado. **Isso não é um teste TLS real do endpoint novo no Render**, ainda dependente de deploy.
- Hardware Banana 2.1.2.2 / biblioteca existente 2.7.2: A1 −3 → −3,5 → −3 dB; Cinema A2/A3 3/6 → 2,5/5,5 → 3/6 dB. Diferença de 3 dB preservada. Nenhum mute, strip ou roteamento foi alterado.
- Hardware: HEADSET/SINCRONIZACAO bloqueou a alteração. A3 retornou 100 ms após pedidos de 90 e 110 ms, inclusive pela interface `option.delay[2]` e pelas instruções documentadas. **Teste de alteração física do delay não passou**. O resultado ficou `parcial/alteracao_nao_confirmada`; não houve reinício do motor nem alteração de A2.
- Uma falha inicial de confirmação de ganho revelou o snapshot nativo desatualizado; `pdirty` corrigiu o adaptador e um teste de regressão cobre a diferença entre cache Python e snapshot nativo. O ganho original foi restaurado e conferido por uma nova conexão independente.

Evidência local do teste físico e recibos: `.artifacts/audio-fisico-a4148609-9db2-4489-aeba-2b7ec16f16f2/`. Baseline final conferida: A1 −3 dB, A2 +3 dB, A3 +6 dB, todos com mute=0; delay A2=0 ms, A3=100 ms. Feedback/lâmpada não foram acionados nos testes físicos.

Comandos de verificação:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.venvs/Scripts/python.exe -m pytest tests/test_controle_audio.py tests/test_audio_ha.py -q -p no:cacheprovider
.venvs/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
.venvs/Scripts/python.exe -m pytest api/test_api_v1_endpoints.py -q -p no:cacheprovider
cd ollie-master-next
npm.cmd test
npm.cmd run build
```

## Restauração do comportamento anterior

**Agora:** nenhum YAML foi aplicado e nenhum botão mudou. Os testes usaram estado isolado em `.artifacts`, sem selecionar um perfil na configuração normal do usuário. Todos os parâmetros físicos conferidos estão no baseline acima.

**Depois de uma eventual ativação autorizada:**

1. Desabilitar temporariamente a automação Mesa Touch para impedir novos gestos durante a restauração.
2. Definir `feedback_habilitado: false`. Se o script de feedback estiver aguardando restauração, recuperar primeiro a lâmpada pela cena anterior antes de pará-lo/recarregá-lo.
3. Restaurar o corpo da Mesa Touch e do feedback a partir de `mesa-touch.json`/`feedback-visual.json` do backup; JSON também é YAML válido no editor de configuração. Restaurar a definição original do `rest_command.ollie_desk_media` que deverá ser copiada antes da futura edição.
4. Validar/recarregar os componentes correspondentes no HA e reabilitar a automação. Os três gestos voltam a enviar os comandos antigos de mídia; toque longo permanece como estava.
5. Opcionalmente reverter o commit desta implementação e reconstruir o desktop/deployar o backend anterior. Não usar `reset --hard` nem apagar mudanças de outros trabalhos.
6. Para zerar apenas a seleção de perfil/modo, com a Ollie parada, renomear `%LOCALAPPDATA%\Ollie\audio\estado.json` para uma cópia de backup. Isso não mexe nos parâmetros do mixer. Ajustes de volume/delay feitos durante uso normal precisam ser restaurados explicitamente aos valores desejados; o controlador não reseta o áudio ao sair.
