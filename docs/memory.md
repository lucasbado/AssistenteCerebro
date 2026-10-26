# Sistema de Memórias

Cada memória possui apenas uma responsabilidade.

---

Working Memory

Curto prazo.

Contexto imediato.

---

Semantic Memory

Conhecimento permanente.

---

Episodic Memory

Histórico cronológico.

Batidas internas de agendador (`TICK_AGENDA`, `TICK_TAREFAS`, `TICK_MENSAGENS`
e `TICK_ROTINA`) não são acontecimentos pessoais e não são arquivadas. Resultados
de ações e avisos produzidos a partir delas continuam seguindo o histórico normal.

Quando a persistência fica bloqueada por cota, a composição de controles pode
funcionar em [modo limitado](modo-limitado-neon.md), sem criar outra memória nem
anunciar gravações que não aconteceram.

---

User Profile

Preferências.

---

Statistics

Métricas.

Jamais utilizar uma memória para finalidade diferente.
