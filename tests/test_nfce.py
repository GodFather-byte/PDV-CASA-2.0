"""NFC-e (Will Fiscal): montagem da nota, fila, respostas do provedor, cancelamento e cupom impresso."""
from __future__ import annotations

import base64
import unittest
from datetime import datetime
from types import SimpleNamespace

from src.controllers.fiscal_controller import FiscalController
from src.fiscal import danfe, nfce
from src.fiscal.focus import Focus, Resposta
from tests.test_caixa import BaseCaixa

CHAVE = "35261112345678000195650010000000011000000019"


class TransmissorFalso:
    def __init__(self, respostas=None):
        self.respostas = list(respostas or [])
        self.chamadas = []

    def _proxima(self, padrao):
        return self.respostas.pop(0) if self.respostas else padrao

    def emitir(self, ref, dados):
        self.chamadas.append(("emitir", ref, dados))
        return self._proxima(autorizada(ref))

    def consultar(self, ref):
        self.chamadas.append(("consultar", ref, None))
        return self._proxima(autorizada(ref))

    def cancelar(self, ref, justificativa):
        self.chamadas.append(("cancelar", ref, justificativa))
        return self._proxima(Resposta("cancelada", "Evento registrado e vinculado a NF-e", 200,
                                      {"status": "cancelado", "status_sefaz": "135"}))


def autorizada(ref="x"):
    return Resposta("autorizada", "Autorizado o uso da NF-e", 201, {
        "status": "autorizado", "status_sefaz": "100", "chave_nfe": "NFe" + CHAVE, "numero": "1", "serie": "1",
        "qrcode_url": "https://www.homologacao.nfce.fazenda.sp.gov.br/qrcode?p=" + CHAVE + "|2|2|1|ABC",
        "url_consulta_nf": "https://www.homologacao.nfce.fazenda.sp.gov.br/consulta",
        "caminho_xml_nota_fiscal": "/arquivos/x.xml", "caminho_danfe": "/notas_fiscais_consumidor/x.html"})


class BaseNfce(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.executar("UPDATE loja SET razao_social = 'EMPORIO TESTE LTDA', cnpj = '12.345.678/0001-95', "
                            "ie = '123456789012', endereco = 'Rua A, 10', cidade = 'São Paulo', uf = 'SP' WHERE id = 1")
        self.banco.executar("UPDATE produtos SET ncm = '22030000'")
        self.banco.cfg_set("nfce_token_homologacao", "token-de-teste")
        self.fiscal = FiscalController(self.banco, TransmissorFalso())
        self.fiscal.ligar("homologacao")

    def fechar(self, *itens, pagamentos=None):
        vid = self.vender(*itens)
        total = self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (vid,))
        for forma, valor in (pagamentos or [("Dinheiro", total)]):
            self.pagar(vid, forma, valor)
        self.caixa.fechar(vid)
        return vid

    def nota(self, vid):
        return dict(self.banco.um("SELECT * FROM nfce_notas WHERE venda_id = ?", (vid,)))


