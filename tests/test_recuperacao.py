"""Retomada persistente e reserva de impressão, sem periféricos nem banco de loja."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from src.controllers.fila_impressao_controller import FilaImpressao
from src.core.erros import ErroNegocio, ErroPermissao
from src.database.conexao import BancoDados
from src.homologacao import executar
from tests.base import BaseTeste


class _Queda(BaseException):
    pass


class TesteImpressaoInterrompida(BaseTeste):
    def setUp(self):
        super().setUp()
        self.adm = self.operador_adm()
        self.enviados = []
        self.fila = FilaImpressao(self.banco, lambda item, maquina: self.enviados.append(item["id"]))
        self.documento = self.fila.enfileirar("caixa", "teste", b"SEM HARDWARE")

    def test_reserva_persistida_antes_do_envio_e_interrupcao_bloqueia_destino(self):
        def interromper(item, maquina):
            self.assertEqual(self.banco.valor("SELECT status FROM fila_impressao WHERE id = ?",
                                              (item["id"],)), "enviando")
            raise _Queda()
        self.fila.enviador = interromper
        with self.assertRaises(_Queda):
            self.fila.processar()
        self.assertEqual(self.fila.recuperar_interrompidos(), 1)
        self.assertEqual(self.fila.recuperar_interrompidos(), 0)
        self.fila.enfileirar("caixa", "seguinte", b"y")
        remota = self.fila.enfileirar("remota", "cozinha", b"z")
        self.fila.enviador = lambda item, maquina: self.enviados.append(item["id"])
        self.fila.reenviar_todos()
        self.fila.processar()
        self.assertEqual(self.enviados, [remota])
        self.assertEqual(self.fila.texto_indicador()[1], "erro")
        from src.controllers.alertas_controller import AlertasController
        alertas = AlertasController(self.banco).alertas({"operacao"})
        self.assertTrue(any("interrompido" in a["titulo"] and a["nivel"] == "critico" for a in alertas))
        with self.assertRaises(ErroNegocio):
            self.fila.reenviar(self.documento)
        with self.assertRaises(ErroNegocio):
            self.fila.cancelar(self.documento)
        self.fila.limpar_antigos(0)
        self.assertEqual(self.banco.valor("SELECT status FROM fila_impressao WHERE id = ?", (self.documento,)), "incerto")

    def test_papel_confirmado_nao_reenvia_e_decisao_e_auditada(self):
        self.banco.executar("UPDATE fila_impressao SET status = 'incerto' WHERE id = ?", (self.documento,))
        self.fila.conferir_interrompido(self.documento, impresso=True, operador_id=self.adm)
        self.fila.processar()
        self.assertEqual(self.enviados, [])
        self.assertEqual(self.banco.valor("SELECT status FROM fila_impressao WHERE id = ?", (self.documento,)), "enviado")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'impressao_conferida'"), 1)
        with self.assertRaises(ErroNegocio):
            self.fila.conferir_interrompido(self.documento, impresso=False, operador_id=self.adm)

    def test_reenvio_interrompido_so_apos_decisao_explicita(self):
        self.banco.executar("UPDATE fila_impressao SET status = 'incerto' WHERE id = ?", (self.documento,))
        self.fila.conferir_interrompido(self.documento, impresso=False, operador_id=self.adm)
        self.fila.processar()
        self.fila.processar()
        self.assertEqual(self.enviados, [self.documento])

    def test_conferencia_recusa_inativo_e_sem_permissao(self):
        self.banco.executar("UPDATE fila_impressao SET status = 'incerto' WHERE id = ?", (self.documento,))
        with patch("src.controllers.acesso_controller.AcessoController.exigir",
                   side_effect=ErroPermissao("Acesso revogado")):
            with self.assertRaises(ErroPermissao):
                self.fila.conferir_interrompido(self.documento, impresso=False, operador_id=self.adm)
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.adm,))
        with self.assertRaises(ErroNegocio):
            self.fila.conferir_interrompido(self.documento, impresso=True, operador_id=self.adm)
        self.assertEqual(self.banco.valor("SELECT status FROM fila_impressao WHERE id = ?", (self.documento,)), "incerto")

    def test_nao_envia_dentro_da_transacao_de_venda(self):
        with self.banco.transacao(), self.assertRaises(ErroNegocio):
            self.fila.processar()
        self.assertEqual(self.enviados, [])


class TesteHomologacao(BaseTeste):
    def test_roteiro_isolado_mesmo_com_pdv_db_apontando_para_banco_real(self):
        with tempfile.TemporaryDirectory() as pasta:
            producao = Path(pasta) / "producao.db"
            producao.write_bytes(b"NAO ABRIR NEM ALTERAR")
            relatorio = Path(pasta) / "resultado.json"
            with patch.dict(os.environ, {"PDV_DB": str(producao)}), patch("builtins.print"):
                self.assertEqual(executar(str(relatorio)), 0, relatorio.read_text(encoding="utf-8") if relatorio.exists() else "")
            dados = json.loads(relatorio.read_text(encoding="utf-8"))
            self.assertTrue(dados["ok"])
            self.assertTrue(dados["isolado"])
            self.assertEqual(len(dados["cenarios"]), 5)
            self.assertEqual(producao.read_bytes(), b"NAO ABRIR NEM ALTERAR")

    def test_interrupcao_real_do_processo_preserva_commit_e_desfaz_transacao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = str(Path(pasta) / "queda.db")
            banco = BancoDados(caminho)
            banco.fechar()
            codigo = """
