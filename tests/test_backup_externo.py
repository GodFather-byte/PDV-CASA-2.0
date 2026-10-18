"""Backup externo: autenticação, recuperação real e falhas sem perder o banco."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.controllers.utilitario_controller import UtilitarioController
from src.core import backup_seguro
from src.core.erros import ErroNegocio
from src.database import protecao
from src.database.conexao import BancoDados

SENHA = "recuperacao-teste-2026"


class TesteFormatoSeguro(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.raiz = Path(self.pasta.name)
        self.origem = self.raiz / "origem.db"
        self.origem.write_bytes(b"SQLite dados confidenciais" * 100000)
        self.cifrado = self.raiz / "backup.pdvbkp"
        self.recuperado = self.raiz / "recuperado.db"

    def test_roundtrip_em_blocos_sem_conteudo_aberto(self):
        backup_seguro.criptografar(self.origem, self.cifrado, SENHA)
        self.assertNotIn(b"dados confidenciais", self.cifrado.read_bytes())
        backup_seguro.descriptografar(self.cifrado, self.recuperado, SENHA)
        self.assertEqual(self.recuperado.read_bytes(), self.origem.read_bytes())

    def test_mesma_senha_produz_arquivos_distintos(self):
        backup_seguro.criptografar(self.origem, self.cifrado, SENHA)
        outro = self.raiz / "outro.pdvbkp"
        backup_seguro.criptografar(self.origem, outro, SENHA)
        self.assertNotEqual(self.cifrado.read_bytes(), outro.read_bytes())

    def test_senha_incorreta_preserva_destino_e_remove_temporario(self):
        backup_seguro.criptografar(self.origem, self.cifrado, SENHA)
        self.recuperado.write_bytes(b"anterior")
        with self.assertRaisesRegex(ValueError, "Senha incorreta"):
            backup_seguro.descriptografar(self.cifrado, self.recuperado, "senha-incorreta-longa")
        self.assertEqual(self.recuperado.read_bytes(), b"anterior")
        self.assertEqual(list(self.raiz.glob("*.tmp")), [])

    def test_alteracao_de_sal_nonce_conteudo_ou_tag_e_detectada(self):
        backup_seguro.criptografar(self.origem, self.cifrado, SENHA)
        original = self.cifrado.read_bytes()
        for posicao in (len(backup_seguro.CABECALHO), len(backup_seguro.CABECALHO) + 16, 100, -1):
            with self.subTest(posicao=posicao):
                alterado = bytearray(original)
                alterado[posicao] ^= 1
                self.cifrado.write_bytes(alterado)
                with self.assertRaises(ValueError):
                    backup_seguro.descriptografar(self.cifrado, self.recuperado, SENHA)
                self.assertFalse(self.recuperado.exists())

    def test_formato_invalido_e_truncamento(self):
        for dados in (b"", b"WILLPDV-BKP\x02" + b"x" * 100, backup_seguro.CABECALHO):
            with self.subTest(dados=dados[:12]):
                self.cifrado.write_bytes(dados)
                with self.assertRaises(ValueError):
                    backup_seguro.descriptografar(self.cifrado, self.recuperado, SENHA)

    def test_falha_de_publicacao_nao_substitui_copia_anterior(self):
        self.cifrado.write_bytes(b"anterior")
        with mock.patch.object(backup_seguro.os, "replace", side_effect=OSError("disco indisponível")):
            with self.assertRaises(OSError):
                backup_seguro.criptografar(self.origem, self.cifrado, SENHA)
        self.assertEqual(self.cifrado.read_bytes(), b"anterior")
        self.assertEqual(list(self.raiz.glob("*.tmp")), [])

    def test_senha_curta_recusada(self):
        with self.assertRaisesRegex(ValueError, "12"):
            backup_seguro.criptografar(self.origem, self.cifrado, "curta")
        self.assertFalse(self.cifrado.exists())

    @unittest.skipUnless(os.name == "nt", "DPAPI é específico do Windows")
    def test_cofre_windows_real_e_portabilidade_do_arquivo(self):
        cofre = self.raiz / "backup.key"
        backup_seguro.guardar_senha(cofre, SENHA)
        self.assertNotIn(SENHA.encode(), cofre.read_bytes())
        self.assertEqual(backup_seguro.ler_senha(cofre), SENHA)


class TesteBackupExterno(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.raiz = Path(self.pasta.name)
        self.banco = BancoDados(str(self.raiz / "loja.db"))
        self.addCleanup(self.banco.fechar)
        self.util = UtilitarioController(self.banco)
        self.local = self.raiz / "local"
        self.externo = self.raiz / "sincronizada"
        self.banco.cfg_set("pasta_backup", str(self.local))
        self.banco.cfg_set("backup_externo_pasta", str(self.externo))
        self.banco.cfg_set("marcador_teste", "antes")

    def gerar(self):
        return Path(self.util.backup_externo(senha=SENHA))

    def test_gera_e_verifica_recuperacao_sem_sqlite_na_pasta_externa(self):
        arquivo = self.gerar()
        self.util.verificar_backup_externo(str(arquivo), SENHA)
        self.assertEqual([p.suffix for p in self.externo.iterdir()], [".pdvbkp"])
        self.assertTrue(self.banco.cfg("backup_externo_verificado_em"))
        self.assertEqual(self.banco.cfg("marcador_teste"), "antes")
        self.assertIn("cópia externa verificada", self.util.situacao_backup()[1])

    def test_configuracao_nao_grava_senha_no_banco(self):
        with mock.patch.object(backup_seguro, "guardar_senha") as guardar:
            self.util.configurar_backup_externo(str(self.externo), SENHA)
        guardar.assert_called_once_with(self.raiz / "loja.db.backup.key", SENHA)
        self.assertNotIn(SENHA, "\n".join(self.banco.conexao.iterdump()))

    def test_backup_automatico_inclui_copia_externa_e_situacao_honesta(self):
        with mock.patch.object(backup_seguro, "ler_senha", return_value=SENHA):
            self.assertTrue(self.util.backup_automatico("teste"))
        self.assertTrue(list(self.externo.glob("*.pdvbkp")))
        nivel, texto = self.util.situacao_backup()
        self.assertEqual(nivel, "ok")
        self.assertIn("depende", texto)

    def test_falha_externa_preserva_backup_local_mas_avisa(self):
        with mock.patch.object(backup_seguro, "ler_senha", side_effect=OSError("cofre indisponível")):
            caminho = self.util.backup_automatico("teste")
        self.assertTrue(protecao.backup_valido(caminho))
        self.assertIn("cofre indisponível", self.banco.cfg("backup_externo_erro"))
        self.assertEqual(self.util.situacao_backup()[0], "aviso")

    def test_verificar_senha_errada_nao_marca_restauracao(self):
        arquivo = self.gerar()
        with self.assertRaises(ErroNegocio):
            self.util.pedir_restauracao_externa(str(arquivo), "outra-senha-de-recuperacao")
        self.assertFalse(Path(self.banco.caminho + ".restaurar.pendente").exists())
        self.assertEqual(self.banco.cfg("marcador_teste"), "antes")

    def test_recupera_banco_real_so_na_proxima_abertura(self):
        arquivo = self.gerar()
        self.banco.cfg_set("marcador_teste", "depois")
        with mock.patch.object(backup_seguro, "ler_senha", return_value=SENHA):
            self.util.pedir_restauracao_externa(str(arquivo), SENHA)
        self.assertEqual(self.banco.cfg("marcador_teste"), "depois")
        self.banco.fechar()
        protecao.aplicar_restauracao_pendente(self.raiz / "loja.db")
        with sqlite3.connect(self.raiz / "loja.db") as con:
            self.assertEqual(con.execute("SELECT valor FROM config WHERE chave='marcador_teste'").fetchone()[0], "antes")
        con.close()

    def test_retencao_preserva_arquivos_alheios(self):
        self.externo.mkdir()
        alheio = self.externo / "importante.pdvbkp"
        alheio.write_bytes(b"nao remover")
        self.gerar()
        atual = Path(self.util.backup_externo(senha=SENHA, manter=1))
        self.assertEqual(len(list(self.externo.glob("loja_offline-seguro-*.pdvbkp"))), 1)
        self.assertTrue(atual.exists())
        self.assertTrue(alheio.exists())

    def test_conteudo_autenticado_mas_nao_sqlite_e_recusado(self):
        self.externo.mkdir()
        origem = self.raiz / "texto.txt"
        origem.write_text("não é banco", encoding="utf-8")
        arquivo = self.externo / "falso.pdvbkp"
        backup_seguro.criptografar(origem, arquivo, SENHA)
        with self.assertRaisesRegex(ErroNegocio, "banco válido"):
            self.util.verificar_backup_externo(str(arquivo), SENHA)

    def test_configuracao_sem_pasta_recusada(self):
        with self.assertRaises(ErroNegocio):
            self.util.configurar_backup_externo("", SENHA)

    def test_pasta_criptografada_nao_pode_ser_a_mesma_do_backup_aberto(self):
        with self.assertRaisesRegex(ErroNegocio, "pasta exclusiva"):
            self.util.configurar_backup_externo(str(self.local), SENHA)

    def test_backup_de_versao_futura_nao_e_marcado_para_restaurar(self):
        from src.database.esquema import VERSAO_ESQUEMA
        futuro = self.raiz / "futuro.db"
        self.banco.copiar_para(str(futuro))
        con = sqlite3.connect(futuro)
        try:
            con.execute(f"PRAGMA user_version = {VERSAO_ESQUEMA + 1}")
        finally:
            con.close()
        self.externo.mkdir()
        arquivo = self.externo / "futuro.pdvbkp"
        backup_seguro.criptografar(futuro, arquivo, SENHA)
        with self.assertRaisesRegex(ErroNegocio, "versão mais recente"):
            self.util.pedir_restauracao_externa(str(arquivo), SENHA)
        self.assertFalse(Path(self.banco.caminho + ".restaurar.pendente").exists())

    def test_desativar_preserva_arquivos_existentes(self):
        arquivo = self.gerar()
        self.util.desativar_backup_externo()
        self.assertEqual(self.banco.cfg("backup_externo_pasta"), "")
        self.assertTrue(arquivo.exists())


class TesteInterfaceBackupExterno(unittest.TestCase):
    def setUp(self):
        from src.ui import utilitarios_ui
        self.ui = utilitarios_ui
        self.ctx = mock.Mock()
        self.ctx.banco.cfg.return_value = ""

    def test_senhas_diferentes_nao_alteram_configuracao(self):
        with mock.patch.object(self.ui.tema, "escolher", return_value="configurar"), \
                mock.patch.object(self.ui.filedialog, "askdirectory", return_value="C:\\Backup"), \
                mock.patch.object(self.ui.tema, "pedir_texto", side_effect=[SENHA, "diferente"]), \
                mock.patch.object(self.ui.tema, "aviso") as aviso:
            self.ui.backup_externo(None, self.ctx)
        self.ctx.utilitarios.configurar_backup_externo.assert_not_called()
        aviso.assert_called_once()

    def test_cancelar_restauracao_nao_altera_banco(self):
        with mock.patch.object(self.ui.tema, "escolher", return_value="recuperar"), \
                mock.patch.object(self.ui.filedialog, "askopenfilename", return_value="C:\\copia.pdvbkp"), \
                mock.patch.object(self.ui.tema, "pedir_texto", return_value=SENHA), \
                mock.patch.object(self.ui.tema, "confirmar", return_value=False):
            self.ui.backup_externo(None, self.ctx)
        self.ctx.utilitarios.pedir_restauracao_externa.assert_not_called()

    def test_backup_local_nao_oculta_falha_externa(self):
        self.ctx.utilitarios.situacao_backup.return_value = ("aviso", "A cópia externa falhou.")
        with mock.patch.object(self.ui.tema, "tratar", return_value=(True, "local.db")), \
                mock.patch.object(self.ui.tema, "mensagem") as mensagem:
            self.ui.executar(None, self.ctx, "backup")
        self.assertIn("externa falhou", mensagem.call_args.args[1])
