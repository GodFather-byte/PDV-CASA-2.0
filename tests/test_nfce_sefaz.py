"""Emissão própria da NFC-e (SEFAZ-SP): chave, XML 4.00 no schema oficial, assinatura e conversa SOAP (sem rede)."""
import datetime as dt
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from src.fiscal.nfce import ErroFiscal
from src.fiscal.sefaz import assinatura, chave, cliente, qrcode, xml_nfce

XSD = Path(__file__).parent / "dados" / "xsd_nfe"
NS = xml_nfce.NS


def certificado_teste(dias=365, senha="1234") -> bytes:
    """Certificado autoassinado no formato A1 (.pfx), só para teste."""
    chave_rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LOJA TESTE LTDA:12345678000195")])
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave_rsa.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - dt.timedelta(days=1))
            .not_valid_after(agora + dt.timedelta(days=dias)).sign(chave_rsa, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(b"loja", chave_rsa, cert, None,
                                                 serialization.BestAvailableEncryption(senha.encode()))


EMIT = xml_nfce.Emitente(cnpj="12.345.678/0001-95", razao_social="LOJA TESTE LTDA", ie="123.456.789.110", crt="1",
                         logradouro="RUA DAS FLORES", numero="100", bairro="CENTRO", cod_municipio="3534401",
                         municipio="OSASCO", uf="SP", cep="06010-000", nome_fantasia="ADEGA TESTE", fone="(11) 99999-0000")
RESP = xml_nfce.ResponsavelTecnico("12345678000195", "WILLYAN", "suporte@exemplo.com", "11999990000")


def dados(**extra):
    base = {
        "cnpj_emitente": "12345678000195", "data_emissao": "2026-11-14T01:30:00-03:00",
        "natureza_operacao": "VENDA AO CONSUMIDOR", "items": [
            {"numero_item": 1, "codigo_produto": "1", "descricao": "CERVEJA SKOL LATA 350ML", "cfop": "5102",
             "codigo_ncm": "22030000", "unidade_comercial": "UN", "quantidade_comercial": "2",
             "valor_unitario_comercial": "4.5", "unidade_tributavel": "UN", "quantidade_tributavel": "2",
             "valor_unitario_tributavel": "4.5", "valor_bruto": "9.00", "icms_origem": "0",
             "icms_situacao_tributaria": "102", "pis_situacao_tributaria": "49",
             "cofins_situacao_tributaria": "49", "valor_desconto": "0.50", "cest": "0302100"},
            {"numero_item": 2, "codigo_produto": "77", "descricao": "GELO EM CUBO 5KG", "cfop": "5102",
             "codigo_ncm": "22019000", "unidade_comercial": "UN", "quantidade_comercial": "1",
             "valor_unitario_comercial": "15", "unidade_tributavel": "UN", "quantidade_tributavel": "1",
             "valor_unitario_tributavel": "15", "valor_bruto": "15.00", "icms_origem": "0",
             "icms_situacao_tributaria": "500", "pis_situacao_tributaria": "07",
             "cofins_situacao_tributaria": "07", "valor_outras_despesas": "1.50"}],
        "formas_pagamento": [{"forma_pagamento": "01", "valor_pagamento": "10.00"},
                             {"forma_pagamento": "04", "valor_pagamento": "15.00"}],
    }
    base.update(extra)
    return base


def esquema(nome="nfe_v4.00.xsd"):
    return etree.XMLSchema(etree.parse(str(XSD / nome)))


class TestChave(unittest.TestCase):
    def test_digito_e_formato(self):
        emissao = dt.datetime(2026, 11, 14)
        c = chave.montar("35", emissao, "12345678000195", 1, 42, 1, "12345678")
        self.assertEqual(len(c), 44)
        self.assertTrue(c.startswith("35" + "2611" + "12345678000195" + "65" + "001" + "000000042" + "1" + "12345678"))
        self.assertTrue(chave.valida(c))
        self.assertFalse(chave.valida(c[:-1] + str((int(c[-1]) + 1) % 10)))

    def test_resto_zero_ou_um_da_zero(self):
        for base in ("0" * 43, "1" * 43, "3526111234567800019565001000000001100000001"):
            dv = chave.digito(base)
            soma, peso = 0, 2
            for n in reversed(base):
                soma += int(n) * peso
                peso = 2 if peso == 9 else peso + 1
            self.assertEqual(dv, "0" if soma % 11 < 2 else str(11 - soma % 11))

    def test_cnf_nunca_igual_ao_numero(self):
        for _ in range(50):
            self.assertNotEqual(int(chave.codigo_numerico(7)), 7)
            self.assertEqual(len(chave.codigo_numerico(7)), 8)


class TestXmlNfce(unittest.TestCase):
    def montar(self, ambiente="homologacao", **extra):
        return xml_nfce.montar(dados(**extra), EMIT, xml_nfce.Numeracao(1, 42, "12345678"), ambiente,
                               resp_tec=RESP, ver_proc="WillPDV 1.14.7")

    def test_xml_valido_no_schema_oficial_depois_de_assinado(self):
        nfe, ch = self.montar()
        cert = assinatura.Certificado.do_pfx(certificado_teste(), "1234")
        assinatura.assinar(nfe, nfe.find(f"{{{NS}}}infNFe"), cert)
        validador = esquema()
        self.assertTrue(validador.validate(nfe), validador.error_log)
        self.assertTrue(assinatura.verificar(nfe, nfe.find(f"{{{NS}}}infNFe")))
        self.assertEqual(nfe.find(f"{{{NS}}}infNFe").get("Id"), "NFe" + ch)

    def test_totais_qr_code_e_destinatario(self):
        nfe, ch = self.montar(cpf_destinatario="52998224725")
        t = lambda caminho: nfe.findtext(caminho, namespaces={"n": NS})
        self.assertEqual(t(".//n:ICMSTot/n:vProd"), "24.00")
        self.assertEqual(t(".//n:ICMSTot/n:vDesc"), "0.50")
        self.assertEqual(t(".//n:ICMSTot/n:vOutro"), "1.50")
        self.assertEqual(t(".//n:ICMSTot/n:vNF"), "25.00")
        self.assertEqual(t(".//n:qrCode"), f"https://www.homologacao.nfce.fazenda.sp.gov.br/qrcode?p={ch}|3|2")
        self.assertEqual(t(".//n:dest/n:CPF"), "52998224725")
        self.assertEqual(t(".//n:ide/n:tpAmb"), "2")
        self.assertIsNotNone(nfe.find(".//n:detPag/n:card", namespaces={"n": NS}))      # débito leva o grupo card
        self.assertTrue(esquema().validate(self._assinado(nfe)))

    def _assinado(self, nfe):
        assinatura.assinar(nfe, nfe.find(f"{{{NS}}}infNFe"), assinatura.Certificado.do_pfx(certificado_teste(), "1234"))
        return nfe

    def test_regime_normal_e_cst_sem_suporte(self):
        normal = xml_nfce.Emitente(**{**EMIT.__dict__, "crt": "3"})
        itens = dados()["items"]
        itens[0]["icms_situacao_tributaria"], itens[1]["icms_situacao_tributaria"] = "60", "40"
        nfe, _ = xml_nfce.montar(dados(items=itens), normal, xml_nfce.Numeracao(1, 1, "00000002"), "producao")
        self.assertTrue(esquema().validate(self._assinado(nfe)), esquema().error_log)
        itens[0]["icms_situacao_tributaria"] = "00"
        with self.assertRaisesRegex(ErroFiscal, "ainda não é emitida"):
            xml_nfce.montar(dados(items=itens), normal, xml_nfce.Numeracao(1, 1, "00000002"), "producao")
        itens[0]["icms_situacao_tributaria"], itens[0]["pis_situacao_tributaria"] = "60", "01"
        with self.assertRaisesRegex(ErroFiscal, "precisa de alíquota"):
            xml_nfce.montar(dados(items=itens), normal, xml_nfce.Numeracao(1, 1, "00000002"), "producao")

    def test_dados_da_loja_incompletos_e_fora_de_sp(self):
        with self.assertRaisesRegex(ErroFiscal, "código do município"):
            xml_nfce.montar(dados(), xml_nfce.Emitente(**{**EMIT.__dict__, "cod_municipio": ""}),
                            xml_nfce.Numeracao(1, 1, "00000002"), "producao")
        with self.assertRaisesRegex(ErroFiscal, "só SP"):
            xml_nfce.montar(dados(), xml_nfce.Emitente(**{**EMIT.__dict__, "uf": "RJ"}),
                            xml_nfce.Numeracao(1, 1, "00000002"), "producao")

    def test_pagamento_que_nao_fecha(self):
        with self.assertRaisesRegex(ErroFiscal, "não fecham"):
            self.montar(formas_pagamento=[{"forma_pagamento": "01", "valor_pagamento": "20.00"}])


class TestCertificado(unittest.TestCase):
    def test_senha_errada_e_validade(self):
        pfx = certificado_teste(dias=30)
        with self.assertRaises(assinatura.ErroCertificado):
            assinatura.Certificado.do_pfx(pfx, "errada")
        cert = assinatura.Certificado.do_pfx(pfx, "1234")
        self.assertFalse(cert.vencido())
        self.assertTrue(cert.vencido(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=60)))
        self.assertIn("LOJA TESTE", cert.titular)

    def test_arquivos_pem_sao_apagados(self):
        cert = assinatura.Certificado.do_pfx(certificado_teste(), "1234")
        with cert.arquivos_pem() as (c, k):
            self.assertTrue(Path(c).exists() and Path(k).exists())
        self.assertFalse(Path(c).exists() or Path(k).exists())

    def test_assinatura_adulterada_nao_confere(self):
        nfe, _ = xml_nfce.montar(dados(), EMIT, xml_nfce.Numeracao(1, 9, "00000010"), "homologacao")
        inf = nfe.find(f"{{{NS}}}infNFe")
        assinatura.assinar(nfe, inf, assinatura.Certificado.do_pfx(certificado_teste(), "1234"))
        inf.find(f".//{{{NS}}}vNF").text = "1.00"
        self.assertFalse(assinatura.verificar(nfe, inf))