import os, sys
from src.database.conexao import BancoDados
from src.controllers.caixa_controller import CaixaController
from src.controllers.cadastro_controller import CadastroController
from src.controllers.turno_controller import TurnoController
b = BancoDados(sys.argv[1], semear=False)
adm = b.valor("SELECT id FROM operadores WHERE nome = 'ADM'")
TurnoController(b).abrir(adm, 1, 0)
c = CaixaController(b, adm)
cad = CadastroController(b)
produto = cad.salvar("produtos", {
    "codigo": cad.proximo_codigo_produto(), "nome": "HOMOLOGACAO",
    "subgrupo_id": b.valor("SELECT id FROM subgrupos LIMIT 1"),
    "unidade_id": b.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'"),
    "preco_cent": "10,00", "controla_estoque": "S"})
b.executar("UPDATE produtos SET qt_atual = 10 WHERE id = ?", (produto,))
venda = c.abrir_balcao()
c.adicionar_item(venda, produto, 2)
dinheiro = b.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'")
c.adicionar_pagamento(venda, dinheiro, 1000)
print(b.valor("SELECT uuid FROM vendas WHERE id = ?", (venda,)), flush=True)
with b.transacao():
    c.adicionar_pagamento(venda, dinheiro, 1000)
    c.fechar(venda)
    os._exit(17)
"""
            filho = subprocess.run([sys.executable, "-c", codigo, caminho], capture_output=True,
                                   text=True, timeout=60)
            self.assertEqual(filho.returncode, 17, filho.stderr)
            banco = BancoDados(caminho, semear=False)
            try:
                self.assertEqual(banco.valor("SELECT COUNT(*) FROM vendas WHERE status = 'aberta'"), 1)
                self.assertEqual(banco.valor("SELECT uuid FROM vendas"), filho.stdout.strip())
                self.assertEqual(banco.valor("SELECT COUNT(*) FROM pagamentos_venda"), 1)
                self.assertEqual(banco.valor("SELECT valor_cent FROM pagamentos_venda"), 1000)
                self.assertIsNone(banco.valor("SELECT cupom FROM vendas"))
                self.assertEqual(banco.valor("SELECT qt_atual FROM produtos WHERE nome = 'HOMOLOGACAO'"), 10)
                self.assertEqual(banco.valor("PRAGMA integrity_check"), "ok")
            finally:
                banco.fechar()

    def test_duas_conexoes_nao_enviam_o_mesmo_documento(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = str(Path(pasta) / "fila.db")
            primeiro = BancoDados(caminho)
            segundo = BancoDados(caminho, semear=False)
            try:
                enviados = []
                concorrente = FilaImpressao(segundo, lambda item, maquina: enviados.append("duplicado"))
                def enviar(item, maquina):
                    self.assertEqual(concorrente.processar()["enviados"], 0)
                    enviados.append(item["id"])
                fila = FilaImpressao(primeiro, enviar)
                documento = fila.enfileirar("caixa", "teste", b"x")
                self.assertEqual(fila.processar()["enviados"], 1)
                self.assertEqual(enviados, [documento])
            finally:
                segundo.fechar()
                primeiro.fechar()