class TesteMontagem(BaseNfce):
    def test_itens_pagamentos_e_homologacao(self):
        vid = self.fechar((self.skol, 3), (self.agua, 1), pagamentos=[("Pix", 1000), ("Dinheiro", 2000)])
        dados = nfce.montar(self.banco, vid, "homologacao", agora=datetime(2026, 11, 12, 18, 0))
        self.assertEqual(dados["cnpj_emitente"], "12345678000195")
        self.assertEqual(len(dados["items"]), 2)
        primeiro, segundo = dados["items"]
        self.assertEqual(primeiro["descricao"], nfce.DESCRICAO_HOMOLOGACAO)   # exigência da SEFAZ em homologação
        self.assertEqual(segundo["descricao"], "AGUA")
        self.assertEqual((primeiro["valor_bruto"], primeiro["quantidade_comercial"], primeiro["codigo_ncm"]),
                         ("24.00", "3", "22030000"))
        self.assertEqual((primeiro["cfop"], primeiro["icms_situacao_tributaria"], primeiro["pis_situacao_tributaria"]),
                         ("5102", "102", "49"))
        self.assertNotIn("ibs_cbs_situacao_tributaria", primeiro)               # Simples: só se ligar
        # 30,00 pagos com 27,50 de conta: o dinheiro entra pelo líquido (pago - troco)
        self.assertEqual(dados["formas_pagamento"], [{"forma_pagamento": "17", "valor_pagamento": "10.00"},
                                                     {"forma_pagamento": "01", "valor_pagamento": "17.50"}])
        self.assertEqual(nfce.montar(self.banco, vid, "producao")["items"][0]["descricao"], "SKOL")

    def test_desconto_e_taxa_rateados_batem_com_o_total(self):
        self.banco.cfg_set("usar_desconto", "S")
        vid = self.vender((self.skol, 1), (self.agua, 1), (self.agua, 1))
        self.caixa.definir_desconto(vid, valor_cent=100)
        total = self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (vid,))
        self.pagar(vid, "Dinheiro", total)
        self.caixa.fechar(vid)
        # acréscimo (taxa) entra como "outras despesas"; o pagamento cobre o total novo
        self.banco.executar("UPDATE vendas SET acrescimo_cent = 77, total_cent = total_cent + 77 WHERE id = ?", (vid,))
        self.banco.executar("UPDATE pagamentos_venda SET valor_cent = valor_cent + 77 WHERE venda_id = ?", (vid,))
        dados = nfce.montar(self.banco, vid, "producao")
        centavos = lambda campo: sum(int(round(float(i.get(campo, "0")) * 100)) for i in dados["items"])
        self.assertEqual(centavos("valor_bruto") - centavos("valor_desconto") + centavos("valor_outras_despesas"),
                         self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (vid,)))
        self.assertEqual((centavos("valor_desconto"), centavos("valor_outras_despesas")), (100, 77))

    def test_ratear(self):
        self.assertEqual(nfce.ratear(100, [800, 350, 350]), [54, 23, 23])
        self.assertEqual(sum(nfce.ratear(7, [1, 1, 1])), 7)
        self.assertEqual(nfce.ratear(0, [5, 5]), [0, 0])

    def test_dados_do_produto_tem_prioridade_sobre_o_padrao(self):
        self.banco.executar("UPDATE produtos SET cfop = '5405', situacao_tributaria = '500', cest = '03.002.00', "
                            "origem_mercadoria = '2', ibscbs_cst = '200', ibscbs_class = '200001' WHERE id = ?",
                            (self.skol,))
        self.banco.cfg_set("nfce_ibscbs_enviar", "S")
        vid = self.fechar((self.skol, 1), (self.agua, 1))
        skol, agua = nfce.montar(self.banco, vid, "producao")["items"]
        self.assertEqual((skol["cfop"], skol["icms_situacao_tributaria"], skol["cest"], skol["icms_origem"]),
                         ("5405", "500", "0300200", "2"))
        self.assertEqual((skol["ibs_cbs_situacao_tributaria"], skol["ibs_cbs_classificacao_tributaria"]), ("200", "200001"))
        self.assertEqual((agua["ibs_cbs_situacao_tributaria"], agua["ibs_cbs_classificacao_tributaria"]), ("000", "000001"))

    def test_o_que_impede_a_emissao(self):
        vid = self.fechar((self.skol, 1))
        self.banco.executar("UPDATE produtos SET ncm = '' WHERE id = ?", (self.skol,))
        with self.assertRaisesRegex(nfce.ErroFiscal, "sem NCM"):
            nfce.montar(self.banco, vid, "producao")
        self.banco.executar("UPDATE produtos SET ncm = '22030000'")
        with self.assertRaisesRegex(nfce.ErroFiscal, "CPF"):
            nfce.montar(self.banco, vid, "producao", cpf="111.111.111-11")
        self.assertEqual(nfce.montar(self.banco, vid, "producao", cpf="529.982.247-25")["cpf_destinatario"], "52998224725")
        self.banco.executar("UPDATE loja SET cnpj = '' WHERE id = 1")
        with self.assertRaisesRegex(nfce.ErroFiscal, "CNPJ"):
            nfce.montar(self.banco, vid, "producao")

    def test_forma_fiscal_pelo_cadastro_ou_pelo_nome(self):
        self.assertEqual(nfce.forma_fiscal("Cartão Crédito"), "03")
        self.assertEqual(nfce.forma_fiscal("Cartão Débito"), "04")
        self.assertEqual(nfce.forma_fiscal("Pix"), "17")
        self.assertEqual(nfce.forma_fiscal("Vale Refeição"), "11")
        self.assertEqual(nfce.forma_fiscal("Caderneta"), "05")
        self.assertEqual(nfce.forma_fiscal("Cortesia"), "99")
        self.assertEqual(nfce.forma_fiscal("Pix", "20"), "20")


