"""Alertas operacionais da loja, para o painel do caixa.

Só LEITURA do banco local: nenhuma consulta daqui grava, envia, reprocessa fila ou faz rede. As regras são as que o PDV já
usa em outras telas, sem limites novos inventados aqui:
  * estoque: produto controlado zerado (ruptura) ou no ponto de pedido (saldo até o mínimo cadastrado), pelo mesmo painel
    do Estoque;
  * mesas/comandas: as "paradas" do painel de mesas (`tempo_inatividade_min`, 0 desliga), só com o módulo de mesas ligado;
  * entregas em aberto (só com o delivery ligado), informativo, sem prazo arbitrário;
  * filas: impressão (erro/falhando/aguardando) e vendas aguardando o painel na nuvem;
  * integrações iFood/NFC-e em preparação (informativo: continuam bloqueadas).
Nenhum alerta traz valor em dinheiro, e nada daqui segue para a central do fornecedor.

Permissões (revalidadas no banco a cada consulta da tela): a seção de estoque exige `rel_estoque`; a operacional
(mesas, entregas, filas e integrações) exige `rel_informativos`.
"""
from __future__ import annotations

from typing import TypedDict

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao

NIVEIS = ("critico", "aviso", "info")
ROTULO_NIVEL = {"critico": "Crítico", "aviso": "Atenção", "info": "Informativo"}
CATEGORIAS = {"estoque": "Estoque", "mesas": "Mesas/comandas", "entregas": "Entregas", "impressao": "Impressão",
              "nuvem": "Painel na nuvem", "integracoes": "Integrações"}
# seção do painel -> módulo de acesso exigido
SECOES = {"estoque": "rel_estoque", "operacao": "rel_informativos"}
TODAS = frozenset(SECOES)


class Alerta(TypedDict):
    categoria: str
    nivel: str
    titulo: str
    detalhe: str


def _qtd(q) -> str:
    """2,000 -> '2'; 1,500 -> '1,5'."""
    return fmt.fmt_qtd(q).rstrip("0").rstrip(",")


