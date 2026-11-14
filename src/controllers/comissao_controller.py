"""Comissão das garotas (boate).

No caixa, o código 50 (configurável) lança a comissão na própria linha de entrada (ou, com `comissao_na_linha` desligada, abre a
janela): o número da garota é o da comanda dela (comanda 180 = garota 180) e o operador digita o valor. Aqui a comissão é
registrada no número da garota. Não é venda: nada disso entra no faturamento, no estoque nem na conferência do dinheiro até a
comissão ser PAGA, quando sai dinheiro do caixa (uma sangria).

Drinks da garota (código D, configurável): o que ela bebeu durante a noite, lançado na comanda dela com o preço digitado
(a dose da casa; sem estoque e fora do faturamento). No acerto o total dos drinks é descontado do que ela recebe; se os
drinks passam do que ela tem a receber, ela paga a diferença ao caixa.

Situações: 'pendente' (a pagar), 'paga' e 'cancelada'. Nada é apagado: lançamento errado é cancelado, com quem e quando.
O cadastro de garotas (número e nome) é opcional: serve para mostrar o nome na hora de lançar e nos relatórios.
"""
from __future__ import annotations

import re

from src.controllers.config_controller import codigo_especial
from src.controllers.turno_controller import TurnoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

NUMERO_MAXIMO = 99999
LIMITE_CONFIRMAR_CENT = 50000     # a tela pede confirmação acima disso: 2500 digitado no lugar de 25,00
SHOWS_MAXIMO = 999                # shows de uma vez no acerto: acima disso é erro de digitação
SHOW_VALORES_PADRAO = (5000, 6000)   # R$ 50,00 e R$ 60,00: as duas tarifas de show da casa


