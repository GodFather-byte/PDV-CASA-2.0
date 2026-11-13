"""Roteiros sem Qt e conclusão por operador, sem criar cadastros fictícios.

Cada tutorial guia um cadastro de verdade, passo a passo, em linguagem simples (pensada para quem nunca usou um
sistema). Para criar outro: escreva os passos e registre em `ROTEIROS`. O alvo de cada passo é o `objectName` do campo
na tela real (`produto_<campo>` no formulário; `tutorial_busca`, `tutorial_novo` e `tutorial_salvar` nos botões).
"""
from dataclasses import dataclass
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

@dataclass(frozen=True)
class Passo:
    janela: str
    widget: str
    texto: str
    condicao: str = ""


@dataclass(frozen=True)
class Roteiro:
    chave: str
    titulo: str          # texto do botão no menu Tutoriais
    cadastro: str        # chave da entidade (a tela que abre)
    modulo: str          # acesso exigido
    passos: tuple
    fim: str             # mensagem ao concluir

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

_NOVO = Passo("lista", "tutorial_novo", "Clique no botão Novo.", "formulario")
_SALVAR = Passo("formulario", "tutorial_salvar", "Agora clique em Salvar. Pronto: fica gravado de verdade.", "salvo")

GRUPO = (
    Passo("lista", "tutorial_busca", "Grupos são como as prateleiras da loja: Bebidas, Comidas, Cigarros. "
                                     "Vamos criar um grupo de verdade."),
    _NOVO,
    Passo("formulario", "produto_nome", "Escreva o nome do grupo. Exemplo: Bebidas.", "preenchido"),
    _SALVAR,
)

SUBGRUPO = (
    Passo("lista", "tutorial_busca", "Subgrupo é a divisão dentro do grupo. Exemplo: dentro de Bebidas ficam "
                                     "Cervejas, Refrigerantes e Águas. Todo produto fica em um subgrupo."),
    _NOVO,
    Passo("formulario", "produto_nome", "Escreva o nome do subgrupo. Exemplo: Cervejas.", "preenchido"),
    Passo("formulario", "produto_grupo_id", "Clique aqui e escolha em qual grupo ele fica.", "escolhido"),
    _SALVAR,
)

CLIENTE = (
    Passo("lista", "tutorial_busca", "Aqui ficam os clientes. Serve para vender fiado (caderneta), entregar em casa "
                                     "e achar a pessoa pelo telefone."),
    _NOVO,
    Passo("formulario", "produto_numero_consulta", "Este é o número para achar o cliente no caixa. O sistema já "
                                                   "sugeriu um: pode deixar assim ou trocar pelo telefone dele.",
          "preenchido"),
    Passo("formulario", "produto_nome", "Escreva o nome do cliente.", "preenchido"),
    Passo("formulario", "produto_telefone", "Digite o telefone com DDD. Se não souber, pode deixar vazio."),
    Passo("formulario", "produto_limite_cent", "Se este cliente pode comprar fiado, escreva até quanto ele pode dever. "
                                               "Exemplo: 100,00. Deixe 0,00 para não vender fiado."),
    _SALVAR,
)

OPERADOR = (
    Passo("lista", "tutorial_busca", "Cada pessoa que usa o sistema tem o seu nome e a sua senha. "
                                     "Assim você sabe quem fez cada venda."),
    _NOVO,
    Passo("formulario", "produto_nome", "Escreva o nome da pessoa.", "preenchido"),
    Passo("formulario", "produto_senha", "Crie uma senha com até 10 letras ou números, sem espaço. "
                                         "Só essa pessoa deve saber.", "preenchido"),
    Passo("formulario", "produto_nivel", "Escolha o nível. 0 é só o caixa (vender e receber). 4 é o dono: abre tudo. "
                                         "Na dúvida, deixe 0 para quem só vende."),
    _SALVAR,
)

PAGAMENTO = (
    Passo("lista", "tutorial_busca", "Aqui ficam as formas de pagamento que aparecem no caixa: Dinheiro, Pix, "
                                     "Cartão. Vamos criar mais uma."),
    _NOVO,
    Passo("formulario", "produto_tipo", "Escreva o nome da forma de pagamento. Exemplo: Vale refeição.", "preenchido"),
    Passo("formulario", "produto_permite_troco", "Marque Sim só se esta forma dá troco, como o dinheiro. "
                                                 "Cartão e Pix não dão troco."),
    Passo("formulario", "produto_na_gaveta", "Marque Sim se o que você recebe fica na gaveta (dinheiro, ticket de "
                                             "papel). Cartão e Pix não ficam na gaveta."),
    _SALVAR,
)

FORNECEDOR = (
    Passo("lista", "tutorial_busca", "Fornecedor é de quem você compra a mercadoria. Com ele cadastrado, o sistema "
                                     "ajuda na hora de repor o estoque."),
    _NOVO,
    Passo("formulario", "produto_nome", "Escreva o nome do fornecedor. Exemplo: Distribuidora Central.", "preenchido"),
    Passo("formulario", "produto_telefone", "Digite o telefone. Se não souber agora, pode deixar vazio."),
    _SALVAR,
)

ROTEIROS = {r.chave: r for r in (
    Roteiro("produto", "Cadastrar um produto", "produtos", "cad_produtos", PRODUTO,
            "Produto cadastrado. Tutorial concluído!"),
    Roteiro("grupo", "Criar um grupo", "grupos", "cad_grupos", GRUPO, "Grupo criado. Tutorial concluído!"),
    Roteiro("subgrupo", "Criar um subgrupo", "subgrupos", "cad_subgrupos", SUBGRUPO,
            "Subgrupo criado. Tutorial concluído!"),
    Roteiro("operador", "Cadastrar quem usa o sistema", "operadores", "cad_operadores", OPERADOR,
            "Pessoa cadastrada. Ela já pode entrar com o nome e a senha."),
    Roteiro("cliente", "Cadastrar um cliente", "clientes", "cad_clientes", CLIENTE,
            "Cliente cadastrado. Tutorial concluído!"),
    Roteiro("pagamento", "Criar forma de pagamento", "tipos_pagamento", "cad_tipos_pagamento", PAGAMENTO,
            "Forma de pagamento criada. Ela já aparece no caixa."),
    Roteiro("fornecedor", "Cadastrar um fornecedor", "fornecedores", "cad_fornecedores", FORNECEDOR,
            "Fornecedor cadastrado. Tutorial concluído!"),
)}

class Tutoriais:
    def __init__(self, banco, operador_id):
        self.banco, self.operador_id = banco, operador_id

    def _chave(self, tutorial):
        if tutorial not in ROTEIROS or self.operador_id is None:
            raise ErroNegocio("Tutorial ou operador inválido.")
        return f"tutorial_{tutorial}_operador_{self.operador_id}"

    def concluido(self, tutorial="produto"):
        return self.banco.cfg(self._chave(tutorial)) == "S"

    def concluir(self, tutorial="produto"):
        self.banco.cfg_set(self._chave(tutorial), "S")

    def situacao(self):
        """Todos os tutoriais, na ordem do menu, com o que este operador já concluiu."""
        return [(r, self.operador_id is not None and self.concluido(r.chave)) for r in ROTEIROS.values()]

    @staticmethod
    def permite(passo, valor="", formulario=False, salvo=False):
        if passo.condicao == "formulario":
            return formulario
        if passo.condicao == "salvo":
            return salvo
        if passo.condicao in ("preenchido", "escolhido"):
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
