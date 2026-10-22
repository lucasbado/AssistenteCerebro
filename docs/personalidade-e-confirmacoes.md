# Personalidade e confirmações da Ollie

## Mudança

As frases repetidas de “PC: abertura concluída” eram produzidas pelo executor,
sem passar pelo modelo. Alterar somente o prompt não mudaria essas confirmações.

`servicos/respostas_acoes.py` transforma resultados em uma resposta curta com os
nomes dos aplicativos, sites e buscas. Aberturas confirmadas consecutivas no PC
são agrupadas: “Pronto, abri o YouTube e o HBO Max no PC.” Uma busca preserva o
termo, por exemplo: “Abri a busca por ‘ESP32 + Home Assistant’ no YouTube no PC.”

Os agentes mantêm execução, ordem, confirmações e proteção contra repetição.
A apresentação fica em serviço separado, sem nova chamada à LLM. Aberturas
simples no PC/celular também usam essa apresentação. No celular, a frase continua
indicando envio: “Mandei abrir o WhatsApp no celular.” Erro, falta de confirmação
e falha de foco continuam visíveis; não são agrupados como sucesso. URLs
desconhecidas são descritas pelo domínio, sem repetir credenciais ou query.

## Tom das conversas

`servicos/personalidade_ollie.py` concentra a orientação usada pelo raciocínio e
pela síntese de pesquisas: português brasileiro próximo, solto e direto, com
contrações e respostas proporcionais ao pedido. Evita entusiasmo automático,
bordões, elogios gratuitos, emojis em série e intimidade forçada.

O modelo pode usar um palavrão ocasional quando o próprio usuário fala assim e o
contexto combina. Isso não é obrigatório, não deve aparecer em toda resposta e
não autoriza insultar pessoas. Linguagem de notificações citadas não determina o
tom do usuário. Nos retornos locais de ações, o texto casual do pedido pode mudar
“Pronto” para “Fechou”; não há inserção automática de palavrões.

A resposta do modelo também deixa de passar por `capitalize()`, que convertia
todo o restante da frase para minúsculas e alterava nomes como YouTube e HBO Max.

## Validação e publicação

Suíte completa de backend: **334 testes aprovados e dois ignorados**. Os casos
cobrem respostas com nomes reais, agrupamento, busca, sucesso parcial, envio ao
celular, falta de confirmação da casa, aviso de foco e preservação das marcas.
A política de personalidade foi conferida na entrada do modelo com provedor
simulado; o tom das respostas livres ainda depende do modelo e deve ser observado
após o deploy.

Esta mudança é do backend: exige **deploy manual no Render** do commit publicado.
Não é necessário recompilar o desktop ou reinstalar o Android.
