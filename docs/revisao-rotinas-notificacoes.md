# Revisão de rotinas, abertura de apps e notificações

Revisão de 19/10/2026. O foco foi o caminho sensor → aprendizado → descoberta →
aprovação → execução → notificação e sua apresentação na timeline. Não foi uma
auditoria completa de segurança nem uma validação no Android.

## Problemas encontrados e corrigidos

| Problema | Efeito anterior | Correção |
| --- | --- | --- |
| `AgenteInferencia` chamava `registrar_uso_app(categoria, valor)`, que aceita apenas um argumento | `TypeError` interrompia a análise de eventos de uso | Método próprio para registrar uso por período |
| Inferência varria novamente os mesmos eventos de PC em cada evento recebido | Contagem e confiança cresciam sem novas observações | Cada observação atualiza o perfil uma vez; descoberta consulta o histórico datado |
| Associação PC lia um `payload.payload` já removido pelos gateways | Atividade de PC real não formava associações | Normalização compartilhada para formatos UDP e WebSocket |
| Ponto no nome distinguia app Android de programa PC | `chrome.exe` e `code.exe` eram tratados como Android | Dispositivo identificado pela categoria do evento |
| Duas coincidências criavam associações, sem contar fracassos nem dias | Uma sessão isolada parecia um hábito confiável | Amostras, dias, proporção de acertos e recência explícitos |
| Descoberta ignorava `min_conf` em associações semânticas | Associações antigas, sem evidência, viravam sugestões | Evidência calculada na memória episódica, sem reutilizar esses scores |
| `AgenteFoco` executava associação sem passar pelas rotinas aprovadas | Automação concorrente com o executor de rotinas | Aprendizado não executa; abertura baseada em hábito passa pelas rotinas |
| Rotinas eram carregadas apenas no construtor | Aprovar/adicionar/excluir só surtia efeito após reiniciar | Recarga por versão do arquivo e gravação atômica |
| Caminhos relativos e fallback específico do computador | API e executor podiam ler arquivos diferentes | Caminhos únicos relativos à raiz do projeto |
| Rotinas temporais dependiam de `PC_LOGIN`/`SYSTEM_START`, sem produtores encontrados | Rotinas geradas não disparavam | Novas rotinas usam `PC_ACTIVITY` ou o evento de relógio `TICK_ROTINA` |
| Horários eram avaliados em UTC ou no fuso do servidor | Manhã/noite aprendidas ou executadas na hora errada | Conversão pelo fuso configurado; intervalos atravessando meia-noite |
| Gatilhos sem limitação, com comparação parcial de processo | Aberturas repetidas e correspondências falsas | Processo exato, cooldown, exclusão mútua e limite diário temporal |
| Abertura do próximo app no mesmo instante em que o primeiro era aberto | O usuário perdia o app que acabava de escolher | Fluxos mobile oferecem uma notificação com botão para abrir |
| Comentário dizia existir um gestor de interrupções, mas não havia esse filtro no fluxo | Todas as intenções eram enviadas | Política única na saída do agente de notificações |
| Intenções IA sem `tipo_ws` podiam virar `CHAT_RESPONSE`; conteúdo aninhado não era normalizado | Sugestão aparecia no lugar errado ou com texto de sucesso genérico | Normalização de título/texto e destino antes do transporte |
| Mensagens de favorito, elogios a cada música e fallback de AC/DC | Interrupções sem informação ou preferência observada | Mensagens decorativas removidas; sugestão musical exige evidência |
| Bem-estar tinha variável incorreta no `any`, pacote no campo errado e somava sessões distintas | Erro em execução ou alertas de duração falsa | Pacote canônico, sessão por app e descarte de intervalos sem observação |
| Notificação do próprio app era registrada como uso | Perfil confundia receber aviso com abrir aplicativo | Notificações não incrementam esse uso; foreground repetido é deduplicado |
| Feedback negativo podia produzir `log(score + 1)` inválido | Erro ao rejeitar preferências com score baixo | Score limitado a zero |
| Timeline exibia telemetria e intenções como se fossem resultados | Muito ruído e nenhuma distinção entre sugerir e encaminhar | Timeline exibe encaminhamentos após o filtro e ações solicitadas no PC |
| Rejeição removia só a sugestão pendente | Sugestão reaparecia no ciclo seguinte | Registro de rejeições consultado na descoberta e geração |

## Critérios atuais

- Histórico dos últimos 21 dias, com confirmação do padrão nos últimos sete.
- Associações: pelo menos cinco ocorrências, em três dias distintos, com 80%
  de acerto por padrão. A janela entre os apps é de até 60 segundos. O mesmo
  gatilho não conta outra oportunidade em menos de dez minutos.
- Padrões temporais: presença em pelo menos cinco dias; confiança representa a
  proporção de dias observados naquele período em que o app foi usado.