class AlertasController:
    def __init__(self, banco):
        self.banco = banco

    # ------------------------------------------------------------ permissões
    def secoes_permitidas(self, operador_id: int | None) -> set[str]:
        """Seções que o operador pode ver AGORA, lidas do banco (operador ativo e nível atual dos módulos)."""
        if operador_id is None:
            return set()
        linha = self.banco.um("SELECT ativo FROM operadores WHERE id = ?", (operador_id,))
        if linha is None or not linha["ativo"]:
            return set()
        from src.controllers.acesso_controller import AcessoController
        acesso = AcessoController(self.banco)
        operador = acesso.operador(operador_id)
        return {secao for secao, modulo in SECOES.items() if acesso.pode(operador, modulo)}

    def exigir_secoes(self, operador_id: int | None) -> set[str]:
        secoes = self.secoes_permitidas(operador_id)
        if not secoes:
            raise ErroPermissao("Seu nível de acesso não permite ver os alertas (relatórios de estoque ou informativos).")
        return secoes

    # ------------------------------------------------------------ consultas
    def estoque(self) -> dict:
        """{'controlados': n, 'sem': [...], 'ponto': [...]}, cada produto com nome, saldo, mínimo, unidade e reposição sugerida."""
        from src.controllers.estoque_controller import EstoqueController
        sem, ponto = [], []
        for p in EstoqueController(self.banco).painel():
            if p["situacao"] not in ("sem", "ponto"):
                continue
            item = {"id": p["id"], "nome": p["nome"], "qt_atual": p["qt_atual"], "estoque_minimo": p["estoque_minimo"],
                    "unidade": p["unidade"], "repor": p["repor"]}
            (sem if p["situacao"] == "sem" else ponto).append(item)
        controlados = self.banco.valor("SELECT COUNT(*) FROM produtos WHERE controla_estoque = 1 AND ativo = 1", (), 0)
        return {"controlados": controlados, "sem": sem, "ponto": ponto}

    def mesas(self) -> dict:
        """Mesas/comandas paradas pelo critério do painel de mesas. {'ligado', 'limite_min', 'abertas', 'paradas'}."""
        ligado = self.banco.cfg_bool("usar_mesas", True)
        limite = self.banco.cfg_int("tempo_inatividade_min", 30)
        if not ligado:
            return {"ligado": False, "limite_min": limite, "abertas": 0, "paradas": []}
        from src.controllers.caixa_controller import CaixaController
        abertas = CaixaController(self.banco).mesas()
        paradas = [{"rotulo": m["rotulo"], "minutos": m["minutos_parada"], "n_itens": m["n_itens"]}
                   for m in abertas if m["inativa"]]
        paradas.sort(key=lambda m: -m["minutos"])
        return {"ligado": True, "limite_min": limite, "abertas": len(abertas), "paradas": paradas}

    def entregas(self) -> dict:
        if not self.banco.cfg_bool("usar_delivery", False):
            return {"ligado": False, "abertas": 0, "mais_antiga_min": 0}
        datas = [r["aberta_em"] for r in self.banco.todos(
            "SELECT aberta_em FROM vendas WHERE modalidade = 'entrega' AND status IN ('aberta','conta_enviada') ORDER BY aberta_em")]
        return {"ligado": True, "abertas": len(datas), "mais_antiga_min": fmt.minutos_entre(datas[0]) if datas else 0}

    def filas(self) -> dict:
        """Contagens das filas locais (sem o texto dos erros, que pode ter detalhe técnico)."""
        from src.controllers.fila_impressao_controller import FilaImpressao
        imp = FilaImpressao(self.banco).contagem()
        from src.sync import painel_envio
        nuvem_ligada = painel_envio.ligado(self.banco)
        return {
            "impressao": {"pendentes": imp["pendentes"], "falhando": imp["falhando"], "erros": imp["erros"]},
            "nuvem": {"ligada": nuvem_ligada, "pendentes": painel_envio.pendentes(self.banco) if nuvem_ligada else 0,
                      "com_erro": nuvem_ligada and bool(self.banco.cfg(painel_envio.CHAVE_ULTIMO_ERRO).strip())},
        }

    def integracoes(self) -> list[dict]:
        """iFood/NFC-e em preparação (nunca operam nesta versão). [{'modulo', 'nome', 'pendencias' | 'erro'}]."""
        from src.controllers.integracoes_controller import IntegracoesController
        ctl = IntegracoesController(self.banco)
        saida = []
        for modulo, nome in (("ifood", "iFood"), ("nfce", "NFC-e")):
            try:
                s = ctl.situacao(modulo)
            except ErroNegocio as e:
                saida.append({"modulo": modulo, "nome": nome, "erro": str(e)})
                continue
            if s["estado"] == "preparacao":
                saida.append({"modulo": modulo, "nome": nome, "pendencias": len(s["pendencias"])})
        return saida

    # ------------------------------------------------------------ lista unificada
    def alertas(self, secoes=TODAS) -> list[Alerta]:
        """Todos os alertas das seções pedidas, do mais grave ao informativo."""
        secoes = set(secoes) & TODAS
        lista: list[Alerta] = []
        if "estoque" in secoes:
            lista += self._alertas_estoque()
        if "operacao" in secoes:
            lista += self._alertas_operacao()
        return sorted(lista, key=lambda a: NIVEIS.index(a["nivel"]))

    def contagem(self, alertas: list[Alerta]) -> dict:
        r = {n: 0 for n in NIVEIS}
        for a in alertas:
            r[a["nivel"]] += 1
        r["total"] = len(alertas)
        return r

    def _alertas_estoque(self) -> list[Alerta]:
        e = self.estoque()
        lista = [Alerta(categoria="estoque", nivel="critico", titulo=f"Sem estoque: {p['nome']}",
                        detalhe=f"Saldo {_qtd(p['qt_atual'])} {p['unidade']}"
                                + (f"; mínimo {_qtd(p['estoque_minimo'])}" if p["estoque_minimo"] else "; mínimo não definido"))
                 for p in e["sem"]]
        lista += [Alerta(categoria="estoque", nivel="aviso", titulo=f"Abaixo do mínimo: {p['nome']}",
                         detalhe=f"Saldo {_qtd(p['qt_atual'])} {p['unidade']} de mínimo {_qtd(p['estoque_minimo'])}"
                                 + (f"; repor {_qtd(p['repor'])}" if p["repor"] else ""))
                  for p in e["ponto"]]
        return lista

    def _alertas_operacao(self) -> list[Alerta]:
        lista: list[Alerta] = []
        m = self.mesas()
        for p in m["paradas"]:
            lista.append(Alerta(categoria="mesas", nivel="aviso", titulo=f"{p['rotulo']} sem lançamento há {p['minutos']} min",
                                detalhe=f"Limite configurado: {m['limite_min']} min; {p['n_itens']} item(ns) lançado(s)"))
        e = self.entregas()
        if e["abertas"]:
            lista.append(Alerta(categoria="entregas", nivel="info", titulo=f"{e['abertas']} entrega(s) em aberto",
                                detalhe=f"A mais antiga foi pedida há {e['mais_antiga_min']} min"))
        f = self.filas()
        imp = f["impressao"]
        incertos = self.banco.valor("SELECT COUNT(*) FROM fila_impressao WHERE status = 'incerto'", padrao=0)
        if incertos:
            lista.append(Alerta(categoria="impressao", nivel="critico",
                                titulo=f"{incertos} envio(s) de impressão interrompido(s)",
                                detalhe="Confira fisicamente o papel e confirme ou autorize o reenvio na Fila de impressão. "
                                        "Não entram no reenvio automático."))
        if imp["erros"]:
            lista.append(Alerta(categoria="impressao", nivel="critico", titulo=f"{imp['erros']} documento(s) com erro na impressão",
                                detalhe="Confira a impressora e reenvie em Utilitários > Fila de impressão"))
        if imp["falhando"]:
            lista.append(Alerta(categoria="impressao", nivel="aviso",
                                titulo=f"Impressora sem responder: {imp['pendentes']} na fila",
                                detalhe=f"{imp['falhando']} documento(s) já tentaram e aguardam nova tentativa"))
        elif imp["pendentes"]:
            lista.append(Alerta(categoria="impressao", nivel="info", titulo=f"{imp['pendentes']} documento(s) aguardando impressão",
                                detalhe="Saem sozinhos assim que a impressora responder"))
        n = f["nuvem"]
        if n["ligada"] and n["com_erro"]:
            lista.append(Alerta(categoria="nuvem", nivel="aviso", titulo="Último envio ao painel na nuvem falhou",
                                detalhe=f"{n['pendentes']} venda(s) aguardando envio; o caixa segue normalmente"))
        elif n["ligada"] and n["pendentes"]:
            lista.append(Alerta(categoria="nuvem", nivel="info", titulo=f"{n['pendentes']} venda(s) aguardando envio à nuvem",
                                detalhe="Sobem na próxima sincronização"))
        for i in self.integracoes():
            if "erro" in i:
                lista.append(Alerta(categoria="integracoes", nivel="aviso", titulo=f"{i['nome']}: configuração inválida",
                                    detalhe=i["erro"]))
            else:
                lista.append(Alerta(categoria="integracoes", nivel="info", titulo=f"{i['nome']} em preparação (sem operação)",
                                    detalhe=f"{i['pendencias']} pendência(s) antes de homologar; nada é enviado"))
        return lista
