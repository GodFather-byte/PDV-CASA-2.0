"""Tela Tk real da auditoria: consulta protegida, páginas e detalhes."""
from __future__ import annotations

import gc
import tkinter as tk
from unittest.mock import patch

from src.controllers.acesso_controller import AcessoController
from src.controllers.cadastro_controller import CadastroController
from src.core.erros import ErroPermissao
from src.ui import tema
from src.ui.auditoria_ui import JanelaAuditoria
from src.ui.contexto import Contexto
from tests.base import BaseTeste


class TesteAuditoriaUI(BaseTeste):
    def setUp(self):
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as erro:
            self.skipTest(f"Sem ambiente gráfico: {erro}")
        self.root.withdraw()
        tema.aplicar_tema(self.root)
        self.addCleanup(self.fechar)
        self.ctx = Contexto(self.banco, AcessoController(self.banco).operador(self.operador_adm()))
        erros = patch("src.ui.auditoria_ui.tema.erro")
        self.erro = erros.start()
        self.addCleanup(erros.stop)
        self.janela = None

    def fechar(self):
        self.root.destroy()
        self.janela = self.ctx = self.root = None
        gc.collect()

    def abrir(self):
        self.janela = JanelaAuditoria(self.root, self.ctx)
        self.root.update()
        return self.janela

    def criar_eventos(self, quantidade):
        for n in range(quantidade):
            self.banco.inserir("grupos", {"nome": f"GRUPO {n:03}"})

    def test_abre_sem_eventos_e_mostra_consulta_vazia(self):
        janela = self.abrir()
        self.assertEqual(janela.grade.total(), 0)
        self.assertIn("nenhum evento", janela.situacao.cget("text"))
        self.assertEqual(str(janela.anterior.cget("state")), "disabled")
        self.assertEqual(str(janela.proxima.cget("state")), "disabled")
        self.erro.assert_not_called()

    def test_grade_e_detalhe_antes_depois_somente_leitura(self):
        produto = self.novo_produto(preco=800)
        CadastroController(self.banco).salvar("produtos", {"preco_cent": "9,00"}, produto)
        janela = self.abrir()
        self.assertEqual(janela.grade.total(), 2)
        texto = janela.detalhe.get("1.0", "end")
        self.assertIn("preco_alterado", texto)
        self.assertIn("ANTES", texto)
        self.assertIn('"preco_cent": 800', texto)
        self.assertIn('"preco_cent": 900', texto)
        self.assertEqual(str(janela.detalhe.cget("state")), "disabled")
        janela.detalhe.insert("end", "ALTERACAO INDEVIDA")
        self.assertNotIn("ALTERACAO INDEVIDA", janela.detalhe.get("1.0", "end"))
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (produto,)), 900)
        self.erro.assert_not_called()

    def test_paginas_100_proxima_anterior_e_fim(self):
        self.criar_eventos(201)
        janela = self.abrir()
        self.assertEqual(janela.grade.total(), 100)
        primeira = janela.grade.tree.get_children()[0]
        janela.proxima.invoke()
        self.root.update()
        self.assertEqual(janela.offset, 100)
        self.assertEqual(janela.grade.total(), 100)
        self.assertNotIn(primeira, janela.grade.tree.get_children())
        janela.proxima.invoke()
        self.root.update()
        self.assertEqual(janela.offset, 200)
        self.assertEqual(janela.grade.total(), 1)
        self.assertEqual(str(janela.proxima.cget("state")), "disabled")
        janela.anterior.invoke()
        janela.anterior.invoke()
        self.assertEqual(janela.offset, 0)
        self.assertEqual(janela.grade.tree.get_children()[0], primeira)
        self.erro.assert_not_called()

    def test_pagina_exatamente_cheia_seguida_de_vazia_permite_voltar(self):
        self.criar_eventos(100)
        janela = self.abrir()
        janela.proxima.invoke()
        self.assertEqual(janela.grade.total(), 0)
        self.assertIn("nenhum evento", janela.situacao.cget("text"))
        self.assertEqual(str(janela.proxima.cget("state")), "disabled")
        self.assertEqual(str(janela.anterior.cget("state")), "normal")
        janela.anterior.invoke()
        self.assertEqual(janela.grade.total(), 100)

    def test_filtros_periodo_acao_e_limpar_voltam_primeira_pagina(self):
        self.criar_eventos(101)
        self.avancar(days=1)
        self.banco.executar("UPDATE grupos SET nome = 'NOVO NOME' WHERE id = 1")
        janela = self.abrir()
        janela.proxima.invoke()
        janela.inicio.set("2026-10-04")
        janela.fim.set("2026-10-04")
        janela.acao.set("alteracao")
        janela.consultar()
        self.assertEqual(janela.offset, 0)
        self.assertEqual(janela.grade.total(), 1)
        self.assertIn("NOVO NOME", janela.detalhe.get("1.0", "end"))
        janela.limpar()
        self.assertEqual(janela.grade.total(), 100)
        self.assertEqual((janela.inicio.get(), janela.fim.get(), janela.acao.get()), ("", "", ""))
        self.erro.assert_not_called()

    def test_paginacao_preserva_filtros_aplicados_ate_consultar(self):
        self.criar_eventos(101)
        janela = self.abrir()
        janela.inicio.set("invalido ainda nao consultado")
        janela.proxima.invoke()
        self.assertEqual(janela.offset, 100)
        self.assertEqual(janela.grade.total(), 1)
        self.erro.assert_not_called()

    def test_periodo_invalido_exibe_erro_e_limpa_detalhe_antigo(self):
        self.criar_eventos(1)
        janela = self.abrir()
        janela.inicio.set("31/12/2026")
        self.assertFalse(janela.consultar())
        self.erro.assert_called_once()
        self.assertIn("ISO", self.erro.call_args.args[1])
        self.assertEqual(janela.grade.total(), 0)
        self.assertEqual(janela.detalhe.get("1.0", "end").strip(), "")
        self.assertIn("não concluída", janela.situacao.cget("text"))
        janela.limpar()
        self.assertEqual(janela.grade.total(), 1)

    def test_acesso_negado_antes_do_construtor_nao_deixa_janela_orfa(self):
        self.criar_eventos(1)
        self.ctx.operador = None
        janelas = self.root.winfo_children()
        with self.assertRaises(ErroPermissao):
            self.abrir()
        self.assertEqual(self.root.winfo_children(), janelas)
        self.erro.assert_not_called()

    def test_rota_tema_tratar_mostra_permissao_sem_janela_orfa(self):
        self.ctx.operador = None
        ok, _ = tema.tratar(self.root, JanelaAuditoria, self.root, self.ctx)
        self.assertFalse(ok)
        self.assertEqual(self.root.winfo_children(), [])
        self.erro.assert_called_once()
        self.assertIn("administrador", self.erro.call_args.args[1])

    def test_revogacao_na_consulta_remove_dados_da_pagina_anterior(self):
        self.criar_eventos(1)
        janela = self.abrir()
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.ctx.operador.id,))
        janela.consultar()
        self.assertEqual(janela.grade.total(), 0)
        self.assertFalse(janela.eventos)
        self.assertEqual(janela.detalhe.get("1.0", "end").strip(), "")
        self.erro.assert_called_once()

    def test_revogacao_na_selecao_nao_reabre_retrato(self):
        self.criar_eventos(2)
        janela = self.abrir()
        self.ctx.operador = None
        janela.grade.selecionar_indice(1)
        janela.detalhar()
        self.assertEqual(janela.grade.total(), 0)
        self.assertEqual(janela.detalhe.get("1.0", "end").strip(), "")
        self.erro.assert_called_once()

    def test_erro_inesperado_de_consulta_nao_e_silenciado(self):
        janela = self.abrir()
        with patch("src.controllers.auditoria_controller.AuditoriaController.listar",
                   side_effect=RuntimeError("Falha ao ler banco")):
            self.assertFalse(janela.consultar())
        self.erro.assert_called_once_with(janela, "Falha ao ler banco", "Auditoria")

    def test_consulta_utiliza_controller_protegido_e_limite_100(self):
        from src.controllers.auditoria_controller import AuditoriaController
        with patch.object(AuditoriaController, "listar", autospec=True, return_value=[]) as listar:
            janela = self.abrir()
            chamada = listar.call_args
            self.assertIs(chamada.args[0].banco, self.banco)
            self.assertEqual(chamada.kwargs, {
                "inicio": None, "fim": None, "acao": None, "limite": 100, "offset": 0})
        self.assertEqual(janela.grade.total(), 0)

    def test_sistema_tem_origem_e_operador_ausente_na_grade(self):
        self.ctx.operador = None
        self.criar_eventos(1)
        self.ctx.operador = AcessoController(self.banco).operador(self.operador_adm())
        janela = self.abrir()
        valores = janela.grade.valores(janela.grade.tree.get_children()[0])
        self.assertEqual(valores[2:4], ["—", "sistema"])
