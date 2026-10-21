# Revisão da interface do PC — 21/10/2026

A interface do Ollie Master Next foi organizada em quatro páginas, preservando
o fundo escuro, os detalhes verdes e lilás e os fluxos existentes de comando e voz.

## Problemas encontrados e mudanças

| Antes | Agora |
| --- | --- |
| Conversa misturada com registros técnicos, sem hierarquia clara. | Página **Conversa**, com mensagens separadas por autor e horário; registros em **Atividade**. |
| Rolagem automática procurava a primeira `.custom-scrollbar`, que era a barra lateral. | Referências independentes para conversa e registros; a rolagem acompanha novas entradas quando o usuário está próximo do fim. |
| Indicador “REC” estático sugeria uma gravação inexistente. | Estado real da voz, distinguindo chamada desligada, espera, escuta, processamento, fala e erro. |
| Microfone, monitoramento e ações locais competiam com o chat. | Página **Computador**, com janela em uso, processador, RAM, entrada de áudio e conexões. |
| Autonomia ficava em um modal apertado. | Página **Autonomia**, com importância mínima, aplicativos permitidos/bloqueados e revisão de sugestões. |
| Falhas de consulta deixavam valores iniciais parecendo configurações carregadas. | Estados explícitos de carregamento, erro e nova tentativa; controles indisponíveis enquanto a política não é conhecida. |
| Resposta da política continha metadado de versão rejeitado pelo POST. | Somente os quatro campos editáveis são reenviados; valores válidos entre zero e um são aceitos na leitura. |
| Sugestões antigas podiam ter nomes repetidos e faltava explicar uma ativação indisponível. | Chaves de renderização distintas; sugestões marcadas como inválidas pelo servidor mostram o motivo e não oferecem ativação. |

## Organização e interação

- `src/components/DesktopInterface.tsx` concentra a apresentação; transporte,
  execução e coordenação da voz continuam em `App.tsx` e nos módulos existentes.
- Sugestões da conversa preenchem o rascunho; o envio depende de uma ação explícita.
- O rascunho continua disponível ao navegar entre páginas. Sem conexão, permanece
  no campo e o envio fica indisponível.
- Falhas e confirmações têm avisos visíveis. As respostas aceitas continuam usando
  a correlação e a proteção contra repetição de `DesktopReplies`.
- A chamada por voz e o comando `wake_ollie` levam à página de conversa.
- A barra lateral se compacta em janelas estreitas; painéis têm rolagem própria.
- Controles possuem nomes acessíveis, foco visível, indicação da página atual e
  suporte à preferência de movimento reduzido. A janela usa os controles nativos
  do Windows, sem uma segunda barra de minimizar/maximizar/fechar dentro do app.

## Validação executada

- `npm.cmd run build`: TypeScript e bundle Vite aprovados.
- `npm.cmd test`: **14 testes existentes aprovados**, cobrindo coordenação da
  escuta, cancelamento, correlação de respostas, reprodução e silenciamento.
- `cargo build --offline --features tauri/custom-protocol`: executável Windows
  compilado com a interface embarcada.
- Inspeção no aplicativo nativo: navegação nas quatro páginas, conexão ao
  servidor, dados do computador, leitura da política e das sugestões existentes.
- Conversa real: envio de “Responda apenas: interface pronta.” e recebimento de
  “Interface pronta.” em balões distintos.
- Rascunho preservado ao ir para Atividade e voltar à Conversa.
- Janela estreita de aproximadamente 640 px: navegação compacta e acesso aos
  controles do computador pela rolagem.

As preferências de microfone, chamada e voz foram preservadas. Abertura de apps,
acionamento da casa e alteração/ativação/descarte de rotinas não foram executados
como parte desta validação visual. A chamada acústica não foi testada novamente
ao vivo nesta revisão; os testes automatizados de voz passaram.

## Limites e próximos pontos

O histórico mostrado mantém até 100 mensagens desta sessão e não é persistido
entre reinicializações. As listas de aplicativos permitidos/bloqueados são
exibidas, mas ainda não possuem editor no PC. O cadastro do servidor e do token
continua no mecanismo atual. Nomes de rotinas repetidos no servidor não foram
alterados por esta revisão.

Esta mudança é do cliente do PC. Não exige novo deploy no Render.
