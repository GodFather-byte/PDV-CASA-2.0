"""Roteiros sem Qt e conclusão por operador, sem criar cadastros fictícios."""
from dataclasses import dataclass
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

@dataclass(frozen=True)
class Passo:
    janela: str
    widget: str
    texto: str
    condicao: str = ""

PRODUTO = (
    Passo("lista", "tutorial_busca", "Aqui ficam os produtos. Vamos cadastrar um produto real."),
    Passo("lista", "tutorial_novo", "Clique em Novo para começar.", "formulario"),
    Passo("formulario", "produto_nome", "Digite o nome do seu produto.", "preenchido"),
    Passo("formulario", "produto_preco_cent", "Informe o preço de venda, por exemplo 12,50.", "preco"),
    Passo("formulario", "produto_cbarra", "Leia ou digite o código de barras. Se não tiver, pode deixar vazio."),
    Passo("formulario", "tutorial_estoque", "Informe a quantidade inicial. Vazio não lança estoque; ajustes exigem acesso de gerente."),
    Passo("formulario", "produto_codigo", "Confira o código interno, o subgrupo e a unidade nas opções desta aba antes de salvar."),
    Passo("formulario", "tutorial_salvar", "Clique em Salvar. Só concluímos quando o produto for gravado.", "salvo"),
)

class Tutoriais:
    def __init__(self, banco, operador_id):
        self.banco, self.operador_id = banco, operador_id

    def _chave(self, tutorial):
        if tutorial != "produto" or self.operador_id is None:
            raise ErroNegocio("Tutorial ou operador inválido.")
        return f"tutorial_{tutorial}_operador_{self.operador_id}"

    def concluido(self, tutorial="produto"):
        return self.banco.cfg(self._chave(tutorial)) == "S"

    def concluir(self, tutorial="produto"):
        self.banco.cfg_set(self._chave(tutorial), "S")

    @staticmethod
    def permite(passo, valor="", formulario=False, salvo=False):
        if passo.condicao == "formulario":
            return formulario
        if passo.condicao == "salvo":
            return salvo
        if passo.condicao == "preenchido":
            return bool(valor.strip())
        if passo.condicao == "preco":
            try:
                return fmt.para_centavos(valor) >= 0 and bool(valor.strip())
            except (ValueError, ErroNegocio):
                return False
        return True

    def cadastrar(self, cadastros, valores, quantidade, concluir=True):
        from src.controllers.estoque_controller import EstoqueController
        try:
            qtd = fmt.para_qtd(quantidade) if quantidade.strip() else None
        except ValueError as erro:
            raise ErroNegocio("Informe uma quantidade inicial válida.") from erro
        if qtd is not None and qtd < 0:
            raise ErroNegocio("Estoque inicial não pode ser negativo.")
        with self.banco.transacao():
            produto = cadastros.salvar("produtos", valores)
            if qtd is not None:
                estoque = EstoqueController(self.banco, self.operador_id)
                lanc = estoque.criar_lancamento("inicial", descricao="Cadastro guiado de produto")
                estoque.adicionar_item(lanc, produto, qtd)
            if concluir:
                self.concluir()
        return produto
