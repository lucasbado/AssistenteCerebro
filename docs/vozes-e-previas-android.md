# Vozes e prévias no celular

Em **Configurações → Voz da Ollie**, o seletor agora separa **Vozes naturais**
de **Vozes do celular**. As naturais aparecem como Thalita, Francisca e Antônio,
com idioma, gênero informado pelo catálogo e indicação de internet. As vozes
instaladas recebem nomes como “Voz do celular 1”, com idioma/região e indicação
de funcionamento com ou sem internet; não é inventado gênero para códigos opacos
do motor TTS. O identificador original continua sendo usado internamente.

## Ouvir e escolher

**Ouvir** toca uma frase curta na opção solicitada. Mostra preparação, reprodução,
conclusão ou erro; durante a amostra o botão vira **Parar**. A prévia usa o volume
de mídia e funciona mesmo quando a leitura automática está desligada ou o modo
foco silencia respostas proativas. Ouvir não grava outra voz como preferência.

Tocar na opção seleciona e salva a voz para as próximas respostas. A amostra
anterior para ao selecionar outra voz ou fechar o seletor. A seleção é respeitada
também pelas instâncias de voz usadas na ilha/assistente e no serviço de mensagens,
que leem a preferência antes de falar.

As vozes do celular são publicadas na tela após a inicialização assíncrona do TTS.
As naturais ficam disponíveis para escolha mesmo enquanto o motor local inicia.
Selecionar uma voz não habilita a leitura automática por conta própria.

## Problemas corrigidos

O botão antigo recebia o nome da voz mas o ignorava: chamava a reprodução padrão
da nuvem. A seleção alterava somente o TTS local, enquanto as respostas tentavam
a nuvem primeiro. A prévia ainda era silenciada no modo foco, sem informar isso.

Agora a escolha determina o motor: uma voz local vai ao TTS do celular, e uma
natural envia seu nome explícito ao endpoint autenticado `/api/v1/voice/speak`.
**A prévia não usa outra voz em caso de erro**, pois isso impediria comparar as
opções. Nas respostas normais, a voz da nuvem ainda pode usar a voz padrão do
celular se a rede falhar, mantendo a resposta audível.

O nome padrão `pt-BR-ThalitaNeural` estava desatualizado. O catálogo público do
Edge TTS consultado em 24/10/2026 oferece `pt-BR-ThalitaMultilingualNeural`.
O backend usa o nome atual e aceita o anterior como alias. O parâmetro de tom,
antes calculado e descartado, também é passado ao sintetizador, junto da velocidade.
Não foi adicionado provedor pago ou nova permissão Android.

O ciclo de reprodução possui identificação por sessão para impedir que callbacks
de amostras canceladas iniciem áudio atrasado ou encerrem a amostra seguinte.
Durante a prévia, a detecção de chamada cede o microfone pela sinalização de voz
ocupada já existente; ao terminar ou cancelar, essa sinalização é liberada.

## Verificação e entrega

- Backend: **454 testes passaram**, dois foram pulados, incluindo voz selecionada,
  alias antigo, velocidade, tom e falha sem áudio de outra voz.
- Android: **63 testes unitários passaram** e o APK compilou.
- No celular conectado: a prévia natural Francisca e uma voz local iniciaram e
  terminaram a reprodução, mantendo a preferência salva; cancelamento e os botões
  Ouvir/Parar também passaram nos testes de interface/reprodução.
- A captura do seletor foi inspecionada; nomes e botões ficaram legíveis.
- O usuário confirmou ouvir amostras diferentes de Francisca e Antônio.

O APK atualizado foi instalado preservando as preferências. A assistente foi
reconectada após os testes. As correções do backend para nome padrão/alias e tom
precisam de **deploy manual no Render**. As amostras com nome explícito já funcionam
no endpoint anterior. Não há mudança no app do PC nesta etapa.

O código Android desta etapa está preservado em
[android-vozes-previa.patch](patches/android-vozes-previa.patch), com manifesto de
hashes. A base é a cópia local após a integração da caixa de mensagens; não inclui
todas as alterações anteriores do projeto Android.
