from core.kernel import kernel
from servicos.llm import ServicoLLM
from servicos.catalogo_semantico import catalogo

class AgregadorStatus:
    def __init__(self):
        # Instanciamos o serviço LLM para obter o nome do modelo
        self.llm_service = ServicoLLM()

    async def obter_dados_status(self) -> dict:
        """
        Coleta métricas de diferentes partes do sistema.
        """
        kernel_stats = kernel.estatisticas()
        # A funcionalidade de memória semântica foi refatorada para dentro do 'catalogo'.
        cache_semantico_size = catalogo.memoria.tamanho_cache()
        # 🛡️ FIX: Usa o nome correto do atributo após a refatoração da Groq
        modelo_llm = getattr(self.llm_service, "modelo_atual", "Desconhecido")

        return {
            "kernel": kernel_stats,
            "llm_modelo": modelo_llm,
            "cache_semantico": cache_semantico_size
        }

agregador_status = AgregadorStatus()