class RespostaFalsa:
    def __init__(self, conteudo: bytes, status=200):
        self.content, self.status_code = conteudo, status


class HttpFalso:
    def __init__(self, resposta):
        self.resposta, self.chamadas = resposta, []

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


def soap(corpo: str) -> bytes:
    return (f'<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"><soap:Body>'
            f'<nfeResultMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4">{corpo}</nfeResultMsg>'
            f'</soap:Body></soap:Envelope>').encode()


AUTORIZADO = soap(
    '<retEnviNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><tpAmb>2</tpAmb><verAplic>SP</verAplic>'
    '<cStat>104</cStat><xMotivo>Lote processado</xMotivo><cUF>35</cUF><dhRecbto>2026-11-14T01:30:05-03:00</dhRecbto>'
    '<protNFe versao="4.00"><infProt><tpAmb>2</tpAmb><verAplic>SP</verAplic><chNFe>{ch}</chNFe>'
    '<dhRecbto>2026-11-14T01:30:05-03:00</dhRecbto><nProt>135260000000001</nProt><digVal>x</digVal>'
    '<cStat>100</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe></retEnviNFe>')


class TestCliente(unittest.TestCase):
    def setUp(self):
        self.cert = assinatura.Certificado.do_pfx(certificado_teste(), "1234")
        self.nfe, self.ch = xml_nfce.montar(dados(), EMIT, xml_nfce.Numeracao(1, 42, "12345678"), "homologacao")
        assinatura.assinar(self.nfe, self.nfe.find(f"{{{NS}}}infNFe"), self.cert)

    def test_autorizacao_sincrona_monta_lote_valido_e_le_o_protocolo(self):
        http = HttpFalso(RespostaFalsa(AUTORIZADO.replace(b"{ch}", self.ch.encode())))
        ret = cliente.ClienteSefaz(self.cert, "homologacao", http=http).autorizar(self.nfe, id_lote=7)
        self.assertEqual((ret.situacao, ret.cstat, ret.protocolo), ("autorizada", "100", "135260000000001"))
        url, kw = http.chamadas[0]
        self.assertEqual(url, "https://homologacao.nfce.fazenda.sp.gov.br/ws/NFeAutorizacao4.asmx")
        self.assertIn('action="http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4/nfeAutorizacaoLote"',
                      kw["headers"]["Content-Type"])
        self.assertEqual(len(kw["cert"]), 2)
        envi = etree.fromstring(kw["data"]).find(f".//{{{NS}}}enviNFe")
        self.assertTrue(esquema("enviNFe_v4.00.xsd").validate(envi), esquema("enviNFe_v4.00.xsd").error_log)
        proc = etree.fromstring(cliente.nfe_proc(self.nfe, ret.xml_protocolo))
        self.assertEqual(proc.findtext(f".//{{{NS}}}nProt"), "135260000000001")

    def test_rejeicao_falta_de_rede_e_status(self):
        rejeitada = soap('<retEnviNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><cStat>104</cStat>'
                         '<protNFe versao="4.00"><infProt><cStat>539</cStat><xMotivo>Duplicidade de NF-e</xMotivo>'
                         '</infProt></protNFe></retEnviNFe>')
        ret = cliente.ClienteSefaz(self.cert, "homologacao", http=HttpFalso(RespostaFalsa(rejeitada))).autorizar(self.nfe)
        self.assertEqual((ret.situacao, ret.cstat), ("rejeitada", "539"))
        ret = cliente.ClienteSefaz(self.cert, "homologacao", http=HttpFalso(OSError("sem rede"))).autorizar(self.nfe)
        self.assertIsNone(ret.situacao)
        status = soap('<retConsStatServ xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><cStat>107</cStat>'
                      '<xMotivo>Servico em Operacao</xMotivo></retConsStatServ>')
        http = HttpFalso(RespostaFalsa(status))
        self.assertEqual(cliente.ClienteSefaz(self.cert, "producao", http=http).status().situacao, "em_servico")
        self.assertTrue(http.chamadas[0][0].endswith("nfce.fazenda.sp.gov.br/ws/NFeStatusServico4.asmx"))
        cons = etree.fromstring(http.chamadas[0][1]["data"]).find(f".//{{{NS}}}consStatServ")
        self.assertTrue(esquema("consStatServ_v4.00.xsd").validate(cons))

    def test_lote_em_processamento_nao_e_rejeicao(self):
        lote = soap('<retEnviNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><cStat>103</cStat>'
                    '<xMotivo>Lote recebido com sucesso</xMotivo></retEnviNFe>')
        ret = cliente.ler_retorno(lote)
        self.assertIsNone(ret.situacao)
        self.assertEqual(cliente.ler_retorno(b"<html>erro").situacao, None)


