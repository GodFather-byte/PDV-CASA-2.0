"""Código de instalação da central: formato, aplicação no caixa (nuvem simulada) e tela de entrada."""
from __future__ import annotations

import os
import unittest
from datetime import date
from unittest.mock import patch

from src.core import codigo_instalacao, ed25519, licenca
from src.core.erros import ErroNegocio
from src.sync import instalacao_nuvem
from tests.base import BaseTeste

SEMENTE = bytes(range(32))
PUBLICA = ed25519.chave_publica(SEMENTE).hex()
URL = "https://willpdv-nuvem-6sp0.onrender.com"
TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-xy"


class TesteFormato(unittest.TestCase):
    def test_ida_e_volta_ignorando_espacos_e_quebras(self):
        codigo = codigo_instalacao.gerar(URL + "/", "ADEGA-01", TOKEN)
        self.assertTrue(codigo.startswith("WILL1-"))
        quebrado = "  " + codigo[:20] + "\n" + codigo[20:] + "  "
        self.assertTrue(codigo_instalacao.parece_codigo(quebrado))
        self.assertEqual(codigo_instalacao.ler(quebrado), {"url": URL, "chave": "ADEGA-01", "token": TOKEN})
        self.assertEqual(codigo_instalacao.ler(codigo_instalacao.gerar("http://localhost:8000", "L", TOKEN))["url"],
                         "http://localhost:8000")

    def test_recusa_endereco_inseguro_e_dados_estranhos(self):
        for url in ("http://nuvem.com", "https://u:s@nuvem.com", "ftp://nuvem.com", "https://nuvem.com/?x=1", ""):
            with self.assertRaises(ValueError):
                codigo_instalacao.gerar(url, "LOJA", TOKEN)
        for chave, token in (("LOJA ESPACO", TOKEN), ("LOJA", "curto"), ("LOJA", "token com espaço" * 3)):
            with self.assertRaises(ValueError):
                codigo_instalacao.gerar(URL, chave, token)
        import base64
        import json
        forjado = "WILL1-" + base64.urlsafe_b64encode(json.dumps(
            {"u": "http://evil.com", "l": "LOJA", "t": TOKEN}).encode()).decode().rstrip("=")
        for texto in ("WILLPDV.abc.def", "WILL1-", "WILL1-!!!", "WILL1-" + "A" * 2000, forjado,
                      "WILL1-" + base64.urlsafe_b64encode(b"[1,2]").decode()):
            with self.assertRaises(ErroNegocio):
                codigo_instalacao.ler(texto)


class Resposta:
    def __init__(self, status, corpo=None):
        self.status_code, self._corpo = status, corpo or {}

    def json(self):
        return self._corpo


class Http:
    def __init__(self, resposta):
        self.resposta, self.pedidos = resposta, []

    def get(self, url, headers=None, timeout=None):
        self.pedidos.append((url, headers))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


