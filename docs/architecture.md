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
