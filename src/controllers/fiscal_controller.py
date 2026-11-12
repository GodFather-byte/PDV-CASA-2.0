"""Fila da NFC-e (Will Fiscal): cada venda fechada depois de ligar a emissão vira uma nota, enviada ao provedor.

Não mexe no fechamento da venda (o único fluxo de venda continua sendo o CaixaController): o serviço olha as vendas
fechadas e põe na fila. Situações da nota em `nfce_notas`:

- `pendente`: esperando envio (ou nova tentativa depois de falha de rede, com espera crescente);
- `processando`: o provedor ainda não respondeu da SEFAZ; consulta de novo;
- `autorizada`: tem chave e QR Code; o cupom fiscal vai para a fila de impressão;
- `rejeitada`: a SEFAZ recusou (o motivo fica em `mensagem`); depois de corrigir o cadastro, reenviar;
- `erro`: a venda não pôde virar nota (cadastro fiscal, pagamento) ou o provedor recusou o pedido; idem;
- `cancelada`: cancelada na SEFAZ. Venda cancelada no caixa com nota autorizada é cancelada sozinha.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.fiscal import nfce

log = logging.getLogger("pdv.fiscal")

LOTE = 10
ESPERAS_MIN = (0, 1, 2, 5, 10, 30)               # espera antes da tentativa n (depois, 30 min)
JUSTIFICATIVA_AUTOMATICA = "Venda cancelada no caixa da loja"
CANCELAR_ATE_MIN = 30


class FiscalController:
    def __init__(self, banco, transmissor=None, operador_id: int | None = None):
        self.banco = banco
        self._transmissor = transmissor
        self.operador_id = operador_id

    # ------------------------------------------------------------ estado
    def ambiente(self) -> str | None:
        valor = (self.banco.cfg("nfce_emissao") or "desligada").strip()
        return valor if valor in ("homologacao", "producao") else None

    def ligada(self) -> bool:
        return self.ambiente() is not None

    def transmissor(self):
        if self._transmissor is None:
            from src.fiscal.focus import Focus
            ambiente = self.ambiente()
            if ambiente is None:
                raise ErroNegocio("A NFC-e está desligada (Configurações > Integrações).")
            self._transmissor = Focus(self.banco.cfg(f"nfce_token_{ambiente}"), ambiente)
        return self._transmissor

    def ligar(self, ambiente: str) -> None:
        """Liga a emissão: só as vendas fechadas daqui em diante viram NFC-e. "desligada" para de emitir."""
        if ambiente == "desligada":
            self.banco.cfg_set("nfce_emissao", "desligada")
            return
        if ambiente not in ("homologacao", "producao"):
            raise ErroNegocio("Ambiente inválido.")
        if not self.banco.cfg(f"nfce_token_{ambiente}"):
            raise ErroNegocio("Falta o token da Focus NFe deste ambiente (Configurações > Integrações).")
        with self.banco.transacao():
            self.banco.cfg_set("nfce_emissao", ambiente)
            self.banco.cfg_set("nfce_ativada_em", fmt.agora())

    # ------------------------------------------------------------ fila
    def registrar_novas(self) -> int:
        """Põe na fila as vendas fechadas desde que a emissão foi ligada e que ainda não têm nota."""
        ambiente = self.ambiente()
        if ambiente is None:
            return 0
        desde = self.banco.cfg("nfce_ativada_em") or fmt.agora()
        if not self.banco.cfg("nfce_ativada_em"):
            self.banco.cfg_set("nfce_ativada_em", desde)
        novas = self.banco.todos(
            """SELECT v.id, v.uuid FROM vendas v LEFT JOIN nfce_notas n ON n.venda_id = v.id
                WHERE v.status = 'fechada' AND v.fechada_em >= ? AND v.total_cent > 0 AND n.id IS NULL
                ORDER BY v.id LIMIT 200""", (desde,))
        for venda in novas:
            self.banco.inserir("nfce_notas", {"venda_id": venda["id"], "ref": venda["uuid"], "ambiente": ambiente,
                                              "situacao": "pendente", "criada_em": fmt.agora()})
        return len(novas)

    def _gravar(self, nota_id: int, **campos) -> None:
        sets = ", ".join(f"{c} = ?" for c in campos)
        self.banco.executar(f"UPDATE nfce_notas SET {sets} WHERE id = ?", (*campos.values(), nota_id))

    def _adiar(self, nota, mensagem: str) -> None:
        tentativas = int(nota["tentativas"]) + 1
        espera = ESPERAS_MIN[min(tentativas, len(ESPERAS_MIN) - 1)]
        quando = (fmt.agora_dt() + timedelta(minutes=espera)).strftime("%Y-%m-%d %H:%M:%S")
        self._gravar(nota["id"], tentativas=tentativas, proxima_tentativa=quando, mensagem=mensagem[:300])

    def _aplicar(self, nota, resposta) -> str:
        """Grava a resposta do provedor. Devolve a situação nova."""
        dados = resposta.dados or {}
        campos = {"mensagem": (resposta.mensagem or "")[:300], "status_sefaz": str(dados.get("status_sefaz") or "")[:10],
                  "situacao": resposta.situacao}
        for coluna, chave in (("numero", "numero"), ("serie", "serie"), ("chave", "chave_nfe"),
                              ("qrcode_url", "qrcode_url"), ("url_consulta", "url_consulta_nf"),
                              ("caminho_xml", "caminho_xml_nota_fiscal"), ("caminho_danfe", "caminho_danfe")):
            if dados.get(chave):
                campos[coluna] = str(dados[chave])[:1000]
        if resposta.situacao == "autorizada" and not nota["autorizada_em"]:
            campos["autorizada_em"] = fmt.agora()
        if resposta.situacao == "cancelada" and not nota["cancelada_em"]:
            campos["cancelada_em"] = fmt.agora()
        if resposta.situacao == "processando":
            campos["proxima_tentativa"] = (fmt.agora_dt() + timedelta(seconds=20)).strftime("%Y-%m-%d %H:%M:%S")
        self._gravar(nota["id"], **campos)
        return resposta.situacao

    def emitir(self, nota_id: int) -> str:
        """Envia uma nota pendente. Devolve a situação depois da tentativa."""
        nota = self.banco.um("SELECT * FROM nfce_notas WHERE id = ?", (nota_id,))
        if nota is None:
            raise ErroNegocio("Nota não encontrada.")
        if nota["situacao"] not in ("pendente", "processando"):
            return nota["situacao"]
        transmissor = self.transmissor()
        if nota["situacao"] == "processando":
            resposta = transmissor.consultar(nota["ref"])
        else:
            try:
                dados = nfce.montar(self.banco, nota["venda_id"], nota["ambiente"], nota["cpf"])
            except nfce.ErroFiscal as erro:
                self._gravar(nota_id, situacao="erro", mensagem=str(erro)[:300])
                return "erro"
            resposta = transmissor.emitir(nota["ref"], dados)
            if resposta.referencia_em_uso:                     # já foi enviada antes (resposta perdida): consulta
                resposta = transmissor.consultar(nota["ref"])
        if resposta.situacao is None:
            self._adiar(nota, resposta.mensagem or "Sem resposta do provedor fiscal.")
            return nota["situacao"]
        situacao = self._aplicar(nota, resposta)
        if situacao == "autorizada":
            self._imprimir(nota_id)
        return situacao

    def processar(self, agora: str | None = None) -> dict:
        """Uma rodada do serviço: novas vendas, envios vencidos e cancelamentos automáticos."""
        if not self.ligada():
            return {"novas": 0, "enviadas": 0, "canceladas": 0}
        novas = self.registrar_novas()
        agora = agora or fmt.agora()
        fila = self.banco.todos(
            """SELECT id FROM nfce_notas WHERE situacao IN ('pendente','processando')
                 AND (proxima_tentativa IS NULL OR proxima_tentativa <= ?) ORDER BY id LIMIT ?""", (agora, LOTE))
        enviadas = 0
        for nota in fila:
            try:
                self.emitir(nota["id"])
                enviadas += 1
            except Exception:
                log.exception("NFC-e: falha ao enviar a nota %s.", nota["id"])
        canceladas = self._cancelar_vendas_canceladas()
        return {"novas": novas, "enviadas": enviadas, "canceladas": canceladas}

    def _cancelar_vendas_canceladas(self) -> int:
        notas = self.banco.todos(
            """SELECT n.id FROM nfce_notas n JOIN vendas v ON v.id = n.venda_id
                WHERE v.status = 'cancelada' AND n.situacao = 'autorizada' AND n.justificativa IS NULL""")
        feitas = 0
        for nota in notas:
            try:
                self.cancelar(nota["id"], JUSTIFICATIVA_AUTOMATICA, automatico=True)
                feitas += 1
            except ErroNegocio as erro:
                self._gravar(nota["id"], justificativa=JUSTIFICATIVA_AUTOMATICA, mensagem=str(erro)[:300])
        return feitas

    # ------------------------------------------------------------ ações do gerente
    def reenviar(self, nota_id: int) -> str:
        """Depois de corrigir o cadastro: volta a nota rejeitada ou com erro para a fila e envia."""
        nota = self.banco.um("SELECT * FROM nfce_notas WHERE id = ?", (nota_id,))
        if nota is None or nota["situacao"] not in ("rejeitada", "erro", "pendente"):
            raise ErroNegocio("Só nota rejeitada, com erro ou pendente pode ser reenviada.")
        self._gravar(nota_id, situacao="pendente", proxima_tentativa=None, tentativas=0)
        return self.emitir(nota_id)

    def informar_cpf(self, nota_id: int, cpf: str) -> None:
        if not nfce.cpf_valido(cpf):
            raise ErroNegocio("CPF inválido.")
        nota = self.banco.um("SELECT situacao FROM nfce_notas WHERE id = ?", (nota_id,))
        if nota is None or nota["situacao"] not in ("pendente", "rejeitada", "erro"):
            raise ErroNegocio("O CPF só entra em nota que ainda não foi autorizada.")
        self._gravar(nota_id, cpf="".join(c for c in cpf if c.isdigit()))

    def cancelar(self, nota_id: int, justificativa: str, automatico: bool = False) -> str:
        justificativa = " ".join((justificativa or "").split())
        if not 15 <= len(justificativa) <= 255:
            raise ErroNegocio("Escreva o motivo do cancelamento com 15 a 255 letras.")
        nota = self.banco.um("SELECT * FROM nfce_notas WHERE id = ?", (nota_id,))
        if nota is None or nota["situacao"] != "autorizada":
            raise ErroNegocio("Só nota autorizada pode ser cancelada.")
        if nota["autorizada_em"] and fmt.minutos_entre(nota["autorizada_em"]) > CANCELAR_ATE_MIN:
            raise ErroNegocio(f"A NFC-e só pode ser cancelada até {CANCELAR_ATE_MIN} minutos depois da autorização. "
                              "Fale com o contador.")
        resposta = self.transmissor().cancelar(nota["ref"], justificativa)
        if resposta.situacao != "cancelada":
            raise ErroNegocio("O cancelamento não foi aceito: " + (resposta.mensagem or "sem resposta do provedor"))
        self._gravar(nota_id, justificativa=justificativa)
        situacao = self._aplicar(dict(nota), resposta)
        self.banco.executar("INSERT INTO log_eventos (quando, operador_id, evento, detalhe) VALUES (?, ?, ?, ?)",
                            (fmt.agora(), self.operador_id, "nfce_cancelada",
                             f"Nota {nota['numero'] or ''} da venda {nota['venda_id']}: {justificativa}"
                             + (" (automático)" if automatico else "")))
        return situacao

    # ------------------------------------------------------------ consulta e impressão
    def notas(self, situacao: str | None = None, limite: int = 200) -> list[dict]:
        filtro, params = ("WHERE n.situacao = ?", (situacao,)) if situacao else ("", ())
        return [dict(l) for l in self.banco.todos(
            f"""SELECT n.*, v.cupom, v.total_cent, v.fechada_em FROM nfce_notas n JOIN vendas v ON v.id = n.venda_id
                {filtro} ORDER BY n.id DESC LIMIT ?""", (*params, limite))]

    def resumo(self) -> dict:
        linhas = self.banco.todos("SELECT situacao, COUNT(*) AS n FROM nfce_notas GROUP BY situacao")
        return {l["situacao"]: l["n"] for l in linhas}

    def _imprimir(self, nota_id: int, forcar: bool = False) -> bool:
        if not forcar and not self.banco.cfg_bool("nfce_imprimir", True):
            return False
        nota = self.banco.um("SELECT * FROM nfce_notas WHERE id = ?", (nota_id,))
        try:
            from src.controllers.fila_impressao_controller import FilaImpressao
            from src.fiscal import danfe
            dados = danfe.escpos(self.banco, dict(nota))
            FilaImpressao(self.banco).enfileirar("caixa", f"NFC-e {nota['numero'] or ''}", dados,
                                                           "nfce", nota["venda_id"])
        except Exception:
            log.exception("NFC-e: não consegui pôr o cupom fiscal %s na fila de impressão.", nota_id)
            return False
        self._gravar(nota_id, impressa=1)
        return True

    def reimprimir(self, nota_id: int) -> bool:
        nota = self.banco.um("SELECT situacao FROM nfce_notas WHERE id = ?", (nota_id,))
        if nota is None or nota["situacao"] != "autorizada":
            raise ErroNegocio("Só nota autorizada tem cupom fiscal para imprimir.")
        return self._imprimir(nota_id, forcar=True)
