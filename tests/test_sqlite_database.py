import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.controllers.produto_controller import ProdutoController
from src.database.conexao import BancoDados
from src.database.esquema import VERSAO_ESQUEMA
from src.database import esquema
from tests.base import BaseTeste


class BancoSQLiteTests(BaseTeste):
    def test_migracao_em_arquivo_guarda_snapshot_com_versao_e_dados_anteriores(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "migrar.db"
            banco = BancoDados(caminho)
            banco.cfg_set("dado_preservado", "ANTES")
            versao_anterior = esquema.VERSAO_ESQUEMA - 1
            banco.executar(f"PRAGMA user_version = {versao_anterior}")
            banco.fechar()
            migrado = BancoDados(caminho)
            try:
                self.assertEqual(migrado.valor("PRAGMA user_version"), esquema.VERSAO_ESQUEMA)
                self.assertEqual(migrado.cfg("dado_preservado"), "ANTES")
            finally:
                migrado.fechar()
            backups = list(Path(pasta).glob(f"migrar.db.antes-migracao-v{versao_anterior}-*.bak"))
            self.assertEqual(len(backups), 1)
            copia = sqlite3.connect(backups[0])
            try:
                self.assertEqual(copia.execute("PRAGMA user_version").fetchone()[0], versao_anterior)
                self.assertEqual(copia.execute(
                    "SELECT valor FROM config WHERE chave='dado_preservado'").fetchone()[0], "ANTES")
                self.assertEqual(copia.execute("PRAGMA quick_check").fetchone()[0], "ok")
            finally:
                copia.close()
            reaberto = BancoDados(caminho)
            reaberto.fechar()
            self.assertEqual(list(Path(pasta).glob("*.antes-migracao-*.bak")), backups)

    def test_falha_no_backup_impede_ddl_e_migracao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "migrar.db"
            banco = BancoDados(caminho)
            versao_anterior = esquema.VERSAO_ESQUEMA - 1
            banco.executar(f"PRAGMA user_version = {versao_anterior}")
            banco.fechar()
            conectar = sqlite3.connect

            def falhar_backup(destino, *args, **kw):
                if ".antes-migracao-" in str(destino):
                    raise sqlite3.OperationalError("disco cheio")
                return conectar(destino, *args, **kw)

            with mock.patch.object(sqlite3, "connect", side_effect=falhar_backup), \
                    mock.patch.object(BancoDados, "_criar_esquema") as criar:
                with self.assertRaisesRegex(sqlite3.OperationalError, "disco cheio"):
                    BancoDados(caminho)
            criar.assert_not_called()
            self.assertEqual(list(Path(pasta).glob("*.antes-migracao-*")), [])
            con = conectar(caminho)
            try:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], versao_anterior)
            finally:
                con.close()

    def test_banco_novo_e_memoria_nao_geram_backup_de_migracao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "novo.db"
            banco = BancoDados(caminho)
            banco.fechar()
            self.assertEqual(list(Path(pasta).glob("*.antes-migracao-*")), [])
        self.banco.executar("PRAGMA user_version = 1")
        with mock.patch.object(sqlite3, "connect") as conectar:
            self.banco._guardar_antes_migracao()
        conectar.assert_not_called()

    def test_banco_futuro_e_recusado_sem_alterar_bytes_ou_journal(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "futuro.db"
            con = sqlite3.connect(caminho)
            con.execute("CREATE TABLE dado_futuro (valor TEXT)")
            con.execute("INSERT INTO dado_futuro VALUES ('preservar')")
            con.execute(f"PRAGMA user_version = {esquema.VERSAO_ESQUEMA + 1}")
            con.commit()
            con.close()
            original = caminho.read_bytes()
            with self.assertRaisesRegex(ValueError, "superior"):
                BancoDados(caminho)
            self.assertEqual(caminho.read_bytes(), original)
            self.assertFalse(Path(str(caminho) + "-wal").exists())
            con = sqlite3.connect(caminho)
            try:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], esquema.VERSAO_ESQUEMA + 1)
                self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                self.assertEqual(con.execute("SELECT valor FROM dado_futuro").fetchone()[0], "preservar")
            finally:
                con.close()

    def test_migracao_parcial_nao_repete_etapa_concluida(self):
        banco = self.banco
        banco.executar("PRAGMA user_version = 1")
        migracoes = {2: ["CREATE TABLE etapa_teste (id INTEGER PRIMARY KEY)"],
                     3: ["INSERT INTO tabela_inexistente VALUES (1)"]}
        with mock.patch.object(esquema, "VERSAO_ESQUEMA", 3), mock.patch.object(esquema, "MIGRACOES", migracoes):
            with self.assertRaises(sqlite3.OperationalError):
                banco._criar_esquema()
            self.assertEqual(banco.valor("PRAGMA user_version"), 2)
            migracoes[3] = [("coluna", "etapa_teste", "nome", "TEXT"),
                            "INSERT INTO etapa_teste (id, nome) VALUES (1, 'preservado')"]
            banco._criar_esquema()
            banco._criar_esquema()
            self.assertEqual(banco.valor("SELECT COUNT(*) FROM etapa_teste"), 1)
            self.assertEqual(banco.valor("PRAGMA user_version"), 3)

    def test_migracao_de_coluna_existente_e_reabertura_preservam_dados(self):
        self.banco.executar("CREATE TABLE etapa_teste (id INTEGER PRIMARY KEY, nome TEXT)")
        self.banco.executar("INSERT INTO etapa_teste VALUES (1, 'preservado')")
        self.banco.executar("PRAGMA user_version = 1")
        with mock.patch.object(esquema, "VERSAO_ESQUEMA", 2), \
                mock.patch.object(esquema, "MIGRACOES", {2: [("coluna", "etapa_teste", "nome", "TEXT")]}):
            self.banco._criar_esquema()
            self.banco._criar_esquema()
        self.assertEqual(self.banco.valor("SELECT nome FROM etapa_teste"), "preservado")

    def test_busca_por_codigo_e_preco_promocional(self):
        self.novo_produto("Refrigerante", preco=850, codigo="789", promo_de="03/10/2026", promo_ate="03/10/2026",
                          promo_preco_cent="7,50")
        produtos = ProdutoController(self.banco)
        produto = produtos.buscar_codigo("789")
        self.assertEqual(produto["nome"], "Refrigerante")
        self.assertEqual(produtos.preco_vigente(produto), 750)

    def test_tabela_mesas_do_prototipo_some_na_v10(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "v9.db"
            b = BancoDados(caminho)
            b.executar("CREATE TABLE mesas (id INTEGER PRIMARY KEY, numero INTEGER)")    # como estava no banco v9
            b.executar("PRAGMA user_version = 9")
            b.fechar()
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertIsNone(b.valor("SELECT name FROM sqlite_master WHERE name = 'mesas'"))
            finally:
                b.fechar()

    def test_arquiva_banco_legado_e_cria_esquema_novo(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "legado.db"
            legado = sqlite3.connect(caminho)
            legado.executescript(
                """
                CREATE TABLE produtos (
                    id INTEGER PRIMARY KEY, codigo_barras TEXT, nome TEXT,
                    preco REAL, estoque_atual INTEGER
                );
                CREATE TABLE vendas (
                    id INTEGER PRIMARY KEY, data_venda TEXT, total_venda REAL,
                    forma_pagamento TEXT, sincronizado INTEGER
                );
                CREATE TABLE itens_venda (
                    id INTEGER PRIMARY KEY, venda_id INTEGER, produto_id INTEGER,
                    quantidade INTEGER, preco_unitario REAL
                );
                CREATE TABLE config (
                    id INTEGER PRIMARY KEY, chave_loja TEXT, licenca_ativa INTEGER
                );
                INSERT INTO produtos VALUES (4, '789', 'Refrigerante', 8.5, 7);
                INSERT INTO vendas VALUES
                    (9, '2026-10-03 09:00:00', 8.5, 'Dinheiro', 0);
                INSERT INTO itens_venda VALUES (12, 9, 4, 1, 8.5);
                INSERT INTO config VALUES (1, 'loja-teste', 1);
                """
            )
            legado.close()

            banco = BancoDados(caminho)
            try:
                self.assertEqual(
                    banco.valor("SELECT COUNT(*) FROM produtos"),
                    0,
                )
                self.assertEqual(
                    banco.conexao.execute("PRAGMA user_version").fetchone()[0],
                    VERSAO_ESQUEMA,
                )
            finally:
                banco.fechar()

            arquivo_backup = next(Path(pasta).glob("legado.db.legado-*.bak"))
            backup = sqlite3.connect(arquivo_backup)
            try:
                self.assertEqual(
                    backup.execute(
                        "SELECT nome, preco FROM produtos WHERE id = 4"
                    ).fetchone(),
                    ("Refrigerante", 8.5),
                )
                self.assertEqual(
                    backup.execute(
                        "SELECT total_venda, forma_pagamento FROM vendas WHERE id = 9"
                    ).fetchone(),
                    (8.5, "Dinheiro"),
                )
            finally:
                backup.close()


if __name__ == "__main__":
    unittest.main()
