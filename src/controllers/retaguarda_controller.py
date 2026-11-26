"""Retaguarda na nuvem: o dono (painel) e o fornecedor (central) alteram a loja de longe e o caixa aplica.

Este arquivo é o lado do caixa. Ele faz duas coisas:

- monta o **espelho**: o retrato dos cadastros, das configurações e do financeiro que sobe para a nuvem, para a
  página da retaguarda mostrar o que existe na loja (senha, token e segredo nunca sobem);
- aplica os **comandos** que descem da nuvem, sempre pelas mesmas regras das telas do PDV (`CadastroController`,
  `EstoqueController`, `ConfigController`, `ContasController`). O que a regra recusaria na tela é recusado aqui,
  com a mesma mensagem, e a nuvem mostra o motivo.

Contrato dos valores (igual ao do resto do sistema): dinheiro em centavos inteiros, quantidade em número, sim/não em
0 ou 1, data em `YYYY-MM-DD`. Cada comando é aplicado uma vez só: o id da nuvem fica em `retaguarda_comandos`.
Vale a alteração que chega por último, na retaguarda ou no caixa.
"""
from __future__ import annotations

import re
from contextlib import contextmanager

import hashlib
import json
import logging

from src.controllers.cadastro_controller import CadastroController
from src.controllers.config_controller import CAMPOS_CONFIG, ConfigController, modulos_desligados
from src.controllers.contas_controller import ContasController
from src.controllers.entidades import ENTIDADES
from src.controllers.estoque_controller import EstoqueController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

log = logging.getLogger(__name__)

CHAVE_LIGADA = "retaguarda_nuvem"
VERSAO_ESPELHO = 1
LIMITE_LINHAS = 20000                       # por cadastro: acima disso sobem os primeiros e o espelho avisa
DIAS_CONTAS = 120                           # contas quitadas há mais tempo não sobem

# Como a página agrupa os cadastros no menu.
GRUPOS = {
    "produtos": "produtos", "grupos": "produtos", "subgrupos": "produtos", "unidades": "produtos",
    "aliquotas": "produtos", "observacoes": "produtos", "setores_impressao": "produtos",
    "operadores": "pessoas", "cargos": "pessoas", "clientes": "pessoas", "fornecedores": "pessoas",
    "garotas": "pessoas", "bairros": "pessoas",
    "tipos_pagamento": "financeiro", "planos_contas": "financeiro", "subplanos": "financeiro",
}
# Configurações que a nuvem não lê nem altera: endereço e credenciais da nuvem, e-mail e pastas do computador da loja.
SECOES_CONFIG_FORA = {"Nuvem", "E-mail", "Utilitários", "Integrações"}
TIPOS_ESTOQUE = ("entrada", "saida", "contagem", "quebra", "descarte")
LIMITE_LOTE_PRODUTOS = 200
CAMPOS_LOTE = ("codigo", "nome", "preco", "custo", "comissao", "comissao_pct", "grupo", "unidade", "quantidade",
               "estoque_minimo", "codigo_barras", "atalho", "controla_estoque", "preco_gelada", "atacado_qtd",
               "preco_atacado", "ncm")
TIPOS_COMANDO = ("cadastro.salvar", "cadastro.excluir", "estoque.movimento", "config.salvar", "produtos.importar",
                 "produtos.desfazer", "conta.incluir", "conta.alterar", "conta.quitar", "conta.desfazer", "conta.excluir")


def _campo_publico(c) -> dict:
    return {"nome": c.nome, "rotulo": c.rotulo, "tipo": c.tipo, "obrigatorio": bool(c.obrigatorio),
            "tamanho": c.tamanho, "padrao": c.padrao, "opcoes": [list(o) for o in (c.opcoes or [])] or None,
            "lookup": c.lookup, "na_grade": bool(c.na_grade), "somente_leitura": bool(c.somente_leitura),
            "secao": c.secao, "minimo": c.minimo, "maximo": c.maximo}


def _reais(centavos) -> str:
    """Centavos do comando -> o texto que o CadastroController converte (ele lê inteiro puro como reais)."""
    if isinstance(centavos, bool) or not isinstance(centavos, int):
        raise ErroNegocio("Valor em dinheiro inválido: informe os centavos em número inteiro.")
    sinal = "-" if centavos < 0 else ""
    return f"{sinal}{abs(centavos) // 100},{abs(centavos) % 100:02d}"


