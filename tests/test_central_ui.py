"""A janela configura e opera somente o banco isolado da central."""
from __future__ import annotations

import os
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from licenciador.central import Central
from licenciador.central_tela import JanelaCentral


class TesteCentralTela(unittest.TestCase):
    def test_cadastro_local_listado_sem_rede_e_sem_callback_pendente(self):
        with tempfile.TemporaryDirectory() as pasta:
            banco = Path(pasta) / "central.db"
            central = Central(banco)
            central.cadastrar("TESTE", "Loja de teste")
            central.fechar()
            root = tk.Tk()
            root.withdraw()
            janela = None
            try:
                with patch("licenciador.central_tela.caminho_padrao", return_value=banco), \
                        patch.dict(os.environ, {"WILLCENTRAL_API_URL": "", "PDV_CENTRAL_TOKEN": "",
                                                "WILLCENTRAL_TELEGRAM_TOKEN": ""}):
                    janela = JanelaCentral(root)
                janela.withdraw()
                janela.atualizar()
                limite = time.monotonic() + 5
                while janela.ocupada and time.monotonic() < limite:
                    root.update()
                    time.sleep(0.01)
                self.assertFalse(janela.ocupada)
                itens = janela.lista.get_children()
                self.assertEqual(len(itens), 1)
                self.assertEqual(janela.lista.item(itens[0], "values")[0], "TESTE")
                janela.destroy()
                self.assertIsNone(janela._after_id)
                root.update()
            finally:
                if janela is not None and janela.winfo_exists():
                    janela.destroy()
                root.destroy()