class TestEventoEConsulta(unittest.TestCase):
    def test_cancelamento_e_consulta_validos_no_schema(self):
        cert = assinatura.Certificado.do_pfx(certificado_teste(), "1234")
        ch = chave.montar("35", dt.datetime(2026, 11, 14), "12345678000195", 1, 5, 1, "00000099")
        envio = cliente.evento_cancelamento(ch, "12345678000195", "135260000000777", "Cliente desistiu da compra",
                                            "homologacao", dt.datetime(2026, 11, 14, 2, 0, tzinfo=dt.timezone(
                                                dt.timedelta(hours=-3))), cert, id_lote=1)
        validador = esquema("envEventoCancNFe_v1.00.xsd")
        self.assertTrue(validador.validate(envio), validador.error_log)
        evento = envio.find(f"{{{NS}}}evento")
        self.assertTrue(assinatura.verificar(evento, evento.find(f"{{{NS}}}infEvento")))
        self.assertEqual(evento.find(f"{{{NS}}}infEvento").get("Id"), f"ID110111{ch}01")
        consulta = cliente.corpo_consulta(ch, "producao")
        self.assertTrue(esquema("consSitNFe_v4.00.xsd").validate(consulta), esquema("consSitNFe_v4.00.xsd").error_log)

    def test_retorno_do_evento(self):
        ret = cliente.ler_retorno(soap(
            f'<retEnvEvento xmlns="{NS}" versao="1.00"><cStat>128</cStat><retEvento versao="1.00"><infEvento>'
            '<cStat>135</cStat><xMotivo>Evento registrado e vinculado a NF-e</xMotivo><nProt>135260000000999</nProt>'
            '</infEvento></retEvento></retEnvEvento>'))
        self.assertEqual((ret.situacao, ret.cstat, ret.protocolo), ("cancelada", "135", "135260000000999"))


