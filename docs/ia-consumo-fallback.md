# Consumo de IA e alternativas

A IA permanece um serviço dos agentes. Orçamento, cache e transporte ficam
em serviços próprios; nenhuma decisão foi adicionada ao kernel.

## O que consumia sem conversar

As notificações eram analisadas antes de suprimir repetições. Abrir o perfil
gerava outro resumo e cadastrar contatos usava IA para interpretar somente
o nome. HTTP 429 não colocava o modelo em espera nas outras instâncias.
Não havia medição por função: não é possível atribuir retroativamente o uso
anterior com precisão. O histórico novo começa com esta atualização.

## Controle de consumo

- A triagem local seleciona perguntas, convites, prazos e sinais de urgência
  ou segurança antes da análise. Avisos técnicos, posts e mensagens sem
  esses sinais não iniciam IA. Captura de eventos e pendências é independente.
- A mesma notificação não inicia outra análise por 24 horas, mesmo que o
  Android renove sua referência. Falhas permitem tentativa depois de dez
  minutos; revisões resolvidas/ignoradas não voltam a mobilizar o modelo.
- A análise de notificações usa um prompt menor, sem catálogo de comandos.
- O resumo do perfil persiste por 24 horas; mudanças permitem atualização
  depois de uma hora. Falhas mantêm o resumo anterior. Chamadas simultâneas
  não duplicam a geração. Contatos novos guardam o nome sem inferir relações.
- Reservas transacionais impedem ultrapassar o orçamento por concorrência.
  Uso informado pela API substitui a estimativa. Falhas de rede ambíguas
  conservam a estimativa; recusas 4xx não contam como geração.
- HTTP 429 coloca o modelo em espera compartilhada, usando `Retry-After`
  ou o prazo informado pela Groq. Não há nova tentativa sem JSON por esse erro.

Orçamentos iniciais do app, configuráveis no ambiente:

```dotenv
OLLIE_IA_TOKENS_24H=100000
OLLIE_IA_AUTO_TOKENS_24H=20000
OLLIE_IA_AUTO_TOKENS_1H=4000
```

A janela é móvel. O total inclui pedidos e automáticos; os outros dois tetos
restringem apenas automáticos para preservar capacidade para conversar.
São limites da Ollie, não o saldo oficial da conta. O provedor pode recusar
antes por limite de minuto, modelo ou uso de outros programas.

**Atividade → Uso da IA**, no PC, mostra total e origem das chamadas. A API
autenticada `GET /api/v1/ia/consumo` oferece a mesma informação. Estimativas
são identificadas. O ledger mantém 30 dias sem prompts ou mensagens pessoais.

## Cloudflare

Pedidos diretos seguem **Groq → Cloudflare → PC** quando há falha. Um backend
local ainda pode usar Ollama em loopback. Análises automáticas não gastam
Cloudflare/PC ao esgotar o orçamento: aguardam em silêncio. Comandos resolvidos
por regras locais continuam sem IA.

Na Cloudflare, abra Workers AI → Use REST API, crie o token pelo modelo
Workers AI Read/Edit e copie o **Account ID**. Os IDs das permissões não são
o ID da conta. Configure no `.env` e em **Render → Environment**:

```dotenv
CLOUDFLARE_ACCOUNT_ID=seu_account_id
CLOUDFLARE_API_TOKEN=seu_token_privado
```

As credenciais desta máquina já foram configuradas e testadas. O `.env` fica
fora do Git: **o push não envia essas variáveis ao Render**. Configure-as lá e
faça o deploy manual. Não é necessário criar/hospedar um Worker para usar a
[API REST oficial](https://developers.cloudflare.com/workers-ai/get-started/rest-api/).

O código seleciona somente `@cf/meta/llama-3.1-8b-instruct`, com JSON. Não
altera planos nem habilita cobrança; mantenha Workers Free. Existe um teto
conservador adicional de 60 mil tokens/24h para pedidos diretos na Cloudflare.
Esse teto não representa o saldo oficial de neurons da conta.

A [oferta atual](https://developers.cloudflare.com/workers-ai/platform/pricing/)
inclui 10 mil neurons/dia, com reset às 00:00 UTC. No Free, novas operações
falham ao acabar a cota. Modelos que exigem pagamento não são selecionados.

## Alternativa no PC

Celular, inclusive em 4G → Render → WebSocket autenticado do PC → Ollama local
→ Render → dispositivo que fez o pedido. O app do PC precisa estar aberto,
conectado, com computador acordado. O uso remoto depende do backend atualizado;
não foi afirmado um teste de 4G antes desse deploy.

O PC anuncia `LOCAL_LLM` apenas quando o helper confirma o modelo, revalidando
a cada minuto. A resposta é texto; esse helper não executa código nem comandos.
O backend mantém a validação normal das ações pedidas pelo usuário.

Pedidos têm UUID, aceitam resposta somente do socket PC original, encerram
esperas ao desconectar/substituir a sessão e usam timeout. Não há broadcast
de prompts ou fila ilimitada. Só uma inferência é atendida por vez.
A cadeia tem prazo total de 55 segundos por geração, preservando tempo para
trocar de provedor em vez de acumular esperas longas em cada um.

Ollama portátil oficial e `qwen2.5:3b` foram instalados fora do Git:

```text
.artifacts/local_ai/runtime/
.artifacts/local_ai/models/
.artifacts/local_ai/config.json
```

Configuração local:

```json
{"enabled": true, "model": "qwen2.5:3b"}
```

Para desativar, altere `enabled` para `false`; o app atualiza a capacidade em
até um minuto. O modelo é escolhido localmente. Para outro PC, instale Ollama,
baixe o modelo e crie esse arquivo no checkout correspondente. O helper pode
iniciar o runtime portátil Windows ou usar um Ollama já iniciado em loopback.

Ollama escuta somente `127.0.0.1:11434`; não foram abertas portas de firewall
ou roteador. Ollama Cloud fica desativado no runtime portátil. Um modelo por vez,
liberado após dois minutos sem uso. Não há cota paga, mas há uso de GPU/RAM e
energia. Não funciona com o computador desligado.

O [Qwen 2.5 3B](https://ollama.com/library/qwen2.5:3b) tem cerca de 1,9 GB em
pesos quantizados. É menor que o modelo principal e pode errar mais. Respostas
continuam sujeitas aos contratos e limites da Ollie.

## Verificações

Testes cobrem orçamento concorrente, reserva para pedidos diretos, uso real,
cooldown compartilhado, janela móvel, cache concorrente, triagem, deduplicação,
revisões encerradas, Cloudflare simulada, socket incorreto, timeout e isolamento
de análises automáticas. No desktop, cobrem correlação, repetição, ocupação e
falha de inferência. Chamadas reais à Cloudflare e ao modelo local verificam
perguntas comuns sem controlar dispositivos.
O teste local com Groq e Cloudflare indisponíveis atravessou um WebSocket
autenticado real, executou o helper/modelo no PC e devolveu a resposta para
o destino MOBILE com a mesma correlação em cerca de quatro segundos.
Relatório privado: `.artifacts/ia-live/resultado-ponte.json`.
