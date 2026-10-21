"""Importação e exportação de produtos em massa por planilha (CSV ou Excel .xlsx).

Fluxo: `ler_tabela` lê o arquivo, `analisar` monta a PRÉVIA (o que será criado, atualizado ou recusado, e por quê) sem gravar nada,
e `importar` grava tudo de uma vez numa única transação: se algo der errado no meio, nada fica pela metade.

Colunas da planilha (a ordem não importa; os cabeçalhos aceitam variações como "Produto", "Bebida", "Valor", "Código"):
  codigo, nome, preco, comissao (R$ por unidade), grupo, unidade, quantidade (estoque inicial), estoque_minimo,
  codigo_barras, atalho, controla_estoque
Só `nome` e `preco` são obrigatórios. Sem código, os produtos são numerados em sequência (1, 2, 3...), pulando os códigos
reservados do caixa (comissão das garotas, saída da comanda) e os que já existem.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET

from src.controllers.cadastro_controller import CadastroController
from src.controllers.config_controller import CODIGOS_ESPECIAIS, codigo_especial
from src.controllers.estoque_controller import EstoqueController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao

COLUNAS = ["codigo", "nome", "preco", "comissao", "grupo", "unidade", "quantidade", "estoque_minimo", "codigo_barras", "atalho",
           "controla_estoque", "preco_gelada", "atacado_qtd", "preco_atacado"]
TITULOS = {"codigo": "Código", "nome": "Produto", "preco": "Preço", "comissao": "Comissão (R$)", "grupo": "Grupo", "unidade": "Unidade",
           "quantidade": "Quantidade", "estoque_minimo": "Estoque mínimo", "codigo_barras": "Código de barras", "atalho": "Atalho",
           "controla_estoque": "Controla estoque", "preco_gelada": "Preço gelada", "atacado_qtd": "Atacado a partir de",
           "preco_atacado": "Preço atacado"}
# Variações de cabeçalho que a planilha pode ter (comparadas sem acento, maiúsculas/minúsculas e símbolos).
ALIAS = {
    "codigo": {"codigo", "cod", "cod produto", "codigo produto", "numero", "n"},
    "nome": {"nome", "produto", "bebida", "descricao", "item", "nome produto", "nome do produto"},
    "preco": {"preco", "valor", "preco venda", "valor venda", "preco de venda", "valor de venda", "preco r", "preco natural",
              "natural"},
    "comissao": {"comissao", "comissao r", "comissao reais", "comissao valor", "comissao garota"},
    "comissao_pct": {"comissao pct", "comissao percentual", "comissao porcentagem"},
    "grupo": {"grupo", "categoria", "subgrupo", "sub grupo", "tipo"},
    "unidade": {"unidade", "un", "und", "medida"},
    "quantidade": {"quantidade", "qtd", "qt", "estoque", "estoque inicial", "qtde", "saldo"},
    "estoque_minimo": {"estoque minimo", "minimo", "est minimo", "estoque min"},
    "codigo_barras": {"codigo barras", "codigo de barras", "barras", "cbarra", "ean", "gtin"},
    "atalho": {"atalho", "apelido", "abreviacao"},
    "controla_estoque": {"controla estoque", "controle estoque", "controla"},
    # Adega: preço gelada e uma faixa de atacado (natural). Colunas opcionais; vazias não mexem no que já está cadastrado.
    "preco_gelada": {"preco gelada", "gelada", "valor gelada", "preco gelado", "gelado", "preco trincando"},
    "atacado_qtd": {"atacado a partir de", "atacado qtd", "qtd atacado", "atacado minimo", "minimo atacado", "a partir de",
                    "atacado quantidade", "quantidade atacado"},
    "preco_atacado": {"preco atacado", "atacado", "valor atacado", "preco de atacado", "preco no atacado", "atacado r"},
}
GRUPO_PADRAO, UNIDADE_PADRAO = "DIVERSOS", "UN"
LIMITE_LINHAS = 5000


# ------------------------------------------------------------------------------------------- leitura de arquivo
def _chave(texto) -> str:
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def _coluna_de(cabecalho: str) -> str | None:
    if "%" in str(cabecalho) and "comiss" in _chave(cabecalho):
        return "comissao_pct"                      # "Comissão %" é percentual; "Comissão" e "Comissão (R$)" são valor por unidade
    k = _chave(cabecalho)
    for coluna, nomes in ALIAS.items():
        if k in nomes:
            return coluna
    return None


def _texto_csv(dados: bytes) -> str:
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1")


def _ler_csv(dados: bytes) -> list[list[str]]:
    texto = _texto_csv(dados)
    primeira = texto.splitlines()[0] if texto.strip() else ""
    delimitador = max(";\t,", key=primeira.count) if any(d in primeira for d in ";\t,") else ";"
    return [[c.strip() for c in linha] for linha in csv.reader(io.StringIO(texto), delimiter=delimitador)]


def _ler_xlsx(dados: bytes) -> list[list[str]]:
    """Primeira planilha de um .xlsx, só com a biblioteca padrão (sem precisar instalar o openpyxl)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            compartilhadas: list[str] = []
            if "xl/sharedStrings.xml" in z.namelist():
                raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
                compartilhadas = ["".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")) for si in raiz.findall("m:si", ns)]
            planilhas = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
            if not planilhas:
                raise ErroNegocio("O arquivo Excel não tem nenhuma planilha.")
            raiz = ET.fromstring(z.read(planilhas[0]))
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
        raise ErroNegocio("Não consegui abrir esse arquivo Excel. Salve-o de novo como .xlsx ou como CSV.") from e
    linhas: list[list[str]] = []
    for r in raiz.iter(f"{{{ns['m']}}}row"):
        celulas: dict[int, str] = {}
        for c in r.findall("m:c", ns):
            letras = re.match(r"[A-Z]+", c.get("r", "A"))
            idx = 0
            for ch in (letras.group(0) if letras else "A"):
                idx = idx * 26 + ord(ch) - 64
            tipo, v = c.get("t"), c.find("m:v", ns)
            if tipo == "s" and v is not None:
                valor = compartilhadas[int(v.text)]
            elif tipo == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
            else:
                valor = v.text if v is not None and v.text is not None else ""
            celulas[idx] = valor.strip()
        linhas.append([celulas.get(i, "") for i in range(1, (max(celulas) if celulas else 0) + 1)])
    return linhas


def ler_tabela(caminho: str | Path) -> list[dict]:
    """Lê CSV ou XLSX e devolve uma lista de {coluna_padrão: texto, '_linha': nº na planilha}. Levanta ErroNegocio se o arquivo não servir."""
    caminho = Path(caminho)
    try:
        dados = caminho.read_bytes()
    except OSError as e:
        raise ErroNegocio(f"Não consegui ler o arquivo: {e}") from e
    linhas = _ler_xlsx(dados) if caminho.suffix.lower() in (".xlsx", ".xlsm") else _ler_csv(dados)
    linhas = [l for l in linhas if any(c.strip() for c in l)]
    if not linhas:
        raise ErroNegocio("A planilha está vazia.")
    mapa = {i: _coluna_de(c) for i, c in enumerate(linhas[0])}
    if "nome" not in mapa.values():
        raise ErroNegocio("Não achei a coluna do nome do produto. A primeira linha da planilha precisa ter os títulos "
                          "(ex.: Código, Produto, Preço). Baixe a planilha modelo para ver.")
    if len(linhas) - 1 > LIMITE_LINHAS:
        raise ErroNegocio(f"A planilha tem mais de {LIMITE_LINHAS} produtos. Divida em arquivos menores.")
    saida = []
    for n, l in enumerate(linhas[1:], start=2):
        linha = {"_linha": n}
        for i, valor in enumerate(l):
            coluna = mapa.get(i)
            if coluna and coluna not in linha:
                linha[coluna] = valor.strip()
        saida.append(linha)
    return saida


# ------------------------------------------------------------------------------------------------ prévia
@dataclass
class LinhaPrevia:
    linha: int
    acao: str                       # 'criar' | 'atualizar' | 'recusar'
    codigo: str = ""
    nome: str = ""
    preco_cent: int = 0
    comissao_pct: float | None = None
    grupo: str = ""
    unidade: str = ""
    quantidade: float | None = None
    estoque_minimo: float | None = None
    codigo_barras: str = ""
    atalho: str = ""
    preco_gelada_cent: int | None = None    # None: a planilha não trouxe (não mexe); 0 desliga a gelada
    atacado_qtd: float | None = None
    preco_atacado_cent: int | None = None
    produto_id: int | None = None   # produto existente (atualizar)
    liberar_id: int | None = None   # produto guardado (inativo) que ocupa o código da linha e passa para um código de arquivo
    motivo: str = ""                # por que foi recusado, ou aviso
    avisos: list[str] = field(default_factory=list)


@dataclass
class Previa:
    linhas: list[LinhaPrevia]

    def contar(self, acao: str) -> int:
        return sum(1 for l in self.linhas if l.acao == acao)

    @property
    def importaveis(self) -> list[LinhaPrevia]:
        return [l for l in self.linhas if l.acao != "recusar"]

    def resumo(self) -> str:
        return f"{self.contar('criar')} para criar, {self.contar('atualizar')} para atualizar, {self.contar('recusar')} recusados"


def _cod13(texto: str) -> str:
    return texto.zfill(13)


def _numero(texto: str, campo: str) -> float | None:
    if texto is None or str(texto).strip() == "":
        return None
    try:
        v = fmt.para_qtd(texto)
    except ValueError:
        raise ValueError(f"{campo} inválido: '{texto}'.") from None
    if v < 0:
        raise ValueError(f"{campo} não pode ser negativo.")
    return v


class ImportacaoProdutos:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.cad = CadastroController(banco)
        self.estoque = EstoqueController(banco, operador_id)
        self.operador_id = operador_id

    # --------------------------------------------------------------- apoio
    def reservados(self) -> set[str]:
        """Códigos que o caixa usa para outra coisa (comissão das garotas, saída da comanda): nenhum produto pode ficar com eles."""
        usados = set()
        for chave in CODIGOS_ESPECIAIS:
            v = codigo_especial(self.banco, chave)
            if v.isdigit():
                usados.add(_cod13(v))
        return usados

    def _proximo_livre(self, atual: int, ocupados: set[str]) -> tuple[str, int]:
        n = atual
        while _cod13(str(n)) in ocupados:
            n += 1
        return _cod13(str(n)), n + 1

    def numero_inicial_sugerido(self) -> int:
        maior = 0
        for (c,) in self.banco.todos("SELECT codigo FROM produtos"):
            if c.isdigit() and int(c) < 1_000_000:
                maior = max(maior, int(c))
        return maior + 1

    # -------------------------------------------------------------- análise
    def analisar(self, tabela: list[dict], *, atualizar_existentes: bool = True, sequencia_a_partir_de: int | None = None,
                 usar_codigo_da_planilha: bool = True, maiusculas: bool = True) -> Previa:
        """Confere cada linha e diz o que aconteceria. NÃO grava nada.

        `usar_codigo_da_planilha`: respeita a coluna Código; sem ela (ou com False), numera tudo em sequência a partir de
        `sequencia_a_partir_de` (padrão: depois do maior código que já existe)."""
        reservados = self.reservados()
        existentes_cod = {r["codigo"]: dict(r) for r in self.banco.todos("SELECT id, codigo, nome, ativo FROM produtos")}
        inativos = {r["id"] for r in existentes_cod.values() if not r["ativo"]}
        existentes_nome = {r["nome"].casefold(): dict(r) for r in existentes_cod.values()}
        grupos = {self._k(r["nome"]) for r in self.banco.todos("SELECT nome FROM subgrupos")} | \
                 {self._k(r["nome"]) for r in self.banco.todos("SELECT nome FROM grupos")}
        unidades = {r["abreviatura"].upper() for r in self.banco.todos("SELECT abreviatura FROM unidades")}

        # 1º passo: códigos explícitos da planilha entram como ocupados, para a sequência não colidir com eles
        ocupados = set(existentes_cod) | reservados
        explicitos = set()
        if usar_codigo_da_planilha:
            for l in tabela:
                c = str(l.get("codigo") or "").strip()
                if c.isdigit() and len(c) <= 13:
                    explicitos.add(_cod13(c))
        proximo = sequencia_a_partir_de if sequencia_a_partir_de else self.numero_inicial_sugerido()

        vistos_cod: dict[str, int] = {}
        vistos_nome: dict[str, int] = {}
        saida: list[LinhaPrevia] = []
        for l in tabela:
            p = LinhaPrevia(linha=l.get("_linha", 0), acao="criar")
            saida.append(p)
            try:
                self._preencher(p, l, maiusculas, grupos, unidades)
            except ValueError as e:
                p.acao, p.motivo = "recusar", str(e)
                continue
            bruto = str(l.get("codigo") or "").strip() if usar_codigo_da_planilha else ""
            if bruto and not (bruto.isdigit() and len(bruto) <= 13):
                p.acao, p.motivo = "recusar", f"Código '{bruto}' inválido: use só números, até 13 dígitos."
                continue
            nome_existente = existentes_nome.get(p.nome.casefold())
            if bruto:
                p.codigo = _cod13(bruto)
                if p.codigo in reservados:
                    p.acao, p.motivo = "recusar", f"O código {int(p.codigo)} é reservado do caixa (comissão ou saída da comanda)."
                    continue
                dono = existentes_cod.get(p.codigo)
                if dono is not None and dono["id"] in inativos and (nome_existente is None or nome_existente["id"] != dono["id"]):
                    # O código está com um produto guardado (inativo, já vendido): o código vai para a planilha e o guardado
                    # passa para um código de arquivo, sem mudar o nome dele (o histórico das vendas continua certo).
                    p.liberar_id = dono["id"]
                    p.avisos.append(f"O código {int(p.codigo)} estava com '{dono['nome']}' (inativo); "
                                    "o cadastro antigo será excluído, preservando o histórico.")
                    dono = None
                if nome_existente is not None and nome_existente["codigo"] != p.codigo and nome_existente["id"] in inativos \
                        and dono is None:
                    # o produto da planilha estava guardado com outro código: volta com o código da planilha
                    p.acao, p.produto_id = "atualizar", nome_existente["id"]
                    p.avisos.append(f"O código muda de {int(nome_existente['codigo'])} para {int(p.codigo)}.")
                elif dono is not None:
                    if dono["nome"].casefold() == p.nome.casefold() or not nome_existente:
                        p.acao, p.produto_id = "atualizar", dono["id"]
                        if dono["nome"].casefold() != p.nome.casefold():
                            p.avisos.append(f"O nome vai mudar de '{dono['nome']}' para '{p.nome}'.")
                    else:
                        p.acao, p.motivo = "recusar", f"O código {int(p.codigo)} já é de '{dono['nome']}' e o nome '{p.nome}' é de outro produto."
                        continue
                elif nome_existente is not None:
                    p.acao, p.motivo = "recusar", f"Já existe '{p.nome}' com o código {int(nome_existente['codigo'])}. Use esse código para atualizar."
                    continue
            else:
                if nome_existente is not None:
                    p.acao, p.produto_id, p.codigo = "atualizar", nome_existente["id"], nome_existente["codigo"]
                else:
                    ocupados_agora = ocupados | explicitos | set(vistos_cod)
                    p.codigo, proximo = self._proximo_livre(proximo, ocupados_agora)
            if p.codigo_barras:
                outro = self.banco.um("SELECT nome FROM produtos WHERE cbarra = ? AND codigo <> ?", (p.codigo_barras, p.codigo))
                if outro:
                    p.acao, p.motivo = "recusar", f"O código de barras {p.codigo_barras} já é de '{outro['nome']}'."
                    continue
            if p.acao == "atualizar" and not atualizar_existentes:
                p.acao, p.motivo = "recusar", "Já existe e a opção 'atualizar produtos existentes' está desligada."
                continue
            if p.acao == "atualizar" and p.produto_id in inativos:
                p.avisos.append("Estava inativo (guardado por já ter sido vendido) e volta a ficar ativo.")
            if p.codigo in vistos_cod:
                p.acao, p.motivo = "recusar", f"O código {int(p.codigo)} aparece de novo na linha {vistos_cod[p.codigo]} da planilha."
                continue
            if p.nome.casefold() in vistos_nome:
                p.acao, p.motivo = "recusar", f"O produto '{p.nome}' aparece de novo na linha {vistos_nome[p.nome.casefold()]} da planilha."
                continue
            vistos_cod[p.codigo], vistos_nome[p.nome.casefold()] = p.linha, p.linha
        return Previa(saida)

    @staticmethod
    def _k(texto: str) -> str:
        return (texto or "").strip().casefold()

    def _preencher(self, p: LinhaPrevia, l: dict, maiusculas: bool, grupos: set, unidades: set) -> None:
        nome = re.sub(r"\s+", " ", str(l.get("nome") or "")).strip()
        if not nome:
            raise ValueError("Falta o nome do produto.")
        p.nome = nome.upper() if maiusculas else nome
        if len(p.nome) > 50:
            raise ValueError(f"O nome passa de 50 letras ({len(p.nome)}).")
        bruto_preco = str(l.get("preco") or "").strip()
        if not bruto_preco:
            raise ValueError("Falta o preço.")
        try:
            p.preco_cent = fmt.para_centavos(bruto_preco)
        except ValueError:
            raise ValueError(f"Preço inválido: '{bruto_preco}'.") from None
        if p.preco_cent < 0:
            raise ValueError("O preço não pode ser negativo.")
        if p.preco_cent == 0:
            p.avisos.append("Preço zero.")
        pct = str(l.get("comissao_pct") or "").strip()
        reais = str(l.get("comissao") or "").strip()
        if pct:
            p.comissao_pct = _numero(pct, "Comissão %")
        elif reais:
            valor = fmt.para_centavos(reais) if reais else 0
            if valor < 0:
                raise ValueError("A comissão não pode ser negativa.")
            if valor and not p.preco_cent:
                raise ValueError("Comissão informada, mas o preço é zero.")
            if valor > p.preco_cent:
                raise ValueError("A comissão é maior que o preço.")
            # O PDV guarda a comissão em % do valor vendido; a planilha traz o valor por unidade (como a lista do salão).
            p.comissao_pct = round(valor * 100 / p.preco_cent, 4) if p.preco_cent else 0.0
        p.grupo = re.sub(r"\s+", " ", str(l.get("grupo") or "")).strip().upper() or GRUPO_PADRAO
        if self._k(p.grupo) not in grupos:
            p.avisos.append(f"O grupo '{p.grupo}' será criado.")
        un = str(l.get("unidade") or "").strip().upper() or UNIDADE_PADRAO
        if un not in unidades:
            raise ValueError(f"A unidade '{un}' não existe (cadastre em Unidades ou use {', '.join(sorted(unidades)) or UNIDADE_PADRAO}).")
        p.unidade = un
        p.quantidade = _numero(l.get("quantidade"), "Quantidade")
        p.estoque_minimo = _numero(l.get("estoque_minimo"), "Estoque mínimo")
        if p.quantidade is None and str(l.get("controla_estoque") or "").strip().upper() in ("S", "SIM", "1", "X"):
            p.quantidade = 0.0                       # "controla estoque" sem quantidade: passa a controlar, começando em zero
        p.codigo_barras = re.sub(r"\D", "", str(l.get("codigo_barras") or ""))
        if p.codigo_barras and len(p.codigo_barras) > 14:
            raise ValueError("Código de barras com mais de 14 números.")
        p.atalho = str(l.get("atalho") or "").strip()[:10]
        self._preencher_adega(p, l)

    @staticmethod
    def _preencher_adega(p: LinhaPrevia, l: dict) -> None:
        """Preço gelada e a faixa de atacado natural (opcionais). Célula vazia não mexe no cadastro; '0' desliga."""
        gelada = str(l.get("preco_gelada") or "").strip()
        if gelada:
            try:
                p.preco_gelada_cent = fmt.para_centavos(gelada)
            except ValueError:
                raise ValueError(f"Preço gelada inválido: '{gelada}'.") from None
            if p.preco_gelada_cent < 0:
                raise ValueError("O preço gelada não pode ser negativo.")
        qtd, preco = str(l.get("atacado_qtd") or "").strip(), str(l.get("preco_atacado") or "").strip()
        if not qtd and not preco:
            return
        if not qtd or not preco:
            raise ValueError("Atacado: informe a quantidade mínima e o preço unitário (ou os dois em branco).")
        p.atacado_qtd = _numero(qtd, "Atacado a partir de")
        try:
            p.preco_atacado_cent = fmt.para_centavos(preco)
        except ValueError:
            raise ValueError(f"Preço atacado inválido: '{preco}'.") from None
        if p.preco_atacado_cent < 0:
            raise ValueError("O preço atacado não pode ser negativo.")
        if (p.atacado_qtd > 0) != (p.preco_atacado_cent > 0):
            raise ValueError("Atacado: quantidade e preço devem ser os dois positivos, ou os dois zero para desligar.")
        if p.preco_atacado_cent > p.preco_cent:
            raise ValueError("O preço de atacado é maior que o preço normal.")

    # ------------------------------------------------------------ gravação
    def _subgrupo(self, grupo: str) -> int:
        """Subgrupo com este nome (de qualquer grupo); se não existe, cria o grupo e o subgrupo com o mesmo nome."""
        r = self.banco.um("SELECT id FROM subgrupos WHERE nome = ? COLLATE NOCASE ORDER BY id LIMIT 1", (grupo,))
        if r:
            return r["id"]
        g = self.banco.um("SELECT id FROM grupos WHERE nome = ? COLLATE NOCASE", (grupo,))
        grupo_id = g["id"] if g else self.banco.inserir("grupos", {"nome": grupo})
        return self.banco.inserir("subgrupos", {"nome": grupo, "grupo_id": grupo_id})

    def importar(self, previa: Previa) -> dict:
        """Grava os produtos criados/atualizados da prévia, numa transação só. Devolve {'criados', 'atualizados', 'estoque'}."""
        itens = previa.importaveis
        if not itens:
            raise ErroNegocio("Nada para importar: todas as linhas foram recusadas.")
        criados = atualizados = 0
        com_estoque: list[tuple[int, LinhaPrevia]] = []
        with self.banco.transacao():
            for p in itens:                                  # primeiro os códigos que os guardados cedem à planilha
                if p.liberar_id:
                    self._arquivar_codigo(p.liberar_id)
            for p in itens:
                valores = {"nome": p.nome, "preco_cent": f"{p.preco_cent / 100:.2f}".replace(".", ","),
                           "unidade_id": self.banco.valor("SELECT id FROM unidades WHERE abreviatura = ?", (p.unidade,)),
                           "subgrupo_id": self._subgrupo(p.grupo)}
                if p.comissao_pct is not None:
                    valores["comissao_pct"] = str(p.comissao_pct).replace(".", ",")
                if p.codigo_barras:
                    valores["cbarra"] = p.codigo_barras
                if p.atalho:
                    valores["atalho"] = p.atalho
                if p.preco_gelada_cent is not None:
                    valores["preco_gelada_cent"] = fmt.fmt_num(p.preco_gelada_cent)
                if p.atacado_qtd is not None:
                    valores["atacado_qtd"] = fmt.fmt_qtd(p.atacado_qtd, 4).rstrip("0").rstrip(",")
                    valores["preco_atacado_cent"] = fmt.fmt_num(p.preco_atacado_cent or 0)
                try:
                    if p.acao == "atualizar":
                        valores["ativo"] = "S"                  # o produto que a planilha traz volta a valer (ver excluir_todos_produtos)
                        valores["codigo"] = p.codigo            # e fica com o código da planilha (igual ao que já tinha, em geral)
                        self.cad.salvar("produtos", valores, p.produto_id)
                        pid = p.produto_id
                        atualizados += 1
                    else:
                        valores["codigo"] = p.codigo
                        valores["controla_estoque"] = "N"
                        pid = self.cad.salvar("produtos", valores)
                        criados += 1
                except ErroValidacao as e:
                    raise ErroNegocio(f"Linha {p.linha} ({p.nome}): {e}") from e
                if p.quantidade is not None or p.estoque_minimo is not None:
                    com_estoque.append((pid, p))
            if com_estoque:
                lanc = self.estoque.criar_lancamento("inicial", descricao="Importação de produtos")
                for pid, p in com_estoque:
                    if p.quantidade is not None:
                        self.estoque.adicionar_item(lanc, pid, p.quantidade, estoque_minimo=p.estoque_minimo)
                    else:
                        self.estoque.definir_minimo(pid, p.estoque_minimo or 0)
            self.banco.log("importacao_produtos", f"{criados} criados, {atualizados} atualizados, {len(com_estoque)} com estoque")
        return {"criados": criados, "atualizados": atualizados, "estoque": len(com_estoque)}

    def _arquivar_codigo(self, produto_id: int) -> None:
        """Remove somente um cadastro ainda inativo; uma prévia antiga não pode apagar um produto reativado."""
        produto = self.cad.obter("produtos", produto_id)
        if produto is None or produto["ativo"]:
            raise ErroNegocio("O cadastro mudou depois da prévia. Analise a planilha novamente.")
        self.cad.excluir("produtos", produto_id)

    # ----------------------------------------------------- modelo e exportação
    @staticmethod
    def _csv(linhas: list[list]) -> str:
        saida = io.StringIO()
        csv.writer(saida, delimiter=";", lineterminator="\r\n").writerows(linhas)
        return saida.getvalue()

    def modelo(self) -> str:
        """Planilha-modelo (CSV com ';', que o Excel brasileiro abre direto) com dois exemplos."""
        cab = [TITULOS[c] for c in COLUNAS]
        return self._csv([cab,
                          ["1", "CERVEJA LATA", "4,50", "", "CERVEJA", "UN", "48", "12", "7891234567895", "", "", "5,50", "12", "3,99"],
                          ["2", "DOSE DE VODKA", "25,00", "10,00", "DESTILADOS", "UN", "", "", "", "", "", "", "", ""]])

    def exportar(self) -> str:
        """Todos os produtos ativos no mesmo formato da importação: dá para editar preços na planilha e importar de volta."""
        linhas = [[TITULOS[c] for c in COLUNAS]]
        for r in self.banco.todos(
                """SELECT p.codigo, p.nome, p.preco_cent, p.comissao_pct, g.nome AS grupo, u.abreviatura AS un, p.controla_estoque,
                          p.qt_atual, p.estoque_minimo, p.cbarra, p.atalho, p.preco_gelada_cent, p.atacado_qtd, p.preco_atacado_cent
                   FROM produtos p JOIN subgrupos s ON s.id = p.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                   JOIN unidades u ON u.id = p.unidade_id WHERE p.ativo = 1 ORDER BY CAST(p.codigo AS INTEGER), p.nome"""):
            comissao = fmt.fmt_num(round(r["preco_cent"] * r["comissao_pct"] / 100)) if r["comissao_pct"] else ""
            atacado = r["atacado_qtd"] > 0 and r["preco_atacado_cent"] > 0
            linhas.append([str(int(r["codigo"])) if r["codigo"].isdigit() else r["codigo"], r["nome"], fmt.fmt_num(r["preco_cent"]),
                           comissao, r["grupo"], r["un"], fmt.fmt_qtd(r["qt_atual"]).rstrip("0").rstrip(",") if r["controla_estoque"] else "",
                           fmt.fmt_qtd(r["estoque_minimo"]).rstrip("0").rstrip(",") if r["estoque_minimo"] else "", r["cbarra"] or "",
                           r["atalho"] or "", "S" if r["controla_estoque"] else "",
                           fmt.fmt_num(r["preco_gelada_cent"]) if r["preco_gelada_cent"] else "",
                           fmt.fmt_qtd(r["atacado_qtd"], 4).rstrip("0").rstrip(",") if atacado else "",
                           fmt.fmt_num(r["preco_atacado_cent"]) if atacado else ""])
        return self._csv(linhas)


@dataclass
class ItemNFe:
    numero: int
    codigo: str
    nome: str
    unidade: str
    quantidade: float
    custo_unit_cent: int
    custo_total_cent: int
    codigo_barras: str = ""
    produto_id: int | None = None
    sugestoes: list[dict] = field(default_factory=list)


@dataclass
class PreviaNFe:
    chave: str
    numero: str
    emitente: str
    cnpj: str
    data: str
    arquivo: str
    itens: list[ItemNFe]


class ImportacaoNFe:
    """Leitura e entrada de estoque de NF-e modelo 55, sem alterar preço de venda."""

    LIMITE_XML_BYTES = 10 * 1024 * 1024
    LIMITE_ITENS = 5000

    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id
        self.cad = CadastroController(banco)
        self.estoque = EstoqueController(banco, operador_id)

    @staticmethod
    def _filho(elemento, nome: str):
        if elemento is None:
            return None
        return next((e for e in elemento if e.tag.rsplit("}", 1)[-1] == nome), None)

    @classmethod
    def _texto(cls, elemento, nome: str, padrao: str = "") -> str:
        filho = cls._filho(elemento, nome)
        return (filho.text or "").strip() if filho is not None else padrao

    def analisar(self, caminho: str | Path) -> PreviaNFe:
        caminho = Path(caminho)
        try:
            if caminho.stat().st_size > self.LIMITE_XML_BYTES:
                raise ErroNegocio("O XML da NF-e passa de 10 MiB.")
            dados = caminho.read_bytes()
            maiusculo = dados.upper().replace(b"\x00", b"")
            if b"<!DOCTYPE" in maiusculo or b"<!ENTITY" in maiusculo:
                raise ErroNegocio("O XML da NF-e não pode declarar entidades ou DTD.")
            raiz = ET.fromstring(dados)
        except (OSError, ET.ParseError) as erro:
            raise ErroNegocio(f"Não consegui ler o XML da NF-e: {erro}") from erro
        info = next((e for e in raiz.iter() if e.tag.rsplit("}", 1)[-1] == "infNFe"), None)
        if info is None:
            raise ErroNegocio("O XML não contém uma NF-e válida.")
        ide = self._filho(info, "ide")
        if self._texto(ide, "mod") != "55":
            raise ErroNegocio("A importação aceita somente NF-e modelo 55.")
        emit = self._filho(info, "emit")
        cnpj = re.sub(r"\D", "", self._texto(emit, "CNPJ") or self._texto(emit, "CPF"))
        emitente = self._texto(emit, "xNome") or f"Fornecedor NF-e {cnpj}".strip()
        chave = info.get("Id", "").removeprefix("NFe") or hashlib.sha256(dados).hexdigest()
        data = self._texto(ide, "dhEmi", self._texto(ide, "dEmi"))[:10]
        previa = PreviaNFe(chave, self._texto(ide, "nNF"), emitente, cnpj, data,
                           caminho.name, [])
        for numero, det in enumerate(
                (e for e in info.iter() if e.tag.rsplit("}", 1)[-1] == "det"), start=1):
            prod = self._filho(det, "prod")
            nome = re.sub(r"\s+", " ", self._texto(prod, "xProd")).strip()[:50]
            unidade = self._texto(prod, "uCom").upper()[:6] or "UN"
            try:
                quantidade_xml = Decimal(self._texto(prod, "qCom"))
                quantidade = fmt.para_qtd(str(quantidade_xml))
                unitario = Decimal(self._texto(prod, "vUnCom"))
                total = (Decimal(self._texto(prod, "vProd")) - Decimal(self._texto(prod, "vDesc", "0"))
                         + Decimal(self._texto(prod, "vFrete", "0")) + Decimal(self._texto(prod, "vSeg", "0"))
                         + Decimal(self._texto(prod, "vOutro", "0")))
                if (quantidade <= 0 or not unitario.is_finite() or not total.is_finite()
                        or unitario < 0 or total < 0):
                    raise ValueError
            except (ValueError, InvalidOperation):
                raise ErroNegocio(f"Item {numero} da NF-e tem quantidade ou custo inválido.") from None
            try:
                total_cent = int((total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            except (InvalidOperation, OverflowError):
                raise ErroNegocio(f"Item {numero} da NF-e tem custo fora do limite permitido.") from None
            unit_cent = fmt.dividir_cent(total_cent, quantidade)
            codigo = self._texto(prod, "cProd")
            gtin = ""
            for valor_gtin in (self._texto(prod, "cEAN"), self._texto(prod, "cEANTrib")):
                candidato = re.sub(r"\D", "", valor_gtin) if valor_gtin.upper() != "SEM GTIN" else ""
                if candidato and len(candidato) <= 14:
                    gtin = candidato
                    break
            achado = None
            if gtin:
                achado = self.banco.um("SELECT id FROM produtos WHERE cbarra = ?", (gtin,))
            codigo_interno = codigo.zfill(13) if codigo.isdigit() and len(codigo) <= 13 else codigo
            if achado is None and codigo_interno:
                achado = self.banco.um("SELECT id FROM produtos WHERE codigo = ?", (codigo_interno,))
            sugestoes = []
            if achado is None and nome:
                sugestoes = [dict(r) for r in self.banco.todos(
                    """SELECT id, codigo, nome FROM produtos
                       WHERE ativo = 1 AND nome LIKE ? COLLATE NOCASE ORDER BY nome LIMIT 10""",
                    (f"%{nome[:30]}%",))]
            previa.itens.append(ItemNFe(numero, codigo, nome, unidade, quantidade, unit_cent,
                                        total_cent, gtin, achado["id"] if achado else None,
                                        sugestoes))
            if numero > self.LIMITE_ITENS:
                raise ErroNegocio(f"A NF-e passa do limite de {self.LIMITE_ITENS} itens.")
        if not previa.itens:
            raise ErroNegocio("A NF-e não tem itens para importar.")
        return previa

    def importar(self, previa: PreviaNFe, grupo: str, associacoes: dict[int, int | None] | None = None,
                 precos_venda: dict[int, int] | None = None) -> dict:
        """Aplica a entrada em uma transação e registra a nota e o resultado de cada item."""
        grupo = " ".join((grupo or "").split()).upper()
        if grupo not in ("BAR", "ADEGA"):
            raise ErroNegocio("Escolha a categoria Bar ou Adega.")
        associacoes = associacoes or {}
        precos_venda = precos_venda or {}
        if self.banco.um("SELECT 1 FROM importacoes_nfe WHERE chave = ?", (previa.chave,)):
            raise ErroNegocio("Esta NF-e já foi importada.")
        resultados = []
        com_alerta_preco = []
        with self.banco.transacao():
            fornecedor = self.banco.um("SELECT id FROM fornecedores WHERE cnpj = ? AND cnpj <> ''",
                                       (previa.cnpj,)) if previa.cnpj else None
            if fornecedor is None:
                fornecedor = self.banco.um("SELECT id FROM fornecedores WHERE nome = ?", (previa.emitente,))
            fornecedor_id = fornecedor["id"] if fornecedor else self.banco.inserir(
                "fornecedores", {"nome": previa.emitente, "cnpj": previa.cnpj or None})
            lancamento = self.estoque.criar_lancamento(
                "compra", data=previa.data, descricao=f"Entrada NF-e {previa.numero}",
                documento=previa.chave, nota_fiscal=previa.numero, fornecedor_id=fornecedor_id)
            importacao_id = self.banco.inserir("importacoes_nfe", {
                "chave": previa.chave, "arquivo": previa.arquivo, "numero": previa.numero,
                "emitente": previa.emitente, "cnpj": previa.cnpj, "data_emissao": previa.data or None,
                "importado_em": fmt.agora(), "operador_id": self.operador_id,
                "lancamento_id": lancamento, "quantidade_itens": len(previa.itens)})
            for item in previa.itens:
                produto_id = associacoes.get(item.numero, item.produto_id)
                resultado = "atualizado"
                if produto_id is not None:
                    produto = self.banco.um("SELECT id, ativo FROM produtos WHERE id = ?", (produto_id,))
                    if produto is None:
                        raise ErroNegocio(f"Produto escolhido para o item {item.numero} não existe mais.")
                    if not produto["ativo"]:
                        self.banco.executar("UPDATE produtos SET ativo = 1 WHERE id = ?", (produto_id,))
                else:
                    resultado = "criado"
                    grupo_id = self._grupo(grupo)
                    unidade_id = self._unidade(item.unidade)
                    preco_venda = precos_venda.get(item.numero, 0)
                    if type(preco_venda) is not int or preco_venda < 0:
                        raise ErroNegocio(f"Preço de venda inválido para o item {item.numero}.")
                    produto_id = self.cad.salvar("produtos", {
                        "codigo": self.cad.proximo_codigo_produto(), "nome": item.nome or f"Produto NF-e {item.numero}",
                        "subgrupo_id": self._subgrupo(grupo, grupo_id), "unidade_id": unidade_id,
                        "preco_cent": fmt.fmt_num(preco_venda), "controla_estoque": "S", "venda": "S",
                        "cbarra": item.codigo_barras or "",
                    })
                self.estoque.adicionar_item(lancamento, produto_id, item.quantidade, item.custo_total_cent,
                                            ligar_controle=True, observacao=f"Importação NF-e {previa.numero}")
                self.banco.inserir("itens_importacao_nfe", {
                    "importacao_id": importacao_id, "produto_id": produto_id,
                    "codigo_xml": item.codigo, "ean": item.codigo_barras,
                    "nome_xml": item.nome, "quantidade": item.quantidade,
                    "custo_unit_cent": item.custo_unit_cent, "custo_total_cent": item.custo_total_cent,
                    "resultado": resultado})
                resultados.append({"numero": item.numero, "produto_id": produto_id, "resultado": resultado})
                produto_atual = self.banco.um("SELECT nome, preco_cent, ult_preco_cent FROM produtos WHERE id = ?",
                                              (produto_id,))
                minimo = self._margem_minima()
                if minimo and produto_atual["preco_cent"] > 0:
                    margem = ((produto_atual["preco_cent"] - produto_atual["ult_preco_cent"])
                              * 100 / produto_atual["preco_cent"])
                    if margem < minimo:
                        com_alerta_preco.append({"produto_id": produto_id, "nome": produto_atual["nome"],
                                                 "margem_pct": margem, "minima_pct": minimo})
            self.banco.log("importacao_nfe", f"NF-e {previa.numero}: {len(resultados)} itens", self.operador_id)
        return {"criados": sum(r["resultado"] == "criado" for r in resultados),
                "atualizados": sum(r["resultado"] == "atualizado" for r in resultados),
                "itens": resultados, "alertas_margem": com_alerta_preco}

    def _margem_minima(self) -> float:
        try:
            return max(0.0, min(100.0, float(self.banco.cfg("margem_minima_pct", "0").replace(",", "."))))
        except (TypeError, ValueError):
            return 0.0

    def _grupo(self, nome: str) -> int:
        registro = self.banco.um("SELECT id FROM grupos WHERE nome = ? COLLATE NOCASE", (nome,))
        return registro["id"] if registro else self.banco.inserir("grupos", {"nome": nome})

    def _subgrupo(self, nome: str, grupo_id: int) -> int:
        registro = self.banco.um("SELECT id FROM subgrupos WHERE nome = ? COLLATE NOCASE AND grupo_id = ?",
                                 (nome, grupo_id))
        return registro["id"] if registro else self.banco.inserir(
            "subgrupos", {"nome": nome, "grupo_id": grupo_id})

    def _unidade(self, abreviatura: str) -> int:
        unidade = self.banco.um(
            "SELECT id FROM unidades WHERE abreviatura = ? COLLATE NOCASE OR nome = ? COLLATE NOCASE",
            (abreviatura, abreviatura))
        if unidade:
            return unidade["id"]
        return self.banco.inserir("unidades", {"nome": abreviatura, "abreviatura": abreviatura})
