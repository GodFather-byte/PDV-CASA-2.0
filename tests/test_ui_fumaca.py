"""Teste de fumaça da interface Tkinter: abre cada janela contra um banco em memória e fecha.

Pega erros de integração entre telas e controladores (método inexistente, coluna errada,
atributo faltando) que os testes de controlador não enxergam. Pula se não houver Tk/display.
"""
from __future__ import annotations

import gc
import tkinter as tk
import unittest

from src.controllers.acesso_controller import AcessoController
from src.ui import app as modulo_app
from src.ui import tema
from src.ui.contexto import Contexto
from tests.base import BaseTeste


def _tk_disponivel() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(_tk_disponivel(), "Tk indisponível neste ambiente")
class TesteFumacaUI(BaseTeste):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self._fechar_tk)
        tema.aplicar_tema(self.root)
        self.ctx = Contexto(self.banco)
        adm = self.banco.valor("SELECT nome FROM operadores WHERE nome = 'ADM'")
        senha = self.banco.valor("SELECT senha FROM operadores WHERE nome = 'ADM'") or ""
        try:
            self.ctx.operador = AcessoController(self.banco).autenticar(adm, senha)
        except Exception:
            self.ctx.operador = AcessoController(self.banco).operador(self.operador_adm())

    def _fechar_tk(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self.root = None
        gc.collect()        # o lixo do Tk morre na thread principal (ver BaseUI._fechar em test_ui.py)

    def _abrir_e_fechar(self, criar):
        janela = criar()
        self.root.update()
        self.assertTrue(janela.winfo_exists())
        janela.destroy()

    def test_cadastros_abrem(self):
        from src.ui.cadastros_tk import JanelaCadastro
        for chave, _ in modulo_app.CADASTROS:
            if chave == "composicao":
                continue
            with self.subTest(cadastro=chave):
                self._abrir_e_fechar(lambda c=chave: JanelaCadastro(self.root, self.ctx, c))

    def test_composicao_abre(self):
        from src.ui.composicao_ui import JanelaComposicao
        self._abrir_e_fechar(lambda: JanelaComposicao(self.root, self.ctx))

    def test_lancamentos_abrem(self):
        from src.ui.lancamentos_ui import JanelaContas, JanelaEstoque
        for classe in (JanelaContas, JanelaEstoque):
            with self.subTest(janela=classe.__name__):
                self._abrir_e_fechar(lambda c=classe: c(self.root, self.ctx))

    def test_relatorios_do_menu_abrem(self):
        from src.ui.relatorios_ui import abrir_relatorio
        for _, itens in modulo_app.RELATORIOS:
            for chave, rotulo, _mod in itens:
                with self.subTest(relatorio=chave):
                    self._abrir_e_fechar(lambda c=chave: abrir_relatorio(self.root, self.ctx, c))

    def test_caixa_abre_com_turno_aberto(self):
        from src.ui.caixa_ui import JanelaCaixa
        self.ctx.turnos.abrir(self.ctx.operador_id, self.ctx.turnos.numero_sugerido(), 0)
        self._abrir_e_fechar(lambda: JanelaCaixa(self.root, self.ctx))

    def test_clientes_e_entregas_abrem(self):
        from src.ui.clientes_ui import JanelaClientes, JanelaEntregas
        for classe in (JanelaClientes, JanelaEntregas):
            with self.subTest(janela=classe.__name__):
                self._abrir_e_fechar(lambda c=classe: c(self.root, self.ctx, modal=False))

    def test_modulos_do_menu_existem_no_banco(self):
        # Todo item de menu do app precisa ter módulo de acesso cadastrado, senão nunca aparece.
        conhecidos = {m["modulo"] for m in self.ctx.acesso.modulos()}
        esperados = {f"cad_{c}" if c != "planos_contas" else "cad_plano_contas"
                     for c, _ in modulo_app.CADASTROS}
        esperados |= {m for _, _, m in modulo_app.LANCAMENTOS}
        esperados |= {m for _, itens in modulo_app.RELATORIOS for _, _, m in itens}
        esperados |= {m for _, _, m in modulo_app.UTILITARIOS}
        esperados |= {m for _, _, m in modulo_app.CONFIGURACOES}
        self.assertEqual(sorted(esperados - conhecidos), [])


if __name__ == "__main__":
    unittest.main()