def _inteiro(valor, nome: str) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErroNegocio(f"{nome}: número inválido.")
    return valor


class RetaguardaController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    def _gerente(self) -> int | None:
        """Quem assina os lançamentos da retaguarda no caixa: o operador da sessão quando ele é gerente; senão o
        primeiro gerente ativo; sem gerente nenhum na loja, o operador da sessão. A autoridade não depende disso: o
        que vem do painel vale como do dono (`_como_gerente`)."""
        if self.operador_id and self.banco.valor("SELECT nivel FROM operadores WHERE id = ?", (self.operador_id,), 0) >= 4:
            return self.operador_id
        gerente = self.banco.valor("SELECT id FROM operadores WHERE ativo = 1 AND nivel >= 4 ORDER BY id LIMIT 1")
        return gerente or self.operador_id

    @contextmanager
    def _como_gerente(self):
        """A alteração veio do dono ou do fornecedor: vale com autoridade de gerente, mesmo que no caixa
        esteja logado um operador. A identidade da sessão volta ao que era, para a tela continuar escondendo
        custo e lucro de quem não é gerente."""
        gerente = self._gerente()
        anterior = getattr(self.banco, "_operador_auditoria", None)
        autoridade_antes = getattr(self.banco, "_autoridade_dono", False)
        trocou = type(gerente) is int and gerente != anterior
        if trocou:
            self.banco.definir_operador_auditoria(gerente)
        # O dono manda mais que o gerente: quem estiver logado no caixa (ou a falta de gerente na loja) não barra o
        # que ele mandou pelo painel, como o custo dos produtos.
        self.banco._autoridade_dono = True
        try:
            yield
        finally:
            self.banco._autoridade_dono = autoridade_antes
            if trocou:
                self.banco.definir_operador_auditoria(anterior)

    # ------------------------------------------------------------ ligada?
    def ligada(self) -> bool:
        return self.banco.cfg_bool(CHAVE_LIGADA, False)

    # ------------------------------------------------------------ espelho
    def entidades(self) -> list:
        """Os cadastros que a casa usa (módulo desligado em Configurações > Módulos não sobe)."""
        fora = modulos_desligados(self.banco)
        return [e for e in ENTIDADES.values() if e.modulo not in fora]

    def _config_publica(self) -> list[tuple]:
        return [c for c in CAMPOS_CONFIG if c[2] != "segredo" and c[3] not in SECOES_CONFIG_FORA]

    def esquema(self) -> dict:
        """Como montar as telas: campos de cada cadastro, opções das listas e as configurações que a nuvem pode mexer."""
        from src.core import edicao
        cadastro = CadastroController(self.banco)
        entidades, lookups = [], {}
        for ent in self.entidades():
            campos = [_campo_publico(c) for c in ent.campos]
            for c in ent.campos:
                if c.lookup and c.lookup not in lookups:
                    lookups[c.lookup] = [[i, str(r)] for i, r in cadastro.opcoes(c.lookup)]
            entidades.append({"chave": ent.chave, "titulo": ent.titulo, "grupo": GRUPOS.get(ent.chave, "outros"),
                              "tem_ativo": bool(ent.tem_ativo), "busca": list(ent.busca), "campos": campos})
        if self.banco.cfg_bool("usar_contas", False):      # a tela de contas a pagar usa estas listas
            for nome in ("subplanos", "tipos_pagamento", "fornecedores"):
                lookups.setdefault(nome, [[i, str(r)] for i, r in cadastro.opcoes(nome)])
        config = [{"chave": c[0], "rotulo": c[1], "tipo": c[2], "secao": c[3],
                   "opcoes": [list(o) for o in c[4]] if len(c) > 4 else None} for c in self._config_publica()]
        ed = edicao.atual()
        return {"versao": VERSAO_ESPELHO, "edicao": getattr(ed, "chave", ""), "programa": ed.nome,
                "loja": ConfigController(self.banco).nome_loja(), "entidades": entidades, "lookups": lookups,
                "config": {"campos": config, "valores": {c["chave"]: self.banco.cfg(c["chave"]) for c in config}},
                "estoque_tipos": list(TIPOS_ESTOQUE),
                "contas": self.banco.cfg_bool("usar_contas", False),
                "caderneta": self.banco.cfg_bool("usar_caderneta", False)}

    def linhas(self, chave: str) -> dict:
        """Todas as linhas de um cadastro, só com os campos da tela (senha não sobe)."""
        ent = ENTIDADES[chave]
        nomes = ["id"] + [c.nome for c in ent.campos if c.tipo != "senha"]
        total = self.banco.valor(f"SELECT COUNT(*) FROM {ent.tabela}", (), 0)
        colunas = list(nomes)
        if chave == "produtos":            # a retaguarda mostra e filtra quem tem foto (a imagem não sobe)
            colunas.append("EXISTS(SELECT 1 FROM produto_fotos f WHERE f.produto_id = produtos.id) AS tem_foto")
            nomes = nomes + ["tem_foto"]
        consulta = f"SELECT {', '.join(colunas)} FROM {ent.tabela} ORDER BY {ent.ordem}, id LIMIT {LIMITE_LINHAS}"
        return {"campos": nomes, "linhas": [list(l) for l in self.banco.todos(consulta)], "total": total}

    def financeiro(self) -> dict:
        """Contas a pagar em aberto e as quitadas recentes, mais quem deve na caderneta."""
        saida = {"contas": [], "devedores": []}
        if self.banco.cfg_bool("usar_contas", False):
            corte = fmt.somar_dias(fmt.hoje(), -DIAS_CONTAS)
            for c in ContasController(self.banco).listar():
                if c.get("dt_quitacao") and c["dt_quitacao"] < corte:
                    continue
                saida["contas"].append({k: c.get(k) for k in (
                    "id", "descricao", "valor_cent", "dt_entrada", "dt_vencimento", "dt_quitacao", "documento",
                    "nota", "previsao", "parcela", "subplano_id", "tipo_pagamento_id", "fornecedor_id")})
        if self.banco.cfg_bool("usar_caderneta", False):
            saida["devedores"] = [{"id": l["id"], "nome": l["nome"], "saldo_cent": l["saldo_cent"]}
                                  for l in self.banco.todos(
                                      "SELECT id, nome, saldo_cent FROM clientes WHERE saldo_cent < 0 ORDER BY saldo_cent, nome")]
        return saida

    def espelho(self) -> dict:
        """As seções que sobem: `esquema`, `financeiro` e uma `cadastro:<chave>` por cadastro."""
        secoes = {"esquema": self.esquema(), "financeiro": self.financeiro(), "combos": {"linhas": self.combos()},
                  "impressora": self.impressora()}
        for ent in self.entidades():
            secoes[f"cadastro:{ent.chave}"] = self.linhas(ent.chave)
        return secoes

    def impressora(self) -> dict:
        """Impressora de cupom do caixa principal (onde a retaguarda chega): papel, letra e colunas."""
        from src.controllers import impressao_assistente
        try:
            return impressao_assistente.situacao_tamanho(self.banco)
        except Exception:                                  # noqa: BLE001 - sem máquina configurada: seção vazia
            return {}

    def combos(self) -> list[dict]:
        """Combos e montagens (produto feito de outros, que baixa cada item na venda): itens, preço e quanto os itens
        custariam separados, para a retaguarda mostrar a economia do cliente."""
        from src.controllers.produto_controller import ProdutoController
        produtos = ProdutoController(self.banco)
        saida = []
        for p in self.banco.todos(
                """SELECT DISTINCT p.id, p.nome, p.preco_cent, p.ativo, p.cbarra FROM produtos p
                   JOIN composicoes c ON c.produto_id = p.id ORDER BY p.nome LIMIT 500"""):
            itens = [{"produto_id": i["insumo_id"], "nome": i["nome"], "quantidade": i["quantidade"]}
                     for i in self.banco.todos(
                         """SELECT c.insumo_id, c.quantidade, i.nome FROM composicoes c
                            JOIN produtos i ON i.id = c.insumo_id WHERE c.produto_id = ? ORDER BY i.nome""", (p["id"],))]
            saida.append({"id": p["id"], "nome": p["nome"], "preco_cent": p["preco_cent"], "ativo": bool(p["ativo"]),
                          "cbarra": p["cbarra"] or "", "itens": itens,
                          "fardo": produtos.embalagem(p["id"]) is not None,
                          "avulso_cent": produtos.preco_avulso([(i["produto_id"], i["quantidade"]) for i in itens])})
        return saida

    @staticmethod
    def resumo_secao(dados) -> str:
        """Impressão digital da seção: o caixa só sobe de novo o que mudou."""
        texto = json.dumps(dados, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:32]

    # ------------------------------------------------------------ comandos
    def ja_aplicado(self, comando_id: int) -> dict | None:
        l = self.banco.um("SELECT situacao, detalhe, novo_id FROM retaguarda_comandos WHERE id = ?", (comando_id,))
        return dict(l) if l else None

    def aplicar(self, comando: dict) -> dict:
        """Aplica um comando da nuvem uma única vez e devolve {situacao, detalhe, novo_id}. Nunca lança."""
        try:
            ident = _inteiro(comando.get("id"), "Comando")
        except ErroNegocio:
            return {"situacao": "recusado", "detalhe": "Comando sem identificação.", "novo_id": None}
        anterior = self.ja_aplicado(ident)
        if anterior:
            return anterior
        tipo = str(comando.get("tipo") or "")
        dados = comando.get("dados") if isinstance(comando.get("dados"), dict) else {}
        situacao, detalhe, novo_id = "aplicado", "", None
        self.ultimo_detalhe = ""
        try:
            if not self.ligada():
                raise ErroNegocio("A retaguarda na nuvem está desligada neste caixa (Configurações > Nuvem).")
            with self._como_gerente():
                novo_id = self._executar(tipo, dados)
            detalhe = self.ultimo_detalhe[:300]
        except ErroNegocio as erro:                 # ErroValidacao e ErroPermissao são ErroNegocio
            situacao, detalhe = "recusado", str(erro)[:300]
        except Exception:                           # erro de programa não pode travar a fila: recusa e registra
            log.exception("Retaguarda: falha ao aplicar o comando %s (%s).", ident, tipo)
            situacao, detalhe = "recusado", "O caixa não conseguiu aplicar esta alteração (erro interno registrado)."
        self.banco.executar(
            "INSERT OR REPLACE INTO retaguarda_comandos (id, tipo, resumo, autor, criado_em, aplicado_em, situacao, "
            "detalhe, novo_id, aviso_ok) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (ident, tipo[:40], str(comando.get("resumo") or "")[:200], str(comando.get("autor") or "")[:60],
             str(comando.get("criado_em") or "")[:19] or None, fmt.agora(), situacao, detalhe, novo_id))
        return {"situacao": situacao, "detalhe": detalhe, "novo_id": novo_id}

    def _executar(self, tipo: str, dados: dict):
        if tipo == "cadastro.salvar":
            return self._salvar_cadastro(dados)
        if tipo == "cadastro.excluir":
            ent = self._entidade(dados)
            CadastroController(self.banco).excluir(ent.chave, _inteiro(dados.get("id"), "Registro"))
            return None
        if tipo == "estoque.movimento":
            return self._movimento_estoque(dados)
        if tipo == "config.salvar":
            return self._salvar_config(dados)
        if tipo.startswith("conta."):
            return self._conta(tipo, dados)
        if tipo == "produtos.importar":
            return self._importar_produtos(dados)
        if tipo == "produtos.desfazer":
            return self._desfazer_produtos(dados)
        if tipo == "produto.foto":
            return self._foto_produto(dados)
        if tipo == "produto.combo":
            return self._criar_combo(dados)
        if tipo == "impressora.ajustar":
            return self._ajustar_impressora(dados)
        raise ErroNegocio("Este caixa não conhece este tipo de alteração. Atualize o programa da loja.")

    def _ajustar_impressora(self, dados: dict) -> int:
        """Tamanho do cupom pela retaguarda (papel e letra) no caixa principal; com `testar`, imprime a página de teste."""
        from src.controllers import impressao_assistente
        try:
            papel = int(dados.get("papel_mm") or 0)
        except (TypeError, ValueError):
            papel = 0
        cortar = dados.get("cortar")
        feito = impressao_assistente.ajustar_e_ligar(self.banco, papel, str(dados.get("letra") or "normal"),
                                                    None if cortar is None else bool(cortar))
        from src.hardware import perfis_impressora
        self.ultimo_detalhe = "Impressora: " + perfis_impressora.descrever(feito["papel_mm"], feito["letra"]) + "."
        if feito["impressora_ligada"]:
            self.ultimo_detalhe += f" Cupom ligado na térmica '{feito['impressora_ligada']}'."
        elif feito["modo"] != "termica":
            self.ultimo_detalhe += " Atenção: o caixa não achou impressora de cupom no Windows; use o assistente no caixa."
        if dados.get("testar"):
            from src.controllers.impressao_controller import ImpressaoController
            try:
                ImpressaoController(self.banco).imprimir_teste()
                self.ultimo_detalhe += " Página de teste enviada."
            except Exception as erro:                      # noqa: BLE001 - o tamanho já ficou gravado
                self.ultimo_detalhe += f" O teste não saiu: {erro}"[:200]
        return 0

    def _criar_combo(self, dados: dict) -> int:
        """Combo montado pela retaguarda: as mesmas regras do "Criar combo" do caixa (ProdutoController.criar_combo)."""
        from src.controllers.produto_controller import ProdutoController
        itens = dados.get("itens")
        if not isinstance(itens, list) or not 1 <= len(itens) <= 30:
            raise ErroNegocio("Inclua de 1 a 30 produtos no combo.")
        pares = []
        for item in itens:
            if not isinstance(item, dict):
                raise ErroNegocio("Item do combo inválido.")
            try:
                quantidade = float(item.get("quantidade"))
            except (TypeError, ValueError):
                raise ErroNegocio("Quantidade inválida no combo.") from None
            pares.append((_inteiro(item.get("produto_id"), "Produto"), quantidade))
        preco = dados.get("preco_cent")
        if type(preco) is not int:
            raise ErroNegocio("Informe o preço do combo.")
        pid = ProdutoController(self.banco).criar_combo(str(dados.get("nome") or ""), preco, pares,
                                                          cbarra=str(dados.get("cbarra") or "") or None,
                                                          operador_id=self.operador_id)
        self.ultimo_detalhe = "Combo criado."
        return pid

    def _produto_do_comando(self, dados: dict) -> int:
        """O produto pelo id ou, para o cadastrado agora pela retaguarda (o id só existe depois), pelo código."""
        if dados.get("produto_id") not in (None, ""):
            return _inteiro(dados.get("produto_id"), "Produto")
        codigo = re.sub(r"\D", "", str(dados.get("codigo") or ""))
        if not codigo or len(codigo) > 13:
            raise ErroNegocio("Informe o produto da foto.")
        achado = self.banco.valor("SELECT id FROM produtos WHERE codigo = ?", (codigo.zfill(13),))
        if achado is None:
            raise ErroNegocio(f"Produto {codigo} não encontrado no caixa.")
        return int(achado)

    def _foto_produto(self, dados: dict):
        """Foto do produto pedida pela retaguarda: buscada pelo código de barras na base pública (o caixa baixa), enviada
        do celular (JPEG pequeno em base64) ou removida. A imagem passa pelas mesmas regras da foto escolhida no caixa."""
        import base64
        import binascii
        from src.controllers import foto_produto_controller as fotos
        produto_id = self._produto_do_comando(dados)
        controle = fotos.FotoProdutoController(self.banco)
        controle._existe(produto_id)
        origem = str(dados.get("origem") or "")
        if origem == "remover":
            controle.remover(produto_id)
            self.ultimo_detalhe = "Foto removida."
            return produto_id
        if origem == "codigo_barras":
            cbarra = str(dados.get("cbarra") or "") or str(
                self.banco.valor("SELECT cbarra FROM produtos WHERE id = ?", (produto_id,), "") or "")
            controle.gravar(produto_id, fotos.buscar_na_internet(cbarra))
            self.ultimo_detalhe = "Foto baixada pelo código de barras."
            return produto_id
        if origem == "arquivo":
            try:
                imagem = base64.b64decode(str(dados.get("imagem_b64") or ""), validate=True)
            except (binascii.Error, ValueError):
                raise ErroNegocio("A foto enviada está estragada.") from None
            controle.gravar(produto_id, fotos.preparar(imagem))
            self.ultimo_detalhe = "Foto enviada pela retaguarda."
            return produto_id
        raise ErroNegocio("Pedido de foto inválido.")

    def _importar_produtos(self, dados: dict):
        """Lote de produtos (planilha enviada pela central): mesmas regras da importação do caixa, numa transação só.
        Linhas recusadas não travam as outras; o motivo volta no detalhe. Nenhuma importável: recusa o lote."""
        from src.controllers.importacao_produtos import ImportacaoProdutos
        linhas = dados.get("linhas")
        if not isinstance(linhas, list) or not linhas:
            raise ErroNegocio("Lote de produtos vazio.")
        if len(linhas) > LIMITE_LOTE_PRODUTOS:
            raise ErroNegocio(f"Lote grande demais (máximo {LIMITE_LOTE_PRODUTOS} produtos por envio).")
        modo = str(dados.get("modo_quantidade") or "substituir")
        if modo not in ("substituir", "somar"):
            raise ErroNegocio("Modo de quantidade inválido: use substituir ou somar.")
        tabela = []
        for n, linha in enumerate(linhas, start=1):
            if not isinstance(linha, dict):
                raise ErroNegocio("Lote de produtos inválido.")
            item = {c: str(linha.get(c) if linha.get(c) is not None else "").strip() for c in CAMPOS_LOTE}
            item["_linha"] = n
            tabela.append(item)
        if dados.get("casar_barras"):
            self._casar_barras(tabela)
        imp = ImportacaoProdutos(self.banco, self._gerente())
        previa = imp.analisar(tabela, atualizar_existentes=bool(dados.get("atualizar_existentes", True)),
                              usar_codigo_da_planilha=True, maiusculas=True)
        recusadas = [l for l in previa.linhas if l.acao == "recusar"]
        if not previa.importaveis:
            raise ErroNegocio("Nenhum produto importado: " + "; ".join(f"{l.linha}: {l.motivo}" for l in recusadas[:5]))
        with self.banco.transacao():
            resultado = imp.importar(previa, modo_quantidade=modo)
            for item in tabela:                         # NCM do catálogo: só preenche quem ainda não tem
                ncm = re.sub(r"\D", "", item.get("ncm") or "")
                if len(ncm) == 8 and item["nome"]:
                    self.banco.executar(
                        "UPDATE produtos SET ncm = ? WHERE nome = ? COLLATE NOCASE AND COALESCE(ncm, '') = ''",
                        (ncm, item["nome"]))
        self.ultimo_detalhe = (f"{resultado['criados']} criado(s), {resultado['atualizados']} atualizado(s)"
                               + (f"; {len(recusadas)} recusado(s): "
                                  + "; ".join(f"{l.linha} {l.nome or ''}: {l.motivo}" for l in recusadas[:4])
                                  if recusadas else ""))
        return None

    def _casar_barras(self, tabela: list[dict]) -> None:
        """Sem código na linha, o código de barras que já existe na loja atualiza aquele produto (não cria outro)."""
        for item in tabela:
            barras = re.sub(r"\D", "", str(item.get("codigo_barras") or ""))
            if not barras or str(item.get("codigo") or "").strip():
                continue
            dono = self.banco.um(
                "SELECT codigo, nome, ativo FROM produtos WHERE cbarra = ? ORDER BY ativo DESC, id LIMIT 1", (barras,))
            if dono is None:
                continue
            if not dono["ativo"] and str(dono["nome"] or "").casefold() != str(item.get("nome") or "").strip().casefold():
                continue
            codigo = str(dono["codigo"] or "")
            item["codigo"] = str(int(codigo)) if codigo.isdigit() else codigo

    def _desfazer_produtos(self, dados: dict):
        """Desfaz um lote da importação do painel: restaura quem foi atualizado e desativa quem foi criado,
        se esse produto novo ainda não foi vendido."""
        itens = dados.get("itens")
        if not isinstance(itens, list) or not itens:
            raise ErroNegocio("Nada para desfazer.")
        if len(itens) > LIMITE_LOTE_PRODUTOS:
            raise ErroNegocio(f"Lote grande demais (máximo {LIMITE_LOTE_PRODUTOS} itens por envio).")
        with self.banco.transacao():
            desativados, pulados, restaurar = 0, [], []
            for n, item in enumerate(itens, start=1):
                if not isinstance(item, dict):
                    raise ErroNegocio("Desfazer inválido.")
                if item.get("acao") == "atualizar" and isinstance(item.get("anterior"), dict):
                    restaurar.append(self._linha_anterior(item["anterior"], n))
                    continue
                if item.get("acao") != "criar":
                    pulados.append(f"{n}: ação desconhecida")
                    continue
                achado = self._produto_da_importacao(item)
                if achado is None:
                    pulados.append(f"{n}: não achei '{item.get('nome') or item.get('codigo_barras') or ''}'")
                    continue
                if not self._pode_desativar(achado["id"]):
                    pulados.append(f"{n}: '{item.get('nome') or ''}' já foi vendido; ficou como está")
                    continue
                CadastroController(self.banco).salvar("produtos", {"ativo": "N"}, achado["id"])
                desativados += 1
            if restaurar:
                self._importar_produtos({"linhas": restaurar, "casar_barras": True, "modo_quantidade": "substituir",
                                         "atualizar_existentes": True})
            if not desativados and not restaurar:
                raise ErroNegocio("; ".join(pulados[:5]) or "Nada para desfazer.")
        resto = self.ultimo_detalhe if restaurar else ""
        self.ultimo_detalhe = (f"{desativados} desativado(s). {resto}"
                               + (f" Não desfiz: {'; '.join(pulados[:4])}" if pulados else "")).strip()
        return None

    def _linha_anterior(self, ant: dict, n: int) -> dict:
        linha = {"_linha": n, "codigo": str(ant.get("codigo") or ""), "nome": str(ant.get("nome") or ""),
                 "preco": _reais(int(ant.get("preco_cent") or 0)), "grupo": str(ant.get("grupo") or ""),
                 "unidade": str(ant.get("unidade") or "UN"),
                 "codigo_barras": re.sub(r"\D", "", str(ant.get("codigo_barras") or ""))}
        if ant.get("custo_cent") is not None:
            linha["custo"] = _reais(int(ant["custo_cent"]))
        if ant.get("qt_atual") is not None:
            linha["quantidade"] = fmt.fmt_qtd(ant["qt_atual"], 4).rstrip("0").rstrip(",") or "0"
        return linha

    def _produto_da_importacao(self, item: dict):
        barras = re.sub(r"\D", "", str(item.get("codigo_barras") or ""))
        if barras:
            return self.banco.um(
                "SELECT id FROM produtos WHERE cbarra = ? ORDER BY ativo DESC, id DESC LIMIT 1", (barras,))
        nome = str(item.get("nome") or "").strip()
        if nome:
            return self.banco.um(
                "SELECT id FROM produtos WHERE nome = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (nome,))
        return None

    def _pode_desativar(self, produto_id: int) -> bool:
        if self.banco.valor("SELECT 1 FROM itens_venda WHERE produto_id = ? LIMIT 1", (produto_id,)):
            return False
        tipos = {r[0] for r in self.banco.todos(
            "SELECT DISTINCT tipo FROM movimentos_estoque WHERE produto_id = ?", (produto_id,))}
        return tipos <= {"inicial", "entrada"}

    def _entidade(self, dados: dict):
        chave = str(dados.get("entidade") or "")
        permitidas = {e.chave: e for e in self.entidades()}
        if chave not in permitidas:
            raise ErroNegocio("Cadastro desconhecido ou desligado nesta loja.")
        return permitidas[chave]

    def _salvar_cadastro(self, dados: dict) -> int | None:
        ent = self._entidade(dados)
        valores = dados.get("valores")
        if not isinstance(valores, dict) or not valores:
            raise ErroNegocio("Nenhum campo para alterar.")
        ident = dados.get("id")
        if ident is not None:
            ident = _inteiro(ident, "Registro")
        prontos = {}
        for nome, valor in valores.items():
            try:
                campo = ent.campo(nome)
            except KeyError:
                raise ErroNegocio(f"Campo desconhecido em {ent.titulo}: {nome}.") from None
            if campo.somente_leitura:
                continue
            prontos[nome] = _reais(valor) if campo.tipo == "dinheiro" and valor not in (None, "") else valor
        novo = CadastroController(self.banco).salvar(ent.chave, prontos, ident)
        return novo if ident is None else None

    def _movimento_estoque(self, dados: dict) -> int:
        tipo = str(dados.get("tipo") or "")
        if tipo not in TIPOS_ESTOQUE:
            raise ErroNegocio("Tipo de movimento de estoque inválido.")
        quantidade = dados.get("quantidade")
        if isinstance(quantidade, bool) or not isinstance(quantidade, (int, float)):
            raise ErroNegocio("Quantidade inválida.")
        descricao = (str(dados.get("descricao") or "").strip() or "Ajuste pela retaguarda")[:80]
        return EstoqueController(self.banco, self._gerente()).registrar_rapido(
            _inteiro(dados.get("produto_id"), "Produto"), tipo, float(quantidade), descricao)

    def _salvar_config(self, dados: dict) -> None:
        valores = dados.get("valores")
        if not isinstance(valores, dict) or not valores:
            raise ErroNegocio("Nenhuma configuração para alterar.")
        permitidas = {c[0] for c in self._config_publica()}
        fora = [c for c in valores if c not in permitidas]
        if fora:
            raise ErroNegocio(f"Esta configuração só pode ser alterada no próprio caixa: {fora[0]}.")
        ConfigController(self.banco).salvar_config({c: "" if v is None else str(v) for c, v in valores.items()})
        return None

    def _conta(self, tipo: str, dados: dict):
        if not self.banco.cfg_bool("usar_contas", False):
            raise ErroNegocio("O módulo de contas está desligado nesta loja.")
        contas = ContasController(self.banco, self._gerente())
        if tipo == "conta.incluir":
            ids = contas.incluir(
                _inteiro(dados.get("subplano_id"), "Sub plano"), str(dados.get("descricao") or ""),
                _inteiro(dados.get("tipo_pagamento_id"), "Forma de pagamento"),
                _inteiro(dados.get("valor_cent"), "Valor"), dados.get("dt_vencimento") or None,
                dados.get("dt_entrada") or None, dados.get("dt_quitacao") or None,
                (str(dados.get("documento") or "").strip() or None), False,
                (str(dados.get("nota") or "").strip() or None), bool(dados.get("previsao")),
                dados.get("fornecedor_id") if isinstance(dados.get("fornecedor_id"), int) else None,
                dados.get("meses") if isinstance(dados.get("meses"), int) else 1)
            return ids[0]
        ident = _inteiro(dados.get("id"), "Conta")
        if tipo == "conta.quitar":
            contas.quitar(ident, dados.get("data") or None)
        elif tipo == "conta.desfazer":
            contas.obter(ident)
            contas.desfazer_quitacao(ident)
        elif tipo == "conta.excluir":
            contas.excluir(ident)
        elif tipo == "conta.alterar":
            campos = dados.get("valores") if isinstance(dados.get("valores"), dict) else {}
            if not campos:
                raise ErroNegocio("Nenhum campo para alterar.")
            if "valor_cent" in campos:
                _inteiro(campos["valor_cent"], "Valor")
            contas.atualizar(ident, **campos)
        else:
            raise ErroNegocio("Este caixa não conhece este tipo de alteração. Atualize o programa da loja.")
        return None

    # ------------------------------------------------------------ histórico no caixa
    def recentes(self, limite: int = 100) -> list[dict]:
        return [dict(l) for l in self.banco.todos(
            "SELECT id, tipo, resumo, autor, criado_em, aplicado_em, situacao, detalhe FROM retaguarda_comandos "
            "ORDER BY aplicado_em DESC, id DESC LIMIT ?", (limite,))]
