"""Verificação de backup: teste de restauração ISOLADO, sem tocar no banco em uso."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers.utilitario_controller import UtilitarioController
from src.core import backup_seguro
from src.core.erros import ErroNegocio, ErroPermissao
from src.database import esquema, protecao
from src.database.conexao import BancoDados
from src.ui.contexto import Contexto
from tests.base import BaseTeste

SENHA = "recuperacao-teste-2026"
CHAVES = ("backup_teste_restauracao_em", "backup_teste_restauracao_ok",
          "backup_teste_restauracao_arquivo", "backup_teste_restauracao_erro")


def resumo(caminho: Path) -> str:
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


class BaseVerificacao(BaseTeste):
    def setUp(self):
        super().setUp()
        self.pasta = Path(__file__).parent / f".verificar-backup-{uuid4().hex}"
        self.pasta.mkdir()
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.novo_produto("PRODUTO TESTE", 350)
        self.producao = self.pasta / "producao.db"
        self.banco.copiar_para(str(self.producao))
        self.banco = BancoDados(str(self.producao))
        self.addCleanup(self.banco.fechar)
        self.backups = self.pasta / "backups"
        self.backups.mkdir()
        self.banco.cfg_set("pasta_backup", str(self.backups))
        self.banco.cfg_set("pasta_backup_extra", "")
        self.banco.cfg_set("backup_externo_pasta", "")
        self.ctrl = UtilitarioController(self.banco, self.operador_adm())

    def gerar_backup(self) -> Path:
        return Path(self.ctrl.backup())

    def orfanizar(self, backup: Path) -> None:
        """Registro sem vínculo, como num banco legado gravado sem foreign_keys."""
        con = sqlite3.connect(backup)
        con.execute("CREATE TABLE filho_legado (id INTEGER PRIMARY KEY, produto_id INTEGER REFERENCES produtos(id))")
        con.executemany("INSERT INTO filho_legado (produto_id) VALUES (?)", [(999991,), (999992,)])
        con.commit()
        con.close()

    def assertSemRestauracaoMarcada(self):
        self.assertFalse(Path(str(self.producao) + "." + protecao.PENDENTE).exists())
        self.assertEqual(list(self.pasta.glob("producao.db.antes-*")), [])


class TesteSanitizar(unittest.TestCase):
    def test_remove_caminhos_segredos_e_quebras(self):
        texto = protecao.sanitizar_erro(
            "[Errno 13] Permission denied: 'C:\\Users\\Dono\\Backup\\x.db'\nsenha minha-senha-secreta "
            "em /home/dono/backup/y.db e \\\\servidor\\pasta\\z.db", "minha-senha-secreta")
        self.assertNotIn("Dono", texto)
        self.assertNotIn("dono", texto)
        self.assertNotIn("servidor", texto)
        self.assertNotIn("minha-senha-secreta", texto)
        self.assertNotIn("\n", texto)
        self.assertIn("<caminho>", texto)
        self.assertIn("***", texto)
        self.assertLessEqual(len(protecao.sanitizar_erro("x" * 999)), 240)

    def test_erro_sem_texto_usa_nome_da_classe(self):
        self.assertEqual(protecao.sanitizar_erro(OSError()), "OSError")


class TesteRestauracaoIsolada(BaseVerificacao):
    def test_backup_valido_aprovado_sem_tocar_producao_nem_backup(self):
        backup = self.gerar_backup()
        antes_backup = resumo(backup)
        arquivos_backup = sorted(p.name for p in self.backups.iterdir())
        pasta_teste = self.pasta / "isolada"
        pasta_teste.mkdir()
        resultado = protecao.testar_restauracao_isolada(backup, esquema.VERSAO_ESQUEMA, (self.producao,),
                                                        pasta_temporaria=pasta_teste)
        self.assertTrue(resultado["ok"], resultado["erro"])
        self.assertEqual(resultado["erro"], "")
        self.assertEqual(resultado["versao"], esquema.VERSAO_ESQUEMA)
        self.assertEqual(resultado["contagens"]["produtos"],
                         self.banco.valor("SELECT COUNT(*) FROM produtos"))
        self.assertIn("fechadas", resultado["vendas"])
        itens = [v[0] for v in resultado["verificacoes"]]
        for item in ("Cópia isolada", "Integridade do backup", "Restauração de teste",
                     "Integridade da cópia restaurada", "Esquema do PDV", "Conferência de dados"):
            self.assertIn(item, itens)
        self.assertTrue(all(ok for _, ok, _ in resultado["verificacoes"]))
        self.assertEqual(resumo(backup), antes_backup)
        self.assertEqual(sorted(p.name for p in self.backups.iterdir()), arquivos_backup)
        self.assertEqual(list(pasta_teste.iterdir()), [], "a pasta temporária deve ser apagada")
        self.assertSemRestauracaoMarcada()

    def test_vinculo_quebrado_aprova_com_aviso_explicito(self):
        backup = self.gerar_backup()
        self.assertEqual(protecao.testar_restauracao_isolada(backup)["avisos"], [])
        self.orfanizar(backup)
        resultado = protecao.testar_restauracao_isolada(backup, esquema.VERSAO_ESQUEMA)
        self.assertTrue(resultado["ok"], resultado["erro"])
        self.assertEqual(len(resultado["avisos"]), 1)
        self.assertIn("2 registro(s) sem vínculo", resultado["avisos"][0])
        self.assertIn("filho_legado sem produtos: 2", resultado["avisos"][0])
        vinculo = [v for v in resultado["verificacoes"] if v[0] == "Vínculos entre tabelas"][0]
        self.assertFalse(vinculo[1])
        self.assertTrue(vinculo[2].startswith("AVISO:"))

    def test_backup_corrompido_reprovado(self):
        backup = self.gerar_backup()
        dados = bytearray(backup.read_bytes())
        for i in range(100, len(dados), 997):
            dados[i] ^= 0xFF
        backup.write_bytes(bytes(dados))
        resultado = protecao.testar_restauracao_isolada(backup, esquema.VERSAO_ESQUEMA)
        self.assertFalse(resultado["ok"])
        self.assertTrue(resultado["erro"])
        self.assertTrue(any(not ok for _, ok, _ in resultado["verificacoes"]))
        self.assertNotIn(str(self.pasta), resultado["erro"])

    def test_arquivo_que_nao_e_sqlite_reprovado(self):
        falso = self.backups / "falso.db"
        falso.write_bytes(b"nao sou um banco" * 500)
        resultado = protecao.testar_restauracao_isolada(falso)
        self.assertFalse(resultado["ok"])
        self.assertIn("Integridade do backup", resultado["erro"])

    def test_vazio_ou_inexistente(self):
        vazio = self.backups / "vazio.db"
        vazio.write_bytes(b"")
        self.assertIn("vazio", protecao.testar_restauracao_isolada(vazio)["erro"])
        self.assertIn("não encontrado", protecao.testar_restauracao_isolada(self.backups / "nada.db")["erro"])

    def test_banco_de_producao_e_wal_recusados(self):
        for alvo in (self.producao, Path(str(self.producao) + "-wal")):
            resultado = protecao.testar_restauracao_isolada(alvo, proibidos=(self.producao,))
            self.assertFalse(resultado["ok"])
            self.assertIn("banco em uso", resultado["erro"])

    def test_banco_sem_tabelas_do_pdv_reprovado(self):
        outro = self.backups / "outro.db"
        with sqlite3.connect(outro) as con:
            con.execute("CREATE TABLE qualquer (id INTEGER)")
        con.close()
        resultado = protecao.testar_restauracao_isolada(outro)
        self.assertFalse(resultado["ok"])
        self.assertIn("faltam as tabelas", resultado["erro"])

    def test_versao_futura_reprovada(self):
        backup = self.gerar_backup()
        con = sqlite3.connect(backup)
        con.execute(f"PRAGMA user_version = {esquema.VERSAO_ESQUEMA + 5}")
        con.commit()
        con.close()
        resultado = protecao.testar_restauracao_isolada(backup, esquema.VERSAO_ESQUEMA)
        self.assertFalse(resultado["ok"])
        self.assertIn("Versão do esquema", resultado["erro"])

    def test_erro_de_permissao_na_copia_e_sanitizado(self):
        backup = self.gerar_backup()
        erro = PermissionError(13, "Permission denied", str(backup))
        with mock.patch("src.database.protecao.shutil.copyfile", side_effect=erro):
            resultado = protecao.testar_restauracao_isolada(backup)
        self.assertFalse(resultado["ok"])
        self.assertIn("Permission denied", resultado["erro"])
        self.assertNotIn(str(self.pasta), resultado["erro"])
        self.assertIn("<caminho>", resultado["erro"])

    def test_pasta_temporaria_indisponivel_vira_falha(self):
        backup = self.gerar_backup()
        resultado = protecao.testar_restauracao_isolada(backup, pasta_temporaria=self.pasta / "nao-existe")
        self.assertFalse(resultado["ok"])
        self.assertIn("Erro na verificação", resultado["erro"])


class TesteControladorRecuperacao(BaseVerificacao):
    def test_sem_backup_local_informa(self):
        with self.assertRaisesRegex(ErroNegocio, "Não há backup local"):
            self.ctrl.testar_recuperacao()
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_em"), "")

    def test_padrao_usa_mais_recente_e_registra_resultado(self):
        backup = self.gerar_backup()
        resultado = self.ctrl.testar_recuperacao()
        self.assertTrue(resultado["ok"], resultado["erro"])
        self.assertEqual(resultado["arquivo"], backup.name)
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_ok"), "S")
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_arquivo"), backup.name)
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_erro"), "")
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_em"), resultado["em"])
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM log_eventos WHERE evento = 'backup_restauracao_testada'"), 1)
        self.assertSemRestauracaoMarcada()
        nivel, texto = self.ctrl.situacao_teste_restauracao()
        self.assertEqual(nivel, "ok")
        self.assertIn("aprovado", texto)
        diagnostico = self.ctrl.texto_teste_restauracao(resultado)
        self.assertIn("APROVADO", diagnostico)
        self.assertIn("[OK] Integridade da cópia restaurada", diagnostico)
        self.assertIn("não foi alterado", diagnostico)

    def test_aprovado_com_avisos_nao_e_omitido(self):
        backup = self.gerar_backup()
        self.orfanizar(backup)
        resultado = self.ctrl.testar_recuperacao(str(backup))
        self.assertTrue(resultado["ok"])
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_ok"), "A")
        self.assertIn("sem vínculo", self.banco.cfg("backup_teste_restauracao_erro"))
        nivel, texto = self.ctrl.situacao_teste_restauracao()
        self.assertEqual(nivel, "aviso")
        self.assertIn("APROVADO COM AVISOS", texto)
        diagnostico = self.ctrl.texto_teste_restauracao(resultado)
        self.assertTrue(diagnostico.startswith("APROVADO COM AVISOS"))
        self.assertIn("AVISO: Vínculos entre tabelas", diagnostico)
        self.assertIn("[AVISO] Vínculos entre tabelas", diagnostico)
        self.assertIn("aprovado com avisos", self.banco.valor(
            "SELECT detalhe FROM log_eventos WHERE evento = 'backup_restauracao_testada'"))
        self.assertSemRestauracaoMarcada()

    def test_corrompido_registra_falha_e_situacao_aviso(self):
        backup = self.gerar_backup()
        backup.write_bytes(b"lixo" * 2000)
        resultado = self.ctrl.testar_recuperacao(str(backup))
        self.assertFalse(resultado["ok"])
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_ok"), "N")
        self.assertTrue(self.banco.cfg("backup_teste_restauracao_erro"))
        nivel, texto = self.ctrl.situacao_teste_restauracao()
        self.assertEqual(nivel, "aviso")
        self.assertIn("FALHOU", texto)
        self.assertIn("REPROVADO", self.ctrl.texto_teste_restauracao(resultado))

    def test_banco_em_uso_nunca_e_testado_como_backup(self):
        resultado = self.ctrl.testar_recuperacao(str(self.producao))
        self.assertFalse(resultado["ok"])
        self.assertIn("banco em uso", resultado["erro"])

    def test_situacao_sem_teste_e_teste_antigo(self):
        self.assertEqual(self.ctrl.situacao_teste_restauracao()[0], "sem")
        self.gerar_backup()
        self.ctrl.testar_recuperacao()
        self.avancar(days=31)
        nivel, texto = self.ctrl.situacao_teste_restauracao()
        self.assertEqual(nivel, "aviso")
        self.assertIn("31 dia", texto)
        self.banco.cfg_set("backup_teste_restauracao_em", "data-ruim")
        self.assertEqual(self.ctrl.situacao_teste_restauracao()[0], "aviso")

    def _cifrado(self) -> Path:
        backup = self.gerar_backup()
        cifrado = self.pasta / "externo.pdvbkp"
        backup_seguro.criptografar(backup, cifrado, SENHA)
        return cifrado

    def _sem_senha_gravada(self):
        with sqlite3.connect(self.producao) as con:
            self.assertNotIn(SENHA, "\n".join(con.iterdump()))
        con.close()

    def test_externo_cifrado_valido_com_senha_em_memoria(self):
        cifrado = self._cifrado()
        antes = resumo(cifrado)
        resultado = self.ctrl.testar_recuperacao(str(cifrado), SENHA)
        self.assertTrue(resultado["ok"], resultado["erro"])
        self.assertTrue(resultado["externo"])
        self.assertEqual(resultado["verificacoes"][0][0], "Descriptografia e autenticação")
        self.assertEqual(self.banco.cfg("backup_externo_verificado_em"), resultado["em"])
        self.assertEqual(resumo(cifrado), antes)
        self.assertEqual(list(self.pasta.glob("*.tmp")), [])
        self._sem_senha_gravada()
        self.assertSemRestauracaoMarcada()

    def test_externo_com_avisos_nao_e_comprovado(self):
        backup = self.gerar_backup()
        self.orfanizar(backup)
        cifrado = self.pasta / "externo.pdvbkp"
        backup_seguro.criptografar(backup, cifrado, SENHA)
        self.banco.cfg_set("backup_externo_verificado_em", "2026-09-01 10:00:00")
        situacao_antes = self.ctrl.situacao_backup()
        resultado = self.ctrl.testar_recuperacao(str(cifrado), SENHA)
        self.assertTrue(resultado["ok"])
        self.assertTrue(resultado["avisos"])
        self.assertEqual(self.banco.cfg("backup_externo_verificado_em"), "2026-09-01 10:00:00",
                         "aprovação com avisos não pode promover a data de comprovação")
        self.assertEqual(self.ctrl.situacao_backup(), situacao_antes)
        self.assertEqual(self.ctrl.situacao_teste_restauracao()[0], "aviso")
        self.assertNotEqual(self.banco.cfg("backup_teste_restauracao_ok"), "S")
        avisos = self.ctrl.verificar_backup_externo(str(cifrado), SENHA)
        self.assertTrue(avisos and "sem vínculo" in avisos[0])

    def test_geracao_externa_com_avisos_nao_comunica_comprovacao(self):
        self.banco.cfg_set("backup_externo_pasta", str(self.pasta / "externo"))
        origem = self.gerar_backup()
        self.orfanizar(origem)
        arquivo = Path(self.ctrl.backup_externo(SENHA, origem=origem))
        self.assertTrue(arquivo.is_file())
        self.assertEqual(self.banco.cfg("backup_externo_verificado_em"), "")
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM log_eventos WHERE evento = 'backup_externo_verificado'"), 0)
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM log_eventos WHERE evento = 'backup_externo_com_avisos'"), 1)
        limpo = Path(self.ctrl.backup_externo(SENHA))
        self.assertTrue(limpo.is_file())
        self.assertTrue(self.banco.cfg("backup_externo_verificado_em"))

    def test_externo_senha_errada_registra_falha_sem_vazar_senha(self):
        cifrado = self._cifrado()
        errada = "senha-errada-bem-longa-2026"
        resultado = self.ctrl.testar_recuperacao(str(cifrado), errada)
        self.assertFalse(resultado["ok"])
        self.assertIn("Descriptografia", resultado["erro"])
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_ok"), "N")
        self.assertEqual(self.banco.cfg("backup_externo_verificado_em"), "")
        with sqlite3.connect(self.producao) as con:
            self.assertNotIn(errada, "\n".join(con.iterdump()))
        con.close()

    def test_externo_senha_curta_nao_registra(self):
        cifrado = self._cifrado()
        with self.assertRaises(ErroNegocio):
            self.ctrl.testar_recuperacao(str(cifrado), "123")
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_em"), "")

    def test_externo_sem_senha_e_sem_configuracao_pede_senha(self):
        cifrado = self._cifrado()
        with self.assertRaisesRegex(ErroNegocio, "Informe a senha"):
            self.ctrl.testar_recuperacao(str(cifrado))

    def test_externo_sem_senha_usa_cofre_configurado(self):
        cifrado = self._cifrado()
        self.banco.cfg_set("backup_externo_pasta", str(self.pasta))
        with mock.patch.object(backup_seguro, "ler_senha", return_value=SENHA) as ler:
            resultado = self.ctrl.testar_recuperacao(str(cifrado))
        ler.assert_called_once()
        self.assertTrue(resultado["ok"], resultado["erro"])
        with mock.patch.object(backup_seguro, "ler_senha", side_effect=OSError("cofre indisponível")):
            with self.assertRaisesRegex(ErroNegocio, "Senha protegida indisponível"):
                self.ctrl.testar_recuperacao(str(cifrado))

    def test_verificar_backup_externo_mantem_contrato(self):
        cifrado = self._cifrado()
        self.assertEqual(self.ctrl.verificar_backup_externo(str(cifrado), SENHA), [])
        with self.assertRaisesRegex(ErroNegocio, "Não foi possível verificar"):
            self.ctrl.verificar_backup_externo(str(cifrado), "senha-errada-bem-longa-2026")


class TesteJanelaQt(BaseVerificacao):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar)

    def _fechar(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        from src.ui_qt.restaurar_backup import JanelaVerificarBackup
        janela = JanelaVerificarBackup(self.ctx)
        self.janelas.append(janela)
        return janela

    def test_lista_verifica_e_mostra_ultima_data(self):
        backup = self.gerar_backup()
        janela = self.janela()
        self.assertEqual(janela.grade.rowCount(), 1)
        self.assertIn("ainda não testada", janela.ultima.text())
        self.assertTrue(janela.verificar())
        self.assertIn("APROVADO", janela.resultado.toPlainText())
        self.assertIn("aprovado em", janela.ultima.text())
        janela.grade.selectRow(0)
        self.assertTrue(janela.verificar_selecionado())
        self.assertEqual(self.banco.cfg("backup_teste_restauracao_arquivo"), backup.name)
        self.assertSemRestauracaoMarcada()

    def test_aprovado_com_avisos_mostra_mensagem(self):
        backup = self.gerar_backup()
        self.orfanizar(backup)
        janela = self.janela()
        self.assertTrue(janela.verificar(str(backup)))
        self.assertIn("APROVADO COM AVISOS", janela.mensagem.text())
        self.assertIn("APROVADO COM AVISOS", janela.ultima.text())
        self.assertIn("AVISO:", janela.resultado.toPlainText())

    def test_reprovado_mostra_aviso(self):
        backup = self.gerar_backup()
        backup.write_bytes(b"x" * 4096)
        janela = self.janela()
        self.assertFalse(janela.verificar(str(backup)))
        self.assertIn("REPROVADO", janela.mensagem.text())

    def test_acesso_revalidado_em_cada_acao(self):
        self.gerar_backup()
        janela = self.janela()
        self.assertTrue(janela.exigir_acesso())
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.operador_adm(),))
        with mock.patch.object(UtilitarioController, "testar_recuperacao") as testar:
            self.assertFalse(janela.verificar())
        testar.assert_not_called()
        self.assertIn("inativo", janela.mensagem.text())
        self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 1 WHERE id = ?", (self.operador_adm(),))
        self.banco.executar("UPDATE acessos SET nivel = 4 WHERE modulo = 'util_backup'")
        with mock.patch.object(UtilitarioController, "testar_recuperacao") as testar:
            self.assertFalse(janela.verificar())
        testar.assert_not_called()
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_sem_permissao_nao_abre(self):
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?", (self.operador_adm(),))
        self.banco.executar("UPDATE acessos SET nivel = 4 WHERE modulo = 'util_backup'")
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_externo_pede_arquivo_e_senha_sem_guardar(self):
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        backup = self.gerar_backup()
        cifrado = self.pasta / "externo.pdvbkp"
        backup_seguro.criptografar(backup, cifrado, SENHA)
        janela = self.janela()
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(cifrado), "")), \
                mock.patch.object(QInputDialog, "getText", return_value=(SENHA, True)):
            self.assertTrue(janela.verificar_externo())
        self.assertNotIn(SENHA, janela.resultado.toPlainText())
        self.assertNotIn(SENHA, str(vars(janela)))
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=("", "")), \
                mock.patch.object(QInputDialog, "getText") as pedir:
            self.assertFalse(janela.verificar_externo())
        pedir.assert_not_called()

    def test_botao_em_utilitarios_abre_verificacao(self):
        from src.ui_qt.utilitarios import JanelaUtilitarios
        utilitarios = JanelaUtilitarios(self.ctx)
        self.janelas.append(utilitarios)
        self.assertIn("verificar_backup", utilitarios.botoes)
        self.assertTrue(utilitarios.verificar_backup())
        self.janelas.append(utilitarios.janela_verificacao)
        self.assertIn("ainda não testada", utilitarios.status.text())


class TesteJanelaTk(BaseVerificacao):
    def setUp(self):
        super().setUp()
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as erro:
            self.skipTest(f"Sem display para Tk: {erro}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())

    def test_janela_tk_verifica_e_revalida(self):
        from src.ui import utilitarios_ui
        self.gerar_backup()
        janela = utilitarios_ui.executar(self.root, self.ctx, "verificar_backup")
        self.assertIsNotNone(janela)
        janela.withdraw()
        self.assertEqual(len(janela.caminhos), 1)
        self.assertTrue(janela.verificar())
        self.assertIn("APROVADO", janela.texto_resultado())
        self.assertIn("aprovado em", janela.ultima.cget("text"))
        janela.grade.selection_set(next(iter(janela.caminhos)))
        self.assertTrue(janela.verificar_selecionado())
        self.orfanizar(Path(next(iter(janela.caminhos.values()))))
        self.assertTrue(janela.verificar_selecionado())
        self.assertIn("APROVADO COM AVISOS", janela.mensagem.cget("text"))
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.operador_adm(),))
        with mock.patch.object(UtilitarioController, "testar_recuperacao") as testar:
            self.assertFalse(janela.verificar())
        testar.assert_not_called()
        self.assertIn("inativo", janela.mensagem.cget("text"))
        self.assertSemRestauracaoMarcada()

    def test_tk_sem_acesso_nao_abre(self):
        from src.ui import utilitarios_ui
        self.ctx.operador = None
        with mock.patch.object(utilitarios_ui.tema, "erro") as erro:
            self.assertIsNone(utilitarios_ui.executar(self.root, self.ctx, "verificar_backup"))
        erro.assert_called_once()


if __name__ == "__main__":
    unittest.main()