class TestQrCode(unittest.TestCase):
    def test_urls_de_sp(self):
        self.assertEqual(qrcode.url_online("1" * 44, "producao"),
                         "https://www.nfce.fazenda.sp.gov.br/qrcode?p=" + "1" * 44 + "|3|1")
        self.assertEqual(qrcode.url_chave("homologacao"), "https://www.homologacao.nfce.fazenda.sp.gov.br/NFCeConsultaPublica")


# ---------------------------------------------------------------- provedor próprio dentro da fila real do caixa
import tempfile                                                       # noqa: E402

from src.controllers.fiscal_controller import FiscalController       # noqa: E402
from src.core.erros import ErroNegocio                                # noqa: E402
from src.fiscal.sefaz.provedor import EmissaoPropria                  # noqa: E402
from tests.test_nfce import BaseNfce                                  # noqa: E402


class ClienteFalso:
    """Faz o papel da SEFAZ: guarda o que foi enviado e responde na ordem combinada."""

    def __init__(self, *respostas):
        self.respostas, self.enviadas, self.consultas, self.cancelamentos = list(respostas), [], [], []

    def _proxima(self, padrao):
        return self.respostas.pop(0) if self.respostas else padrao

    def autorizar(self, nfe):
        self.enviadas.append(nfe)
        ch = nfe.find(f"{{{NS}}}infNFe").get("Id")[3:]
        return self._proxima(protocolo(ch))

    def consultar(self, ch):
        self.consultas.append(ch)
        return self._proxima(cliente.Retorno("rejeitada", "217", "NF-e nao consta na base de dados da SEFAZ"))

    def cancelar(self, ch, cnpj, prot, justificativa, quando):
        self.cancelamentos.append((ch, cnpj, prot, justificativa))
        return self._proxima(cliente.Retorno("cancelada", "135", "Evento registrado e vinculado a NF-e"))


