"""XMLs da NFC-e na nuvem: o caixa sobe os de produção, a nuvem guarda por mês e o dono/fornecedor baixam o ZIP."""
import base64
import gzip
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from src.sync import nfce_xmls
from tests.test_notas_dono import _Ponte
from tests.test_painel_dono import BaseNuvem, TestClient, nuvem

try:
    from backend import nfce_xmls as nuvem_xmls
except (ImportError, RuntimeError):
    nuvem_xmls = None

NS = "http://www.portalfiscal.inf.br/nfe"
CHAVE = "35261112345678000195650010000000411000000410"


def nfe_proc(chave=CHAVE, dia="2026-11-14"):
    return (f'<?xml version="1.0" encoding="utf-8"?><nfeProc xmlns="{NS}" versao="4.00"><NFe><infNFe Id="NFe{chave}">'
            f'<ide><dhEmi>{dia}T21:30:00-03:00</dhEmi></ide></infNFe></NFe><protNFe><infProt><cStat>100</cStat>'
            f'</infProt></protNFe></nfeProc>').encode()


def cancelamento(chave=CHAVE):
    return (f'<retEvento xmlns="{NS}" versao="1.00"><infEvento><cStat>135</cStat><chNFe>{chave}</chNFe>'
            f'<dhRegEvento>2026-12-01T10:00:00-03:00</dhRegEvento></infEvento></retEvento>').encode()


@unittest.skipIf(TestClient is None or nuvem_xmls is None, "fastapi/httpx não instalados")
class TesteXmlsNaNuvem(BaseNuvem):
    def setUp(self):
        super().setUp()
        with nuvem.SessionLocal() as db:
            db.query(nuvem_xmls.NfceXml).delete()
            db.commit()
        self.pasta = Path(tempfile.mkdtemp())
        trocar = mock.patch.object(nfce_xmls, "pasta", return_value=self.pasta)
        trocar.start()
        self.addCleanup(trocar.stop)
        self.ponte = _Ponte(self.http)

    def gravar(self, nome, conteudo):
        (self.pasta / nome).write_bytes(conteudo)

    def test_caixa_sobe_uma_vez_e_o_dono_baixa_o_zip_do_mes(self):
        self.assertTrue(nfce_xmls.ha_pendente(self.banco))           # primeira varredura depois de atualizar
        self.gravar(f"{CHAVE}-nfe.xml", nfe_proc())
        self.gravar(f"{CHAVE}-cancelamento.xml", cancelamento())
        self.gravar(f"{CHAVE}-assinada.xml", b"<NFe/>")                 # rascunho assinado: não sobe
        self.gravar("inutilizacao-001-50-50.xml", b'<retInutNFe xmlns="x"><dhRecbto>2026-11-20T10:00:00-03:00'
                                                  b'</dhRecbto></retInutNFe>')
        self.assertEqual(nfce_xmls.sincronizar(self.banco, self.ponte), 3)
        self.assertFalse(nfce_xmls.ha_pendente(self.banco))
        self.assertEqual(nfce_xmls.sincronizar(self.banco, self.ponte), 0)           # não reenvia
        self.assertEqual(sum(1 for c in self.ponte.chamadas if c[0] == "POST"), 1)
        nfce_xmls.avisar(self.banco)
        self.assertTrue(nfce_xmls.ha_pendente(self.banco))

        dono = self.entrar()
        meses = self.http.get("/v1/painel/nfce/meses", headers=dono).json()["meses"]
        self.assertEqual([(m["mes"], m["nfe"], m["cancelamento"], m["inutilizacao"]) for m in meses],
                         [("2026-12", 0, 1, 0), ("2026-11", 1, 0, 1)])
        r = self.http.get("/v1/painel/nfce/xmls", params={"mes": "2026-11"}, headers=dono)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            self.assertEqual(sorted(z.namelist()), [f"autorizadas/{CHAVE}-nfe.xml",
                                                    "inutilizadas/inutilizacao-001-50-50.xml"])
            self.assertEqual(z.read(f"autorizadas/{CHAVE}-nfe.xml"), nfe_proc())
        self.assertEqual(self.http.get("/v1/painel/nfce/xmls", params={"mes": "2025-01"}, headers=dono).status_code, 404)
        self.assertEqual(self.http.get("/v1/painel/nfce/xmls", params={"mes": "nov"}, headers=dono).status_code, 422)
        outra = self.entrar("ADEGA-2")                                    # cada dono só vê a própria loja
        self.assertEqual(self.http.get("/v1/painel/nfce/meses", headers=outra).json()["meses"], [])

    def test_nuvem_recusa_arquivo_estranho_sem_travar_o_lote(self):
        def item(nome, xml, mes="2026-11", tipo="nfe"):
            return {"nome": nome, "tipo": tipo, "mes": mes, "chave": CHAVE,
                    "conteudo_gz_b64": base64.b64encode(gzip.compress(xml)).decode()}
        lote = [item(f"{CHAVE}-nfe.xml", nfe_proc()),
                item("x-nfe.xml", b'<!DOCTYPE a [<!ENTITY b "c">]><a>&b;</a>'),
                item("../../etc-nfe.xml", nfe_proc()),
                item("ok2-nfe.xml", nfe_proc(), mes="2026-13"),
                {"nome": "sem-gzip-nfe.xml", "tipo": "nfe", "mes": "2026-11", "conteudo_gz_b64": "bm9wZQ=="}]
        from tests.test_painel_dono import cabecalho
        r = self.http.post("/v1/nfce/xmls", json={"arquivos": lote}, headers=cabecalho("ADEGA-1"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["recebidos"], [f"{CHAVE}-nfe.xml"])
        self.assertEqual(len(r.json()["recusados"]), 4)
        self.assertEqual(self.http.post("/v1/nfce/xmls", json={"arquivos": lote * 5},
                                        headers=cabecalho("ADEGA-1")).status_code, 422)
        dono = self.entrar()
        self.assertEqual(self.http.post("/v1/nfce/xmls", json={"arquivos": lote[:1]}, headers=dono).status_code, 401)

    def test_homologacao_nao_avisa_e_producao_avisa(self):
        from src.fiscal.sefaz.provedor import EmissaoPropria
        self.banco.cfg_set(nfce_xmls.AVISO, "")
        EmissaoPropria(self.banco, "homologacao", cliente=object(), pasta=tempfile.mkdtemp())._avisar_nuvem()
        self.assertEqual(self.banco.cfg(nfce_xmls.AVISO), "")
        EmissaoPropria(self.banco, "producao", cliente=object(), pasta=tempfile.mkdtemp())._avisar_nuvem()
        self.assertEqual(self.banco.cfg(nfce_xmls.AVISO), "S")
