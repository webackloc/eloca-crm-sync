"""
run_once.py — Executa um único ciclo de sincronização e encerra.
Usado pelo GitHub Actions (sem o loop infinito do scheduler.py).
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from scheduler import executar_sincronizacao

if __name__ == "__main__":
    asyncio.run(executar_sincronizacao())