- Alterações de título/aba do mesmo processo não contam como novas aberturas
  dentro de uma janela de 30 minutos. Isso é uma aproximação de sessão, não
  uma medição de duração de uso.
- Sugestões nascem desativadas, com justificativa e evidência. Aprovação mantém
  essas informações e passa a valer no próximo evento compatível.
- Rotinas aprovadas de PC podem abrir apps como ações do sistema. A política
  `auto_open_enabled` continua controlando comandos proativos de origem IA;
  não é um interruptor global das rotinas que o usuário ativou explicitamente.
- Cooldown padrão de uma hora por rotina; rotinas temporais geradas têm também
  limite de uma execução por dia local. Eventos antigos ou de origem IA não
  são novas aberturas para o motor de rotinas.
- Notificações proativas: intervalo de dez minutos e até três por hora. A mesma
  sugestão não se repete por uma hora. `urgencia: ALTA` permite ultrapassar o
  orçamento, mantendo deduplicação. Respostas de chat são atendidas sem esse
  orçamento. Rotinas não recebem urgência alta automaticamente.
- Uma intenção suprimida permanece no histórico técnico, mas não vira item da
  timeline. `NOTIFICACAO_PRONTA_PARA_ENVIO` registra encaminhamento ao transporte;
  não comprova recebimento ou leitura no aparelho. Comando PC representa uma
  ação solicitada, não execução confirmada.

## Operação

Execute `main:app` para ter kernel, agentes e relógio ativos. A aplicação
`api.main_api:app_api` é a camada de consulta e não inicia esses componentes.

Configure `OLLIE_TIMEZONE` quando necessário; o padrão é `America/Sao_Paulo`.
`tzdata` está declarado em `requirements.txt` para disponibilizar os fusos no
Windows. O banco continua armazenando timestamps em UTC.

O ciclo de reflexão gera sugestões a cada hora; havia dois ciclos sobrepostos
de geração e agora há um. Para testar sob demanda, use
`POST /api/v1/capabilities/discover/run`: a resposta informa quantas sugestões
foram geradas. Consulte `/discovered` e aprove apenas as desejadas por `/approve`.

Sugestões rejeitadas ficam em `config/rejected_routines.json`. Para reconsiderar
uma sugestão, remova seu registro desse arquivo e execute novamente a análise.
Os arquivos pessoais existentes não foram apagados nem tiveram rotinas ativadas.
Pendências antigas continuam presentes e devem ser revistas: elas não ganham
evidência retroativamente. Scores antigos do perfil também não foram reescritos;
a nova descoberta deixa de depender deles.

## Limitações e próximos passos

1. O cliente Android foi localizado em `D:\Programacao\Projetos\AssistenteCell`;
   contratos, autenticação, ações e coleta foram revisados, compilados e testados.
   Consulte a [revisão complementar](revisao-cliente-android.md). Permanece a
   validação no aparelho. Sem telemetria suficiente, o sistema prefere não sugerir
   uma rotina.
2. Medir aceitação, rejeição e execução real por sugestão. Confiança estatística
   de uso não demonstra que o usuário quer automatizar aquele comportamento.
   Coocorrência entre dispositivos também pode ser coincidência.
3. Separar resposta a pedido explícito de execução autônoma da LLM. Atualmente
   comandos de chat publicados como origem IA também passam pelo bloqueio de
   auto-open do executor; isso é independente das rotinas aprovadas.
4. O governor ainda mantém sua configuração em memória e não aplica whitelist
   nem `min_priority_score`. Não confundir esses controles da interface com os
   critérios de confiança da descoberta implementados nesta revisão.
5. Cooldowns e orçamento de notificações são locais ao processo e reiniciam com
   ele. Para múltiplos workers ou garantia entre reinícios, persistir reservas e
   execução em banco. Os arquivos JSON também não são uma transação entre dois
   arquivos durante aprovação; o fluxo atual pressupõe uma instância escritora.
6. Bem-estar só estima uso contínuo se houver observações a cada cinco minutos
   ou menos. Sem heartbeat/tempo acumulado confiável do Android, não afirma que
   um app ficou aberto durante todo um intervalo sem eventos.
7. A consulta histórica pode crescer com o volume de uso. Antes de escalar,
   medir custo e mover estatísticas de sessões para agregação incremental.

## Validação

Testes usam SQLite temporário e substituem transporte, LLM e hardware quando
necessário. Incluem descoberta persistida, falsos padrões de um dia, proporção
de acertos, processos `.exe`, fuso local, geração concorrente, rejeição,
aprovação com recarga, execução sem repetição, contrato da Home e notificações,
timeline e sessões de bem-estar.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venvs\Scripts\python.exe -m pytest -q -p no:cacheprovider
```