def protocolo(ch, cstat="100"):
    xml = (f'<protNFe xmlns="{NS}" versao="4.00"><infProt><tpAmb>2</tpAmb><verAplic>SP</verAplic><chNFe>{ch}</chNFe>'
           f'<dhRecbto>2026-11-14T01:30:05-03:00</dhRecbto><nProt>135260000000777</nProt><digVal>x</digVal>'
           f'<cStat>{cstat}</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe>').encode()
    return cliente.ler_retorno(soap(f'<retEnviNFe xmlns="{NS}" versao="4.00"><cStat>104</cStat>'
                                    + xml.decode() + '</retEnviNFe>'))


class TestEmissaoPropriaNaFila(BaseNfce):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.mkdtemp()
        self.banco.executar("UPDATE loja SET bairro = 'CENTRO', cep = '01001-000' WHERE id = 1")
        for chave_cfg, valor in (("nfce_provedor", "propria"), ("nfce_regime_tributario", "simples_nacional"),
                                 ("nfce_cod_municipio", "3550308"), ("nfce_endereco_numero", "10"),
                                 ("nfce_proximo_numero_homologacao", "41")):
            self.banco.cfg_set(chave_cfg, valor)
        self.sefaz = ClienteFalso()
        self.propria = EmissaoPropria(self.banco, "homologacao", cliente=self.sefaz,
                                      certificado=assinatura.Certificado.do_pfx(certificado_teste(), "1234"),
                                      pasta=self.pasta)
        self.fiscal = FiscalController(self.banco, self.propria)

    def test_autoriza_numera_guarda_o_xml_e_cancela(self):
        vid = self.fechar((self.skol, 2))
        self.fiscal.processar()
        nota = self.nota(vid)
        self.assertEqual((nota["situacao"], nota["numero"], nota["serie"]), ("autorizada", "41", "1"))
        self.assertTrue(chave.valida(nota["chave"]))
        self.assertTrue(nota["qrcode_url"].endswith(f"?p={nota['chave']}|3|2"))
        self.assertEqual(self.banco.cfg("nfce_proximo_numero_homologacao"), "42")
        proc = etree.parse(nota["caminho_xml"]).getroot()
        self.assertEqual(proc.tag, f"{{{NS}}}nfeProc")
        nfe = proc.find(f"{{{NS}}}NFe")
        self.assertTrue(esquema().validate(nfe), esquema().error_log)
        self.assertTrue(assinatura.verificar(nfe, nfe.find(f"{{{NS}}}infNFe")))
        self.fiscal.cancelar(nota["id"], "Cliente desistiu da compra no caixa")
        self.assertEqual(self.nota(vid)["situacao"], "cancelada")
        self.assertEqual(self.sefaz.cancelamentos[0][2], "135260000000777")

    def test_resposta_perdida_consulta_antes_de_reenviar_e_nao_gasta_numero(self):
        self.sefaz.respostas = [cliente.Retorno(None, motivo="Sem conexão com a SEFAZ (ConnectionError).")]
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        nota = self.nota(vid)
        self.assertEqual((nota["situacao"], nota["numero"]), ("pendente", "41"))
        primeira_chave = nota["chave"]
        self.sefaz.respostas = [protocolo(primeira_chave)]          # a SEFAZ tinha autorizado: a consulta acha
        self.banco.executar("UPDATE nfce_notas SET proxima_tentativa = NULL")
        self.fiscal.processar()
        nota = self.nota(vid)
        self.assertEqual((nota["situacao"], nota["chave"]), ("autorizada", primeira_chave))
        self.assertEqual(len(self.sefaz.enviadas), 1)                    # não reenviou
        self.assertEqual(self.banco.cfg("nfce_proximo_numero_homologacao"), "42")

    def test_rejeicao_e_cadastro_incompleto(self):
        self.sefaz.respostas = [cliente.Retorno("rejeitada", "778", "Informado NCM inexistente")]
        vid = self.fechar((self.skol, 1))
        self.fiscal.processar()
        nota = self.nota(vid)
        self.assertEqual(nota["situacao"], "rejeitada")
        self.assertIn("778", nota["mensagem"])
        self.banco.cfg_set("nfce_cod_municipio", "")
        vid2 = self.fechar((self.agua, 1))
        self.fiscal.processar()
        self.assertEqual(self.nota(vid2)["situacao"], "erro")
        self.assertIn("código do município", self.nota(vid2)["mensagem"])

    def test_ligar_exige_certificado_e_dados_da_loja(self):
        fiscal = FiscalController(self.banco)
        fiscal.ligar("desligada")
        with self.assertRaisesRegex(ErroNegocio, "Certificado A1 não encontrado"):
            fiscal.ligar("homologacao")
        self.assertEqual(fiscal.provedor(), "propria")
        caminho = Path(self.pasta) / "loja.pfx"
        caminho.write_bytes(certificado_teste())
        self.banco.cfg_set("nfce_certificado_arquivo", str(caminho))
        self.banco.cfg_set("nfce_certificado_senha", "1234")
        self.banco.cfg_set("nfce_cod_municipio", "")
        with self.assertRaisesRegex(ErroNegocio, "código do município"):
            fiscal.ligar("homologacao")
        self.banco.cfg_set("nfce_cod_municipio", "3550308")
        fiscal.ligar("homologacao")
        self.assertIsInstance(FiscalController(self.banco).transmissor(), EmissaoPropria)
