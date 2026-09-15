# Tarefas: Central de Verificação de Rotinas no App

- [x] **Android: Infraestrutura de API**
    - [x] Atualizar `CognitiveApiService.kt` com endpoints de descoberta e aprovação
    - [x] Atualizar `CognitiveRepository.kt` para suportar as novas chamadas
- [x] **Android: Lógica de Negócio**
    - [x] Criar `AutomationViewModel.kt` para gerenciar a fila de rotinas
- [x] **Android: Interface do Usuário (UI)**
    - [x] Adicionar seção "Descobertas pela Ollie" em `CapabilitiesScreen.kt`
    - [x] Atualizar `HomeScreen.kt` para aprovação remota via API
- [x] **Backend: Otimização de Tokens**
    - [x] Reordenar Prompt para Caching (Static first)
    - [x] Implementar Injeção Seletiva no Obsidian (Busca por keyword)
    - [x] Adicionar Rodízio de Modelos Fallback (Llama 3.3/3.1)
    - [x] Poda agressiva de histórico (Working Memory limit 5)
    - [x] Extração de 'retry-after' do erro 429 para Backoff inteligente