class TesteFila(BaseNfce):
    def test_so_vendas_depois_de_ligar_entram_e_saem_autorizadas_com_cupom(self):
        self.banco.cfg_set("nfce_emissao", "desligada")
        antes = self.fechar((self.agua, 1))
        self.avancar(minutes=5)
        self.fiscal.ligar("homologacao")
        vid = self.fechar((self.skol, 1))
        r = self.fiscal.processar()
        self.assertEqual((r["novas"], r["enviadas"]), (1, 1))
        self.assertIsNone(self.banco.um("SELECT id FROM nfce_notas WHERE venda_id = ?", (antes,)))
        nota = self.nota(vid)
        self.assertEqual((nota["situacao"], nota["chave"], nota["numero"]), ("autorizada", "NFe" + CHAVE, "1"))
        self.assertEqual(nota["ref"], self.banco.valor("SELECT uuid FROM vendas WHERE id = ?", (vid,)))
        cupom = self.banco.um("SELECT dados, tipo FROM fila_impressao WHERE venda_id = ? AND tipo = 'nfce'", (vid,))
        self.assertIsNotNone(cupom)
        self.assertIn(b"\x1d(k", cupom["dados"])                                   # QR Code
        self.assertEqual(self.fiscal.processar()["enviadas"], 0)                   # não envia de novo

    def test_desligada_nao_faz_nada(self):
        self.banco.cfg_set("nfce_emissao", "desligada")
        self.fechar((self.skol, 1))
        self.assertEqual(self.fiscal.processar(), {"novas": 0, "enviadas": 0, "canceladas": 0})
        self.assertEqual(self.fiscal._transmissor.chamadas, [])

    def test_rede_fora_tenta_de_novo_depois(self):
        self.fiscal._transmissor.respostas = [Resposta(None, "Sem conexão com o provedor fiscal.")]
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        nota = self.nota(vid)
        self.assertEqual((nota["situacao"], nota["tentativas"]), ("pendente", 1))
        self.assertEqual(self.fiscal.processar()["enviadas"], 0)                    # espera antes de tentar de novo
        self.avancar(minutes=2)
        self.fiscal.processar()
        self.assertEqual(self.nota(vid)["situacao"], "autorizada")

    def test_rejeitada_mostra_o_motivo_e_reenvia_depois_de_corrigir(self):
        self.fiscal._transmissor.respostas = [Resposta("rejeitada", "Rejeição: NCM inexistente", 201,
                                                       {"status": "erro_autorizacao", "status_sefaz": "778"})]
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        nota = self.nota(vid)
        self.assertEqual((nota["situacao"], nota["mensagem"], nota["status_sefaz"]),
                         ("rejeitada", "Rejeição: NCM inexistente", "778"))
        self.assertEqual(self.fiscal.reenviar(nota["id"]), "autorizada")

    def test_cadastro_incompleto_vira_erro_sem_chamar_o_provedor(self):
        self.banco.executar("UPDATE produtos SET ncm = NULL WHERE id = ?", (self.skol,))
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        self.assertEqual(self.nota(vid)["situacao"], "erro")
        self.assertIn("NCM", self.nota(vid)["mensagem"])
        self.assertEqual(self.fiscal._transmissor.chamadas, [])

    def test_referencia_ja_usada_consulta_em_vez_de_duplicar(self):
        self.fiscal._transmissor.respostas = [Resposta("erro", "Referência já utilizada", 422, {},
                                                       referencia_em_uso=True)]
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        self.assertEqual([c[0] for c in self.fiscal._transmissor.chamadas], ["emitir", "consultar"])
        self.assertEqual(self.nota(vid)["situacao"], "autorizada")

    def test_processando_consulta_na_rodada_seguinte(self):
        self.fiscal._transmissor.respostas = [Resposta("processando", "", 201, {"status": "processando_autorizacao"})]
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        self.assertEqual(self.nota(vid)["situacao"], "processando")
        self.avancar(minutes=1)
        self.fiscal.processar()
        self.assertEqual(self.fiscal._transmissor.chamadas[-1][0], "consultar")
        self.assertEqual(self.nota(vid)["situacao"], "autorizada")


