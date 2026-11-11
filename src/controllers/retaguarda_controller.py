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
TIPOS_COMANDO = ("cadastro.salvar", "cadastro.excluir", "estoque.movimento", "config.salvar",
                 "conta.incluir", "conta.alterar", "conta.quitar", "conta.desfazer", "conta.excluir")


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
        """Quem assina os lançamentos da retaguarda no caixa: o operador da sessão ou, na sincronização (sem ninguém
        logado), o primeiro gerente ativo. O dono e o fornecedor mexem com autoridade de gerente."""
        if self.operador_id:
            return self.operador_id
        return self.banco.valor("SELECT id FROM operadores WHERE ativo = 1 AND nivel >= 4 ORDER BY id LIMIT 1")

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
        consulta = f"SELECT {', '.join(nomes)} FROM {ent.tabela} ORDER BY {ent.ordem}, id LIMIT {LIMITE_LINHAS}"
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
        secoes = {"esquema": self.esquema(), "financeiro": self.financeiro()}
        for ent in self.entidades():
            secoes[f"cadastro:{ent.chave}"] = self.linhas(ent.chave)
        return secoes

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
        try:
            if not self.ligada():
                raise ErroNegocio("A retaguarda na nuvem está desligada neste caixa (Configurações > Nuvem).")
            novo_id = self._executar(tipo, dados)
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
        raise ErroNegocio("Este caixa não conhece este tipo de alteração. Atualize o programa da loja.")

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
