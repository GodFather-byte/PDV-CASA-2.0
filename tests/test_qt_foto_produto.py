"""Foto do produto nas telas: aba Foto do cadastro e foto do último item no caixa."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers import foto_produto_controller as fotos
from src.controllers.foto_produto_controller import FotoProdutoController
from tests.test_foto_produto import API, FOTO_URL, HttpFalso, Resposta, imagem
from tests.test_qt_caixa import BaseCaixaQt

try:
    from PySide6.QtWidgets import QDialog
    from src.ui_qt.cadastros import FormularioCadastro
except ImportError:                                   # pragma: no cover - sem PySide6 estes testes não rodam
    QDialog = None


@unittest.skipIf(QDialog is None, "PySide6 não instalado")
class TesteFotoNasTelas(BaseCaixaQt):
    def formulario(self, id_=None):
        f = FormularioCadastro(self.ctx, "produtos", id_)
        self.janelas_cadastro.append(f)
        return f

    def setUp(self):
        super().setUp()
        self.janelas_cadastro = []
        self.addCleanup(lambda: [f.close() for f in self.janelas_cadastro])
        self.fotos = FotoProdutoController(self.banco)

    def test_cadastro_tem_aba_foto_e_so_grava_ao_salvar(self):
        pid = self.novo_produto("VINHO TINTO", 4500, codigo="77")
        f = self.formulario(pid)
        self.assertEqual(f.abas.tabText(f.abas.count() - 1), "Foto")
        self.assertEqual(f.editor_foto.situacao.text(), "Sem foto")
        self.assertFalse(f.editor_foto.btn_remover.isEnabled())
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "vinho.jpg"
            caminho.write_bytes(imagem(900, 1200, "JPEG", "RGB"))
            self.assertTrue(f.editor_foto.escolher_arquivo(str(caminho)))
        self.assertTrue(f.editor_foto.quadro.tem_foto())
        self.assertFalse(self.fotos.tem_foto(pid))                       # prévia: nada gravado ainda
        f.salvar()
        self.assertEqual(f.result(), QDialog.DialogCode.Accepted, f.mensagem.text())
        self.assertTrue(self.fotos.tem_foto(pid))
        reaberto = self.formulario(pid)
        self.assertEqual(reaberto.editor_foto.situacao.text(), "Foto atual")
        reaberto.editor_foto.remover()
        reaberto.salvar()
        self.assertFalse(self.fotos.tem_foto(pid))

    def test_arquivo_invalido_avisa_e_nao_troca_a_foto(self):
        pid = self.novo_produto("GIN", 9000)
        self.fotos.gravar(pid, fotos.preparar(imagem(50, 50)))
        f = self.formulario(pid)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "falso.jpg"
            caminho.write_text("isto não é foto")
            self.assertFalse(f.editor_foto.escolher_arquivo(str(caminho)))
        self.assertIn("Não foi possível abrir", f.editor_foto.mensagem.text())
        self.assertIsNone(f.editor_foto.pendente)

    def test_busca_pelo_codigo_de_barras_digitado_no_formulario(self):
        f = self.formulario()
        f.campos["subgrupo_id"].setCurrentIndex(1)
        f.campos["unidade_id"].setCurrentIndex(1)
        f.campos["nome"].setText("SKOL LATA 350")
        f.campos["preco_cent"].setText("4,50")
        f.campos["cbarra"].setText("7891149103102")
        import json
        http = HttpFalso({API: Resposta(200, json.dumps({"product": {"image_front_url": FOTO_URL}}).encode()),
                          FOTO_URL: Resposta(200, imagem(600, 600, "JPEG", "RGB"))})
        self.assertTrue(f.editor_foto.buscar_na_internet(http))
        self.assertIn("Confira se é o produto certo", f.editor_foto.situacao.text())
        f.salvar()
        self.assertEqual(f.result(), QDialog.DialogCode.Accepted, f.mensagem.text())
        self.assertEqual(self.fotos.origem(f.id_), FOTO_URL)
        f2 = self.formulario()
        f2.campos["cbarra"].setText("")
        self.assertFalse(f2.editor_foto.buscar_na_internet(HttpFalso({})))
        self.assertIn("código de barras", f2.editor_foto.mensagem.text())

    def test_caixa_mostra_a_foto_do_produto_bipado_e_esconde_sem_foto(self):
        self.abrir_turno()
        com_foto = self.novo_produto("HEINEKEN LONG NECK", 900, codigo="44")
        self.novo_produto("GELO 5KG", 1000, codigo="45")
        self.fotos.gravar(com_foto, fotos.preparar(imagem(400, 600, "JPEG", "RGB")))
        j = self.janela()
        self.assertFalse(j.foto_item.isVisibleTo(j))
        self.lancar(j, "44")
        self.assertTrue(j.foto_item.isVisibleTo(j))
        self.assertTrue(j.foto_item.tem_foto())
        self.assertEqual(j.lbl_foto_item.text(), "HEINEKEN LONG NECK")
        self.assertLessEqual(j.foto_item.height(), 200)
        self.lancar(j, "45")                                              # sem foto: o espaço volta a ficar livre
        self.assertFalse(j.foto_item.isVisibleTo(j))
        self.lancar(j, "44")
        self.assertTrue(j.foto_item.isVisibleTo(j))
        j.dialogos.confirmacoes = [True]
        j.btn_cancelar_venda.click()                                      # venda vazia: a foto sai
        self.assertFalse(j.foto_item.isVisibleTo(j))
