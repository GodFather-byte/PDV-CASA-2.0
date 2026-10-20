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


class ErroEstoqueInsuficiente(ErroNegocio):
    """Venda recusada porque um ou mais produtos não têm saldo suficiente."""

    def __init__(self, faltas: list[dict]):
        self.faltas = faltas
        qtd = lambda valor: f"{valor:.4f}".replace(".", ",").rstrip("0").rstrip(",")
        linhas = [
            f"{f['nome']}: disponível {qtd(f['disponivel'])}, necessário {qtd(f['necessario'])}"
            for f in faltas
        ]
        super().__init__("Estoque insuficiente para concluir a venda — " + "; ".join(linhas) + ".")