class TesteCancelamento(BaseNfce):
    def test_gerente_cancela_com_motivo(self):
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        nota = self.nota(vid)
        with self.assertRaisesRegex(Exception, "15 a 255"):
            self.fiscal.cancelar(nota["id"], "errei")
        self.assertEqual(self.fiscal.cancelar(nota["id"], "Cliente desistiu da compra"), "cancelada")
        self.assertEqual(self.nota(vid)["situacao"], "cancelada")
        with self.assertRaisesRegex(Exception, "autorizada"):
            self.fiscal.cancelar(nota["id"], "Cliente desistiu da compra")

    def test_fora_do_prazo_nao_cancela(self):
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        self.avancar(minutes=45)
        with self.assertRaisesRegex(Exception, "30 minutos"):
            self.fiscal.cancelar(self.nota(vid)["id"], "Cliente desistiu da compra")

    def test_venda_cancelada_no_caixa_cancela_a_nota_sozinha(self):
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        self.caixa.cancelar_venda(vid, "Cliente desistiu")
        self.assertEqual(self.fiscal.processar()["canceladas"], 1)
        nota = self.nota(vid)
        self.assertEqual((nota["situacao"], nota["justificativa"]), ("cancelada", "Venda cancelada no caixa da loja"))
        self.assertEqual(self.fiscal._transmissor.chamadas[-1][0], "cancelar")


class TesteCupom(BaseNfce):
    def test_cupom_fiscal_tem_o_que_a_sefaz_pede(self):
        vid = self.fechar((self.skol, 2), pagamentos=[("Dinheiro", 2000)])
        self.fiscal.processar()
        antes, depois = danfe.texto(self.banco, self.nota(vid), largura=48)
        for trecho in ("EMPORIO TESTE LTDA", "DANFE NFC-e", "HOMOLOGAÇÃO", "SKOL", "VALOR A PAGAR R$",
                       "Dinheiro", "Troco R$", "Consulte pela Chave de Acesso",
                       "3526 1112 3456 7800", "0000 0019", "CONSUMIDOR NÃO IDENTIFICADO",
                       "NFC-e nº 1"):
            self.assertIn(trecho, antes)
        self.assertTrue(all(len(l) <= 48 for l in antes.splitlines()))

    def test_qr_code_escpos(self):
        dados = danfe.qrcode("https://x/qrcode?p=123")
        self.assertIn(b"https://x/qrcode?p=123", dados)
        self.assertTrue(dados.startswith(b"\x1ba\x01"))


class TesteFocus(unittest.TestCase):
    def http(self, codigo, corpo):
        chamadas = []

        def chamar(url, **kw):
            chamadas.append((url, kw))
            return SimpleNamespace(status_code=codigo, json=lambda: corpo)
        return SimpleNamespace(post=chamar, get=chamar, delete=chamar), chamadas

    def test_autenticacao_e_endereco(self):
        http, chamadas = self.http(201, {"status": "autorizado", "chave_nfe": "NFe1"})
        r = Focus("TOKEN123", "homologacao", http).emitir("venda-1", {"a": 1})
        url, kw = chamadas[0]
        self.assertEqual(url, "https://homologacao.focusnfe.com.br/v2/nfce")
        self.assertEqual(kw["params"]["ref"], "venda-1")
        self.assertEqual(kw["headers"]["Authorization"], "Basic " + base64.b64encode(b"TOKEN123:").decode())
        self.assertEqual(r.situacao, "autorizada")
        Focus("T", "producao", http).cancelar("venda-1", "motivo longo o bastante")
        self.assertEqual(chamadas[-1][0], "https://api.focusnfe.com.br/v2/nfce/venda-1")
        self.assertEqual(chamadas[-1][1]["json"], {"justificativa": "motivo longo o bastante"})

    def test_traducao_das_respostas(self):
        casos = [(201, {"status": "erro_autorizacao", "mensagem_sefaz": "Rejeição: X"}, "rejeitada"),
                 (200, {"status": "cancelado"}, "cancelada"),
                 (201, {"status": "processando_autorizacao"}, "processando"),
                 (503, {}, None), (422, {"codigo": "empresa_nao_configurada", "mensagem": "Empresa não configurada"}, "erro")]
        for codigo, corpo, esperado in casos:
            http, _ = self.http(codigo, corpo)
            self.assertEqual(Focus("T", "producao", http).emitir("r", {}).situacao, esperado, corpo)
        http, _ = self.http(422, {"mensagem": "Referência já utilizada"})
        self.assertTrue(Focus("T", "producao", http).emitir("r", {}).referencia_em_uso)

    def test_sem_rede(self):
        def quebra(*a, **k):
            raise OSError("sem rede")
        r = Focus("T", "producao", SimpleNamespace(post=quebra)).emitir("r", {})
        self.assertIsNone(r.situacao)

    def test_sem_token(self):
        with self.assertRaisesRegex(ValueError, "token"):
            Focus("", "producao", object())


if __name__ == "__main__":
    unittest.main()
