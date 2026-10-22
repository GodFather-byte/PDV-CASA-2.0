"""Janelas Tk de retornáveis, com banco real e revalidação de sessão."""
import tkinter as tk

from src.core.erros import ErroPermissao
from src.ui.contexto import Contexto
from src.ui.retornaveis_ui import abrir
from tests.base import BaseTeste


class TestRetornaveisTk(BaseTeste):
    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.cliente_id = self.banco.inserir("clientes", {"numero_consulta": "10", "nome": "ANA"})
        self.produto_id = self.novo_produto("BALDE")
        try:
            self.root = tk.Tk()
        except tk.TclError as erro:
            self.skipTest(str(erro))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def janela(self):
        janela = abrir(self.root, self.ctx)
        janela.cliente.current(0)
        janela.produto.current(0)
        janela.quantidade.insert(0, "2,1234")
        janela.motivo.insert(0, "Entrega combinada")
        return janela

    def test_abrir_retorna_janela_gravar_consultar_e_devolver(self):
        janela = self.janela()
        self.assertTrue(janela.registrar())
        self.assertEqual(len(janela.grade_historico.get_children()), 1)
        self.assertEqual(janela.grade_saldos.item(
            janela.grade_saldos.get_children()[0], "values")[-1], "2,1234")
        janela.tipo.current(1)
        janela.quantidade.insert(0, "0,1234")
        janela.motivo.insert(0, "Retorno parcial")
        self.assertTrue(janela.registrar())
        self.assertEqual(len(janela.grade_historico.get_children()), 2)

    def test_abertura_sem_sessao_ou_operador_inativo_recusada(self):
        operador = self.ctx.operador
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            abrir(self.root, self.ctx)
        self.ctx.operador = operador
        self.banco.atualizar("operadores", operador.id, {"ativo": 0})
        with self.assertRaises(ErroPermissao):
            abrir(self.root, self.ctx)
        self.assertEqual(len(self.root.winfo_children()), 0)

    def test_revogacao_revalidada_em_gravacao_atualizacao_e_reabertura(self):
        janela = self.janela()
        self.assertTrue(janela.registrar())
        self.banco.atualizar("operadores", self.ctx.operador_id, {"nivel": 0})
        with self.assertRaises(ErroPermissao):
            janela.exigir_acesso()
        self.assertFalse(janela.registrar())
        self.assertFalse(janela.atualizar())
        self.assertEqual(janela.grade_historico.get_children(), ())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 1)

    def test_inativacao_operador_e_saida_sessao_impedem_gravacao(self):
        janela = self.janela()
        self.banco.atualizar("operadores", self.ctx.operador_id, {"ativo": 0})
        self.assertFalse(janela.registrar())
        self.ctx.operador = None
        self.assertFalse(janela.registrar())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 0)

    def test_cliente_inativo_consulta_historico_mas_nao_grava(self):
        janela = self.janela()
        self.assertTrue(janela.registrar())
        self.banco.atualizar("clientes", self.cliente_id, {"ativo": 0})
        self.assertTrue(janela.atualizar())
        self.assertIn("(inativo)", janela.cliente.get())
        janela.quantidade.insert(0, "1")
        janela.motivo.insert(0, "Teste")
        self.assertFalse(janela.registrar())
        self.assertEqual(len(janela.grade_historico.get_children()), 1)

    def test_devolucao_excessiva_e_quantidade_invalida_preservam_formulario(self):
        janela = self.janela()
        janela.tipo.current(1)
        self.assertFalse(janela.registrar())
        self.assertEqual(janela.quantidade.get(), "2,1234")
        janela.tipo.current(0)
        janela.quantidade.delete(0, "end")
        janela.quantidade.insert(0, "nan")
        self.assertFalse(janela.registrar())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 0)
