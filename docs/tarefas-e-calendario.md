# Tarefas, pendências e calendário do celular

Primeira etapa da evolução da assistência: tarefas ligadas às mensagens e à agenda.
O resumo do dia, as demais funções de mensagens, a edição da memória pessoal e
os próximos cenários continuam como etapas posteriores.

## Pela conversa

- “Preciso pagar a conta sexta.”
- “Crie uma tarefa comprar pão.”
- “Minhas tarefas.”
- “Adie pagar conta para amanhã às 15h.”
- “Já paguei a conta.”
- “Descarte a tarefa comprar pão.”

Tarefas podem ficar sem prazo. Se tiverem apenas uma data, ela vale até o fim do
dia no fuso configurado, sem inventar horário de aviso. Prazo com horário pode
gerar um aviso único, com a mesma dependência de servidor/conexão dos lembretes.
Vencer o prazo não remove a pendência; ela continua visível até concluir ou descartar.

Quando houver dois alvos possíveis, a Ollie pergunta e oferece os itens. A resposta
pode dizer o nome completo ou “a primeira/a segunda”. Ao pedir para adiar sem
data, ela pergunta e completa o pedido seguinte no mesmo dispositivo por dez minutos.
Uma ordem nova de agenda/dispositivo pode seguir seu caminho sem ser confundida
com essa continuação. O reconhecimento atual usa regras locais, não entende
qualquer formulação possível.

No PC há a página **Tarefas**. No celular há o ícone de tarefas no topo da
**Conversa** e o atalho **Ver tarefas e prazos** na agenda. As telas oferecem criar,
concluir, adiar, aceitar/descartar sugestões e consultar itens encerrados.

## Mensagens e agenda

Mensagens com uma ação identificável e data, como “pode enviar o relatório até
sexta?”, podem gerar uma sugestão de tarefa. Ela exige revisão antes de virar
pendência e não executa comandos nem configura alarmes. Cancelamentos e mensagens
sem data não entram nesse caminho automático.

A sugestão passa pelos filtros e orçamento de notificações existentes. Repetições
da mesma mensagem no dia não criam outra tarefa nem reabrem um item encerrado.
Um pedido explícito novo pode criar outra tarefa após concluir a anterior.

A consulta “qual minha agenda amanhã?” inclui também as tarefas com prazo nesse
dia, com links de revisão, sem duplicá-las como compromissos no banco.

## Cópia automática no Calendário Samsung ou outro calendário do Android

Em **Agenda/Tarefas → Conectar calendário do celular**:

1. Toque em **Autorizar calendário** e responda à autorização do Android.
2. Escolha um calendário gravável da sua conta/aparelho.
3. Confira o estado da sincronização nessa tela.

O recurso fica desligado até essa escolha. A integração usa o
[Calendar Provider do Android](https://developer.android.com/identity/providers/calendar-provider),
compartilhado pelos aplicativos de calendário do aparelho. A lista mostra os
calendários que o provedor disponibiliza com acesso de gravação. Não há login
Google no servidor nem envio dos outros eventos pessoais à Ollie.

São copiados apenas compromissos confirmados e tarefas confirmadas com prazo.
Sugestões, tarefas sem data e despertadores ficam fora. Alterar/adiar na Ollie
atualiza a própria cópia; concluir, descartar ou cancelar remove apenas a cópia
criada por ela. Os demais eventos do calendário não são modificados.

Datas de dia inteiro usam meia-noite UTC do dia declarado, conforme o contrato
do Android. Compromissos sem duração usam uma hora como padrão. Tarefas com
horário usam um marcador de um minuto, com disponibilidade livre. Não se
acrescenta um segundo alarme no calendário; o relógio continua separado.

O celular recebe um aviso para buscar mudanças, inclusive quando o pedido vem
do PC. Há também atualização periódica pelo WorkManager, com intervalo mínimo
de quinze minutos, sujeito às restrições de bateria/rede do Android. Precisa do
servidor atualizado e acessível. Salvar na Ollie não equivale a confirmar escrita
no calendário: o estado da cópia é apresentado no celular.

O vínculo entre item e evento evita duplicação em sincronizações repetidas e
permite recuperar uma gravação interrompida antes de salvar o ID local. Se você
apagar a cópia diretamente no calendário, ela não será recriada enquanto o item
da Ollie não mudar. Alterações feitas no calendário não retornam ao servidor;
uma nova mudança na Ollie pode atualizar novamente a cópia.

**Pausar integração** mantém as cópias. **Desconectar e remover cópias da Ollie**
remove somente eventos reconhecidos como seus, permitindo escolher outro
calendário. Um ID local que não corresponda mais a um evento da Ollie não é
alterado ou apagado.

## Contrato e persistência

- `GET /api/v1/tarefas?estado=abertas|pendente|sugestao|concluida|descartada`.
- `GET /api/v1/tarefas/{id}` e `POST /api/v1/tarefas`.
- `PATCH /api/v1/tarefas/{id}`: `aceitar`, `concluir`, `descartar`, `adiar`.
  A versão vista pelo cliente impede atualizar um prazo já alterado por outro cliente.
- `POST /api/v1/calendario/sincronizar`: projeção autenticada, somente leitura,
  de itens confirmados e estados dos IDs já copiados pelo celular.
- `acoes_tarefas` nas respostas e `TAREFA_REVISAR` nas notificações abrem revisão;
  `CALENDARIO_ATUALIZAR` apenas solicita atualização em segundo plano.
- Tabelas aditivas `tarefas_pessoais` e `tarefas_contextos`, no banco configurado.
- O kernel continua despachante. Agentes compartilham serviços de domínio,
  sem chamar outros agentes. O contexto de continuação não entra na memória
  semântica permanente.

O feed inicial inclui até 500 itens ativos por domínio; o celular pode consultar
até 1.000 IDs de cópias conhecidas por atualização. Ausência de um item no feed
não autoriza apagar o evento local. Os avisos de prazo recuperam conexão por
até uma hora; tarefas antigas continuam na lista mesmo depois dessa janela.

## Publicação

Precisa de deploy manual no Render e do novo APK. A autorização de calendário
deve ser dada pelo usuário na interface do Android. O patch do projeto Android
separado está em [android-tarefas-calendario.patch](patches/android-tarefas-calendario.patch),
aplicado sobre a integração de agenda anterior. Mantém as outras alterações locais.

## Validação desta entrega

391 testes Python passaram, dois foram ignorados. Os 59 testes unitários Android
e 17 testes do PC passaram. Frontend e executável Tauri compilaram; o PC foi
reaberto com a nova página e o APK foi instalado no celular.

Dois testes instrumentados abriram as telas de tarefas e de conexão ao calendário
sem criar dados pessoais nem autorizar permissões automaticamente. Depois da
autorização e escolha do Calendário Samsung pelo usuário, outro teste inseriu,
atualizou e removeu imediatamente um único evento temporário, sem alarme nem
convidados. O teste passou; nenhum evento de teste foi mantido.

A configuração local confirmou integração habilitada e calendário selecionado.
A sincronização com o servidor publicado ainda exige deploy manual no Render.
Isso é mostrado separadamente da autorização local, sem afirmar que um item
já foi copiado antes da escrita. O vínculo de voz é conferido novamente após os
testes instrumentados.
