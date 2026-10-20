# Superpoderes e gestão de rotinas

Atualização posterior: [controle de abertura automática e importância](abertura-automatica.md).
Rotina aprovada também respeita o interruptor geral de abertura e começa em
Só sugerir. Os resultados e pendências abaixo registram a revisão anterior.

## Problemas encontrados

A consulta ao Render encontrou 48 sugestões e quatro rotinas cadastradas. O
Android só buscava sugestões, lia o formato de cards da Home em vez de
`gatilho`/`acoes`, escondia erros e não oferecia pausa ou exclusão das aprovadas.
Os interruptores de habilidades e regras locais não eram consumidos por um
executor. O botão de criar modo enviava um nome, sem uma sequência executável.

Registros antigos também continham comandos como `launch_app` no celular e
`opera.exe` como nome de comando PC. Outros dependiam de `PC_LOGIN`, evento sem
produtor. Nomes passados na URL dificultavam operações com barras e caracteres
especiais. Os arquivos locais tinham 51 sugestões e três rotinas: reutilizá-los
no deploy perderia o estado que estava no Render.

## Comportamento implementado

- A tela separa sugestões e rotinas cadastradas e permite buscar pelo nome.
- Cada card mostra o gatilho real, todas as ações, intervalo e evidência. Sugestão
  antiga sem evidência fica identificada para revisão.
- Aprovar exige uma rotina válida. A rotina aguarda o próximo gatilho; ativar não
  executa suas ações imediatamente. Pausar não depende de reiniciar o backend.
- Excluir uma sugestão ou rotina registra o padrão rejeitado. Nome, texto ou rótulo
  diferente para o mesmo próximo aplicativo não contornam essa rejeição.
- Contratos antigos reconhecidos são normalizados; comandos desconhecidos e
  gatilhos sem produtor ficam bloqueados com explicação.
- Falhas da API aparecem sem apagar a lista. Controles ficam bloqueados enquanto
  uma operação está em andamento. Nomes são enviados no corpo das requisições.
- Nova rotina pelo formulário cria um aviso com botão para abrir um aplicativo,
  disparado ao abrir outro aplicativo. É salva pausada, com intervalo de uma hora.
- Regras antigas locais podem ser revistas e salvas pausadas no servidor; a cópia
  local só é retirada após o servidor confirmar que salvou.
- Os interruptores que só alteravam preferências locais foram retirados da tela.
  Essas preferências e as regras antigas não foram apagadas automaticamente.

## Persistência e execução

`CatalogoRotinas` mantém sugestões, rotinas aprovadas, rejeições e reservas de
disparo em `catalogo_rotinas`, no banco configurado por `DATABASE_URL`. A API,
descoberta e executor usam essa fonte. Aprovação move a sugestão em uma única
transação; uma falha de validação não remove a pendência.

O primeiro acesso importa `config/migracao_rotinas.json`, se presente, ou os
arquivos legados. Após criar o catálogo, alterações nesses arquivos não substituem
as escolhas no banco. A inicialização normal de `main:app` cria a tabela nova.
Não há remoção ou recriação das tabelas existentes.

O executor revalida a rotina e sua ativação antes de reservar um disparo. O
intervalo e o limite diário sobrevivem a reinícios. Se um PC/celular necessário
estiver offline, a sequência não começa e a reserva é liberada. Há proteção
transacional por linha no PostgreSQL, além da exclusão mútua no processo.

A reserva registra encaminhamento, não comprova execução física de cada ação.
Se houver falha depois de encaminhar parte de uma sequência, não existe rollback
dos efeitos já produzidos. Falha de processo durante um disparo mantém a reserva
conservadora até vencer o intervalo, evitando uma repetição imediata.
Rotinas de casa publicam eventos para `AgenteCasa`; sua confirmação entra como
notificação de rotina, sujeita ao orçamento, em vez de resposta de chat.

## Publicação manual no Render

O APK foi atualizado no celular. O backend novo **ainda precisa ser publicado**.
O app detecta a ausência da validação no servidor antigo e mostra o motivo pelo
qual ativar/pausar ainda não está disponível. Revisão e exclusão permanecem
acessíveis; exclusão de aprovadas tem compatibilidade com a rota antiga.

Foi preparado `config/migracao_rotinas.json` com quatro rotinas e 48 sugestões
exportadas do servidor, sem tokens. As flags de ativação foram preservadas;
nenhuma rotina pessoal foi ativada ou excluída durante a revisão.
Se as listas mudarem antes do deploy, atualize a cópia:

```powershell
.\.venvs\Scripts\python.exe scripts/exportar_catalogo_rotinas.py --url https://SEU-BACKEND.onrender.com
```

O script usa `OLLIE_API_TOKEN` do `.env`, faz apenas consultas ao servidor e grava
a cópia local. Rejeições antigas que existam em `config/rejected_routines.json`
também entram na cópia. O servidor antigo não expõe suas rejeições por API;
portanto, rejeições que só estejam no filesystem remoto precisam ser preservadas
desse arquivo antes de trocar a instância, caso seja necessário mantê-las.

Publique as alterações de backend com a cópia de migração e mantenha a
`DATABASE_URL` persistente do serviço. O processo deve iniciar `main:app` para
ter kernel, agentes e relógio. Depois do deploy, toque em atualizar na tela:
o aviso de versão antiga desaparece e as rotinas válidas ficam gerenciáveis.

O banco é a fonte permanente após a primeira importação. Não apague a linha do
catálogo para atualizar o serviço: isso repetiria a importação inicial.

## Validação

Resultado final: **120 testes Python e 33 testes Android passaram**; o APK final
compilou e foi instalado. Relatório: `.artifacts/teste-superpoderes.json`.

Testes isolados cobrem importação única, prioridade da cópia do Render,
aprovação/pausa/exclusão pela API com nomes Unicode e barras, preservação de
evidência, rollback de aprovação inválida, deduplicação semântica, concorrência,
reinício do executor, indisponibilidade de ponte e integração por eventos com a
casa. No Android, os testes cobrem os DTOs reais, autenticação, nomes no corpo,
consulta sem ativação, erros visíveis, migração local pausada e rota legada.

A tela instalada foi conferida contra o Render: exibiu 48 sugestões e quatro
rotinas, gatilhos/ações corretos e o aviso de backend antigo. Nenhuma operação
de ativar, pausar ou excluir foi feita sobre os registros pessoais. O teste de
mutação completo usou banco e transporte isolados; a validação em produção
depende do deploy manual.
