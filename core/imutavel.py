"""Coleções JSON imutáveis, compatíveis com JSON e Pydantic."""

def _bloquear(*args, **kwargs):
    raise TypeError("Eventos são imutáveis; use clonar().")

class FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _bloquear
    def __deepcopy__(self, memo):
        return self

class FrozenList(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _bloquear
    def __deepcopy__(self, memo):
        return self

def congelar(valor):
    if isinstance(valor, dict):
        return FrozenDict({chave: congelar(item) for chave, item in valor.items()})
    if isinstance(valor, (list, tuple)):
        return FrozenList(congelar(item) for item in valor)
    return valor
