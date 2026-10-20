# Arquitetura Cognitiva

## Objetivo

Construir uma Assistente Cognitiva Local.

Não é um chatbot.

É um sistema operacional cognitivo composto por agentes independentes.

---

## Filosofia

O sistema deve funcionar semelhante a um cérebro.

Pipeline:

Sensores

↓

Filtro de Atenção

↓

Kernel

↓

Agentes

↓

Novos Eventos

↓

Kernel

↓

...

---

## Componentes

Android

↓

Gateway

↓

Pipeline de Atenção

↓

Kernel

↓

Agentes

↓

Memórias

↓

LLM

↓

Planejamento

↓

Execução

---

## Princípios

Baixo acoplamento

Alta coesão

Responsabilidade única

Eventos imutáveis

Componentes independentes

Escalabilidade horizontal

## Controle da casa

A Ollie coordena pedidos de chat, voz e botões através de eventos canônicos.
`AgenteCasa` resolve o dispositivo cadastrado, serializa ações por entidade e
responde após confirmação de estado. Home Assistant executa as ações físicas;
PC e Android funcionam como pontes locais. ESPHome amplia as entradas e saídas
do ambiente. O kernel mantém apenas despacho e supervisão.

Detalhes e limites atuais: [Central da casa](central-da-casa.md).

## Rotinas aprendidas e aprovadas

Descoberta, API de gerenciamento e `AgenteRotina` compartilham um catálogo
transacional no banco configurado. Arquivos JSON são usados apenas na primeira
importação. Sugestões não executam antes da aprovação do usuário. Validação e
normalização de contratos ficam em serviço próprio; o kernel continua apenas
despachando eventos. Reservas persistentes evitam repetir disparos após reinícios.

Fluxo, migração e validação: [Superpoderes e rotinas](superpoderes-rotinas.md).

## Abertura de aplicativos

`InterventionGovernor` persiste política e limites de abertura no banco. Aprovar
uma rotina não dispensa importância e autorização de destino. O raciocínio pode
sugerir apps a partir de eventos externos; pedidos explícitos mantêm sua origem
e correlação até o executor. Android verifica autorização, importância e intervalo
antes de iniciar outro app. O kernel permanece responsável apenas pelo despacho.

Regras e publicação: [Abertura automática e importância](abertura-automatica.md).

Pedidos explícitos carregam dispositivo e canal de origem desde a entrada. O
serviço de roteamento escolhe a origem como destino padrão de aberturas e respeita
o destino explícito no texto. Respostas retornam exclusivamente à origem; o
executor físico da casa pode ser outro dispositivo. A voz de desktop é consumida
apenas pelo cliente que iniciou o pedido, com deduplicação por correlação/resposta.
Detalhes: [Comandos por origem e voz do PC](roteamento-dispositivos.md).
