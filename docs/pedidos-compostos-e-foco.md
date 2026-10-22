# Pedidos compostos, buscas e primeiro plano — 22/10/2026

## Uso

Exemplos reconhecidos pela nova interpretação:

- “Abra YouTube no PC e abra WhatsApp no celular.”
- “Apague a luz do quarto e abra HBO Max no PC.”
- “Abra YouTube e pesquise ESP32 + Home Assistant no PC.”
- “Pesquise como configurar C++ e Python 3.11 no PC.”
- “Busque Rust + Tauri no GitHub no computador.”
- “Acesse https://example.com/Video/AbC?Id=XYZ no PC.”

Google, YouTube e GitHub têm endereços próprios de busca. Um domínio informado
ou serviço cadastrado sem integração usa pesquisa Google restrita ao domínio
(`site:dominio termo`). Não são inventados caminhos internos de páginas.
Termos preservam maiúsculas, acentos, versões e sinais como `C++`.
Uma consulta pode conter “como”, “não” ou “se”. Ordens citadas entre aspas não
viram etapas executáveis.

## Interpretação e execução

`linguagem_pedidos` separa orações; `plano_pedidos` interpreta casos conhecidos
e valida o conjunto. Casos livres usam a LLM com a mesma lista de ações e um
`trecho` correspondente ao pedido atual. O sistema decide o destino por etapa.
Sem menção explícita, usa a origem; uma menção única na frase pode determinar
o destino das aberturas. Dois aparelhos na mesma etapa exigem esclarecimento;
PC em uma etapa e celular em outra são válidos.

`AgenteRaciocinio` publica `PLANO_SOLICITADO` para pedidos com várias ações.
`AgentePlano` verifica conexões e executa até seis etapas em ordem pelos serviços
de transporte existentes. Não há chamada direta entre agentes ou lógica nova no
kernel. Só são usados comandos suportados, nunca shell ou código gerado.

A próxima etapa aguarda a confirmação do PC. Erro, desconexão ou ausência de
confirmação interrompem as restantes. A luz exige estado confirmado pelo Home
Assistant. O Android ainda não confirma a abertura de apps: nesse caso, o resumo
informa **envio**, sem afirmar sucesso físico. Há uma resposta consolidada na
origem, IDs distintos por etapa e proteção contra replay no processo atual.
Não há rollback de efeitos já produzidos ou diário persistente para retomar planos
após reiniciar o servidor.

O prazo do plano é de 35 segundos e a espera individual pela confirmação do PC
é de até 12 segundos. Após timeout, não há repetição automática; uma ação enviada
pode terminar mais tarde. Notificações de terceiros não entram no caminho
autorizado de pedidos compostos.

## Janela em primeiro plano

Antes, `webbrowser.open` apenas encaminhava a URL ao Windows. A ponte agora pede
uma aba, identifica o navegador padrão e procura sua janela após o lançamento.
Janelas minimizadas são restauradas. A ativação é verificada pelo handle real
de primeiro plano, com prazo limitado. O mecanismo também atende programas locais.
WebViews não são consideradas navegadores e não se fixa uma janela como “sempre
no topo”. Sem conhecer o navegador padrão, só são consideradas janelas novas
ou com título alterado após o lançamento.

O Tauri inicia o helper sem console e delega o direito de ativação quando dispõe
dele. O helper retorna `primeiro_plano: true|false`, transmitido junto da confirmação.
O app avisa quando encaminhou a abertura, mas não confirmou o foco. O Windows
ainda pode negar foco enquanto outro app está sendo utilizado; políticas do sistema
não são alteradas para contornar essa restrição.

Referências: [webbrowser](https://docs.python.org/3/library/webbrowser.html),
[SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow),
[SetWindowPos](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos).

## Memória e rotinas

Conhecimento pessoal e hábitos eram recuperados no raciocínio, mas os argumentos
não chegavam ao prompt do modelo. Agora entram como dados de contexto, com tamanho
limitado, para interpretar preferências e sugerir próximos passos. Não autorizam
ações extras ou ativação automática de rotinas.

A descoberta de padrões, evidência mínima, catálogo persistente e aprovação de
rotinas continuam no fluxo existente. Uma sequência pedida não cria nem ativa
uma rotina. Abrir um site também não significa ler ou operar seu conteúdo:
autenticação, formulários e cliques internos exigem capacidades adicionais.

## Validação e publicação

- Backend: **323 testes aprovados, dois ignorados** na suíte completa final.
- Desktop: **14 testes aprovados**; TypeScript/Vite compilados.
- Executável Windows compilado com `cargo build --offline --features tauri/custom-protocol`.
- Casos novos cobrem busca completa, consultas citadas, destinos por etapa,
  validação antes de efeitos, confirmação em ordem, falhas, replay e foco negado.
- O app recompilado foi reaberto; conexão e escuta da chamada foram verificadas
  pela interface. O usuário confirmou que, ao pedir “abra https://example.com no
  PC”, o navegador veio para primeiro plano. Os testes automatizados de foco
  também cobrem uma API simulada que recusa a ativação.

A ponte de foco já está no cliente local. Pedidos compostos, novos verbos e contexto
de hábitos no modelo precisam do **deploy manual do backend no Render** a partir
do commit publicado. Não há migração de banco.
