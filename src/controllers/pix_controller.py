"""Pix integrado no caixa: QR Code com o valor exato e baixa só quando o banco confirma.

Vem desligado (`pix_integrado = N`); liga por loja em Configurações > Integrações, com o Access Token do Mercado Pago
da própria loja. Ligado, receber numa forma de Pix (a forma fiscal 17, ou o nome "Pix") abre o QR Code; o pagamento
só entra na venda quando o Mercado Pago diz "aprovado". Acaba com o comprovante falso mostrado no celular.

A parte de rede (`provedor()`) não toca no banco: a tela consulta o Mercado Pago numa thread e grava o resultado com
`aplicar()` na thread principal (a conexão SQLite é da thread que a abriu).
"""
from __future__ import annotations

import uuid

from src.core import formatacao as fmt
from src.controllers.caixa_controller import ABERTAS
from src.core.erros import ErroNegocio
from src.fiscal import nfce
from src.pagamentos.mercadopago_pix import Cobranca, MercadoPagoPix


class PixController:
    def __init__(self, banco, operador_id: int | None = None, provedor=None):
        self.banco = banco
        self.operador_id = operador_id
        self._provedor = provedor

    # ------------------------------------------------------------ estado
    def ligado(self) -> bool:
        return self.banco.cfg_bool("pix_integrado", False)

    def forma_e_pix(self, tipo_pagamento_id: int) -> bool:
        forma = self.banco.um("SELECT tipo, forma_fiscal FROM tipos_pagamento WHERE id = ?", (tipo_pagamento_id,))
        return forma is not None and nfce.forma_fiscal(forma["tipo"], forma["forma_fiscal"]) == "17"

    def usar_no_recebimento(self, tipo_pagamento_id: int) -> bool:
        return self.ligado() and self.forma_e_pix(tipo_pagamento_id)

    def provedor(self) -> MercadoPagoPix:
        if self._provedor is None:
            try:
                self._provedor = MercadoPagoPix(self.banco.cfg("pix_mp_token") or "")
            except ValueError as erro:
                raise ErroNegocio(str(erro)) from None
        return self._provedor

    def email_pagador(self) -> str:
        email = (self.banco.cfg("pix_email_pagador") or "").strip() or (
            self.banco.valor("SELECT email FROM loja WHERE id = 1") or "").strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ErroNegocio("O Mercado Pago exige um e-mail de pagador. Cadastre o e-mail da loja ou preencha "
                              "Configurações > Integrações > Pix integrado: e-mail.")
        return email

    def obter(self, cobranca_id: int) -> dict:
        linha = self.banco.um("SELECT * FROM pix_cobrancas WHERE id = ?", (cobranca_id,))
        if linha is None:
            raise ErroNegocio("Cobrança Pix não encontrada.")
        return dict(linha)

    # ------------------------------------------------------------ cobrança
    def iniciar(self, venda_id: int, valor_cent: int) -> dict:
        """Gera o QR Code no Mercado Pago. Devolve a cobrança com `imagem_base64` (só na memória, não é gravada)."""
        venda = self.banco.um("SELECT id, status, total_cent, cupom, uuid FROM vendas WHERE id = ?", (venda_id,))
        if venda is None or venda["status"] not in ABERTAS:
            raise ErroNegocio("A venda não está aberta.")
        if valor_cent <= 0:
            raise ErroNegocio("Informe um valor maior que zero.")
        pago = int(self.banco.valor("SELECT COALESCE(SUM(valor_cent), 0) FROM pagamentos_venda WHERE venda_id = ?",
                                    (venda_id,)) or 0)
        falta = int(venda["total_cent"]) - pago
        if valor_cent > falta:
            raise ErroNegocio(f"Pix não dá troco: o valor não pode passar do que falta ({fmt.fmt_brl(max(falta, 0))}).")
        email = self.email_pagador()
        provedor = self.provedor()
        referencia = str(uuid.uuid4())
        loja = self.banco.valor("SELECT COALESCE(NULLIF(nome_fantasia, ''), razao_social, '') FROM loja WHERE id = 1")
        descricao = f"{loja or 'Loja'} - venda {venda['uuid'] or venda_id}".strip()
        cobranca_id = self.banco.inserir("pix_cobrancas", {
            "venda_id": venda_id, "valor_cent": valor_cent, "referencia": referencia, "situacao": "pendente",
            "operador_id": self.operador_id, "criada_em": fmt.agora()})
        resposta = provedor.criar(valor_cent, descricao, referencia, email,
                                  self.banco.cfg_int("pix_expira_min", 15))
        if resposta.situacao in (None, "erro") or not resposta.copia_cola:
            mensagem = resposta.mensagem or "O Mercado Pago não devolveu o QR Code."
            self._gravar(cobranca_id, situacao="erro", mensagem=mensagem[:300], provedor_id=resposta.provedor_id or None)
            if resposta.situacao is None:
                mensagem += " Sem internet, receba o Pix pela forma comum e confira no aplicativo do banco."
            raise ErroNegocio(mensagem)
        self._gravar(cobranca_id, provedor_id=resposta.provedor_id, copia_cola=resposta.copia_cola,
                     situacao=resposta.situacao, mensagem=resposta.mensagem[:300])
        return {**self.obter(cobranca_id), "imagem_base64": resposta.imagem_base64}

    def consultar_provedor(self, provedor_id: str) -> Cobranca:
        """Só rede, sem banco: pode rodar numa thread."""
        return self.provedor().consultar(provedor_id)

    def aplicar(self, cobranca_id: int, resposta: Cobranca) -> str:
        """Grava o que o Mercado Pago respondeu. Devolve a situação atual da cobrança."""
        atual = self.obter(cobranca_id)
        if resposta.situacao is None or atual["situacao"] in ("aprovado", "cancelado", "expirado"):
            return atual["situacao"]
        campos = {"situacao": resposta.situacao if resposta.situacao != "erro" else atual["situacao"],
                  "mensagem": (resposta.mensagem or "")[:300]}
        if campos["situacao"] == "aprovado":
            campos["aprovada_em"] = fmt.agora()
        self._gravar(cobranca_id, **campos)
        return campos["situacao"]

    def verificar(self, cobranca_id: int) -> str:
        """Consulta e grava de uma vez (para quem não está numa tela com thread)."""
        atual = self.obter(cobranca_id)
        if atual["situacao"] != "pendente" or not atual["provedor_id"]:
            return atual["situacao"]
        return self.aplicar(cobranca_id, self.consultar_provedor(atual["provedor_id"]))

    def cancelar(self, cobranca_id: int) -> str:
        """Desistiu do Pix. Se o cliente pagou antes de cancelar, volta "aprovado" e o pagamento vale."""
        atual = self.obter(cobranca_id)
        if atual["situacao"] != "pendente":
            return atual["situacao"]
        if atual["provedor_id"]:
            resposta = self.provedor().cancelar(atual["provedor_id"])
            if resposta.situacao != "cancelado":
                conferido = self.consultar_provedor(atual["provedor_id"])
                if conferido.situacao == "aprovado":
                    return self.aplicar(cobranca_id, conferido)
        self._gravar(cobranca_id, situacao="cancelado", mensagem="Cancelado no caixa.")
        return "cancelado"

    def vincular(self, cobranca_id: int, pagamento_id: int) -> None:
        if self.obter(cobranca_id)["situacao"] != "aprovado":
            raise ErroNegocio("Só Pix aprovado entra na venda.")
        self._gravar(cobranca_id, pagamento_id=pagamento_id)

    def imprimir_qr(self, cobranca: dict) -> None:
        """Põe o QR Code na impressora do caixa, para quando o cliente não alcança a tela."""
        from src.controllers.fila_impressao_controller import FilaImpressao
        from src.fiscal.danfe import qrcode
        from src.hardware import impressora_termica as term
        if not cobranca.get("copia_cola"):
            raise ErroNegocio("Esta cobrança não tem QR Code.")
        texto = f"PIX\nValor: {fmt.fmt_brl(cobranca['valor_cent'])}\nAponte a câmera do aplicativo do banco:"
        dados = (term.texto_para_escpos(texto, cortar=False) + qrcode(cobranca["copia_cola"])
                 + term.texto_para_escpos("O caixa confirma sozinho quando o banco aprovar.", cortar=True))
        FilaImpressao(self.banco).enfileirar("caixa", "QR Code Pix", dados, "pix", cobranca["venda_id"])

    def aprovados_sem_pagamento(self) -> list[dict]:
        """Pix pago que não entrou em venda nenhuma (erro no meio do caminho ou pagamento removido depois)."""
        return [dict(l) for l in self.banco.todos(
            "SELECT * FROM pix_cobrancas WHERE situacao = 'aprovado' AND pagamento_id IS NULL ORDER BY id DESC")]

    def _gravar(self, cobranca_id: int, **campos) -> None:
        sets = ", ".join(f"{c} = ?" for c in campos)
        self.banco.executar(f"UPDATE pix_cobrancas SET {sets} WHERE id = ?", (*campos.values(), cobranca_id))