class ComissaoController:
    def __init__(self, banco):
        self.banco = banco

    # --------------------------------------------------------------- o código do caixa
    def ligada(self) -> bool:
        """A casa usa a comissão das garotas (módulo `usar_garotas`, desligado pelo perfil dos outros tipos de negócio)."""
        return self.banco.cfg_bool("usar_garotas", True)

    def codigo(self) -> str:
        """O código que, digitado no caixa, lança a comissão (configuração `codigo_comissao`; vazio ou módulo desligado: nenhum)."""
        return codigo_especial(self.banco, "codigo_comissao")

    def eh_codigo(self, texto) -> bool:
        """True se o que foi digitado no campo do código é o da comissão: 50, 050 e 0000000000050 são o mesmo."""
        cod, t = self.codigo(), ("" if texto is None else str(texto)).strip()
        if not cod or not t:
            return False
        if cod.isdigit() and t.isdigit():
            return int(cod) == int(t)
        return cod.lower() == t.lower()

    # --------------------------------------------------------------- drinks da garota
    def codigo_consumo(self) -> str:
        """O código que lança o drink da garota (configuração `codigo_consumo_garota`; vazio ou módulo desligado: nenhum)."""
        return codigo_especial(self.banco, "codigo_consumo_garota")

    def eh_codigo_consumo(self, texto) -> bool:
        cod, t = self.codigo_consumo(), ("" if texto is None else str(texto)).strip()
        if not cod or not t:
            return False
        if cod.isdigit() and t.isdigit():
            return int(cod) == int(t)
        return cod.lower() == t.lower()

    def lancar_consumo(self, garota, valor_cent: int, turno_id: int | None, operador_id: int | None) -> int:
        """Marca na comanda da garota um drink que ela bebeu, pelo preço digitado. Devolve o id do lançamento."""
        n = self.validar_numero(garota)
        valor_cent = int(valor_cent)
        if valor_cent <= 0:
            raise ErroNegocio("Informe o valor do drink (maior que zero).")
        if turno_id is None or TurnoController(self.banco).obter(turno_id)["status"] != "aberto":
            raise ErroNegocio("Abra o turno do caixa antes de lançar o drink da garota.")
        cid = self.banco.inserir("consumos_garotas", {
            "garota": n, "valor_cent": valor_cent, "turno_id": turno_id, "operador_id": operador_id,
            "criado_em": fmt.agora(), "status": "pendente"})
        self.banco.log("consumo_garota_lancado", f"garota {n} {fmt.fmt_brl(valor_cent)}", operador_id)
        return cid

    def consumos_pendentes(self, garota) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            "SELECT * FROM consumos_garotas WHERE garota = ? AND status = 'pendente' ORDER BY id",
            (self.validar_numero(garota),))]

    def consumo_pendente(self, garota) -> int:
        """Quanto ela bebeu e ainda não foi descontado, em centavos."""
        return sum(c["valor_cent"] for c in self.consumos_pendentes(garota))

    def consumos_marcados(self, garota, turno_id: int | None = None) -> list[dict]:
        """O que aparece na comanda dela: os drinks a descontar (de qualquer turno) e os descontados neste turno."""
        n = self.validar_numero(garota)
        neste_turno = "OR (status = 'descontado' AND descontado_turno_id = ?)" if turno_id else ""
        params: list = [n] + ([turno_id] if turno_id else [])
        return [dict(r) for r in self.banco.todos(
            f"SELECT * FROM consumos_garotas WHERE garota = ? AND (status = 'pendente' {neste_turno}) ORDER BY id", params)]

    def cancelar_consumo(self, consumo_id: int, operador_id: int | None, motivo: str = "") -> None:
        c = self.banco.um("SELECT garota, valor_cent FROM consumos_garotas WHERE id = ?", (consumo_id,))
        n = self.banco.executar(
            "UPDATE consumos_garotas SET status = 'cancelado', cancelado_em = ?, cancelado_por = ?, motivo_cancelamento = ? "
            "WHERE id = ? AND status = 'pendente'", (fmt.agora(), operador_id, (motivo or "").strip() or None, consumo_id)).rowcount
        if not n:
            raise ErroNegocio("Só é possível cancelar drink ainda não descontado.")
        self.banco.log("consumo_garota_cancelado", f"garota {c['garota']} {fmt.fmt_brl(c['valor_cent'])} {motivo}".strip(),
                       operador_id)

    def consumos_do_turno(self, turno_id: int) -> dict:
        """Drinks das garotas descontados nos acertos deste turno (para o fechamento)."""
        linhas = [dict(r) for r in self.banco.todos(
            """SELECT a.garota, COALESCE(MAX(a.nome), g.nome, '') AS nome, SUM(a.consumo_cent) AS total_cent
               FROM acertos_garotas a LEFT JOIN garotas g ON g.numero = a.garota
               WHERE a.turno_id = ? AND a.consumo_cent > 0 GROUP BY a.garota ORDER BY a.garota""", (turno_id,))]
        return {"total_cent": sum(l["total_cent"] for l in linhas), "por_garota": linhas}

    # --------------------------------------------------------------- pontos
    # A casa marca a comissão em pontos: 0,1 = R$ 5,00, 0,2 = R$ 10,00, 0,3 = R$ 15,00... (comissao_em_pontos, padrão S;
    # o valor de cada 0,1 fica em comissao_valor_ponto). No caixa digita-se 1, 2, 3 para 0,1, 0,2, 0,3. Com N, em reais.
    def em_pontos(self) -> bool:
        return self.banco.cfg_bool("comissao_em_pontos", True)

    def valor_ponto_cent(self) -> int:
        """Quanto vale cada 0,1 ponto, em centavos (padrão R$ 5,00)."""
        try:
            cent = fmt.para_centavos(self.banco.cfg("comissao_valor_ponto", "5") or "5")
        except ValueError:
            cent = 500
        return cent if cent > 0 else 500

    def rotulo_valor(self) -> str:
        return f"Pontos (1 = 0,1 = {fmt.fmt_brl(self.valor_ponto_cent())})" if self.em_pontos() else "Valor (R$)"

    def para_centavos(self, texto) -> int:
        """O que o operador digitou no campo da comissão, em centavos. Em pontos, o número sem vírgula conta em décimos, como
        a casa fala: 1 = 0,1 (R$ 5,00), 2 = 0,2, 3 = 0,3, 10 = 1,0. Com vírgula vale o ponto escrito (0,3 = 0,3). Em reais,
        o valor em reais."""
        if not self.em_pontos():
            return fmt.para_centavos(texto)
        t = ("" if texto is None else str(texto)).strip()
        if t.isdigit():
            decimos = int(t)
        else:
            pontos = fmt.para_qtd(t)
            decimos = round(pontos * 10, 6)
            if decimos != int(decimos):
                raise ErroNegocio(f"Use pontos de 0,1 em 0,1 (digite 1 para 0,1 = {fmt.fmt_brl(self.valor_ponto_cent())}).")
        return int(decimos) * self.valor_ponto_cent()

    def em_pontos_texto(self, cent: int) -> str:
        """'0,3 ponto (R$ 15,00)' quando a casa usa pontos; senão só o valor."""
        if not self.em_pontos() or cent % self.valor_ponto_cent():
            return fmt.fmt_brl(cent)
        decimos = cent // self.valor_ponto_cent()
        return f"{decimos // 10},{decimos % 10} ({fmt.fmt_brl(cent)})"

    # --------------------------------------------------------------- shows
    # Show é lançado pelo operador na hora de fechar a conta da garota (nunca contado sozinho): a quantidade e o valor de cada
    # um (as tarifas ficam em `show_valores`, padrão "50;60": a vírgula é dos centavos). O total do acerto é a comissão marcada + quantidade x valor.
    def pede_shows(self) -> bool:
        return self.banco.cfg_bool("comissao_pede_shows", True)

    def shows_quartos_pendentes(self, garota) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            "SELECT s.*, q.quarto FROM shows_quartos s JOIN quartos_uso q ON q.id = s.uso_id "
            "WHERE s.garota = ? AND s.acerto_id IS NULL ORDER BY s.id", (self.validar_numero(garota),))]

    def quantidade_shows_quartos(self, garota) -> int:
        return sum(s["quantidade"] for s in self.shows_quartos_pendentes(garota))

    def valores_show(self) -> list[int]:
        """As tarifas de show escolhíveis no acerto, em centavos e em ordem ("50;60" -> [5000, 6000])."""
        valores = []
        for parte in re.split(r"[;/\s]+", self.banco.cfg("show_valores", "50;60") or ""):
            try:
                cent = fmt.para_centavos(parte) if parte.strip() else 0
            except ValueError:
                continue
            if cent > 0 and cent not in valores:
                valores.append(cent)
        return sorted(valores) or list(SHOW_VALORES_PADRAO)

    @staticmethod
    def validar_quantidade_shows(quantidade) -> int:
        """Valida a contagem independentemente da tarifa, inclusive antes de escolhê-la."""
        try:
            qtd = int(str(quantidade).strip() or 0)
        except (TypeError, ValueError):
            raise ErroNegocio("Quantidade de shows inválida: digite só números.") from None
        if qtd < 0 or qtd > SHOWS_MAXIMO:
            raise ErroNegocio(f"A quantidade de shows vai de 0 a {SHOWS_MAXIMO}.")
        return qtd

    @staticmethod
    def validar_shows(quantidade, valor_cent) -> tuple[int, int]:
        """(quantidade, valor de cada show em centavos) já conferidos; sem shows devolve (0, 0)."""
        qtd = ComissaoController.validar_quantidade_shows(quantidade)
        if qtd == 0:
            return 0, 0
        valor_cent = int(valor_cent or 0)
        if valor_cent <= 0:
            raise ErroNegocio("Escolha o valor do show.")
        return qtd, valor_cent

    # --------------------------------------------------------------- cadastro de garotas
    @staticmethod
    def validar_numero(numero) -> int:
        try:
            n = int(str(numero).strip())
        except (TypeError, ValueError):
            raise ErroNegocio("Digite o número da garota (somente números).") from None
        if not 1 <= n <= NUMERO_MAXIMO:
            raise ErroNegocio(f"O número da garota vai de 1 a {NUMERO_MAXIMO}.")
        return n

    def garota(self, numero) -> dict | None:
        r = self.banco.um("SELECT * FROM garotas WHERE numero = ?", (int(numero),))
        return dict(r) if r else None

    def nome(self, numero) -> str:
        """Nome da garota cadastrada com esse número ('' se não houver cadastro)."""
        try:
            g = self.garota(numero)
        except (TypeError, ValueError):
            return ""
        return (g["nome"] if g else "") or ""

    def cadastro_vazio(self) -> bool:
        return self.banco.valor("SELECT 1 FROM garotas LIMIT 1") is None

    # --------------------------------------------------------------- lançar e consultar
    def lancar(self, garota, valor_cent: int, turno_id: int | None, operador_id: int | None, observacao: str = "") -> int:
        """Marca a comissão no número da garota. Devolve o id do lançamento."""
        n = self.validar_numero(garota)
        valor_cent = int(valor_cent)
        if valor_cent <= 0:
            raise ErroNegocio("Informe o valor da comissão (maior que zero).")
        if turno_id is None or TurnoController(self.banco).obter(turno_id)["status"] != "aberto":
            raise ErroNegocio("Abra o turno do caixa antes de lançar comissão.")
        cid = self.banco.inserir("comissoes_garotas", {
            "garota": n, "valor_cent": valor_cent, "turno_id": turno_id, "operador_id": operador_id,
            "observacao": (observacao or "").strip() or None, "criado_em": fmt.agora(), "status": "pendente"})
        self.banco.log("comissao_lancada", f"garota {n} {fmt.fmt_brl(valor_cent)}", operador_id)
        return cid

    def pendente(self, garota) -> int:
        """Quanto falta pagar a essa garota, em centavos."""
        return self.banco.valor(
            "SELECT COALESCE(SUM(valor_cent), 0) FROM comissoes_garotas WHERE garota = ? AND status = 'pendente'",
            (self.validar_numero(garota),), 0)

    def total_a_pagar(self) -> int:
        """Tudo o que está pendente, de todas as garotas e de todos os turnos, em centavos."""
        return self.banco.valor("SELECT COALESCE(SUM(valor_cent), 0) FROM comissoes_garotas WHERE status = 'pendente'", (), 0)

    def pendentes_por_garota(self) -> list[dict]:
        """Uma linha por garota com comissão a pagar: número, nome, nº de lançamentos, total e o mais antigo."""
        linhas = [dict(r) for r in self.banco.todos(
            """SELECT c.garota, COALESCE(g.nome, '') AS nome, COUNT(*) AS lancamentos, SUM(c.valor_cent) AS total_cent,
                      MIN(c.criado_em) AS desde
               FROM comissoes_garotas c LEFT JOIN garotas g ON g.numero = c.garota
               WHERE c.status = 'pendente' GROUP BY c.garota ORDER BY c.garota""")]
        por_numero = {p["garota"]: p for p in linhas}
        for s in self.banco.todos(
                "SELECT s.garota, COALESCE(g.nome, '') AS nome, SUM(s.quantidade) AS shows, MIN(s.criado_em) AS desde "
                "FROM shows_quartos s LEFT JOIN garotas g ON g.numero = s.garota "
                "WHERE s.acerto_id IS NULL GROUP BY s.garota"):
            p = por_numero.setdefault(s["garota"], dict(garota=s["garota"], nome=s["nome"],
                                                      lancamentos=0, total_cent=0, desde=s["desde"]))
            p["shows_quartos"] = s["shows"]
        return [por_numero[n] for n in sorted(por_numero)]

    def lancamentos(self, garota, status: str | None = "pendente") -> list[dict]:
        sql = ("""SELECT c.*, o.nome AS operador, t.numero AS turno FROM comissoes_garotas c
                  LEFT JOIN operadores o ON o.id = c.operador_id LEFT JOIN turnos t ON t.id = c.turno_id
                  WHERE c.garota = ?""")
        params: list = [self.validar_numero(garota)]
        if status:
            sql += " AND c.status = ?"
            params.append(status)
        return [dict(r) for r in self.banco.todos(sql + " ORDER BY c.id", params)]

    def lancamento(self, comissao_id: int) -> dict | None:
        r = self.banco.um("SELECT * FROM comissoes_garotas WHERE id = ?", (comissao_id,))
        return dict(r) if r else None

    def marcadas(self, garota, turno_id: int | None = None) -> list[dict]:
        """O que aparece quando se abre a comanda da garota: tudo o que está pendente (de qualquer turno) e o que foi pago neste
        turno, para quem pergunta "já paguei?". Os cancelados não aparecem."""
        n = self.validar_numero(garota)
        pago_no_turno = "OR (c.status = 'paga' AND c.pago_turno_id = ?)" if turno_id else ""
        params: list = [n] + ([turno_id] if turno_id else [])
        return [dict(r) for r in self.banco.todos(
            f"""SELECT c.*, o.nome AS operador FROM comissoes_garotas c LEFT JOIN operadores o ON o.id = c.operador_id
                WHERE c.garota = ? AND (c.status = 'pendente' {pago_no_turno}) ORDER BY c.id""", params)]

    def resumo_turno(self, turno_id: int) -> dict:
        """O que foi lançado no turno (sem os cancelados): quantidade, total e o total de cada garota."""
        linhas = [dict(r) for r in self.banco.todos(
            """SELECT c.garota, COALESCE(g.nome, '') AS nome, COUNT(*) AS lancamentos, SUM(c.valor_cent) AS total_cent
               FROM comissoes_garotas c LEFT JOIN garotas g ON g.numero = c.garota
               WHERE c.turno_id = ? AND c.status <> 'cancelada' GROUP BY c.garota ORDER BY c.garota""", (turno_id,))]
        return {"quantidade": sum(l["lancamentos"] for l in linhas), "total_cent": sum(l["total_cent"] for l in linhas),
                "por_garota": linhas}

    # --------------------------------------------------------------- cancelar e pagar
    def cancelar(self, comissao_id: int, operador_id: int | None, motivo: str = "") -> None:
        """Cancela um lançamento ainda pendente (digitado errado). Fica guardado, com quem cancelou e quando."""
        c = self.banco.um("SELECT garota, valor_cent FROM comissoes_garotas WHERE id = ?", (comissao_id,))
        n = self.banco.executar(
            "UPDATE comissoes_garotas SET status = 'cancelada', cancelada_em = ?, cancelada_por = ?, "
            "motivo_cancelamento = ? WHERE id = ? AND status = 'pendente'",
            (fmt.agora(), operador_id, (motivo or "").strip() or None, comissao_id)).rowcount
        if not n:
            raise ErroNegocio("Só é possível cancelar comissão pendente: esta já foi paga ou cancelada.")
        self.banco.log("comissao_cancelada", f"garota {c['garota']} {fmt.fmt_brl(c['valor_cent'])} {motivo}".strip(), operador_id)

    def pagar(self, garota, turno_id: int | None, operador_id: int | None, tirar_do_caixa: bool = True,
              shows: int = 0, valor_show_cent: int = 0, pix_cent: int = 0, vale_cent: int = 0,
              permitir_zerado: bool = False, nome: str | None = None,
              shows_quartos_ids: list[int] | None = None, consumos_ids: list[int] | None = None) -> dict:
        """Acerta a garota: paga TUDO que está pendente e, se o operador lançou, os shows (`shows` x `valor_show_cent`). Com
        `tirar_do_caixa` registra a saída do dinheiro no turno (uma sangria 'Comissão garota 180 NOME'), então a conferência da
        gaveta já conta com ela. Só shows, sem comissão pendente, também é um acerto válido. Devolve o resumo do pagamento:
        `comissao_cent` (o marcado), `shows_cent` e `total_cent` (o que ela recebe, comissão + shows).

        `pix_cent` é a parte do total paga por Pix (sem dinheiro no caixa, ou só parte dele): o Pix nunca passa pela gaveta, então
        só o restante em dinheiro (`dinheiro_cent`) vira sangria. Sem `tirar_do_caixa` o dinheiro é só registrado, como antes.

        `vale_cent` é o vale que a garota já pegou antes (o dinheiro já saiu do caixa): é descontado do total do acerto, então só
        `total - vale` é pago agora, em dinheiro ou em Pix. O vale não sai do caixa de novo. `pix_cent` é a parte do que sobra
        (total - vale) paga por Pix; o resto é dinheiro (e a sangria). O vale não pode passar do total.

        `permitir_zerado` deixa fechar a conta da garota que não tem comissão pendente nem shows (acerto de R$ 0,00, só para
        registrar o fechamento e dar o recibo). Só a tela passa True, depois de o operador confirmar; sem ele, chamar de novo
        com a conta já acertada continua sendo recusado, então um clique repetido não grava um segundo acerto.

        Os drinks dela ainda não descontados (`consumos_garotas`) entram sozinhos: saem do que ela recebe. Se os drinks e o vale
        passam do total, ela paga a diferença ao caixa (`recebido_cent`; com `tirar_do_caixa`, uma entrada no turno) e nada é
        pago a ela. `consumos_ids` é o que a tela mostrou: se mudou no meio, o acerto é recusado.

        `nome` é o nome que o operador digitou no acerto: fica gravado só neste acerto e sai no recibo (o cadastro não muda,
        porque o número da comanda pode ser de outra garota em outra noite). Vazio: o nome do cadastro, se houver."""
        n = self.validar_numero(garota)
        shows, valor_show_cent = self.validar_shows(shows, valor_show_cent)
        pix_cent = int(pix_cent or 0)
        vale_cent = int(vale_cent or 0)
        if pix_cent < 0:
            raise ErroNegocio("O valor pago por Pix não pode ser negativo.")
        if vale_cent < 0:
            raise ErroNegocio("O vale não pode ser negativo.")
        with self.banco.transacao():
            automaticos = self.shows_quartos_pendentes(n)
            ids = [s["id"] for s in automaticos]
            if shows_quartos_ids is not None and ids != list(shows_quartos_ids):
                raise ErroNegocio("Os shows dos quartos mudaram. Reabra o acerto e confira novamente.")
            if shows < sum(s["quantidade"] for s in automaticos):
                raise ErroNegocio("O total de shows não pode ser menor que os shows automáticos dos quartos.")
            itens = self.lancamentos(n, "pendente")
            consumos = self.consumos_pendentes(n)
            if consumos_ids is not None and [c["id"] for c in consumos] != list(consumos_ids):
                raise ErroNegocio("O consumo da garota mudou. Reabra o acerto e confira novamente.")
            if not itens and not shows and not consumos and not permitir_zerado:
                raise ErroNegocio(f"A garota {n} não tem comissão pendente.")
            comissao = sum(i["valor_cent"] for i in itens)
            consumo = sum(c["valor_cent"] for c in consumos)
            shows_cent = shows * valor_show_cent
            total = comissao + shows_cent
            if vale_cent > total:
                raise ErroNegocio(f"O vale ({fmt.fmt_brl(vale_cent)}) não pode ser maior que o total do acerto ({fmt.fmt_brl(total)}).")
            # o vale já saiu do caixa quando ela o pegou; os drinks ela já bebeu: só o que sobra é pago agora
            a_pagar = total - vale_cent - consumo
            recebido = max(0, -a_pagar)                   # drinks além do que ela tem a receber: ela paga a diferença
            a_pagar = max(0, a_pagar)
            if pix_cent > a_pagar:
                raise ErroNegocio(f"O Pix ({fmt.fmt_brl(pix_cent)}) não pode ser maior que o total a pagar ({fmt.fmt_brl(a_pagar)}).")
            dinheiro = a_pagar - pix_cent
            nome = " ".join((nome or "").split())[:60] or self.nome(n)
            movimento, descricao = None, ""
            quem = f"garota {n}{' ' + nome if nome else ''}"
            if tirar_do_caixa and (dinheiro > 0 or recebido > 0):
                if turno_id is None:
                    raise ErroNegocio("Abra o turno do caixa para pagar com o dinheiro do caixa.")
                if recebido:
                    descricao = f"Consumo {quem}: ela pagou a diferença ({fmt.fmt_brl(consumo)} em bebidas)"
                    movimento = TurnoController(self.banco).movimentar(turno_id, operador_id, "entrada", recebido, descricao)
                else:
                    rotulo = "Acerto" if shows else "Comissão"
                    parte_pix = f" (resto no Pix: {fmt.fmt_brl(pix_cent)})" if pix_cent else ""
                    parte_vale = f" (vale descontado: {fmt.fmt_brl(vale_cent)})" if vale_cent else ""
                    parte_drinks = f" (consumo descontado: {fmt.fmt_brl(consumo)})" if consumo else ""
                    descricao = f"{rotulo} {quem}{parte_pix}{parte_vale}{parte_drinks}"
                    movimento = TurnoController(self.banco).movimentar(turno_id, operador_id, "saida", dinheiro, descricao)
            tirou = movimento is not None and not recebido
            agora = fmt.agora()
            self.banco.executar(
                "UPDATE comissoes_garotas SET status = 'paga', paga_em = ?, pago_por = ?, pago_turno_id = ?, movimento_id = ? "
                "WHERE garota = ? AND status = 'pendente'", (agora, operador_id, turno_id, movimento, n))
            acerto = self.banco.inserir("acertos_garotas", {
                "garota": n, "turno_id": turno_id, "operador_id": operador_id, "criado_em": agora, "comissao_cent": comissao,
                "shows_qtd": shows, "show_valor_cent": valor_show_cent, "shows_cent": shows_cent, "total_cent": total,
                "movimento_id": movimento, "tirou_do_caixa": int(tirou), "pix_cent": pix_cent, "vale_cent": vale_cent, "nome": nome or None,
                "consumo_cent": consumo})
            self.banco.executar(
                "UPDATE consumos_garotas SET status = 'descontado', acerto_id = ?, descontado_em = ?, descontado_turno_id = ? "
                "WHERE garota = ? AND status = 'pendente'", (acerto, agora, turno_id, n))
            for show_id in ids:
                self.banco.executar("UPDATE shows_quartos SET acerto_id = ? WHERE id = ? AND acerto_id IS NULL",
                                    (acerto, show_id))
            self.banco.log("comissao_paga", f"garota {n} {fmt.fmt_brl(total)} ({len(itens)} lançamentos"
                           + (f", {shows} shows de {fmt.fmt_brl(valor_show_cent)}" if shows else "") + ")"
                           + (f" Pix {fmt.fmt_brl(pix_cent)}" if pix_cent else "")
                           + (f" vale descontado {fmt.fmt_brl(vale_cent)}" if vale_cent else "")
                           + (f" consumo descontado {fmt.fmt_brl(consumo)}" if consumo else "")
                           + (f" ela pagou {fmt.fmt_brl(recebido)}" if recebido else "")
                           + ("" if tirar_do_caixa or dinheiro == 0 else " fora do caixa"), operador_id)
        return {"garota": n, "nome": nome, "total_cent": total, "comissao_cent": comissao, "quantidade": len(itens),
                "shows_quartos": sum(s["quantidade"] for s in automaticos),
                "shows_manuais": shows - sum(s["quantidade"] for s in automaticos),
                "shows": shows, "valor_show_cent": valor_show_cent, "shows_cent": shows_cent, "acerto_id": acerto,
                "pix_cent": pix_cent, "vale_cent": vale_cent, "dinheiro_cent": dinheiro, "movimento_id": movimento, "movimento_descricao": descricao,
                "consumo_cent": consumo, "consumos": consumos, "recebido_cent": recebido,
                "recebeu_no_caixa": bool(recebido and movimento is not None),
                "lancamentos": itens, "pago_em": agora, "tirou_do_caixa": tirou}

    def pix_do_turno(self, turno_id: int) -> int:
        """Quanto das contas das garotas foi pago por Pix neste turno (não passa pela gaveta; aparece no fechamento)."""
        return self.banco.valor("SELECT COALESCE(SUM(pix_cent), 0) FROM acertos_garotas WHERE turno_id = ?", (turno_id,), 0)

    def shows_do_turno(self, turno_id: int) -> dict:
        """Shows pagos nas contas das garotas neste turno: quantidade, total e o de cada garota (para o fechamento)."""
        linhas = [dict(r) for r in self.banco.todos(
            """SELECT a.garota, COALESCE(MAX(a.nome), g.nome, '') AS nome, SUM(a.shows_qtd) AS shows, SUM(a.shows_cent) AS total_cent
               FROM acertos_garotas a LEFT JOIN garotas g ON g.numero = a.garota
               WHERE a.turno_id = ? AND a.shows_qtd > 0 GROUP BY a.garota ORDER BY a.garota""", (turno_id,))]
        return {"quantidade": sum(l["shows"] for l in linhas), "total_cent": sum(l["total_cent"] for l in linhas),
                "por_garota": linhas}


def entregar_via(ctx, lancamento_id: int) -> str:
    """Imprime a via que a garota leva a cada comissão lançada (config 'imprimir_via_comissao'). Devolve a frase para o status
    da tela. Sem impressora (modo tela) a via só fica gravada no histórico: abrir uma janela a cada lançamento travaria o caixa."""
    if not ctx.banco.cfg_bool("imprimir_via_comissao", True):
        return ""
    try:
        ctx.impressao.imprimir_via_comissao(lancamento_id, ctx.operador.nome)
    except Exception as e:  # noqa: BLE001 - a comissão já está gravada: falha de impressão nunca pode parecer falha do lançamento
        ctx.banco.log("via_comissao_falhou", f"lançamento {lancamento_id}: {e}"[:300], ctx.operador_id)
        return f" ATENÇÃO: a via da garota não foi impressa ({e})."
    if ctx.impressao.deve_mostrar_na_tela():
        return " Sem impressora configurada: a via ficou só no histórico."
    return " Via da garota enviada para a impressora."
