"""Cenário sem efeitos: confirma que o interpretador local consegue executar."""
import sys

if sys.version_info < (3, 10):
    raise RuntimeError("Ollie requer Python 3.10 ou mais recente")
