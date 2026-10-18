"""Excecoes de negocio: carregam mensagem pronta para mostrar ao operador."""


class ErroNegocio(Exception):
    """Regra de negocio violada (ex.: 'Estoque insuficiente')."""


class ErroValidacao(ErroNegocio):
    """Dados invalidos; `campos` mapeia nome do campo -> mensagem."""

    def __init__(self, mensagem: str, campos: dict | None = None):
        super().__init__(mensagem)
        self.campos = campos or {}


class ErroPermissao(ErroNegocio):
    """Operador sem nivel de acesso suficiente."""
