"""Registro declarativo dos cadastros (Manutenção de Cadastros, seção 3 do manual).

Cada Entidade descreve tabela, campos, validações e o módulo de acesso exigido.
O CadastroController usa isto para listar/salvar/excluir e a interface gráfica usa
a mesma descrição para montar formulário e grade, então uma definição serve aos dois.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Callable

from src.controllers.config_controller import CODIGOS_ESPECIAIS, codigo_especial
from src.core import seguranca
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao


@dataclass
class Campo:
    nome: str
    rotulo: str
    tipo: str = "texto"   # texto|int|dinheiro|decimal|sn|data|hora|escolha|lookup|senha|cod13
    obrigatorio: bool = False
    tamanho: int | None = None
    padrao: object = None
    opcoes: list | None = None      # [(valor, rotulo)] para tipo 'escolha'
    lookup: str | None = None       # chave em LOOKUPS para tipo 'lookup'
    na_grade: bool = True
    somente_leitura: bool = False
    secao: str = "Geral"
    largura: int = 14
    minimo: float | None = None
    maximo: float | None = None


@dataclass
class Entidade:
    chave: str
    titulo: str
    tabela: str
    modulo: str
    campos: list
    ordem: str = "id"
    busca: tuple = ()
    antes_salvar: Callable | None = None   # (banco, dados, id_) -> dados
    antes_excluir: Callable | None = None  # (banco, id_) -> None
    excluir_fn: Callable | None = None     # (banco, id_) -> texto|None: no lugar do DELETE simples; o texto vai para a tela
    msg_em_uso: str = "Este registro está em uso e não pode ser excluído."
    tem_ativo: bool = False

    def campo(self, nome: str) -> Campo:
        for c in self.campos:
            if c.nome == nome:
                return c
        raise KeyError(nome)


# ----------------------------------------------------------------- lookups
# chave -> SELECT id, rótulo  (usado nos combos e para rotular a grade)
LOOKUPS = {
    "grupos": "SELECT id, nome FROM grupos ORDER BY nome",
    "subgrupos": ("SELECT s.id, s.nome || ' - ' || g.nome FROM subgrupos s "
                  "JOIN grupos g ON g.id = s.grupo_id ORDER BY s.nome, g.nome"),
    "unidades": "SELECT id, nome FROM unidades ORDER BY nome",
    "aliquotas": "SELECT id, descricao FROM aliquotas ORDER BY descricao",
    "cargos": "SELECT id, nome FROM cargos ORDER BY nome",
    "bairros": "SELECT id, nome FROM bairros ORDER BY nome",
    "setores_impressao": "SELECT id, nome FROM setores_impressao WHERE ativo = 1 ORDER BY ordem, nome",
    "planos_contas": "SELECT id, nome FROM planos_contas ORDER BY ordem, nome",
    "subplanos": ("SELECT sp.id, sp.nome || ' - ' || pl.nome FROM subplanos sp "
                  "JOIN planos_contas pl ON pl.id = sp.plano_id ORDER BY pl.ordem, sp.nome"),
    "operadores": "SELECT id, nome FROM operadores WHERE ativo = 1 ORDER BY nome",
    "fornecedores": "SELECT id, nome FROM fornecedores WHERE ativo = 1 ORDER BY nome",
    "tipos_pagamento": "SELECT id, tipo FROM tipos_pagamento WHERE ativo = 1 ORDER BY ordem, tipo",
    "produtos": "SELECT id, nome FROM produtos WHERE ativo = 1 ORDER BY nome",
    "cascos": ("SELECT id, nome FROM produtos WHERE ativo = 1 AND venda = 1 "
               "AND casco_produto_id IS NULL ORDER BY nome"),
    "clientes": "SELECT id, nome FROM clientes WHERE ativo = 1 ORDER BY nome",
}

NIVEIS = [(i, str(i)) for i in range(0, 5)]
DIAS = [(1, "Dom"), (2, "Seg"), (3, "Ter"), (4, "Qua"), (5, "Qui"), (6, "Sex"), (7, "Sáb")]
TEF = [(0, "Nenhum"), (1, "Visa/Redecard/Amex"), (2, "Tecban"), (3, "Hipercard")]
CONEXAO_SETOR = [("pasta", "Pasta de arquivos"), ("rede", "Rede (TCP/IP)"),
                  ("spooler", "Impressora do Windows (USB ou instalada)"), ("nenhuma", "Nenhuma")]


def _sn(nome, rotulo, padrao=0, secao="Geral", **kw):
    return Campo(nome, rotulo, "sn", padrao=padrao, secao=secao, na_grade=kw.pop("na_grade", False), **kw)


# ------------------------------------------------------------------- hooks
def _antes_aliquota(banco, d, id_):
    if "formato" in d and not re.fullmatch(r"[A-Za-z0-9]{1,4}", d["formato"] or ""):
        raise ErroValidacao("Formato inválido: use até 4 letras/números (ex.: II, FF, 1800). "
                            "A impressora fiscal trava com outros caracteres.", {"formato": "inválido"})
    if "formato" in d:
        d["formato"] = d["formato"].upper()
    return d


def _mesmo_codigo(a, b) -> bool:
    a, b = str(a or "").strip(), str(b or "").strip()
    if not a or not b:
        return False
    return int(a) == int(b) if a.isdigit() and b.isdigit() else a.lower() == b.lower()


def _antes_produto(banco, d, id_):
    for chave, (_, _, uso) in CODIGOS_ESPECIAIS.items():
        reservado = codigo_especial(banco, chave)
        if reservado and any(_mesmo_codigo(d.get(c), reservado) for c in ("codigo", "cbarra", "atalho")):
            raise ErroValidacao(f"O código {reservado} é reservado para {uso} no caixa "
                                "(Configurações). Use outro código, atalho ou código de barras para este produto.",
                                {"codigo": "reservado"})
    if d.get("preco_cent", 0) < 0:
        raise ErroValidacao("O preço de venda não pode ser negativo.", {"preco_cent": "negativo"})
    if d.get("cbarra") is not None and not re.fullmatch(r"\d{1,14}", d["cbarra"]):
        raise ErroValidacao("Código de barras deve conter apenas números.", {"cbarra": "inválido"})
    if "partes" in d and not (1 <= d["partes"] <= 55):
        raise ErroValidacao("'Dividir em' deve estar entre 1 e 55.", {"partes": "inválido"})
    _validar_promocoes(banco, d, id_)
    _validar_adega(banco, d, id_)
    _liberar_produtos_guardados(banco, d, id_)          # por último: só cede o número se o cadastro novo for valer
    return d


def _validar_promocoes(banco, dados, id_):
    atual = banco.um("SELECT * FROM produtos WHERE id = ?", (id_,)) if id_ is not None else None
    produto = dict(atual) if atual else {}
    produto.update(dados)
    if produto.get("promo_de") and produto.get("promo_ate") and produto["promo_de"] > produto["promo_ate"]:
        raise ErroValidacao("Promoção: a data inicial é posterior à final.", {"promo_de": "inválido"})
    for preco, inicio, fim in (
        ("promo_preco_cent", "promo_de", "promo_ate"),
        ("sem_preco_cent", "sem_inicial", "sem_final"),
        ("hora_preco_cent", "hora_ini", "hora_fim"),
    ):
        valor = produto.get(preco, 0)
        if type(valor) is not int or valor < 0 or valor > produto.get("preco_cent", 0):
            raise ErroValidacao("Promoção: preço deve ser não negativo e não superar o preço natural.",
                                {preco: "inválido"})
        if valor > 0 and (not produto.get(inicio) or not produto.get(fim)):
            raise ErroValidacao("Promoção: informe início e fim, ou preço zero para desligar.",
                                {inicio: "obrigatório", fim: "obrigatório"})


def _validar_adega(banco, dados, id_):
    atual = banco.um("SELECT * FROM produtos WHERE id = ?", (id_,)) if id_ is not None else None
    produto = dict(atual) if atual else {}
    produto.update(dados)

    def recusar(campo, mensagem):
        raise ErroValidacao(mensagem, {campo: "inválido"})

    for campo in ("preco_cent", "preco_gelada_cent", "preco_atacado_cent", "preco_atacado_gelada_cent"):
        valor = produto.get(campo, 0)
        if type(valor) is not int or valor < 0:
            recusar(campo, "Preços devem ser inteiros em centavos, maiores ou iguais a zero.")

    for campo, preco, varejo, temperatura in (
        ("atacado_qtd", "preco_atacado_cent", "preco_cent", "natural"),
        ("atacado_gelada_qtd", "preco_atacado_gelada_cent", "preco_gelada_cent", "gelada"),
    ):
        bruto = produto.get(campo, 0)
        texto = str(bruto if bruto not in (None, "") else 0).strip().replace(" ", "")
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            quantidade = Decimal(texto)
        except InvalidOperation:
            recusar(campo, f"Atacado {temperatura}: quantidade inválida.")
        if not quantidade.is_finite() or quantidade < 0 or not math.isfinite(float(quantidade)):
            recusar(campo, f"Atacado {temperatura}: quantidade deve ser finita e não negativa.")
        excesso = -quantidade.as_tuple().exponent - 4
        if excesso > 0 and any(quantidade.as_tuple().digits[-excesso:]):
            recusar(campo, f"Atacado {temperatura}: use no máximo 4 casas decimais.")
        if not produto.get("aceita_decimal", 0) and quantidade != quantidade.to_integral_value():
            recusar(campo, f"Atacado {temperatura}: este produto exige quantidade inteira.")
        unitario = produto.get(preco, 0)
        if (quantidade > 0) != (unitario > 0):
            recusar(campo, f"Atacado {temperatura}: informe mínimo e preço unitário positivos, ou ambos zero para desligar.")
        if unitario > produto.get(varejo, 0):
            recusar(preco, f"Atacado {temperatura}: o preço unitário não pode superar o varejo correspondente."
                    + (" Cadastre o preço gelada antes de ativar o atacado gelada." if temperatura == "gelada" else ""))
        if campo in dados:
            dados[campo] = float(quantidade)

    casco_id = produto.get("casco_produto_id")
    usado_como_casco = id_ is not None and banco.valor(
        "SELECT 1 FROM produtos WHERE casco_produto_id = ? LIMIT 1", (id_,))
    if usado_como_casco and (not produto.get("ativo", 1) or not produto.get("venda", 1) or casco_id is not None):
        recusar("casco_produto_id", "Este produto é casco de outro produto: mantenha-o ativo, à venda e sem casco próprio.")
    if casco_id is None:
        return
    if casco_id == id_:
        recusar("casco_produto_id", "O casco deve ser um produto diferente da bebida.")
    casco = banco.um("SELECT * FROM produtos WHERE id = ?", (casco_id,))
    if casco is None or not casco["ativo"] or not casco["venda"]:
        recusar("casco_produto_id", "Escolha um produto de casco ativo e disponível para venda.")
    if casco["casco_produto_id"] is not None:
        recusar("casco_produto_id", "O casco não pode ter casco próprio ou formar um ciclo.")
    if (produto.get("aceita_decimal", 0) or produto.get("partes", 1) != 1
            or any(produto.get(c, 0) for c in ("montagem", "para_ser_montado", "manual", "composto", "balanca"))
            or (id_ is not None and banco.valor(
                "SELECT 1 FROM composicoes WHERE produto_id = ? OR insumo_id = ? LIMIT 1", (id_, id_)))):
        recusar("casco_produto_id", "Produto com casco não aceita fracionamento, montagem, composição ou fardo/caixa.")


def _antes_operador(banco, d, id_):
    if "senha" in d:
        if d["senha"]:
            if not seguranca.FORMATO_SENHA.fullmatch(d["senha"]):
                raise ErroValidacao("A senha deve ter de 1 a 10 caracteres alfanuméricos.", {"senha": "inválida"})
            d["senha"] = seguranca.gerar_hash(d["senha"])
        else:
            d.pop("senha")  # edição sem trocar a senha
    if id_ is not None and d.get("nivel", 4) < 4 or (id_ is not None and d.get("ativo", 1) == 0):
        atual = banco.um("SELECT nivel, ativo FROM operadores WHERE id = ?", (id_,))
        if atual and atual["nivel"] == 4 and atual["ativo"]:
            outros = banco.valor("SELECT COUNT(*) FROM operadores WHERE nivel = 4 AND ativo = 1 AND id <> ?", (id_,))
            if not outros:
                raise ErroNegocio("Deve existir ao menos um operador ativo de nível 4 (administrador).")
    return d


def _antes_excluir_operador(banco, id_):
    atual = banco.um("SELECT nivel, ativo FROM operadores WHERE id = ?", (id_,))
    if atual and atual["nivel"] == 4 and atual["ativo"]:
        if not banco.valor("SELECT COUNT(*) FROM operadores WHERE nivel = 4 AND ativo = 1 AND id <> ?", (id_,)):
            raise ErroNegocio("Não é possível excluir o único administrador (nível 4).")


def _antes_cliente(banco, d, id_):
    d.pop("saldo_cent", None)  # saldo só muda pela caderneta
    return d


def _antes_excluir_garota(banco, id_):
    g = banco.um("SELECT numero FROM garotas WHERE id = ?", (id_,))
    if g and (banco.valor("SELECT 1 FROM comissoes_garotas WHERE garota = ? LIMIT 1", (g["numero"],))
              or banco.valor("SELECT 1 FROM acertos_garotas WHERE garota = ? LIMIT 1", (g["numero"],))):
        raise ErroNegocio("Esta garota tem comissões registradas. Desmarque 'Ativa' em vez de excluir.")


def _guardar_produto(banco, p) -> None:
    """Libera um cadastro inativo legado preservando sua identidade histórica."""
    _excluir_produto(banco, p["id"])


def _liberar_produtos_guardados(banco, d, id_) -> None:
    """Cadastro novo (ou alterado) que pede um código, nome ou código de barras que só está preso a um produto INATIVO (os que
    ficaram guardados por já terem sido vendidos, ou desmarcados): o inativo cede, para o número poder ser usado de novo. Produto
    ativo continua bloqueando, com o aviso de sempre."""
    for p in banco.todos("SELECT * FROM produtos WHERE ativo = 0 AND id <> ?", (id_ if id_ is not None else -1,)):
        igual = (str(p["codigo"] or "") == str(d.get("codigo") or "~") or
                 str(p["nome"] or "").lower() == str(d.get("nome") or "~").lower() or
                 (d.get("cbarra") and p["cbarra"] == d["cbarra"]))
        if igual:
            _guardar_produto(banco, p)


def _excluir_produto(banco, id_):
    """Remove o cadastro, sem remover os registros históricos associados à sua identidade."""
    p = banco.um("SELECT * FROM produtos WHERE id = ?", (id_,))
    if p is None:
        raise ErroNegocio("Produto não encontrado.")
    with banco.transacao():
        if banco.valor("SELECT 1 FROM produtos WHERE casco_produto_id = ? LIMIT 1", (id_,)):
            raise ErroNegocio("Este produto é casco de uma bebida. Desvincule o casco no cadastro das bebidas antes de excluir.")
        aberto = banco.valor(
            """SELECT COUNT(*) FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
               WHERE i.cancelado = 0 AND v.status IN ('aberta','conta_enviada')
               AND (i.produto_id = ? OR EXISTS (
                   SELECT 1 FROM itens_venda_partes p WHERE p.item_id = i.id AND p.produto_id = ?))""", (id_, id_), 0)
        if aberto:
            raise ErroNegocio("Este produto está em mesa, comanda ou venda aberta. Feche ou cancele antes de excluir.")
        if banco.valor("SELECT 1 FROM composicoes WHERE insumo_id = ? AND produto_id <> ? LIMIT 1", (id_, id_)):
            raise ErroNegocio("Este produto é insumo de uma composição. Remova-o da ficha técnica antes de excluir.")
        if banco.valor("""SELECT 1 FROM itens_estoque i JOIN lancamentos_estoque l ON l.id = i.lancamento_id
                          WHERE i.produto_id = ? AND l.tipo = 'pedido' LIMIT 1""", (id_,)):
            raise ErroNegocio("Este produto está em um pedido de compra. Remova-o do pedido antes de excluir.")
        from src.controllers.produto_controller import ProdutoController
        custo = ProdutoController(banco).custo(id_)
        banco.executar("UPDATE produtos_historico SET custo_cent = ?, ativo = 0, excluido_em = ? WHERE id = ?",
                       (custo, fmt.agora(), id_))
        banco.executar("DELETE FROM composicoes WHERE produto_id = ?", (id_,))
        banco.executar("DELETE FROM produtos WHERE id = ?", (id_,))
        banco.log("produto_excluido", f"produto {id_} ({p['codigo']}) excluído do cadastro; histórico preservado")
    return None


# --------------------------------------------------------------- entidades
_ENTIDADES = [
    Entidade("unidades", "Cadastro de Unidades", "unidades", "cad_unidades", [
        Campo("nome", "Unidade", obrigatorio=True, tamanho=30, largura=24),
        Campo("abreviatura", "Abreviatura", obrigatorio=True, tamanho=6, largura=12),
    ], ordem="nome", busca=("nome", "abreviatura")),

    Entidade("grupos", "Cadastro de Grupos", "grupos", "cad_grupos", [
        Campo("nome", "Grupo", obrigatorio=True, tamanho=40, largura=34),
    ], ordem="nome", busca=("nome",)),

    Entidade("subgrupos", "Cadastro de Subgrupos", "subgrupos", "cad_subgrupos", [
        Campo("nome", "Subgrupo", obrigatorio=True, tamanho=40, largura=30),
        Campo("grupo_id", "Grupo", "lookup", obrigatorio=True, lookup="grupos", largura=24),
        _sn("impressora_remota", "Imprimir em outra impressora (cozinha/bar)", na_grade=True),
        Campo("setor_impressao_id", "Setor de impressão (cozinha/bar)", "lookup", lookup="setores_impressao", na_grade=False),
        _sn("rodizio_incluso", "Incluso no rodízio (preço fixo por pessoa)", na_grade=True),
        Campo("figura", "Figura (bmp 180x121)", na_grade=False, largura=40),
    ], ordem="nome", busca=("nome",)),

    Entidade("aliquotas", "Cadastro de Alíquotas", "aliquotas", "cad_aliquotas", [
        Campo("descricao", "Descrição", obrigatorio=True, tamanho=40, largura=30),
        Campo("aliquota", "Alíquota %", "decimal", padrao=0, largura=10),
        Campo("formato", "Formato (impressora)", obrigatorio=True, tamanho=4, largura=12),
    ], ordem="descricao", busca=("descricao",), antes_salvar=_antes_aliquota),

    Entidade("setores_impressao", "Setores de Impressão (Cozinha/Bar)", "setores_impressao", "cad_setores_impressao", [
        Campo("nome", "Setor", obrigatorio=True, tamanho=40, largura=24),
        Campo("conexao", "Conexão", "escolha", opcoes=CONEXAO_SETOR, padrao="pasta", largura=16),
        Campo("pasta", "Pasta de arquivos", na_grade=False),
        Campo("endereco", "Endereço de rede (IP:porta) ou nome da impressora do Windows", na_grade=False),
        Campo("ordem", "Ordem", "int", padrao=0, largura=7),
        _sn("ativo", "Ativo", 1, na_grade=True),
    ], ordem="ordem", busca=("nome",), tem_ativo=True),

    Entidade("produtos", "Cadastro de Produtos", "produtos", "cad_produtos", [
        Campo("codigo", "Código", "cod13", obrigatorio=True, largura=15),
        Campo("nome", "Produto", obrigatorio=True, tamanho=50, largura=34),
        Campo("subgrupo_id", "Sub Grupo - Grupo", "lookup", obrigatorio=True, lookup="subgrupos", largura=24),
        Campo("unidade_id", "Unidade", "lookup", obrigatorio=True, lookup="unidades", largura=10),
        Campo("aliquota_id", "Alíquota", "lookup", lookup="aliquotas", na_grade=False),
        Campo("preco_cent", "Preço", "dinheiro", padrao=0, largura=11),
        _sn("cobrar_servico", "Cobrar serviço", 1),
        _sn("venda", "Venda", 1, na_grade=True),
        _sn("aceita_decimal", "Aceita decimal"),
        Campo("atalho", "Atalho", tamanho=10, na_grade=False),
        Campo("cbarra", "Código de barras", tamanho=14, na_grade=False),
        Campo("preco_gelada_cent", "Preço gelada (0 desliga; mesmo estoque)", "dinheiro",
              padrao=0, secao="Adega", na_grade=False),
        # Texto preserva a precisão original para validar antes de converter a quantidade.
        Campo("atacado_qtd", "Mínimo atacado natural (0 desliga)", padrao="0", secao="Adega", na_grade=False),
        Campo("preco_atacado_cent", "Preço unitário atacado natural", "dinheiro",
              padrao=0, secao="Adega", na_grade=False),
        Campo("atacado_gelada_qtd", "Mínimo atacado gelada (0 desliga)", padrao="0", secao="Adega", na_grade=False),
        Campo("preco_atacado_gelada_cent", "Preço unitário atacado gelada", "dinheiro",
              padrao=0, secao="Adega", na_grade=False),
        Campo("casco_produto_id", "Casco vendido à parte (somente sem troca)", "lookup",
              lookup="cascos", secao="Adega", na_grade=False),
        _sn("usa_observacao", "Permite observações"),
        Campo("comissao_pct", "Comissão %", "decimal", padrao=0, na_grade=False),
        Campo("texto_sugestao", "Texto para sugestão", tamanho=60, na_grade=False),
        _sn("mostrar_no_cardapio", "Mostrar no cardápio digital", 1, na_grade=True),
        _sn("ativo", "Ativo", 1),
        Campo("controla_estoque", "Controla estoque", "sn", padrao=0, secao="Estoque"),
        Campo("estoque_minimo", "Estoque mínimo", "decimal", padrao=0, secao="Estoque", na_grade=False),
        Campo("qt_atual", "Qt. atual", "decimal", somente_leitura=True, secao="Estoque", largura=10),
        Campo("qt_inicial", "Qt. inicial", "decimal", somente_leitura=True, secao="Estoque", na_grade=False),
        Campo("ult_preco_cent", "Últ. preço (custo)", "dinheiro", somente_leitura=True, secao="Estoque", na_grade=False),
        Campo("ult_atualizacao", "Últ. atualização", somente_leitura=True, secao="Estoque", na_grade=False),
        Campo("partes", "Dividir em (1-55)", "int", padrao=1, minimo=1, maximo=55, secao="Montagem", na_grade=False),
        _sn("maior", "Preço pelo maior (senão proporcional)", 1, "Montagem"),
        _sn("montagem", "Montagem (compõe outros produtos)", 0, "Montagem"),
        _sn("para_ser_montado", "Produto para ser montado", 0, "Montagem"),
        _sn("manual", "Manual (qtd. de cada parte)", 0, "Montagem"),
        _sn("compoe", "Compõe combo", 1, "Montagem"),
        _sn("composto", "Composto (combo, preço único)", 0, "Montagem"),
        Campo("validade_dias", "Validade (dias)", "int", padrao=0, secao="Montagem", na_grade=False),
        _sn("balanca", "Balança", 0, "Montagem"),
        _sn("automatico", "Automático (sem mesa)", 0, "Montagem"),
        Campo("promo_de", "Promoção de", "data", secao="Promoções", na_grade=False),
        Campo("promo_ate", "Promoção até", "data", secao="Promoções", na_grade=False),
        Campo("promo_preco_cent", "Preço (período)", "dinheiro", padrao=0, secao="Promoções", na_grade=False),
        Campo("sem_inicial", "Dia inicial", "escolha", opcoes=DIAS, secao="Promoções", na_grade=False),
        Campo("sem_final", "Dia final", "escolha", opcoes=DIAS, secao="Promoções", na_grade=False),
        Campo("sem_preco_cent", "Preço (dias)", "dinheiro", padrao=0, secao="Promoções", na_grade=False),
        Campo("hora_ini", "Hora inicial", "hora", secao="Promoções", na_grade=False),
        Campo("hora_fim", "Hora final", "hora", secao="Promoções", na_grade=False),
        Campo("hora_preco_cent", "Preço (horário)", "dinheiro", padrao=0, secao="Promoções", na_grade=False),
        Campo("ncm", "Código NCM", tamanho=8, secao="Fiscal", na_grade=False),
        Campo("desc_aliq_icms", "Desc. Aliq. ICMS", tamanho=10, secao="Fiscal", na_grade=False),
        Campo("situacao_tributaria", "Situação tributária", tamanho=4, secao="Fiscal", na_grade=False),
        Campo("aliquota_ipi", "Alíquota IPI %", "decimal", padrao=0, secao="Fiscal", na_grade=False),
        Campo("reducao_base", "Redução base cálc. subst. trib. %", "decimal", padrao=0, secao="Fiscal", na_grade=False),
    ], ordem="nome", busca=("nome", "codigo", "cbarra", "atalho"), antes_salvar=_antes_produto,
        excluir_fn=_excluir_produto, msg_em_uso="Este produto já foi vendido, movimentado ou usado em composição. "
                   "Desmarque 'Ativo' em vez de excluir.", tem_ativo=True),

    Entidade("observacoes", "Observações de Produtos", "observacoes", "cad_observacoes", [
        Campo("codigo", "Código", "int", obrigatorio=True, largura=8),
        Campo("texto", "Observação (ex.: ao ponto, sem gelo)", obrigatorio=True, tamanho=40, largura=40),
    ], ordem="codigo", busca=("texto",)),

    Entidade("cargos", "Cadastro de Cargos", "cargos", "cad_cargos", [
        Campo("nome", "Cargo", obrigatorio=True, tamanho=30, largura=30),
    ], ordem="nome", busca=("nome",)),

    Entidade("operadores", "Cadastro de Operadores", "operadores", "cad_operadores", [
        Campo("nome", "Nome", obrigatorio=True, tamanho=30, largura=26),
        Campo("senha", "Senha (até 10 alfanuméricos)", "senha", obrigatorio=True, tamanho=10, na_grade=False),
        Campo("nivel", "Nível de acesso (0 = só caixa)", "escolha", obrigatorio=True, opcoes=NIVEIS, padrao=0, largura=8),
        Campo("cargo_id", "Cargo", "lookup", lookup="cargos", largura=16),
        _sn("garcom", "É garçom", na_grade=True),
        _sn("entregador", "É entregador", na_grade=True),
        _sn("vendedor", "É vendedor"),
        _sn("recebe_comissao", "Recebe comissão"),
        Campo("comissao_pct", "Comissão sobre vendas %", "decimal", padrao=0, na_grade=False),
        _sn("ativo", "Ativo", 1, na_grade=True),
    ], ordem="nome", busca=("nome",), antes_salvar=_antes_operador, antes_excluir=_antes_excluir_operador,
        msg_em_uso="Este operador possui movimento no sistema. Desmarque 'Ativo' em vez de excluir.", tem_ativo=True),

    Entidade("fornecedores", "Cadastro de Fornecedores", "fornecedores", "cad_fornecedores", [
        Campo("nome", "Fornecedor", obrigatorio=True, tamanho=50, largura=30),
        Campo("contato", "Contato", tamanho=40, largura=16),
        Campo("ddd", "DDD", tamanho=3, na_grade=False),
        Campo("telefone", "Telefone", tamanho=20, largura=14),
        Campo("celular", "Celular", tamanho=20, na_grade=False),
        Campo("cnpj", "CGC/CNPJ", tamanho=20, na_grade=False),
        Campo("ie", "I.E.", tamanho=20, na_grade=False),
        Campo("endereco", "Endereço", tamanho=60, na_grade=False),
        Campo("complemento", "Complemento", tamanho=30, na_grade=False),
        Campo("bairro", "Bairro", tamanho=30, na_grade=False),
        Campo("cidade", "Cidade", tamanho=40, na_grade=False),
        Campo("uf", "Estado", tamanho=2, na_grade=False),
        Campo("cep", "CEP", tamanho=9, na_grade=False),
        Campo("email", "E-mail", tamanho=60, na_grade=False),
        Campo("obs", "Observações", tamanho=120, na_grade=False),
        _sn("ativo", "Ativo", 1, na_grade=True),
    ], ordem="nome", busca=("nome", "contato", "cnpj"), tem_ativo=True),

    Entidade("bairros", "Bairros e Taxas de Entrega", "bairros", "cad_bairros", [
        Campo("nome", "Bairro", obrigatorio=True, tamanho=40, largura=30),
        Campo("taxa_cent", "Taxa de entrega", "dinheiro", padrao=0, largura=12),
    ], ordem="nome", busca=("nome",)),

    Entidade("clientes", "Cadastro de Clientes", "clientes", "cad_clientes", [
        Campo("numero_consulta", "Número para consulta", obrigatorio=True, tamanho=20, largura=14),
        Campo("nome", "Nome do cliente", obrigatorio=True, tamanho=60, largura=30),
        Campo("endereco", "Endereço", tamanho=60, largura=26),
        Campo("complemento", "Complemento", tamanho=30, na_grade=False),
        Campo("cep", "CEP", tamanho=9, na_grade=False),
        Campo("codigo", "Código", tamanho=20, na_grade=False),
        Campo("bairro_id", "Bairro", "lookup", lookup="bairros", largura=16),
        Campo("cidade", "Cidade", tamanho=40, na_grade=False),
        Campo("telefone", "Telefone", tamanho=20, largura=14),
        Campo("rg", "RG", tamanho=20, na_grade=False),
        Campo("cpf", "CPF", tamanho=14, na_grade=False),
        Campo("email", "E-mail", tamanho=60, na_grade=False),
        Campo("obs", "Observações", tamanho=120, na_grade=False),
        Campo("limite_cent", "Limite (caderneta)", "dinheiro", padrao=0, largura=12),
        Campo("saldo_cent", "Saldo", "dinheiro", somente_leitura=True, largura=12),
        _sn("ativo", "Ativo", 1),
    ], ordem="nome", busca=("nome", "numero_consulta", "telefone", "cpf"), antes_salvar=_antes_cliente,
        msg_em_uso="Este cliente possui movimento. Desmarque 'Ativo' em vez de excluir.", tem_ativo=True),

    Entidade("garotas", "Cadastro de Garotas", "garotas", "cad_garotas", [
        Campo("numero", "Número (o mesmo da comanda dela)", "int", obrigatorio=True, largura=12, minimo=1, maximo=99999),
        Campo("nome", "Nome", obrigatorio=True, tamanho=40, largura=30),
        Campo("observacao", "Observações", tamanho=120, na_grade=False),
        _sn("ativo", "Ativa", 1, na_grade=True),
    ], ordem="numero", busca=("nome", "numero"), antes_excluir=_antes_excluir_garota, tem_ativo=True,
        msg_em_uso="Esta garota tem comissões registradas. Desmarque 'Ativa' em vez de excluir."),

    Entidade("tipos_pagamento", "Cadastro de Tipos de Pagamento", "tipos_pagamento", "cad_tipos_pagamento", [
        Campo("tipo", "Tipo de pagamento", obrigatorio=True, tamanho=30, largura=22),
        Campo("ordem", "Ordem", "int", padrao=0, largura=7),
        Campo("caixa", "Aceito no caixa", "sn", padrao=1, largura=9),
        Campo("emite_vale", "Emite vale", "sn", padrao=0, largura=9),
        Campo("permite_troco", "Permite troco", "sn", padrao=0, largura=9),
        Campo("na_gaveta", "Fica na gaveta (dinheiro, cheque, ticket)", "sn", padrao=1, largura=9),
        Campo("saldo_inicial_cent", "Saldo inicial", "dinheiro", padrao=0, largura=12),
        Campo("acrescimo_cent", "Acréscimo cobrado do cliente por venda (ex.: taxa do crédito)", "dinheiro", padrao=0, largura=12),
        Campo("taxa_pct", "Taxa % (banco/operadora)", "decimal", padrao=0, na_grade=False),
        Campo("desc_cartao_pct", "Desc. cartão %", "decimal", padrao=0, na_grade=False),
        Campo("vias", "Nº de vias", "int", padrao=1, na_grade=False),
        Campo("tipo_tef", "Tipo TEF", "escolha", opcoes=TEF, padrao=0, na_grade=False),
        _sn("aciona_tef", "Aciona módulo TEF"),
        _sn("cheque_tef", "Cheque TEF"),
        _sn("mais_info", "Mais informações"),
        _sn("ativo", "Ativo", 1, na_grade=True),
    ], ordem="ordem, tipo", busca=("tipo",), tem_ativo=True,
        msg_em_uso="Esta forma de pagamento já foi usada. Desmarque 'Ativo' em vez de excluir."),

    Entidade("planos_contas", "Plano de Contas", "planos_contas", "cad_plano_contas", [
        Campo("nome", "Plano de contas", obrigatorio=True, tamanho=40, largura=32),
        Campo("codigo", "Código", obrigatorio=True, tamanho=10, largura=8),
        Campo("debito", "Movimento", "escolha", opcoes=[(1, "Saída (débito)"), (0, "Entrada (crédito)")],
              padrao=1, largura=16),
        Campo("resultado", "Afeta o resultado", "sn", padrao=1, largura=12),
        Campo("ordem", "Ordem", "int", padrao=0, largura=7),
    ], ordem="ordem, nome", busca=("nome", "codigo")),

    Entidade("subplanos", "Sub Planos", "subplanos", "cad_subplanos", [
        Campo("nome", "Sub plano", obrigatorio=True, tamanho=40, largura=32),
        Campo("plano_id", "Plano de contas", "lookup", obrigatorio=True, lookup="planos_contas", largura=28),
    ], ordem="nome", busca=("nome",)),
]

ENTIDADES: dict = {e.chave: e for e in _ENTIDADES}