class TesteInstalarNoCaixa(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("licenca_exigir", "S")
        publica = patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA)
        publica.start()
        self.addCleanup(publica.stop)
        self.codigo = codigo_instalacao.gerar(URL, "ADEGA-01", TOKEN)

    def licenca_da_nuvem(self, loja="ADEGA-01", edicao="willpdv"):
        return Http(Resposta(200, {"codigo": licenca.gerar_licenca(SEMENTE, loja, 30, date(2026, 10, 3), edicao),
                                   "expira_em": "2026-11-02"}))

    def test_configura_a_nuvem_liga_o_painel_e_ativa_a_licenca(self):
        http = self.licenca_da_nuvem()
        r = instalacao_nuvem.instalar(self.banco, self.codigo, http)
        self.assertTrue(r["licenca_ativa"], r["mensagem"])
        self.assertEqual((self.banco.cfg("chave_loja"), self.banco.cfg("api_url"), self.banco.cfg("api_token"),
                          self.banco.cfg("painel_dono")), ("ADEGA-01", URL, TOKEN, "S"))
        self.assertEqual(http.pedidos[0], (URL + "/v1/licenca", {"Authorization": f"Bearer {TOKEN}"}))
        self.assertIn("conectada à nuvem", r["mensagem"])
        self.assertFalse(licenca.estado(self.banco).bloqueia)
        evento = self.banco.um("SELECT detalhe FROM log_eventos WHERE evento = 'instalacao_nuvem'")["detalhe"]
        self.assertNotIn(TOKEN, evento)                                      # o token não vai para o log

    def test_sem_licenca_na_nuvem_ou_sem_rede_configura_e_explica(self):
        r = instalacao_nuvem.instalar(self.banco, self.codigo, Http(Resposta(404)))
        self.assertFalse(r["licenca_ativa"])
        self.assertIn("ainda não tem licença", r["mensagem"])
        self.assertEqual(self.banco.cfg("api_token"), TOKEN)
        r = instalacao_nuvem.instalar(self.banco, self.codigo, Http(OSError("sem rede")))
        self.assertIn("Não foi possível buscar a licença", r["mensagem"])

    def test_licenca_de_outro_programa_e_avisada(self):
        r = instalacao_nuvem.instalar(self.banco, self.codigo, self.licenca_da_nuvem(edicao="willadega"))
        self.assertFalse(r["licenca_ativa"])
        self.assertIn("não serviu", r["mensagem"])
        self.assertIn("Will Adega", r["mensagem"])

    def test_outra_loja_so_com_confirmacao(self):
        self.banco.cfg_set("chave_loja", "BOATE-02")
        with self.assertRaises(instalacao_nuvem.OutraLoja) as erro:
            instalacao_nuvem.instalar(self.banco, self.codigo, self.licenca_da_nuvem())
        self.assertEqual((erro.exception.atual, erro.exception.nova), ("BOATE-02", "ADEGA-01"))
        self.assertEqual(self.banco.cfg("api_token"), "")
        r = instalacao_nuvem.instalar(self.banco, self.codigo, self.licenca_da_nuvem(), trocar_loja=True)
        self.assertTrue(r["licenca_ativa"], r["mensagem"])
        self.assertEqual(self.banco.cfg("chave_loja"), "ADEGA-01")

    def test_codigo_ruim_nao_mexe_em_nada(self):
        with self.assertRaises(ErroNegocio):
            instalacao_nuvem.instalar(self.banco, "WILL1-lixo", self.licenca_da_nuvem())
        self.assertEqual((self.banco.cfg("api_url"), self.banco.cfg("chave_loja")), ("", ""))


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    from src.controllers.contexto import Contexto
    from src.ui_qt.login import JanelaLogin
except ImportError:                                   # pragma: no cover - sem PySide6
    JanelaLogin = None


@unittest.skipIf(JanelaLogin is None, "PySide6 não instalado")
class TesteTelaDeEntrada(TesteInstalarNoCaixa):
    def setUp(self):
        super().setUp()
        self.app = QApplication.instance() or QApplication([])
        self.janela = JanelaLogin(Contexto(self.banco))
        self.addCleanup(self._descartar)

    def _descartar(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        self.janela.close()
        self.janela.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_botao_aceita_o_codigo_de_instalacao(self):
        self.assertIn("instalar loja", self.janela.btn_licenca.text())
        http = self.licenca_da_nuvem()
        with patch.object(QInputDialog, "getMultiLineText", return_value=(self.codigo, True)), \
                patch("src.sync.licenca_nuvem.consultar_resultado",
                      side_effect=lambda u, t, _h, timeout: instalacao_nuvem.licenca_nuvem.ResultadoConsulta(
                          True, http.resposta.json()["codigo"])):
            self.janela.pedir_licenca()
        self.assertIn("conectada à nuvem", self.janela.mensagem.text())
        self.assertEqual(self.banco.cfg("chave_loja"), "ADEGA-01")

    def test_troca_de_loja_recusada_mantem_a_atual(self):
        self.banco.cfg_set("chave_loja", "BOATE-02")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.janela.instalar_loja(self.codigo, self.licenca_da_nuvem()))
        self.assertEqual(self.banco.cfg("chave_loja"), "BOATE-02")
        self.assertIn("cancelada", self.janela.mensagem.text())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.janela.instalar_loja(self.codigo, self.licenca_da_nuvem()))
        self.assertEqual(self.banco.cfg("chave_loja"), "ADEGA-01")


for _nome in [n for n in dir(TesteInstalarNoCaixa) if n.startswith("test_")]:
    if JanelaLogin is not None and _nome not in TesteTelaDeEntrada.__dict__:
        setattr(TesteTelaDeEntrada, _nome, None)          # as regras já rodam na classe delas
