import asyncio
import os
import sys

# Adiciona o diretório raiz ao path para importar os serviços
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

async def main():
    print("🚀 Iniciando varredura manual de padrões...")
    from servicos.routine_generator_service import routine_generator_service
    from banco.database import inicializar_banco
    
    # Inicializa o banco para poder ler os padrões
    await inicializar_banco()
    
    # Executa a geração
    await routine_generator_service.run_batch_generation()
    
    print("\n✅ Varredura concluída!")
    print(f"Verifique o arquivo: D:/Programacao/AssistenteCell/config/discovered_routines.json")

if __name__ == "__main__":
    asyncio.run(main())
