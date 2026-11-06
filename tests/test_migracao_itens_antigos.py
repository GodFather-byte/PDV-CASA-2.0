"""Atualização de bancos anteriores à v17 com as 14 colunas originais dos itens."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from src.database import esquema
from src.database.conexao import BancoDados


ITENS_ANTIGOS = """CREATE TABLE itens_venda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venda_id INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade REAL NOT NULL,
    preco_unit_cent INTEGER NOT NULL,
    total_cent INTEGER NOT NULL,
    cobra_servico INTEGER NOT NULL DEFAULT 1,
    observacao TEXT,
    comissao_cent INTEGER NOT NULL DEFAULT 0,
    partes INTEGER NOT NULL DEFAULT 1,
    cancelado INTEGER NOT NULL DEFAULT 0,
    cancelado_em TEXT,
    operador_id INTEGER REFERENCES operadores(id),
    criado_em TEXT NOT NULL
)"""


def criar_antigo(caminho, versao):
    with closing(sqlite3.connect(caminho)) as con:
        con.execute("PRAGMA foreign_keys = ON")
        for ddl in esquema.TABELAS:
            if "CREATE TRIGGER" in ddl or ddl == esquema.PRODUTOS_HISTORICO_DDL:
                continue
            if ddl.startswith("CREATE TABLE IF NOT EXISTS itens_venda ("):
                ddl = ITENS_ANTIGOS
            con.execute(ddl.replace("REFERENCES produtos_historico(id)", "REFERENCES produtos(id)"))
        con.execute("INSERT INTO config(chave,valor) VALUES ('dado_da_loja','PRESERVAR')")
        con.execute("INSERT INTO grupos(id,nome) VALUES (1,'BEBIDAS')")
        con.execute("INSERT INTO subgrupos(id,nome,grupo_id) VALUES (1,'BEBIDAS',1)")
        con.execute("INSERT INTO unidades(id,nome,abreviatura) VALUES (1,'UNIDADE','UN')")
        con.execute("INSERT INTO produtos(id,codigo,nome,subgrupo_id,unidade_id,qt_atual) "
                    "VALUES (8,'0000000000008','PRODUTO ANTIGO',1,1,9)")
        for venda, status in ((1, 'fechada'), (2, 'aberta')):
            con.execute("INSERT INTO vendas(id,uuid,status,aberta_em,total_cent) VALUES (?,?,?,?,?)",
                        (venda, f'venda-{venda}', status, '2026-10-15 21:00:00', 3000))
            con.execute("INSERT INTO itens_venda(id,venda_id,produto_id,quantidade,preco_unit_cent,total_cent,"
                        "observacao,comissao_cent,criado_em) VALUES (?,?,8,2,1500,3000,'SEM GELO',250,?)",
                        (41 + venda, venda, '2026-10-15 21:00:00'))
        con.execute("INSERT INTO itens_venda_partes(id,item_id,produto_id,fracao) VALUES (55,42,8,1)")
        con.execute("INSERT INTO movimentos_estoque(id,produto_id,tipo,quantidade,qt_apos,criado_em) "
                    "VALUES (7,8,'venda',-2,9,'2026-10-15 21:00:00')")
        con.execute("INSERT INTO lancamentos_estoque(id,tipo,data,criado_em) "
                    "VALUES (1,'inicial','2026-10-15','2026-10-15 21:00:00')")
        con.execute("INSERT INTO itens_estoque(id,lancamento_id,produto_id,quantidade) VALUES (10,1,8,11)")
        con.execute("UPDATE sqlite_sequence SET seq = 100 WHERE name='itens_venda'")
        con.execute(f"PRAGMA user_version = {versao}")
        con.commit()


class TestMigracaoItensAntigos(unittest.TestCase):
    def test_atualiza_itens_com_14_colunas_sem_perder_valores_ou_relacoes(self):
        for versao in (12, 16):
            with self.subTest(versao=versao), tempfile.TemporaryDirectory() as pasta:
                caminho = Path(pasta) / 'loja.db'
                criar_antigo(caminho, versao)
                with closing(sqlite3.connect(caminho)) as con:
                    con.row_factory = sqlite3.Row
                    antigos = [dict(r) for r in con.execute('SELECT * FROM itens_venda ORDER BY id')]
                    self.assertEqual(len(antigos[0]), 14)
                b = BancoDados(caminho)
                try:
                    self.assertEqual(b.valor('PRAGMA user_version'), esquema.VERSAO_ESQUEMA)
                    self.assertEqual(b.cfg('dado_da_loja'), 'PRESERVAR')
                    for antigo in antigos:
                        novo = dict(b.um('SELECT * FROM itens_venda WHERE id=?', (antigo['id'],)))
                        self.assertEqual({k: novo[k] for k in antigo}, antigo)
                        self.assertEqual(novo['temperatura'], 'natural')
                        self.assertEqual(novo['status_preparo'], 'pendente')
                        self.assertIsNone(novo['preco_base_cent'])
                        self.assertIsNone(novo['regra_preco_json'])
                    self.assertEqual(b.valor('SELECT qt_atual FROM produtos WHERE id=8'), 9)
                    self.assertEqual(b.valor('SELECT item_id FROM itens_venda_partes WHERE id=55'), 42)
                    self.assertEqual(b.valor('SELECT quantidade FROM itens_estoque WHERE id=10'), 11)
                    self.assertEqual(b.valor('SELECT quantidade FROM movimentos_estoque WHERE id=7'), -2)
                    self.assertEqual(b.valor("SELECT seq FROM sqlite_sequence WHERE name='itens_venda'"), 100)
                    self.assertEqual(b.todos('PRAGMA foreign_key_check'), [])
                    self.assertEqual(b.valor('PRAGMA integrity_check'), 'ok')
                finally:
                    b.fechar()
                backups = list(Path(pasta).glob(f'loja.db.antes-migracao-v{versao}-*.bak'))
                self.assertEqual(len(backups), 1)
                with closing(sqlite3.connect(backups[0])) as con:
                    self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], versao)
                    self.assertEqual(len(con.execute('PRAGMA table_info(itens_venda)').fetchall()), 14)
                    self.assertEqual(con.execute('SELECT total_cent FROM itens_venda WHERE id=42').fetchone()[0], 3000)
                b = BancoDados(caminho)
                try:
                    self.assertEqual(b.valor('SELECT COUNT(*) FROM itens_venda'), 2)
                    self.assertEqual(b.todos('PRAGMA foreign_key_check'), [])
                finally:
                    b.fechar()
                self.assertEqual(list(Path(pasta).glob('*.antes-migracao-*.bak')), backups)

    def test_falha_reverte_copia_e_permite_tentar_novamente(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'loja.db'
            criar_antigo(caminho, 16)
            passos = esquema.MIGRACOES[17] + ['SELECT * FROM falha_simulada']
            with mock.patch.dict(esquema.MIGRACOES, {17: passos}):
                with self.assertRaisesRegex(sqlite3.OperationalError, 'falha_simulada'):
                    BancoDados(caminho)
            with closing(sqlite3.connect(caminho)) as con:
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 16)
                self.assertEqual(len(con.execute('PRAGMA table_info(itens_venda)').fetchall()), 14)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM itens_venda').fetchone()[0], 2)
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor('SELECT COUNT(*) FROM itens_venda'), 2)
            finally:
                b.fechar()

    def test_campo_sem_destino_interrompe_sem_descartar_dados(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'loja.db'
            criar_antigo(caminho, 16)
            with closing(sqlite3.connect(caminho)) as con:
                con.execute('ALTER TABLE itens_venda ADD COLUMN informacao_extra TEXT')
                con.execute("UPDATE itens_venda SET informacao_extra='PRESERVAR'")
                con.commit()
            with self.assertRaisesRegex(ValueError, 'colunas sem destino'):
                BancoDados(caminho)
            with closing(sqlite3.connect(caminho)) as con:
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 16)
                self.assertEqual(con.execute('SELECT informacao_extra FROM itens_venda WHERE id=42').fetchone()[0],
                                 'PRESERVAR')
                self.assertEqual(con.execute('SELECT COUNT(*) FROM itens_venda_partes').fetchone()[0], 1)
