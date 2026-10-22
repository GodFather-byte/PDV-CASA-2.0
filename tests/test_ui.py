"""Testes de interface Tkinter: abrem as telas com dados reais e conduzem os fluxos do caixa.
Pulados automaticamente se não houver ambiente gráfico."""
from __future__ import annotations

import gc
import shutil
import tempfile
import tkinter as tk
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from tkinter import ttk
from unittest import mock

from src.controllers.cadastro_controller import CadastroController
from src.controllers.entidades import ENTIDADES
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.ui import paleta, tema
from src.ui.contexto import Contexto
from tests.ui_robo import Robo, clicar, entradas


def _tk_disponivel() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(_tk_disponivel(), "sem ambiente gráfico")
class BaseUI(unittest.TestCase):
    def setUp(self):
        fmt.definir_relogio(None)
        paleta.aplicar(paleta.PADRAO)         # um teste que troca o modo claro/escuro não pode vazar para os outros
        self.banco = BancoDados(":memory:")
        self.ctx = Contexto(self.banco)
        self.banco.cfg_set("comissao_em_pontos", "N")     # os testes de tela da comissão digitam reais; pontos têm teste próprio
        self.banco.cfg_set("comissao_paga_do_caixa", "S")  # idem: os testes de pagamento esperam a sangria; o padrão N tem teste
        self.banco.cfg_set("imprimir_saida_ao_pagar", "N")   # um papel por pagamento nos testes antigos; o ticket tem teste próprio
        for chave in ("usar_delivery", "usar_caderneta", "usar_contas"):   # os testes de tela exercitam todos os módulos;
            self.banco.cfg_set(chave, "S")                                # o padrão desligado tem teste próprio (test_modulos)
        # Casa já cadastrada: senão o menu abriria a janela do primeiro acesso no meio dos testes (TesteCadastroDaCasa a testa).
        self.banco.atualizar("loja", 1, {"nome_fantasia": "Casa de Teste"})
        self.ctx.operador = self.ctx.acesso.autenticar("adm", "adm")
        cad = CadastroController(self.banco)
        sub = self.banco.valor("SELECT id FROM subgrupos")
        un = self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
        self.skol = cad.salvar("produtos", {"codigo": "1", "nome": "SKOL", "subgrupo_id": sub, "unidade_id": un,
                                            "preco_cent": "8,00", "controla_estoque": "S"})
        self.agua = cad.salvar("produtos", {"codigo": "2", "nome": "AGUA", "subgrupo_id": sub, "unidade_id": un, "preco_cent": "3,50"})
        self.banco.executar("UPDATE produtos SET qt_atual = 50, estoque_minimo = 10 WHERE id = ?", (self.skol,))
        self.cliente = cad.salvar("clientes", {"numero_consulta": "7", "nome": "WESLEY", "limite_cent": "100,00"})
        self.root = tk.Tk()
        self.root.withdraw()
        tema.aplicar_tema(self.root)
        self.robo = Robo(self.root)
        self.pasta_impressao = tempfile.mkdtemp()            # o histórico de impressão dos testes não vai para a pasta do projeto
        self.ctx.impressao.pasta_saida = lambda: Path(self.pasta_impressao)
        self.addCleanup(shutil.rmtree, self.pasta_impressao, True)
        self.addCleanup(self._fechar)

    def _fechar(self):
        self.robo.parar()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self.banco.fechar()
        # Variáveis e janelas do Tk que ficaram em ciclos precisam morrer AQUI, na thread principal: se o coletor de lixo as
        # pegasse numa thread de fundo (fila de impressão, Telegram), o Tcl cai com "Tcl_AsyncDelete: async handler deleted
        # by the wrong thread" (visto no Windows/Python 3.12).
        self.robo = self.root = self.ctx = None
        gc.collect()

    def sem_travar(self):
        self.assertFalse([l for l in self.robo.log if l.startswith("TRAVADO") or l.startswith("TclError")], self.robo.log)

    def abrir_turno(self):
        return self.ctx.turnos.abrir(self.ctx.operador_id, 1, 10000)


class TesteTelasAbrem(BaseUI):
    def test_todos_os_cadastros_abrem_com_dados(self):
        from src.ui.cadastros_tk import JanelaCadastro
        for chave in ENTIDADES:
            with self.subTest(chave=chave):
                j = JanelaCadastro(self.root, self.ctx, chave)
                j.update()
                esperado = len(self.ctx.cadastros.listar(chave))
                self.assertEqual(j.grade.total(), esperado)
                j.ordenar(); j.update()
                j.destroy()

    def test_gravar_produto_pelo_formulario_e_validacao(self):
        from src.ui.cadastros_tk import JanelaCadastro
        j = JanelaCadastro(self.root, self.ctx, "produtos")
        j.update()
        j.incluir()
        j.campos["nome"].var.set("HEINEKEN")
        j.campos["subgrupo_id"].var.set("DIVERSOS - DIVERSOS")
        j.campos["unidade_id"].var.set("Unidade")
        j.campos["preco_cent"].var.set("12,90")
        j.campos["controla_estoque"].bool.set(True)
        j.gravar(); j.update()
        p = self.banco.um("SELECT * FROM produtos WHERE nome = 'HEINEKEN'")
        self.assertEqual((p["preco_cent"], p["controla_estoque"], p["codigo"]), (1290, 1, "0000000000003"))
        # nome repetido: mostra o erro e não grava
        self.robo.quando("Dialogo", lambda w: w.destroy())
        j.incluir()
        j.campos["nome"].var.set("HEINEKEN")
        j.campos["subgrupo_id"].var.set("DIVERSOS - DIVERSOS"); j.campos["unidade_id"].var.set("Unidade")
        j.gravar(); j.update()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos WHERE nome = 'HEINEKEN'"), 1)
        self.sem_travar()
        j.destroy()

    def test_pesquisar_e_excluir(self):
        from src.ui.cadastros_tk import JanelaCadastro
        j = JanelaCadastro(self.root, self.ctx, "produtos")
        j.update()
        j.texto_busca = "agua"; j.carregar(); j.update()
        self.assertEqual(j.grade.total(), 1)
        self.robo.quando("Dialogo", lambda w: clicar(w, "Sim"))
        j.excluir(); j.update()
        self.assertIsNone(self.banco.um("SELECT 1 FROM produtos WHERE nome = 'AGUA'"))
        self.sem_travar()
        j.destroy()

    def test_todos_os_relatorios_abrem(self):
        from src.ui.relatorios_ui import SPECS, abrir_relatorio
        self.abrir_turno()
        for chave in [*SPECS, "vendas_periodo", "estoque_atual"]:
            with self.subTest(chave=chave):
                j = abrir_relatorio(self.root, self.ctx, chave)
                j.update()
                j.destroy()
        self.sem_travar()

    def test_lancamentos_e_configuracoes_abrem(self):
        from src.ui import config_ui
        from src.ui.lancamentos_ui import JanelaContas, JanelaEstoque
        for classe in (JanelaContas, JanelaEstoque):
            j = classe(self.root, self.ctx); j.update(); j.destroy()
        for chave in ("acessos", "loja", "configuracoes", "maquinas"):
            with self.subTest(chave=chave):
                j = config_ui.abrir(self.root, self.ctx, chave); j.update()
                if chave != "acessos":
                    self.robo.quando("Dialogo", lambda w: w.destroy())
                    j.gravar(); j.update()
                j.destroy()
        self.sem_travar()

    def test_configuracao_gravada_pela_tela(self):
        from src.ui import config_ui
        j = config_ui.abrir(self.root, self.ctx, "configuracoes")
        j.vars["servico_pct"].set("12,5")
        j.vars["num_mesas"].set("20")
        self.robo.quando("Dialogo", lambda w: w.destroy())
        j.gravar(); j.update(); j.destroy()
        self.assertEqual((float(self.banco.cfg("servico_pct")), self.banco.cfg_int("num_mesas")), (12.5, 20))

    def test_acessos_alteram_nivel_do_modulo(self):
        from src.ui import config_ui
        j = config_ui.abrir(self.root, self.ctx, "acessos"); j.update()
        j.grade.selecionar("cad_produtos"); j.update()
        j.v_nivel.set("4"); j.gravar(); j.update(); j.destroy()
        self.assertEqual(self.ctx.acesso.nivel_modulo("cad_produtos"), 4)


class TesteMenu(BaseUI):
    def test_menu_mostra_somente_o_que_o_nivel_permite(self):
        from src.ui.app import App
        app = App(self.banco)
        self.addCleanup(app.root.destroy)
        app.ctx.operador = app.ctx.acesso.autenticar("adm", "adm")
        app.mostrar_menu(); app.root.update()
        self.assertEqual(set(app.botoes), {"Cadastros", "Caixa", "Lançamentos", "Relatórios", "Utilitários", "Configurações", "Saída"})
        # operador de nível 1: sem Configurações nem Utilitários
        self.ctx.cadastros.salvar("operadores", {"nome": "Ana", "senha": "1", "nivel": "1"})
        app.ctx.operador = app.ctx.acesso.autenticar("ana", "1")
        app.mostrar_menu(); app.root.update()
        self.assertNotIn("Configurações", app.botoes)
        self.assertNotIn("Utilitários", app.botoes)
        self.assertIn("Caixa", app.botoes)
        self.assertEqual(app.valores["estoque_total"].cget("text"), "1")    # painel do dia
        self.assertIn("nenhum backup", app.lbl_backup.cget("text"))        # painel avisa que ainda não há cópia

    def _menu_do(self, nome, senha):
        from src.ui.app import App
        app = App(self.banco)
        self.addCleanup(app.root.destroy)
        app.ctx.operador = app.ctx.acesso.autenticar(nome, senha)
        return app

    def test_menu_setas_percorrem_os_botoes_e_dao_a_volta(self):
        app = self._menu_do("adm", "adm")
        app.mostrar_menu(); app.root.update()
        app._mover_nav(1)
        self.assertEqual(app._ordem_nav[app._nav_sel], "Cadastros")
        app._mover_nav(-1)                                  # volta ao começo: dá a volta e cai na Saída (a última)
        self.assertEqual(app._ordem_nav[app._nav_sel], "Saída")
        self.assertEqual(app._ordem_nav[-1], "Saída")

    def test_atualizar_painel_a_mao_nao_empilha_temporizadores(self):
        app = self._menu_do("adm", "adm")
        app.mostrar_menu(); app.root.update()
        antigo = app._relogio_id
        app.atualizar_painel()                              # F5
        self.assertNotEqual(app._relogio_id, antigo)
        self.assertNotIn(antigo, app.root.tk.call("after", "info"))

    def test_cartoes_e_atalhos_so_abrem_o_que_o_nivel_permite(self):
        from src.ui.app import App
        with mock.patch.object(App, "abrir_relatorio") as abrir:
            app = self._menu_do("adm", "adm")
            app.mostrar_menu(); app.root.update()
            app.cartoes["vendas_dia"].clique()
            abrir.assert_called_once_with("vendas_periodo")
            self.assertEqual([t for t, _, _ in app._atalhos()],
                             ["Abrir caixa", "Lançar estoque", "Produtos", "Vendas do período", "Backup agora"])
        self.ctx.cadastros.salvar("operadores", {"nome": "Ana", "senha": "1", "nivel": "1"})
        app = self._menu_do("ana", "1")
        app.mostrar_menu(); app.root.update()
        self.assertIsNone(app.cartoes["estoque_total"].clique)      # só informativo: o relatório pede nível maior
        self.assertEqual([t for t, _, _ in app._atalhos()], ["Abrir caixa"])

    def test_login_valida_senha_e_ignora_caixa_alta(self):
        from src.ui.login import JanelaLogin
        self.ctx.acesso.trocar_senha(self.ctx.operador, "Segredo1")
        j = JanelaLogin(self.root, self.ctx, "Loja")
        j.var_usuario.set("adm"); j.var_senha.set("errada"); j.entrar()
        self.assertIsNone(j.operador)
        self.assertEqual(j.lbl_msg.cget("text"), "Senha Incorreta")
        j.var_senha.set("sEGREDO1"); j.entrar()
        self.assertEqual(j.operador.nome, "ADM")

    def test_menu_compacto_mantem_acoes_visiveis_e_rola_indicadores(self):
        app = self._menu_do("adm", "adm")
        app.mostrar_menu()
        app.root.geometry("1000x600")
        app.root.update()
        canvas = app.painel_rolavel.canvas
        for b in [app.atalho_caixa, *app.atalhos_rapidos.values()]:
            with self.subTest(acao=b.texto.cget("text")):
                self.assertGreaterEqual(b.winfo_rootx(), canvas.winfo_rootx())
                self.assertLessEqual(b.winfo_rootx() + b.winfo_width(), canvas.winfo_rootx() + canvas.winfo_width())
                self.assertLessEqual(b.winfo_rooty() + b.winfo_height(), canvas.winfo_rooty() + canvas.winfo_height())
        self.assertLess(canvas.yview()[1], 1.0)     # indicadores abaixo da dobra têm rolagem
        app.atalho_caixa.event_generate("<Button-5>")
        app.root.update()
        self.assertGreater(canvas.yview()[0], 0.0)
        canvas.yview_moveto(1.0)
        app.root.update()
        self.assertLessEqual(app.lbl_barra.winfo_rooty() + app.lbl_barra.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height())
        self.assertTrue(app.botoes["Saída"].winfo_viewable())

    def test_acoes_rapidas_respondem_ao_teclado_e_ao_clique_na_descricao(self):
        from src.ui.app import App
        with mock.patch.object(App, "abrir_caixa") as caixa, mock.patch.object(App, "abrir_cadastro") as cadastro:
            app = self._menu_do("adm", "adm")
            app.mostrar_menu(); app.root.update()
            app.atalho_caixa.focus_force(); app.root.update()
            app.atalho_caixa.event_generate("<Return>")
            app.atalho_caixa.event_generate("<space>")
            self.assertEqual(caixa.call_count, 2)
            app.atalhos_rapidos["Produtos"].detalhe.event_generate("<Button-1>")
            cadastro.assert_called_once_with("produtos")

    def test_menu_sem_contas_nao_mostra_indicadores_do_modulo_desligado(self):
        self.banco.cfg_set("usar_contas", "N")
        app = self._menu_do("adm", "adm")
        app.mostrar_menu(); app.root.update()
        self.assertNotIn("contas_anteriores", app.cartoes)
        self.assertNotIn("contas_hoje", app.cartoes)
        self.assertIn("vendas_total", app.cartoes)
        self.assertIn("Produtos", app.atalhos_rapidos)

    def test_senha_de_fabrica_obriga_a_trocar_antes_de_entrar(self):
        from src.ui.login import JanelaLogin
        respostas = iter(["adm", "Nova123", "nova123"])       # 1ª: igual ao nome (recusada na própria janela)
        titulos = []

        def responder(w):
            titulos.append(w.title())
            campos = entradas(w)
            if campos:
                campos[0].delete(0, "end"); campos[0].insert(0, next(respostas))
            clicar(w, "OK")
        self.robo.quando("Dialogo", responder, vezes=4)        # nova senha (2 tentativas), confirmação e o aviso final
        j = JanelaLogin(self.root, self.ctx, "Loja")
        j.var_usuario.set("adm"); j.var_senha.set("ADM"); j.entrar()
        self.assertEqual(j.operador.nome, "ADM")
        self.assertEqual(titulos, ["Troque a senha", "Troque a senha", "Troque a senha", "Senha"])
        from src.core.erros import ErroNegocio
        self.ctx.acesso.autenticar("ADM", "NOVA123")
        with self.assertRaises(ErroNegocio):
            self.ctx.acesso.autenticar("ADM", "ADM")
        self.sem_travar()

    def test_desistir_da_troca_nao_entra(self):
        from src.ui.login import JanelaLogin
        self.robo.quando("Dialogo", lambda w: clicar(w, "Cancelar"))
        j = JanelaLogin(self.root, self.ctx, "Loja")
        j.var_usuario.set("adm"); j.var_senha.set("adm"); j.entrar()
        self.assertIsNone(j.operador)
        self.assertIn("Troque a senha", j.lbl_msg.cget("text"))
        self.ctx.acesso.autenticar("ADM", "ADM")                # a senha não mudou
        self.sem_travar()


class TesteTelaEntrada(BaseUI):
    def _login(self):
        from src.ui.login import JanelaLogin
        janela = JanelaLogin(self.root, self.ctx, "Casa de Teste")
        self.addCleanup(lambda: janela.winfo_exists() and janela.destroy())
        janela.update()
        return janela

    def test_mostrar_senha_preserva_valor_e_nova_entrada_volta_a_ocultar(self):
        j = self._login()
        j.var_senha.set("Minha123")
        self.assertEqual(j.ent_senha.cget("show"), "*")
        j.chk_mostrar_senha.invoke()
        self.assertEqual(j.ent_senha.cget("show"), "")
        self.assertEqual(j.var_senha.get(), "Minha123")
        j.chk_mostrar_senha.invoke()
        self.assertEqual(j.ent_senha.cget("show"), "*")
        j.chk_mostrar_senha.invoke()
        j.destroy()
        nova = self._login()
        self.assertEqual(nova.ent_senha.cget("show"), "*")
        self.assertEqual(nova.var_senha.get(), "")

    def test_enter_avanca_do_usuario_e_autentica_no_campo_de_senha(self):
        self.ctx.acesso.trocar_senha(self.ctx.operador, "Segredo1")
        j = self._login()
        j.var_usuario.set("adm")
        j.ent_usuario.focus_force(); j.update()
        j.ent_usuario.event_generate("<Return>"); j.update()
        self.assertEqual(j.focus_get(), j.ent_senha)
        self.assertIsNone(j.operador)
        j.var_senha.set("Segredo1")
        j.ent_senha.event_generate("<Return>")
        self.assertEqual(j.operador.nome, "ADM")
        self.assertFalse(j.winfo_exists())

    def test_selecionar_operador_avanca_para_senha_e_esc_cancela(self):
        self.ctx.cadastros.salvar("operadores", {"nome": "Ana", "senha": "1", "nivel": "1"})
        j = self._login()
        self.assertEqual(j.var_usuario.get(), "")  # vários operadores: não escolhe alguém automaticamente
        self.assertIn("ANA", [n.upper() for n in j.ent_usuario.cget("values")])
        j.ent_usuario.focus_force(); j.update()
        j.var_usuario.set("Ana")
        j.ent_usuario.event_generate("<<ComboboxSelected>>"); j.update()
        self.assertEqual(j.focus_get(), j.ent_senha)
        j.ent_senha.event_generate("<Escape>")
        self.assertIsNone(j.operador)
        self.assertFalse(j.winfo_exists())


class TesteAvisoDeVersao(BaseUI):
    def _menu(self, *versoes):
        import json
        from src.ui.app import App
        self.banco.cfg_set("atualizacao_resposta", json.dumps({"url_download": "https://exemplo/pdv.zip", "versoes": [
            {"versao": v, "notas": f"Notas da {v}", "critica": c} for v, c in versoes]}))
        app = App(self.banco)
        self.addCleanup(app.root.destroy)
        self.robo.parar()
        self.robo = Robo(app.root)
        app.ctx.operador = app.ctx.acesso.autenticar("adm", "adm")
        app.mostrar_menu(); app.root.update()
        return app

    def test_sem_versao_nova_nao_mostra_faixa(self):
        app = self._menu()
        self.assertFalse(app.lbl_versao.winfo_ismapped())

    def test_faixa_abre_as_notas_e_pode_ser_dispensada(self):
        app = self._menu(("9.0.0", False))
        self.assertTrue(app.lbl_versao.winfo_ismapped())
        self.assertIn("Nova versão 9.0.0", app.lbl_versao.cget("text"))
        textos = []

        def ver(w):
            textos.extend(str(f.cget("text")) for f in w.corpo.winfo_children() if isinstance(f, ttk.Label))
            clicar(w, "Não avisar")
        self.robo.quando("Dialogo", ver)
        app.abrir_aviso_versao(); app.root.update()
        self.assertIn("Notas da 9.0.0", textos)
        self.assertFalse(app.lbl_versao.winfo_ismapped())
        self.sem_travar()

    def test_versao_critica_fica_vermelha_e_nao_tem_como_dispensar(self):
        app = self._menu(("9.0.0", True))
        self.assertIn("IMPORTANTE", app.lbl_versao.cget("text"))
        botoes = []

        def ver(w):
            from tests.ui_robo import botoes as achar
            botoes.extend(str(b.cget("text")) for b in achar(w))
            clicar(w, "Baixar")
        self.robo.quando("Dialogo", ver)
        with mock.patch("webbrowser.open") as abrir:
            app.abrir_aviso_versao(); app.root.update()
        abrir.assert_called_once_with("https://exemplo/pdv.zip")
        self.assertNotIn("Não avisar desta versão", botoes)
        self.assertTrue(app.lbl_versao.winfo_ismapped())                  # continua avisando até atualizar
        self.sem_travar()


class TesteCadastroDaCasa(BaseUI):
    def _menu(self):
        from src.ui.app import App
        self.banco.atualizar("loja", 1, {"nome_fantasia": "", "razao_social": ""})   # casa ainda não cadastrada
        app = App(self.banco)
        self.addCleanup(app.root.destroy)
        self.robo.parar()
        self.robo = Robo(app.root)
        app.ctx.operador = app.ctx.acesso.autenticar("adm", "adm")
        return app

    def test_primeiro_acesso_pede_o_nome_da_casa_e_ele_sai_no_cupom(self):
        app = self._menu()
        self.assertFalse(app.ctx.config.loja_cadastrada())
        vistos = []

        def cadastrar(w):
            vistos.append(w.title())
            clicar(w, "Gravar")                                   # sem nome: recusa e continua na janela
            campos = entradas(w)
            campos[0].insert(0, "Boate Estrela"); campos[2].insert(0, "12.345.678/0001-90")
            clicar(w, "Gravar")
        self.robo.quando("Dialogo", cadastrar)
        app.mostrar_menu()
        for _ in range(40):
            app.root.update(); app.root.after(25); app.root.update_idletasks()
            if app.ctx.config.loja_cadastrada():
                break
        self.assertEqual(vistos, ["Cadastro da casa"])
        self.assertEqual(app.ctx.config.nome_loja(), "Boate Estrela")
        cab = "\n".join(app.ctx.impressao.cabecalho(40))
        self.assertIn("BOATE ESTRELA", cab)
        self.assertIn("CNPJ 12.345.678/0001-90", cab)
        self.sem_travar()

    def test_casa_cadastrada_nao_pergunta_e_operador_sem_permissao_tambem_nao(self):
        app = self._menu()
        with mock.patch("src.ui.cadastro_loja_ui.pedir") as pedir:
            self.ctx.cadastros.salvar("operadores", {"nome": "Ana", "senha": "1", "nivel": "1"})
            app.ctx.operador = app.ctx.acesso.autenticar("ana", "1")
            app.mostrar_menu(); app.root.update(); app.root.after(300); app.root.update()
            app.ctx.config.cadastrar_loja({"nome_fantasia": "Casa"})
            app.ctx.operador = app.ctx.acesso.autenticar("adm", "adm")
            app.mostrar_menu(); app.root.update(); app.root.after(300); app.root.update()
        pedir.assert_not_called()


class TestePainelFechamentoComAdiantamento(BaseUI):
    def test_painel_mostra_o_adiantamento_de_conta_aberta(self):
        from src.ui.caixa_dialogos import PainelFechamento
        tid = self.abrir_turno()
        self.banco.cfg_set("cobra_servico_mesa", "N")
        vid, _ = self.ctx.caixa.abrir_mesa(7)
        self.ctx.caixa.adicionar_item(vid, self.skol, 5)
        self.ctx.caixa.adicionar_pagamento(vid, self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'"), 1500)
        res = self.ctx.turnos.fechar(tid, self.ctx.operador_id, 10000 + 1500)
        textos = []

        def ler(w):
            pilha = [w]
            while pilha:
                x = pilha.pop()
                pilha.extend(x.winfo_children())
                if isinstance(x, ttk.Label):
                    textos.append(str(x.cget("text")))
            w.destroy()
        self.robo.quando("PainelFechamento", ler)
        PainelFechamento(self.root, self.ctx, res)
        self.assertIn("  Adiant. de contas abertas", textos)
        self.assertNotIn("  Pago em turno anterior", textos)
        self.assertEqual(res["resultado"], 0)
        self.sem_travar()


class TesteSaidaAoPagarNaTela(BaseUI):
    """Pagar a comanda pela tela do caixa: sai o cupom e, logo depois, o ticket de saída da comanda para a portaria."""

    def setUp(self):
        super().setUp()
        self.banco.cfg_set("posicao_padrao", "comanda")
        self.abrir_turno()
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()

    def pagar_comanda(self, posicao):
        self.cx.var_pos.set(posicao); self.cx.chamar_mesa(); self.cx.update()
        self.cx.var_cod.set("1"); self.cx._enter_codigo(); self.cx.update()
        self.cx.var_qtd.set("1"); self.cx.confirmar_item(); self.cx.update()
        impressos = []

        def acao(j):
            f = [i for i in j.grade_formas.tree.get_children() if j.grade_formas.valores(i)[0] == "Dinheiro"][0]
            j.grade_formas.selecionar(f); j._forma_escolhida()
            j.var_valor.set("20,00"); j._lancar_valor()
            j.after(10, j.fechar_venda)
        self.robo.quando("JanelaPagamento", acao)
        self.robo.quando("Visualizador", lambda w: (impressos.append(w.texto), w.destroy()), vezes=2)
        self.cx.pagar(); self.cx.update()
        self.sem_travar()
        return impressos

    def test_comanda_paga_imprime_cupom_e_saida(self):
        self.banco.cfg_set("imprimir_saida_ao_pagar", "S")
        cupom, saida = self.pagar_comanda("100")
        self.assertIn("CUPOM NÃO FISCAL", cupom)
        self.assertIn("TICKET DE SAIDA", saida)
        self.assertIn("CARTAO: 100  PAGO - LIBERADO", saida)
        self.assertIn("CUPOM: 1", saida)

    def test_na_termica_o_cupom_e_o_ticket_vao_para_o_papel(self):
        import os
        self.banco.cfg_set("imprimir_saida_ao_pagar", "S")
        pasta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, pasta, True)
        arquivo = os.path.join(pasta, "saida.prn")
        self.ctx.impressao.pasta_saida = lambda: Path(pasta)
        self.ctx.config.salvar_maquina({"modo_impressao": "termica", "impressora_termica_conexao": "arquivo",
                                        "impressora_termica_endereco": arquivo})
        self.assertEqual(self.pagar_comanda("100"), [])                      # na térmica nada abre na tela
        self.ctx.impressao.fila.processar()
        papel = Path(arquivo).read_bytes()
        self.assertIn(b"CUPOM N", papel)
        self.assertIn(b"TICKET DE SAIDA", papel)
        self.assertLess(papel.index(b"CUPOM N"), papel.index(b"TICKET DE SAIDA"))   # primeiro o cupom, depois o ticket
        self.assertIn(b"CARTAO: 100  PAGO - LIBERADO", papel)

    def test_desligado_sai_so_o_cupom(self):
        impressos = self.pagar_comanda("100")
        self.assertEqual(len(impressos), 1)
        self.assertIn("CUPOM NÃO FISCAL", impressos[0])


class TesteFluxosCaixa(BaseUI):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("posicao_padrao", "mesa")        # notação clássica: 5 é a mesa e C2 a comanda
        self.abrir_turno()
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()

    def lancar(self, cod, qtd):
        self.cx.var_cod.set(cod); self.cx._enter_codigo(); self.cx.update()
        self.cx.var_qtd.set(str(qtd)); self.cx.confirmar_item(); self.cx.update()

    def pagar(self, forma, valor=None, desconto_pct=None):
        def acao(j):
            if desconto_pct:
                j.var_pct.set(str(desconto_pct)); j._aplicar_desconto()
            f = [i for i in j.grade_formas.tree.get_children() if j.grade_formas.valores(i)[0] == forma][0]
            j.grade_formas.selecionar(f); j._forma_escolhida()
            if valor:
                j.var_valor.set(valor)
            j._lancar_valor()
            j.after(10, j.fechar_venda)
        self.robo.quando("JanelaPagamento", acao)
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.pagar(); self.cx.update()

    def test_venda_de_balcao_com_troco_baixa_estoque(self):
        self.lancar("1", 2)
        self.assertEqual(self.cx.lbl_total.cget("text"), "16,00")
        self.pagar("Dinheiro", "20,00")
        v = self.banco.um("SELECT * FROM vendas")
        self.assertEqual((v["cupom"], v["status"], v["troco_cent"]), (1, "fechada", 400))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 48)
        self.assertEqual(self.cx.lbl_troco.cget("text"), "4,00")
        self.sem_travar()

    def test_rodizio_cobra_fixo_por_pessoa_e_bebida_separada(self):
        self.banco.cfg_set("usar_rodizio", "S")
        self.banco.cfg_set("valor_rodizio_pessoa", "89,90")
        grupo_id = self.banco.valor("SELECT id FROM grupos LIMIT 1")
        sub_rodizio = self.banco.inserir("subgrupos", {"nome": "Carnes", "grupo_id": grupo_id, "rodizio_incluso": 1})
        un = self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
        CadastroController(self.banco).salvar("produtos", {
            "codigo": "9", "nome": "PICANHA", "subgrupo_id": sub_rodizio, "unidade_id": un, "preco_cent": "45,00"})
        self.cx.var_pos.set("1"); self.cx.chamar_mesa(); self.cx.update()
        self.lancar("9", 1)                      # picanha: incluso no rodízio, não entra no total por item
        self.lancar("2", 1)                      # água: fica fora, continua cobrada por item

        def responder_pessoas(w):
            e = entradas(w)[0]
            e.delete(0, "end"); e.insert(0, "2")
            clicar(w, "OK")
        self.robo.quando("Dialogo", responder_pessoas)
        self.cx.rodizio(); self.cx.update()
        self.sem_travar()
        # 2 x 89,90 (rodízio) + 3,50 (água) = 183,30; serviço 10% = 18,33; total 201,63
        self.assertEqual(self.cx.lbl_total.cget("text"), "201,63")
        self.assertIn("Rodízio: 2 pessoa(s)", self.cx.lbl_detalhe_total.cget("text"))

        def responder_desligar(w):
            e = entradas(w)[0]
            e.delete(0, "end"); e.insert(0, "0")
            clicar(w, "OK")
        self.robo.quando("Dialogo", responder_desligar)
        self.cx.rodizio(); self.cx.update()                # 0 desliga: volta a cobrar picanha + água por item
        self.sem_travar()
        self.assertEqual(self.cx.lbl_total.cget("text"), "53,35")   # (45,00 + 3,50) x 1,10

    def _produto_balanca(self, codigo: str, nome: str, preco_cent: int) -> int:
        sub = self.banco.valor("SELECT id FROM subgrupos")
        un = self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
        return CadastroController(self.banco).salvar("produtos", {
            "codigo": codigo, "nome": nome, "subgrupo_id": sub, "unidade_id": un,
            "preco_cent": f"{preco_cent / 100:.2f}".replace(".", ","), "aceita_decimal": "S", "balanca": "S"})

    def _responder_peso(self, texto: str):
        def responder(w):
            e = entradas(w)[0]
            e.delete(0, "end"); e.insert(0, texto)
            clicar(w, "OK")
        return responder

    def test_selecionar_produto_de_balanca_pesa_direto_e_calcula_o_total(self):
        self._produto_balanca("9", "QUEIJO KG", 4000)                  # R$ 40,00/kg
        self.robo.quando("Dialogo", self._responder_peso("0,315"))
        self.cx.var_cod.set("9"); self.cx._enter_codigo(); self.cx.update()
        self.sem_travar()
        self.assertEqual(self.cx.var_qtd.get(), "0,315")                # pesou sem pedir quantidade "1" antes
        self.cx.confirmar_item(); self.cx.update()
        self.assertEqual(self.cx.lbl_total.cget("text"), "12,60")
        self.assertEqual(self.banco.valor("SELECT quantidade FROM itens_venda"), 0.315)

    def test_f2_continua_pedindo_o_peso_manualmente_em_produto_comum(self):
        self.cx.var_cod.set("1"); self.cx._enter_codigo(); self.cx.update()    # SKOL, sem balança
        self.assertEqual(self.cx.var_qtd.get(), "1")                    # produto comum: continua sugerindo 1
        self.robo.quando("Dialogo", self._responder_peso("2,5"))
        self.cx.balanca(); self.cx.update()
        self.sem_travar()
        self.assertEqual(self.cx.var_qtd.get(), "2,500")

    def _lancar_parte_da_divisao(self, j, forma: str) -> None:
        """Escolhe a forma e lança o valor já sugerido pela divisão (não digita nada)."""
        f = [i for i in j.grade_formas.tree.get_children() if j.grade_formas.valores(i)[0] == forma][0]
        j.grade_formas.selecionar(f); j._forma_escolhida()
        j._lancar_valor()

    def _responder_dividir_em(self, partes: int):
        def responder(w):
            e = entradas(w)[0]
            e.delete(0, "end"); e.insert(0, str(partes))
            clicar(w, "OK")
        return responder

    def test_dividir_conta_guia_pagamento_em_partes_e_fecha_a_venda(self):
        # Assertivas ficam fora do callback do Tk: uma exceção lá dentro só é impressa, não reprova o teste
        # (ver nota do HANDOFF sobre o robô); por isso só gravamos estado em `resultado` e conferimos depois.
        self.lancar("1", 5)                                             # 40,00
        formas = ["Dinheiro", "Pix", "Dinheiro"]
        resultado = {}

        def acao(j):
            def passo():
                clicar(j, "Dividir conta")                              # abre o Dialogo (robô responde "3")
                for forma in formas:
                    self._lancar_parte_da_divisao(j, forma)
                resultado["divisao_final"] = j._divisao                 # None se as 3 partes esgotaram a divisão
                j.after(10, j.fechar_venda)
            j.after(30, passo)                                          # fora do _tick: permite o Dialogo aninhado
        self.robo.quando("Dialogo", self._responder_dividir_em(3))
        self.robo.quando("JanelaPagamento", acao)
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.pagar(); self.cx.update()
        self.sem_travar()
        self.assertIn("divisao_final", resultado, "o passo() não rodou até o fim (ver saída do teste)")
        self.assertIsNone(resultado["divisao_final"])
        v = self.banco.um("SELECT * FROM vendas")
        self.assertEqual((v["status"], v["pago_cent"], v["troco_cent"]), ("fechada", 4000, 0))
        self.assertEqual(len(self.ctx.caixa.pagamentos(v["id"])), 3)

    def test_remover_pagamento_durante_a_divisao_cancela_o_modo_guiado(self):
        self.lancar("1", 5)                                             # 40,00
        resultado = {}

        def acao(j):
            def passo():
                clicar(j, "Dividir conta")
                self._lancar_parte_da_divisao(j, "Dinheiro")             # parte 1 de 2
                resultado["divisao_apos_lancar"] = j._divisao
                j.grade_pag.selecionar_indice(0)
                j._remover_pagamento()
                resultado["divisao_apos_remover"] = j._divisao
                j.destroy()
            j.after(30, passo)
        self.robo.quando("Dialogo", self._responder_dividir_em(2))
        self.robo.quando("JanelaPagamento", acao)
        self.cx.pagar(); self.cx.update()
        self.sem_travar()
        self.assertIn("divisao_apos_remover", resultado, "o passo() não rodou até o fim (ver saída do teste)")
        self.assertIsNotNone(resultado["divisao_apos_lancar"])          # estava em modo guiado após a parte 1
        self.assertIsNone(resultado["divisao_apos_remover"])            # remover tirou do modo guiado
        self.assertEqual(len(self.ctx.caixa.pagamentos(self.venda_aberta())), 0)

    def test_dividir_conta_depois_de_pagamento_parcial_considera_so_a_falta(self):
        self.lancar("1", 5)                                             # 40,00
        resultado = {}

        def acao(j):
            def passo():
                f = [i for i in j.grade_formas.tree.get_children() if j.grade_formas.valores(i)[0] == "Dinheiro"][0]
                j.grade_formas.selecionar(f); j._forma_escolhida()
                j.var_valor.set("10,00"); j._lancar_valor()             # paga 10,00 manualmente; faltam 30,00
                clicar(j, "Dividir conta")                              # robô responde "3": divide os 30,00 restantes
                resultado["partes"] = list(j._divisao) if j._divisao else None
                for _ in range(3):
                    self._lancar_parte_da_divisao(j, "Pix")
                j.after(10, j.fechar_venda)
            j.after(30, passo)
        self.robo.quando("Dialogo", self._responder_dividir_em(3))
        self.robo.quando("JanelaPagamento", acao)
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.pagar(); self.cx.update()
        self.sem_travar()
        self.assertEqual(resultado.get("partes"), [1000, 1000, 1000])   # dividiu só o que faltava (30,00), não os 40,00
        v = self.banco.um("SELECT * FROM vendas")
        self.assertEqual((v["status"], v["pago_cent"]), ("fechada", 4000))

    def venda_aberta(self) -> int:
        return self.banco.valor("SELECT id FROM vendas WHERE status IN ('aberta', 'conta_enviada')")

    def test_busca_por_nome_e_produto_inexistente(self):
        self.cx.var_cod.set("zzz"); self.cx._enter_codigo(); self.cx.update()
        self.assertIsNone(self.cx.produto)
        self.assertIn("não encontrado", self.cx.status.cget("text"))
        self.cx.var_cod.set("sko"); self.cx._enter_codigo(); self.cx.update()    # único achado: usa direto
        self.assertEqual(self.cx.produto["nome"], "SKOL")

    def test_leitor_optico_lanca_direto_com_quantidade_1(self):
        self.cx.alternar_leitor()
        self.cx.var_cod.set("1"); self.cx._enter_codigo(); self.cx.update()
        self.cx.var_cod.set("1"); self.cx._enter_codigo(); self.cx.update()
        self.assertEqual(self.cx.grade.total(), 2)
        self.assertEqual(self.cx.lbl_total.cget("text"), "16,00")

    def test_mesa_servico_pre_conta_e_pagamento(self):
        self.cx.var_pos.set("5"); self.cx.chamar_mesa(); self.cx.update()
        self.lancar("1", 5)
        self.assertEqual(self.cx.lbl_total.cget("text"), "44,00")           # 40,00 + 10%
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.pre_conta(); self.cx.update()
        self.assertEqual(self.banco.valor("SELECT status FROM vendas WHERE posicao = 5"), "conta_enviada")
        self.cx.var_pos.set("5"); self.cx.chamar_mesa(); self.cx.update()
        self.pagar("Pix")
        self.assertEqual(self.banco.valor("SELECT status FROM vendas WHERE posicao = 5"), "fechada")
        self.assertEqual(self.banco.valor("SELECT servico_cent FROM vendas WHERE posicao = 5"), 400)
        self.sem_travar()

    def test_mesa_vazia_nao_deixa_fantasma(self):
        self.cx.var_pos.set("9"); self.cx.chamar_mesa(); self.cx.update()
        self.cx.var_pos.set("0"); self.cx.chamar_mesa(); self.cx.update()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)

    def tiles(self):
        return [(t["chave"], t["estado"], t["total"]) for t in self.cx.painel_mesas.tiles()]

    def itens_do_icone(self, chave, marca):
        return self.cx.painel_mesas.canvas.find_withtag(f"t:{chave}&&{marca}")

    def clicar_no_icone(self, chave):
        c = self.cx.painel_mesas.canvas
        self.cx.update()
        x1, y1, x2, y2 = c.bbox(f"t:{chave}&&fundo")
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        c.event_generate("<Motion>", x=x, y=y)         # o Tk só sabe qual é o item sob o mouse depois de um movimento
        c.event_generate("<Button-1>", x=x, y=y)
        self.cx.update()

    def foco(self):
        return str(self.cx.focus_lastfor())

    def test_skol_na_comanda_2_aparece_como_icone_no_rodape(self):
        self.assertTrue(self.cx.mesas_visiveis)                       # os ícones ficam à vista, sem apertar Esc
        self.assertEqual(self.tiles(), [("0", "balcao", "")])         # só o balcão
        self.cx.var_cod.set("C2"); self.cx._enter_codigo(); self.cx.update()   # "C2" no código abre a comanda 2
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Comanda 2")
        self.assertEqual(self.cx.var_pos.get(), "C2")
        self.lancar("1", 1)
        self.assertEqual(self.cx.lbl_total.cget("text"), "8,80")      # 8,00 + 10% de serviço, como na mesa
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("C2", "consumindo", "8,80")])
        self.assertTrue(self.itens_do_icone("C2", "icone:comanda"))
        fundo = self.itens_do_icone("C2", "fundo")[0]
        self.assertEqual(float(self.cx.painel_mesas.canvas.itemcget(fundo, "width")), 3.0)   # a que está na tela: borda grossa
        v = self.banco.um("SELECT modalidade, comanda, posicao FROM vendas")
        self.assertEqual((v["modalidade"], v["comanda"], v["posicao"]), ("mesa", 1, 2))
        self.sem_travar()

    def test_mesa_2_e_comanda_2_sao_icones_diferentes_e_o_clique_troca(self):
        self.cx.var_pos.set("2"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("1", 1)
        self.cx.var_pos.set("c2"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("2", 2)
        self.assertEqual([t[0] for t in self.tiles()], ["0", "2", "C2"])      # balcão, mesas e depois comandas
        self.assertTrue(self.itens_do_icone("2", "icone:mesa"))
        self.assertTrue(self.itens_do_icone("C2", "icone:comanda"))
        self.clicar_no_icone("2")
        self.assertEqual((self.cx.lbl_situacao.cget("text"), self.cx.lbl_total.cget("text")), ("Mesa 2", "8,80"))
        self.clicar_no_icone("0")
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Balcão")
        self.clicar_no_icone("C2")
        self.assertEqual((self.cx.lbl_situacao.cget("text"), self.cx.lbl_total.cget("text")), ("Comanda 2", "7,70"))
        self.sem_travar()

    def test_esc_volta_ao_marcar_comanda_e_o_segundo_esc_ao_balcao(self):
        self.cx.var_pos.set("C2"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("1", 1)
        self.cx.ent_codigo.focus_set()
        self.cx._esc_codigo(); self.cx.update()                       # Esc no lançamento de itens
        self.assertEqual(self.foco(), str(self.cx.ent_pos))
        self.assertTrue(self.cx.ent_pos.selection_present())          # o número fica selecionado: é só digitar o próximo
        self.assertEqual(self.cx.var_pos.get(), "C2")
        self.assertTrue(self.cx.mesas_visiveis)
        self.cx._esc_posicao(); self.cx.update()                      # segundo Esc: balcão; a comanda continua gravada
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Balcão")
        self.assertEqual(self.banco.valor("SELECT status FROM vendas WHERE comanda = 1"), "aberta")
        self.assertIn(("C2", "consumindo", "8,80"), self.tiles())
        self.assertEqual(self.foco(), str(self.cx.ent_codigo))
        self.cx._esc_posicao(); self.cx.update()                      # já no balcão: só devolve o foco ao código
        self.assertEqual(self.foco(), str(self.cx.ent_codigo))
        self.sem_travar()

    def test_esc_com_produto_pendente_so_cancela_o_produto(self):
        self.cx.var_pos.set("C2"); self.cx.chamar_mesa(); self.cx.update()
        self.cx.var_cod.set("1"); self.cx._enter_codigo(); self.cx.update()      # produto escolhido, falta a quantidade
        self.assertIsNotNone(self.cx.produto)
        self.cx._esc_codigo(); self.cx.update()
        self.assertIsNone(self.cx.produto)
        self.assertEqual(self.foco(), str(self.cx.ent_codigo))
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Comanda 2")           # continua na comanda
        self.cx._esc_codigo(); self.cx.update()                                   # o próximo Esc marca a comanda
        self.assertEqual(self.foco(), str(self.cx.ent_pos))

    def test_comanda_vazia_deixada_com_esc_nao_vira_icone_fantasma(self):
        self.cx.var_pos.set("C4"); self.cx.chamar_mesa(); self.cx.update()
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("C4", "consumindo", "0,00")])   # recém-aberta já aparece
        self.cx._esc_codigo(); self.cx._esc_posicao(); self.cx.update()
        self.assertEqual(self.tiles(), [("0", "balcao", "")])

    def test_icones_mostram_conta_enviada_e_comanda_parada(self):
        from datetime import timedelta
        self.cx.var_pos.set("C2"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("1", 2)
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.pre_conta(); self.cx.update()                                      # conta enviada
        self.cx.var_pos.set("C3"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("2", 1)
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("C2", "conta", "17,60"), ("C3", "consumindo", "3,85")])
        self.assertTrue(self.itens_do_icone("C2", "icone:conta"))
        self.assertFalse(self.itens_do_icone("C3", "relogio"))
        self.addCleanup(fmt.definir_relogio, None)
        fmt.definir_relogio(lambda: datetime.now() + timedelta(minutes=45))        # passam 45 min sem lançar nada
        self.cx._atualizar_painel(); self.cx.update()
        self.assertEqual(self.tiles()[2], ("C3", "parada", "3,85"))
        self.assertTrue(self.itens_do_icone("C3", "relogio"))
        self.assertFalse(self.itens_do_icone("C2", "relogio"))      # conta enviada não é "parada": o cliente está pagando
        self.sem_travar()

    def test_muitos_icones_quebram_em_linhas_e_rolam(self):
        for n in range(1, 61):
            v, _ = self.ctx.caixa.abrir_mesa(n, comanda=True)
            self.ctx.caixa.adicionar_item(v, self.skol, 1)
        self.cx.carregar_mesas(); self.cx.update()
        p = self.cx.painel_mesas
        self.assertEqual(len(p.tiles()), 61)                          # 60 comandas e o balcão
        self.assertGreater(p._altura_total, p.canvas.winfo_height())  # não cabem na coluna: o painel rola
        self.assertEqual(p.barra.winfo_manager(), "place")            # e a barra de rolagem aparece
        p.focar("C1")
        p._tecla(SimpleNamespace(keysym="End", char=""))
        self.assertEqual(p.cursor(), "C60")
        p._tecla(SimpleNamespace(keysym="Home", char=""))
        self.assertEqual(p.cursor(), "0")
        p._tecla(SimpleNamespace(keysym="Up", char=""))               # no alto da faixa: volta ao campo da posição
        self.assertEqual(self.foco(), str(self.cx.ent_pos))
        self.sem_travar()

    def test_teclado_nos_icones_escolhe_digita_e_transfere(self):
        p = self.cx.painel_mesas
        self.cx.var_pos.set("3"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("1", 1)
        self.cx.var_pos.set("C2"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("2", 1)
        self.cx.var_pos.set("C9"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("1", 2)
        p.focar("3")
        p._tecla(SimpleNamespace(keysym="Return", char="\r"))         # Enter chama a escolhida
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Mesa 3")
        p.focar("0")
        p._tecla(SimpleNamespace(keysym="c", char="c"))               # digitar C já começa a marcar a posição
        self.assertEqual((self.cx.var_pos.get(), self.foco()), ("C", str(self.cx.ent_pos)))
        self.cx.var_pos.set("C9"); self.cx.chamar_mesa(); self.cx.update()

        def digita(w):
            entradas(w)[0].insert(0, "3, C2"); clicar(w, "OK")
        self.robo.quando("Dialogo", digita)
        p.focar("C9")
        p._tecla(SimpleNamespace(keysym="t", char="t")); self.cx.update()      # T: as outras vêm para a escolhida
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("C9", "consumindo", "30,25")])
        self.assertEqual(self.cx.lbl_total.cget("text"), "30,25")     # 16,00 + 8,00 + 3,50 + 10%
        self.sem_travar()

    def test_comanda_desligada_avisa_e_nao_abre(self):
        self.banco.cfg_set("num_comandas", 0)
        self.robo.quando("Dialogo", lambda w: w.destroy())
        self.cx.var_cod.set("C2"); self.cx._enter_codigo(); self.cx.update()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)
        self.assertIsNone(self.cx.venda_id)
        self.assertIn("Dialogo", self.robo.log)
        self.sem_travar()

    def test_produto_com_atalho_c2_vence_a_comanda(self):
        self.banco.executar("UPDATE produtos SET atalho = 'C2' WHERE id = ?", (self.agua,))
        self.cx.var_cod.set("C2"); self.cx._enter_codigo(); self.cx.update()
        self.assertEqual(self.cx.produto["nome"], "AGUA")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)

    def test_pre_conta_e_pagamento_da_comanda(self):
        self.cx.var_pos.set("C2"); self.cx.chamar_mesa(); self.cx.update()
        self.lancar("1", 2)
        textos = []
        self.robo.quando("Visualizador", lambda w: (textos.append(w.texto), w.destroy()))
        self.cx.pre_conta(); self.cx.update()
        self.assertIn("CONTA DA COMANDA", textos[0])
        self.assertEqual(self.banco.valor("SELECT status FROM vendas"), "conta_enviada")
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("C2", "conta", "17,60")])
        self.cx.var_pos.set("C2"); self.cx.chamar_mesa(); self.cx.update()
        self.pagar("Pix")
        v = self.banco.um("SELECT status, comanda, servico_cent FROM vendas")
        self.assertEqual((v["status"], v["comanda"], v["servico_cent"]), ("fechada", 1, 160))
        self.assertEqual(self.tiles(), [("0", "balcao", "")])
        self.sem_travar()

    def test_transferir_comanda_para_mesa_com_f10(self):
        self.cx.var_pos.set("C2"); self.cx.chamar_mesa(); self.cx.update(); self.lancar("1", 1)

        def digita(w):
            entradas(w)[0].insert(0, "7"); clicar(w, "OK")
        self.robo.quando("Dialogo", digita)
        self.cx.transferir_mesa(); self.cx.update()
        v = self.banco.um("SELECT comanda, posicao FROM vendas")
        self.assertEqual((v["comanda"], v["posicao"]), (0, 7))
        self.assertEqual((self.cx.lbl_situacao.cget("text"), self.cx.var_pos.get()), ("Mesa 7", "7"))
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("7", "consumindo", "8,80")])
        self.sem_travar()

    def test_posicao_invalida_e_avisada(self):
        self.robo.quando("Dialogo", lambda w: w.destroy())
        self.cx.var_pos.set("abc"); self.cx.chamar_mesa(); self.cx.update()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)
        self.assertIn("Dialogo", self.robo.log)
        self.sem_travar()

    def test_painel_so_aparece_no_esc_quando_nao_e_fixo(self):
        self.cx.destroy()
        self.banco.cfg_set("painel_mesas_fixo", "N")
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()
        self.assertFalse(self.cx.mesas_visiveis)
        self.assertEqual(self.cx.painel_mesas.winfo_manager(), "")    # fora da tela até o Esc
        self.cx._esc_codigo(); self.cx.update()
        self.assertTrue(self.cx.mesas_visiveis)
        self.assertEqual(self.cx.painel_mesas.winfo_manager(), "pack")
        self.assertEqual(self.foco(), str(self.cx.ent_pos))
        self.cx.var_pos.set("C5"); self.cx.chamar_mesa(); self.cx.update()    # abriu a comanda: o painel some de novo
        self.assertFalse(self.cx.mesas_visiveis)
        self.assertEqual(self.foco(), str(self.cx.ent_codigo))
        self.sem_travar()

    def test_cancelar_item_e_conta_inteira(self):
        self.lancar("1", 1); self.lancar("2", 1)
        self.cx._foco_grade(ultimo=True); self.cx.modo_cancelar = True
        self.robo.quando("Dialogo", lambda w: clicar(w, "Sim"))
        self.cx.cancelar_item_selecionado(); self.cx.update()
        self.assertEqual((self.cx.grade.total(), self.cx.lbl_total.cget("text")), (1, "8,00"))
        self.robo.quando("Dialogo", lambda w: clicar(w, "Sim"))
        self.cx.cancelar_conta(); self.cx.update()
        self.assertIsNone(self.cx.venda_id)
        self.assertEqual(self.banco.valor("SELECT status FROM vendas"), "cancelada")
        self.sem_travar()

    def test_operador_sem_nivel_precisa_de_senha_de_supervisor(self):
        self.ctx.cadastros.salvar("operadores", {"nome": "Caixa1", "senha": "9", "nivel": "0"})
        self.ctx.operador = self.ctx.acesso.autenticar("caixa1", "9")
        self.lancar("1", 1)
        self.cx._foco_grade(ultimo=True)
        senhas = iter(["errada", "ADM"])

        def digita(w):
            entradas(w)[0].insert(0, next(senhas)); clicar(w, "OK")
        self.robo.quando("Dialogo", digita, vezes=1)
        self.robo.quando("Dialogo", lambda w: w.destroy(), vezes=1)       # aviso de senha inválida
        self.robo.quando("Dialogo", digita, vezes=1)
        self.robo.quando("Dialogo", lambda w: clicar(w, "Sim"), vezes=1)
        self.cx.cancelar_item_selecionado(); self.cx.update()
        self.assertEqual(self.cx.grade.total(), 0)

    def test_caderneta_debita_saldo_do_cliente(self):
        self.cx.venda_id = self.ctx.caixa.abrir_caderneta(self.cliente); self.cx.recarregar(); self.cx.update()
        self.assertIn("CADERNETA", self.cx.faixa.cget("text"))
        self.lancar("1", 3)
        self.robo.quando("Dialogo", lambda w: clicar(w, "Sim"))
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.pagar(); self.cx.update()
        self.assertEqual(self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (self.cliente,)), -2400)
        self.sem_travar()

    def test_entrega_pedido_e_recebimento(self):
        self.cx.venda_id = self.ctx.entregas.abrir(self.cliente); self.cx.recarregar(); self.cx.update()
        self.assertIn("ENTREGA", self.cx.faixa.cget("text"))
        self.lancar("1", 2)
        self.ctx.entregas.definir_dados(self.cx.venda_id, 5000)
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.pre_conta(); self.cx.update()                      # F8 na entrega: emite o pedido
        self.assertEqual(self.banco.valor("SELECT status FROM vendas WHERE modalidade = 'entrega'"), "conta_enviada")
        self.assertEqual(len(self.ctx.entregas.pendentes()), 1)
        self.cx.venda_id = self.ctx.entregas.pendentes()[0]["id"]
        self.cx.recarregar(); self.pagar("Dinheiro", "50,00")
        v = self.banco.um("SELECT status, troco_cent FROM vendas WHERE modalidade = 'entrega'")
        self.assertEqual((v["status"], v["troco_cent"]), ("fechada", 3400))
        self.sem_travar()

    def test_sangria_repique_e_troca_de_turno(self):
        self.lancar("1", 1)
        self.pagar("Dinheiro", "8,00")
        def sangria(w):
            ents = entradas(w)
            ents[0].insert(0, "20,00"); ents[1].insert(0, "gelo"); clicar(w, "Gravar")
        self.robo.quando("Dialogo", sangria)
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.sangria(); self.cx.update()
        self.assertEqual(self.banco.valor("SELECT valor_cent FROM movimentos_caixa WHERE tipo = 'saida'"), 2000)
        res = self.ctx.turnos.resumo(self.ctx.turnos.atual()["id"])
        self.assertEqual(res["esperado"], 10000 + 800 - 2000)

        def trocar(w):
            campos = entradas(w)
            if w.title() == "Conferir maquininha":      # 1º diálogo: o que foi lançado em cartão/Pix
                clicar(w, "Continuar")
            elif campos:                         # 2º diálogo: valor encontrado na gaveta
                campos[0].delete(0, "end"); campos[0].insert(0, "88,00"); clicar(w, "OK")
            else:                                # 3º diálogo: "Confirma?"
                clicar(w, "Sim")
        self.robo.quando("Dialogo", trocar, vezes=3)
        self.robo.quando("PainelFechamento", lambda w: w.destroy())
        from unittest.mock import patch
        declarados = {r["tipo_id"]: 8800 if r["dinheiro"] else 0
                      for r in self.ctx.turnos.formas_conferencia(
                          self.ctx.turnos.atual()["id"], self.ctx.operador_id)}
        with patch("src.ui.fechamento_ui.coletar", return_value={
                "informados_por_forma": declarados, "justificativa": ""}):
            self.cx.fechar_turno(); self.cx.update()
        t = self.banco.um("SELECT status, resultado_cent FROM turnos")
        self.assertEqual((t["status"], t["resultado_cent"]), ("fechado", 0))
        self.sem_travar()


class TesteFluxoDeEntrada(BaseUI):
    """App.run de ponta a ponta: login real -> menu (ou caixa direto para o nível 0) -> saída."""

    def _app(self):
        from src.ui.app import App
        self.root.destroy()
        app = App(self.banco)
        self.root = app.root
        self.robo = Robo(app.root)
        return app

    def test_login_leva_ao_menu_e_saida_volta_ao_login(self):
        app = self._app()
        vistos = []

        self.ctx.acesso.trocar_senha(self.ctx.acesso.autenticar("ADM", "ADM"), "Segredo1")

        def logar(w):
            vistos.append("login")
            w.var_usuario.set("adm"); w.var_senha.set("Segredo1"); w.entrar()
        self.robo.quando("JanelaLogin", logar, vezes=1)
        # no 2º login (depois da saída) o usuário fecha a janela: o programa encerra
        self.robo.quando("JanelaLogin", lambda w: (vistos.append("login2"), w.destroy()), vezes=1)

        def sair_do_menu():
            vistos.append("menu" if app.menu is not None else "sem-menu")
            self.robo.quando("Dialogo", lambda w: clicar(w, "Sim"))
            app.sair()
        app.root.after(900, sair_do_menu)
        app.root.after(12000, app.root.destroy)        # rede de segurança
        app.root.after(80, app.entrar)
        app.root.mainloop()
        self.assertEqual(vistos, ["login", "menu", "login2"])
        self.sem_travar()

    def test_operador_nivel_zero_vai_direto_ao_caixa_e_pede_o_turno(self):
        self.ctx.cadastros.salvar("operadores", {"nome": "Caixa1", "senha": "9", "nivel": "0"})
        app = self._app()
        vistos = []

        def logar(w):
            w.var_usuario.set("caixa1"); w.var_senha.set("9"); w.entrar()
        self.robo.quando("JanelaLogin", logar, vezes=1)
        self.robo.quando("JanelaLogin", lambda w: w.destroy(), vezes=1)

        def turno(w):                    # diálogos da abertura do turno: nº do turno, fundo, confirmação
            campos = entradas(w)
            if campos:
                campos[0].delete(0, "end"); campos[0].insert(0, "1" if w.title() == "Abertura do turno" and not vistos else "50,00")
                vistos.append(w.title()); clicar(w, "OK")
            else:
                clicar(w, "Sim")
        self.robo.quando("Dialogo", turno, vezes=3)

        def fechar_caixa():
            from src.ui.caixa_ui import JanelaCaixa
            cx = next((w for w in app.root.winfo_children() if isinstance(w, JanelaCaixa)), None)
            vistos.append("caixa" if cx is not None else "sem-caixa")
            if cx is not None:
                cx.destroy()
        app.root.after(1500, fechar_caixa)
        app.root.after(15000, app.root.destroy)
        app.root.after(80, app.entrar)
        app.root.mainloop()
        self.assertIn("caixa", vistos)
        t = self.banco.um("SELECT numero, valor_inicial_cent, status FROM turnos")
        self.assertEqual((t["numero"], t["valor_inicial_cent"], t["status"]), (1, 5000, "aberto"))
        self.sem_travar()


class TesteLancamentosUI(BaseUI):
    def test_compra_de_estoque_pela_tela(self):
        from src.ui.lancamentos_ui import JanelaEstoque
        forn = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        j = JanelaEstoque(self.root, self.ctx); j.update()
        j.v_tipo.set("compra"); j._tipo_mudou()
        j.v_forn.set("AMBEV"); j.v_valor.set("48,00"); j.v_doc.set("123")
        j.iniciar(); j.update()
        self.assertIsNotNone(j.lanc_id)
        j.v_cod.set("1"); j._achar_codigo()
        j.v_qtd.set("24"); j.v_val_item.set("48,00")
        j.adicionar_item(); j.update()
        p = self.banco.um("SELECT qt_atual, ult_preco_cent FROM produtos WHERE id = ?", (self.skol,))
        self.assertEqual((p["qt_atual"], p["ult_preco_cent"]), (74, 200))
        self.assertEqual(j.grade.total(), 1)
        self.robo.quando("Dialogo", lambda w: clicar(w, "Sim"))
        j.grade.selecionar_indice(0); j.remover_item(); j.update()
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 50)
        self.sem_travar()
        j.destroy()

    def test_lancamento_rapido_150_skol(self):
        from unittest import mock
        from src.ui.lancamentos_ui import JanelaEstoque
        j = JanelaEstoque(self.root, self.ctx); j.update()
        j.v_tipo.set("entrada"); j._tipo_mudou()
        j.iniciar(); j.update()
        j.v_cod.set("150 skol"); j._achar_codigo(); j.update()
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 200)   # 50 + 150
        j.v_cod.set("10x SKOL"); j._achar_codigo(); j.update()
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 210)
        self.assertEqual(j.grade.total(), 2)
        with mock.patch.object(tema, "aviso") as aviso:                  # nome que não existe: cai no comportamento normal
            j.v_cod.set("5 xyzinexistente"); j._achar_codigo()
        aviso.assert_called_once()
        self.assertEqual(j.grade.total(), 2)
        j.destroy()

    def test_produto_sem_controle_pergunta_antes_de_ligar(self):
        from unittest import mock
        from src.ui.lancamentos_ui import JanelaEstoque
        novo = self.agua                                              # cadastrada sem "Controla estoque"
        j = JanelaEstoque(self.root, self.ctx); j.update()
        j.v_tipo.set("entrada"); j._tipo_mudou()
        j.iniciar(); j.update()
        with mock.patch.object(tema, "confirmar", return_value=False) as conf:
            j.v_cod.set("20 agua"); j._achar_codigo()
        conf.assert_called_once()
        self.assertEqual(self.banco.valor("SELECT controla_estoque FROM produtos WHERE id = ?", (novo,)), 0)
        with mock.patch.object(tema, "confirmar", return_value=True):
            j.v_cod.set("20 agua"); j._achar_codigo()
        row = self.banco.um("SELECT controla_estoque, qt_atual FROM produtos WHERE id = ?", (novo,))
        self.assertEqual((row["controla_estoque"], row["qt_atual"]), (1, 20))
        j.destroy()

    def test_conta_mensal_pela_tela(self):
        from src.ui.lancamentos_ui import JanelaContas
        j = JanelaContas(self.root, self.ctx); j.update()
        j.v_sub.set("Aluguel - Imóvel (-)")
        j.v_desc.set("Aluguel"); j.v_valor.set("2.500,00"); j.v_venc.set("10/10/2026"); j.v_meses.set("3")
        j.gravar(); j.update()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM contas"), 3)
        self.assertEqual(self.banco.valor("SELECT MAX(valor_cent) FROM contas"), 250000)
        j.destroy()

    def test_backup_e_limpeza_pela_tela(self):
        from src.ui import utilitarios_ui
        with tempfile.TemporaryDirectory() as pasta:
            self.banco.cfg_set("pasta_backup", pasta)
            self.robo.quando("Dialogo", lambda w: w.destroy())
            utilitarios_ui.executar(self.root, self.ctx, "backup")
            import os
            self.assertEqual(len([f for f in os.listdir(pasta) if f.endswith(".db")]), 1)
        self.sem_travar()


class TesteAvisosDeCorteNasTelas(BaseUI):
    """Listas que mostram só os mais recentes avisam o operador em vez de cortar em silêncio."""

    def setUp(self):
        super().setUp()
        # Relógio fixo no meio da tarde: de 0h às 6h (virada do dia) o "hoje" do calendário e o dia operacional são dias diferentes e
        # o teste, que vende "agora" e consulta "hoje", falhava se a CI rodasse de madrugada.
        fmt.definir_relogio(lambda: datetime(2026, 10, 9, 15, 0, 0))
        self.addCleanup(fmt.definir_relogio, None)

    def vender(self, n):
        self.abrir_turno()
        for _ in range(n):
            v = self.ctx.caixa.abrir_balcao()
            self.ctx.caixa.adicionar_item(v, self.agua, 1)
            self.ctx.caixa.adicionar_pagamento(v, self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'"), 350)
            self.ctx.caixa.fechar(v)

    def test_cupons_do_periodo_avisam_quando_a_grade_corta(self):
        from src.ui import relatorios_ui
        self.vender(3)
        with mock.patch.object(relatorios_ui, "LIMITE_CUPONS", 2):
            j = relatorios_ui.JanelaVendasPeriodo(self.root, self.ctx); j.update()
            texto = j.resumo.cget("text")
            self.assertEqual(j.grade.total(), 2)
            self.assertIn("MOSTRANDO OS 2 ÚLTIMOS DE 3", texto)
            self.assertIn("TC 3", texto)                       # os totais valem para o período inteiro
            j.destroy()
        j = relatorios_ui.JanelaVendasPeriodo(self.root, self.ctx); j.update()
        self.assertEqual(j.grade.total(), 3)
        self.assertNotIn("MOSTRANDO", j.resumo.cget("text"))
        j.destroy()

    def test_lancamentos_anteriores_avisam_quando_a_lista_corta(self):
        from src.ui import lancamentos_ui
        for _ in range(3):
            self.ctx.estoque.criar_lancamento("entrada")
        j = lancamentos_ui.JanelaEstoque(self.root, self.ctx); j.update()
        with mock.patch.object(lancamentos_ui, "LIMITE_LANCAMENTOS", 2), \
                mock.patch.object(tema, "escolher", return_value=None) as escolher:
            j.abrir_anterior()
        itens, rotulo = escolher.call_args.args[2], escolher.call_args.args[3]
        self.assertEqual(len(itens), 2)
        self.assertIn("2 lançamentos mais recentes de 3", rotulo)
        with mock.patch.object(tema, "escolher", return_value=None) as escolher:
            j.abrir_anterior()
        self.assertEqual((len(escolher.call_args.args[2]), escolher.call_args.args[3]), (3, "Filtrar por texto:"))
        j.destroy()

    def test_painel_de_fechamento_mostra_o_total_fora_da_gaveta(self):
        from src.ui.caixa_dialogos import PainelFechamento
        self.abrir_turno()
        v = self.ctx.caixa.abrir_balcao()
        self.ctx.caixa.adicionar_item(v, self.skol, 2)
        self.ctx.caixa.adicionar_pagamento(v, self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Pix'"), 1600)
        self.ctx.caixa.fechar(v)
        res = self.ctx.turnos.fechar(self.ctx.turnos.atual()["id"], self.ctx.operador_id, 10000)
        pares = {}

        def ler(janela):                          # rótulo (coluna 0) e valor (coluna 1) da mesma linha da grade
            linhas, pilha = {}, [janela]
            while pilha:
                w = pilha.pop()
                pilha.extend(w.winfo_children())
                if isinstance(w, ttk.Label) and w.grid_info():
                    info = w.grid_info()
                    linhas.setdefault((str(w.master), int(info["row"])), {})[int(info["column"])] = w.cget("text")
            pares.update({c[0]: c[1] for c in linhas.values() if 0 in c and 1 in c})
            janela.destroy()
        self.robo.quando("PainelFechamento", ler)
        PainelFechamento(self.root, self.ctx, res)
        self.assertEqual(pares["Fora da gaveta (cartão/Pix)"], "16,00")
        self.assertEqual(pares["Valor esperado"], "100,00")
        self.assertEqual(pares["Pix"], "16,00")
        self.assertEqual(res["resultado"], 0)
        self.sem_travar()


class TesteLoginComLicenca(BaseUI):
    """Entrada com a licença exigida (o executável): bloqueio, renovação, aviso e turno aberto."""
    SEMENTE = bytes(range(32))

    def setUp(self):
        super().setUp()
        from src.core import ed25519, licenca
        self.licenca = licenca
        patcher = mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", ed25519.chave_publica(self.SEMENTE).hex())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(fmt.definir_relogio, None)
        fmt.definir_relogio(lambda: datetime(2026, 10, 3, 21, 0, 0))
        self.banco.cfg_set("licenca_exigir", "S")
        self.ctx.acesso.trocar_senha(self.ctx.operador, "Segredo1")    # a senha de fábrica abriria a troca obrigatória

    def codigo(self, dias=30, hoje=date(2026, 10, 3)):
        return self.licenca.gerar_licenca(self.SEMENTE, "LOJA-1", dias, hoje)

    def entrar(self, senha="segredo1", codigo=None):
        from src.ui.login import JanelaLogin
        j = JanelaLogin(self.root, self.ctx, "Loja")
        j.var_usuario.set("adm"); j.var_senha.set(senha)
        with mock.patch.object(tema, "pedir_texto", return_value=codigo) as pedir, \
                mock.patch.object(tema, "mensagem") as aviso:
            j.entrar()
            if j._consulta_licenca is not None:
                from time import monotonic, sleep
                limite = monotonic() + 3
                while j._consulta_licenca is not None and monotonic() < limite:
                    self.root.update()
                    sleep(0.01)
                self.assertIsNone(j._consulta_licenca, "A consulta de licença não terminou.")
        return j, pedir, aviso

    def test_sem_licenca_pede_o_codigo_e_entra_ao_ativar(self):
        j, pedir, aviso = self.entrar(codigo=self.codigo())
        pedir.assert_called_once()
        self.assertEqual(j.operador.nome, "ADM")
        self.assertEqual(self.banco.cfg("chave_loja"), "LOJA-1")
        aviso.assert_not_called()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'licenca_bloqueio'"), 1)

    def test_licenca_paga_na_nuvem_entra_sem_pedir_o_codigo(self):
        from src.sync import licenca_nuvem

        self.banco.cfg_set("api_url", "https://nuvem/v1")
        self.banco.cfg_set("api_token", "tok")
        with mock.patch.object(licenca_nuvem, "consultar_resultado",
                               return_value=licenca_nuvem.ResultadoConsulta(True, self.codigo())) as nuvem:
            j, pedir, _ = self.entrar()
        nuvem.assert_called_once()
        pedir.assert_not_called()
        self.assertEqual(j.operador.nome, "ADM")

    def test_codigo_invalido_ou_cancelado_nao_deixa_entrar(self):
        j, pedir, _ = self.entrar(codigo="lixo")
        self.assertIsNone(j.operador)
        self.assertIn("inválido", j.lbl_msg.cget("text"))
        j.destroy()
        j2, pedir2, _ = self.entrar(codigo=None)
        self.assertIsNone(j2.operador)
        j2.destroy()
        pedir.assert_called_once(); pedir2.assert_called_once()

    def abrir_turno_antes_da_exigencia(self, aberto_em=None):
        """Abre o turno com a licença ainda desligada (como numa loja que já estava operando) e liga a exigência."""
        self.banco.cfg_set("licenca_exigir", "N")
        tid = self.abrir_turno()
        if aberto_em:
            self.banco.executar("UPDATE turnos SET aberto_em = ? WHERE id = ?", (aberto_em, tid))
        self.banco.cfg_set("licenca_exigir", "S")

    def test_com_o_turno_aberto_entra_sem_pedir_codigo_e_avisa(self):
        self.abrir_turno_antes_da_exigencia()
        j, pedir, aviso = self.entrar()
        pedir.assert_not_called()
        self.assertEqual(j.operador.nome, "ADM")
        self.assertIn("turno aberto", aviso.call_args.args[1])

    def test_turno_antigo_ou_esquecido_nao_isenta_da_licenca(self):
        self.abrir_turno_antes_da_exigencia(aberto_em="2026-09-20 08:00:00")
        j, pedir, aviso = self.entrar(codigo=None)
        pedir.assert_called_once()                              # não houve isenção: pediu o código
        self.assertIsNone(j.operador)
        j.destroy()

    def test_sem_licenca_nao_abre_turno_novo_nem_pelo_menu(self):
        from src.core.erros import ErroNegocio
        with self.assertRaisesRegex(ErroNegocio, "Renove a licença"):
            self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)

    def test_perto_do_vencimento_avisa_e_registra_o_uso(self):
        self.licenca.ativar(self.banco, self.codigo(dias=3))
        j, pedir, aviso = self.entrar()
        pedir.assert_not_called()
        self.assertEqual(j.operador.nome, "ADM")
        self.assertIn("vence em 3 dias", aviso.call_args.args[1])
        self.assertEqual(self.banco.cfg("licenca_ultimo_uso"), "2026-10-03")

    def test_licenca_em_dia_entra_sem_aviso_e_senha_errada_continua_barrando(self):
        self.licenca.ativar(self.banco, self.codigo(dias=30))
        j, _, aviso = self.entrar(senha="errada")
        self.assertIsNone(j.operador)
        self.assertEqual(j.lbl_msg.cget("text"), "Senha Incorreta")
        j.destroy()
        j, _, aviso = self.entrar()
        self.assertEqual(j.operador.nome, "ADM")
        aviso.assert_not_called()

    def test_sem_exigencia_o_login_nao_mexe_na_licenca(self):
        self.banco.cfg_set("licenca_exigir", "N")
        j, pedir, aviso = self.entrar()
        self.assertEqual(j.operador.nome, "ADM")
        pedir.assert_not_called(); aviso.assert_not_called()
        self.assertEqual(self.banco.cfg("licenca_ultimo_uso"), "")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento LIKE 'licenca%'"), 0)


class TesteImpressaoTermicaNoCaixa(BaseUI):
    """O caixa em modo térmica: nada abre na tela, tudo vai para a fila e a fila imprime."""

    def setUp(self):
        super().setUp()
        import os
        import shutil
        from pathlib import Path
        from src.controllers.config_controller import ConfigController
        from src.ui.caixa_ui import JanelaCaixa
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.saida = os.path.join(self.dir, "saida.prn")
        self.ctx.impressao.pasta_saida = lambda: Path(self.dir)       # histórico fora do repositório
        self.cfg = ConfigController(self.banco)
        self.cfg.salvar_maquina({"modo_impressao": "termica", "impressora_termica_conexao": "arquivo",
                                 "impressora_termica_endereco": self.saida, "impressora_termica_gaveta": "S"})
        self.abrir_turno()
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()
        self.fila = self.ctx.impressao.fila

    def lancar(self, cod, qtd):
        self.cx.var_cod.set(cod); self.cx._enter_codigo(); self.cx.update()
        self.cx.var_qtd.set(str(qtd)); self.cx.confirmar_item(); self.cx.update()

    def pagar(self, forma, valor):
        def acao(j):
            f = [i for i in j.grade_formas.tree.get_children() if j.grade_formas.valores(i)[0] == forma][0]
            j.grade_formas.selecionar(f); j._forma_escolhida()
            j.var_valor.set(valor); j._lancar_valor()
            j.after(10, j.fechar_venda)
        self.robo.quando("JanelaPagamento", acao)
        self.cx.pagar(); self.cx.update()

    def impresso(self) -> bytes:
        from pathlib import Path
        self.fila.processar()                       # faz o papel da thread
        p = Path(self.saida)
        return p.read_bytes() if p.exists() else b""

    def test_fechar_venda_imprime_o_cupom_na_termica_sem_abrir_tela(self):
        self.lancar("1", 1)
        self.pagar("Dinheiro", "10,00")
        self.assertEqual(self.fila.contagem()["pendentes"], 1)              # entrou na fila ao fechar
        dados = self.impresso()
        self.assertIn("TOTAL".encode("cp850"), dados)
        self.assertIn(b"\x1bp", dados)                                       # dinheiro: a gaveta abriu
        self.assertEqual(dados.count(b"\x1dV"), 1)
        self.sem_travar()                                                    # nenhuma janela ficou pendurada

    def test_cartao_de_duas_vias_imprime_duas_vezes_e_nao_abre_a_gaveta(self):
        self.banco.executar("UPDATE tipos_pagamento SET vias = 2 WHERE tipo = 'Cartão Crédito'")
        self.lancar("1", 1)
        self.pagar("Cartão Crédito", "13,00")                               # 8,00 + R$ 5,00 da taxa do crédito
        dados = self.impresso()
        self.assertEqual(dados.count(b"\x1dV"), 2)
        self.assertNotIn(b"\x1bp", dados)
        self.sem_travar()

    def test_sangria_imprime_o_comprovante_e_abre_a_gaveta(self):
        def sangria(w):
            ents = entradas(w)
            ents[0].insert(0, "20,00"); ents[1].insert(0, "gelo"); clicar(w, "Gravar")
        self.robo.quando("Dialogo", sangria)
        self.cx.sangria(); self.cx.update()
        dados = self.impresso()
        self.assertIn("SANGRIA".encode("cp850"), dados)
        self.assertIn(b"\x1bp", dados)
        self.sem_travar()

    def test_pre_conta_da_mesa_sai_na_termica(self):
        self.cx.var_pos.set("M5"); self.cx.chamar_mesa(); self.cx.update()
        self.lancar("1", 2)
        self.cx.pre_conta(); self.cx.update()
        self.assertIn("CONTA DA MESA".encode("cp850"), self.impresso())
        self.sem_travar()

    def test_segunda_via_pelo_menu_do_caixa(self):
        from pathlib import Path
        self.lancar("1", 1)
        self.pagar("Dinheiro", "8,00")
        self.impresso()
        Path(self.saida).unlink()
        self.cx._reimprimir(self.cx._ultimo_cupom())
        self.assertIn("SEGUNDA VIA".encode("cp850"), self.impresso())
        self.sem_travar()

    def test_impressora_fora_do_ar_nao_segura_a_venda_e_o_indicador_avisa(self):
        self.cfg.salvar_maquina({"impressora_termica_conexao": "rede", "impressora_termica_endereco": "127.0.0.1:1"})
        self.lancar("1", 1)
        self.pagar("Dinheiro", "8,00")
        item = self.fila.listar()[0]
        self.assertEqual((item["status"], item["tentativas"]), ("pendente", 0))   # a venda nem tentou imprimir
        self.assertEqual(self.banco.valor("SELECT status FROM vendas"), "fechada")
        self.fila.processar()                                                      # a thread tenta e falha
        self.cx._atualizar_fila()
        self.assertIn("fora", self.cx.lbl_fila.cget("text"))
        self.sem_travar()

    def test_janela_da_fila_reenvia_e_cancela(self):
        from src.ui.fila_impressao_ui import JanelaFilaImpressao

        def fechar_dialogo(w):
            try:
                clicar(w, "Sim")
            except AssertionError:
                clicar(w, "OK")
        self.robo.quando("Dialogo", fechar_dialogo, vezes=5)
        self.cfg.salvar_maquina({"impressora_termica_conexao": "rede", "impressora_termica_endereco": "127.0.0.1:1"})
        a = self.fila.enfileirar("caixa", "cupom_a", b"\x1b@a")
        self.fila.processar()                                                      # falha: fica esperando
        j = JanelaFilaImpressao(self.cx, self.ctx); j.update()
        self.assertEqual(j.grade.total(), 1)
        self.assertIn("fora", j.lbl.cget("text"))
        j.grade.selecionar(a); j.reenviar()
        self.assertEqual(self.fila.listar()[0]["tentativas"], 0)                   # voltou a zero para tentar já
        j.cancelar(); j.update()
        self.assertEqual(self.fila.listar()[0]["status"], "cancelado")
        j.limpar(); j.update()
        self.assertEqual(j.grade.total(), 0)
        j.destroy()
        self.sem_travar()

    def test_janela_da_fila_nao_deixa_temporizadores_para_tras(self):
        import re
        from tkinter import TclError
        from src.ui.fila_impressao_ui import JanelaFilaImpressao

        def agendados():                                     # só os temporizadores desta janela (o caixa tem os dele)
            achados = set()
            for i in self.cx.tk.splitlist(self.cx.tk.call("after", "info")):
                try:
                    if re.fullmatch(r"\d+atualizar", str(self.cx.tk.call("after", "info", i)[0])):
                        achados.add(i)
                except TclError:
                    pass                                     # disparou entre a listagem e a consulta
            return achados
        antes = agendados()
        j = JanelaFilaImpressao(self.cx, self.ctx); j.update()
        for _ in range(3):                                   # os botões chamam atualizar() direto
            j.atualizar()
        self.assertEqual(len(agendados() - antes), 1)        # continua um único agendamento, não quatro
        j.destroy()
        self.assertEqual(agendados() - antes, set())         # e nada dispara depois de fechar a janela
        self.sem_travar()


class TesteSeletorDeImpressoras(BaseUI):
    """Escolher a impressora numa lista do computador, em vez de digitar o nome dela."""

    def setUp(self):
        super().setUp()
        from unittest import mock
        from src.hardware import impressoras_so as so
        from src.ui import config_ui
        self.so, self.config_ui = so, config_ui
        self.lista = [so.ImpressoraWindows("CAIXA", "TMUSB001", "EPSON TM-T(203dpi) Receipt6", padrao=True, termica_provavel=True),
                      so.ImpressoraWindows("HP DeskJet", "IP_1", "HP DeskJet 5820"),
                      so.ImpressoraWindows("Microsoft Print to PDF", "PORTPROMPT:", "Microsoft Print To PDF", virtual=True)]
        self.portas = [so.PortaSerial("COM3", "USB-SERIAL CH340 (COM3)")]
        for nome, valor in (("listar_impressoras", self.lista), ("listar_portas_seriais", self.portas)):
            p = mock.patch.object(so, nome, return_value=valor)
            p.start()
            self.addCleanup(p.stop)
        self.form = config_ui.abrir(self.root, self.ctx, "maquinas")
        self.form.update()

    def responder(self, vezes: int, sim: bool = True):
        """Fecha os avisos (OK) e responde Sim ou Não às perguntas que a escolha abre."""
        def acao(w):
            for prefixo in ("Sim" if sim else "Não", "OK"):
                try:
                    clicar(w, prefixo)
                    return
                except AssertionError:
                    continue
        self.robo.quando("Dialogo", acao, vezes=vezes)

    def abrir_lista(self, alvo: str = "termica"):
        sel = self.config_ui.escolher_impressora(self.form, self.ctx, alvo)
        sel.update()
        return sel

    def _assistente(self, lista):
        from unittest import mock
        with mock.patch.object(self.so, "listar_impressoras", return_value=lista), \
                mock.patch.object(self.so, "servico_spooler_rodando", return_value=True):
            a = self.config_ui.abrir_assistente(self.form, self.ctx)
            a.update()
        return a

    def test_spooler_nao_quebra_com_saida_indisponivel_e_substitui_bytes_invalidos(self):
        from types import SimpleNamespace
        from unittest import mock
        with mock.patch.object(self.so, "_WINDOWS", True), \
                mock.patch("subprocess.run", return_value=SimpleNamespace(stdout=None)) as executar:
            self.assertIsNone(self.so.servico_spooler_rodando())
        self.assertEqual(executar.call_args.kwargs["errors"], "replace")

    def test_assistente_marca_a_elgin_configura_o_caixa_e_atualiza_a_janela_de_maquinas(self):
        from unittest import mock
        elgin = self.so.ImpressoraWindows("Elgin i9", "USB001", "Elgin i9 Series", termica_provavel=True)
        pdf = self.so.ImpressoraWindows("Microsoft Print to PDF", "PORTPROMPT:", "x", padrao=True, virtual=True)
        a = self._assistente([pdf, elgin])
        self.assertEqual(a.impressoras[int(a.grade.selecionado())].nome, "Elgin i9")           # a Elgin já vem marcada
        textos = " ".join(w.cget("text") for w in a.quadro_achados.winfo_children())
        self.assertIn("modo 'tela'", textos)                                                   # de fábrica nada sai na impressora
        with mock.patch.object(self.ctx.impressao, "imprimir_teste") as teste, \
                mock.patch.object(tema, "confirmar", return_value=True), mock.patch.object(tema, "mensagem") as msg:
            a.configurar_e_testar()
        teste.assert_called_once()
        self.assertEqual(teste.call_args.args[0].endereco, "Elgin i9")
        m = self.ctx.config.maquina()
        self.assertEqual((m["modo_impressao"], m["impressora_termica_conexao"], m["impressora_termica_endereco"]),
                         ("termica", "spooler", "Elgin i9"))
        self.assertEqual(self.form.valor("modo_impressao"), "termica")                         # a janela de Máquinas recarregou
        self.assertEqual(self.form.valor("impressora_termica_endereco"), "Elgin i9")
        self.assertIn("já está imprimindo", msg.call_args.args[1])
        a.destroy()

    def test_assistente_quando_nao_sai_papel_orienta_e_erro_de_envio_nao_trava(self):
        from unittest import mock
        from src.hardware.impressora_termica import ErroImpressao
        elgin = self.so.ImpressoraWindows("Elgin i9", "USB001", "Elgin i9 Series", termica_provavel=True)
        a = self._assistente([elgin])
        with mock.patch.object(self.ctx.impressao, "imprimir_teste"), mock.patch.object(tema, "confirmar", return_value=False), \
                mock.patch.object(tema, "mensagem") as msg:
            a.configurar_e_testar()
        self.assertIn("LIGADA", msg.call_args.args[1])
        self.assertIn("Copiar diagnóstico", msg.call_args.args[1])
        with mock.patch.object(self.ctx.impressao, "imprimir_teste", side_effect=ErroImpressao("Impressora offline")), \
                mock.patch.object(tema, "erro") as erro:
            a.configurar_e_testar()
        self.assertIn("offline", erro.call_args.args[1].lower())
        a.destroy()

    def test_assistente_copia_o_diagnostico_e_destrava_a_fila(self):
        from unittest import mock
        elgin = self.so.ImpressoraWindows("Elgin i9", "USB001", "Elgin i9 Series", termica_provavel=True, pausada=True, trabalhos=2)
        a = self._assistente([elgin])
        with mock.patch.object(tema, "mensagem"), mock.patch.object(a, "clipboard_clear"), \
                mock.patch.object(a, "clipboard_append") as copiado:       # a área de transferência real do X virtual não é confiável no CI
            a.copiar()
        self.assertIn("DIAGNÓSTICO DE IMPRESSÃO", copiado.call_args.args[0])
        with mock.patch.object(self.so, "controlar_fila") as controlar, mock.patch.object(tema, "confirmar", return_value=True), \
                mock.patch.object(tema, "mensagem"), mock.patch.object(self.so, "listar_impressoras", return_value=[elgin]):
            a.destravar()
        self.assertEqual([c.args for c in controlar.call_args_list],
                         [("Elgin i9", self.so.CONTROLE_RETOMAR), ("Elgin i9", self.so.CONTROLE_LIMPAR)])
        a.destroy()

    def test_assistente_instala_a_elgin_pelo_botao_e_atualiza_a_lista(self):
        from unittest import mock
        a = self._assistente([])
        with mock.patch.object(tema, "confirmar", return_value=True), mock.patch.object(tema, "mensagem") as msg, \
                mock.patch("src.controllers.impressao_assistente.instalar_generica", return_value="Elgin i9") as instalar:
            a.instalar()
        instalar.assert_called_once_with("Elgin i9")
        self.assertIn("instalada no Windows", msg.call_args.args[1])
        with mock.patch.object(tema, "confirmar", return_value=False), \
                mock.patch("src.controllers.impressao_assistente.instalar_generica") as instalar:
            a.instalar()                                              # o operador desistiu: nada é instalado
        instalar.assert_not_called()
        with mock.patch.object(tema, "confirmar", return_value=True), mock.patch.object(tema, "erro") as erro, \
                mock.patch("src.controllers.impressao_assistente.instalar_generica", side_effect=ErroNegocio("sem USB")):
            a.instalar()
        self.assertIn("sem USB", erro.call_args.args[1])
        a.destroy()

    def test_assistente_sem_nenhuma_impressora_avisa_em_vez_de_travar(self):
        from unittest import mock
        a = self._assistente([])
        self.assertEqual(a.grade.total(), 0)
        with mock.patch.object(tema, "aviso") as aviso:
            a.configurar_e_testar()
        self.assertIn("instale o driver", aviso.call_args.args[1])
        a.destroy()

    def test_lista_as_impressoras_do_pc_com_a_termica_primeiro_e_as_portas_com(self):
        sel = self.abrir_lista()
        linhas = [sel.grade.valores(i) for i in sel.grade.tree.get_children()]
        self.assertEqual([l[1] for l in linhas], ["CAIXA  (padrão do Windows)", "HP DeskJet", "Microsoft Print to PDF", "COM3"])
        self.assertEqual(linhas[0][0], "Cupom (térmica)")
        self.assertEqual(linhas[2][0], "PDF ou fax (virtual)")
        self.assertIn("TMUSB001", linhas[0][2])
        self.assertIn("EPSON", linhas[0][2])
        self.assertEqual(linhas[3][0], "Porta serial")
        self.assertEqual(sel.itens[sel.grade.selecionado()]["endereco"], "CAIXA")      # a térmica já vem marcada
        self.assertIn("3 impressora(s)", sel.lbl.cget("text"))

    def test_usar_preenche_conexao_e_endereco_e_oferece_ativar_a_termica(self):
        self.responder(3)                          # ativar (Sim), "Escolhida" (OK) e "Configurações gravadas" (OK)
        sel = self.abrir_lista()
        sel.usar()
        self.form.update()
        self.assertEqual((self.form.valor("impressora_termica_conexao"), self.form.valor("impressora_termica_endereco"),
                          self.form.valor("modo_impressao")), ("spooler", "CAIXA", "termica"))
        self.assertFalse(sel.winfo_exists())
        self.form.gravar()
        m = self.ctx.config.maquina()
        self.assertEqual((m["impressora_termica_conexao"], m["impressora_termica_endereco"], m["modo_impressao"]),
                         ("spooler", "CAIXA", "termica"))
        self.sem_travar()

    def test_nao_pergunta_pelo_modo_quando_o_caixa_ja_imprime_pela_termica(self):
        self.form.definir("modo_impressao", "termica")
        self.responder(1)
        self.abrir_lista().usar()
        self.assertEqual(self.robo.log.count("Dialogo"), 1)                           # só o aviso "Escolhida"
        self.sem_travar()

    def test_porta_serial_vira_conexao_serial_e_o_nao_deixa_o_modo_como_estava(self):
        self.responder(2, sim=False)
        sel = self.abrir_lista()
        sel.grade.selecionar("com:0")
        sel.usar()
        self.assertEqual((self.form.valor("impressora_termica_conexao"), self.form.valor("impressora_termica_endereco")),
                         ("serial", "COM3"))
        self.assertNotEqual(self.form.valor("modo_impressao"), "termica")
        self.sem_travar()

    def test_impressora_virtual_pede_confirmacao_e_o_nao_mantem_a_lista_aberta(self):
        self.responder(1, sim=False)
        sel = self.abrir_lista()
        sel.grade.selecionar("imp:2")
        antes = self.form.valor("impressora_termica_endereco")
        sel.usar()
        self.assertTrue(sel.winfo_exists())
        self.assertEqual(self.form.valor("impressora_termica_endereco"), antes)
        self.responder(1)
        sel.testar()                                                                   # teste em PDF: só avisa
        self.sem_travar()

    def test_teste_usa_a_escolha_sem_gravar_nada(self):
        from unittest import mock
        from src.hardware import impressora_termica as term
        self.responder(1)
        sel = self.abrir_lista()
        sel.grade.selecionar("imp:0")
        antes = dict(self.ctx.config.maquina())
        with mock.patch.object(term, "enviar_spooler") as envia:
            sel.testar()
        nome, dados = envia.call_args.args[:2]
        self.assertEqual(nome, "CAIXA")
        self.assertTrue(dados.startswith(b"\x1b@"))
        self.assertIn(b"TOTAL", dados)
        self.assertEqual(self.ctx.config.maquina(), antes)                              # testar não grava a escolha
        self.sem_travar()

    def test_cozinha_lista_so_impressoras_do_windows_e_nao_mexe_no_modo_do_caixa(self):
        self.responder(1)
        sel = self.abrir_lista("remota")
        self.assertEqual(sel.grade.total(), 3)
        sel.grade.selecionar("imp:1")
        sel.usar()
        self.assertEqual((self.form.valor("impressora_remota_conexao"), self.form.valor("impressora_remota_endereco")),
                         ("spooler", "HP DeskJet"))
        self.assertNotEqual(self.form.valor("modo_impressao"), "termica")
        self.sem_travar()

    def test_botoes_ao_lado_dos_campos_e_na_barra_abrem_a_lista(self):
        from src.ui.escolher_impressora_ui import JanelaEscolherImpressora

        def abertas():
            return [w for w in self.form.winfo_children() if isinstance(w, JanelaEscolherImpressora)]
        for chave, alvo in (("impressora_termica_endereco", "termica"), ("impressora_remota_endereco", "remota")):
            self.form.botoes[chave].invoke()
            self.form.update()
            self.assertEqual([a.alvo for a in abertas()], [alvo])
            abertas()[0].destroy()
        clicar(self.form, "Escolher impressora do computador")
        self.assertEqual([a.alvo for a in abertas()], ["termica"])
        abertas()[0].destroy()

    def test_sem_nenhuma_impressora_explica_o_que_fazer(self):
        from unittest import mock
        with mock.patch.object(self.so, "listar_impressoras", return_value=[]), \
                mock.patch.object(self.so, "listar_portas_seriais", return_value=[]):
            sel = self.abrir_lista()
        self.assertEqual(sel.grade.total(), 0)
        self.assertIn("Nenhuma impressora encontrada", sel.lbl.cget("text"))
        self.responder(1)
        sel.usar()                                                                     # sem linha escolhida: só avisa
        self.assertTrue(sel.winfo_exists())
        self.sem_travar()

    def test_definir_e_valor_nos_tipos_de_campo_da_tela(self):
        self.form.definir("impressora_termica_cortar", "N")
        self.form.definir("impressora_termica_codepage", "cp860")
        self.form.definir("colunas_fita", 32)
        self.form.definir("impressora_termica_endereco", "CAIXA")
        self.assertEqual([self.form.valor(c) for c in ("impressora_termica_cortar", "impressora_termica_codepage",
                                                        "colunas_fita", "impressora_termica_endereco")], ["N", "cp860", "32", "CAIXA"])


class TesteComandaPorNumeroNoCaixa(BaseUI):
    """O caixa com o padrão da loja: digita-se o número da comanda (sem C) e o código do produto à parte."""

    def setUp(self):
        super().setUp()
        self.abrir_turno()
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()

    def lancar(self, cod, qtd):
        self.cx.var_cod.set(cod); self.cx._enter_codigo(); self.cx.update()
        self.cx.var_qtd.set(str(qtd)); self.cx.confirmar_item(); self.cx.update()

    def pagar(self, forma):
        def acao(j):
            f = [i for i in j.grade_formas.tree.get_children() if j.grade_formas.valores(i)[0] == forma][0]
            j.grade_formas.selecionar(f); j._forma_escolhida()
            j._lancar_valor()
            j.after(10, j.fechar_venda)
        self.robo.quando("JanelaPagamento", acao)
        self.robo.quando("Visualizador", lambda w: w.destroy())
        self.cx.pagar(); self.cx.update()

    def posicao(self, texto):
        self.cx.var_pos.set(texto); self.cx.chamar_mesa(); self.cx.update()

    def situacao(self):
        return self.cx.lbl_situacao.cget("text"), self.cx.var_pos.get()

    def tiles(self):
        return [(t["chave"], t["estado"], t["total"]) for t in self.cx.painel_mesas.tiles()]

    def itens_do_icone(self, chave, marca):
        return self.cx.painel_mesas.canvas.find_withtag(f"t:{chave}&&{marca}")

    def clicar_no_icone(self, chave):
        c = self.cx.painel_mesas.canvas
        self.cx.update()
        x1, y1, x2, y2 = c.bbox(f"t:{chave}&&fundo")
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        c.event_generate("<Motion>", x=x, y=y)
        c.event_generate("<Button-1>", x=x, y=y)
        self.cx.update()

    def foco(self):
        return str(self.cx.focus_lastfor())

    @staticmethod
    def textos(janela):
        achados = []

        def varre(w):
            for f in w.winfo_children():
                if isinstance(f, ttk.Label):
                    achados.append(str(f.cget("text")))
                varre(f)
        varre(janela)
        return achados

    def test_campo_da_posicao_pergunta_a_comanda(self):
        textos = self.textos(self.cx)
        self.assertIn("Comanda (ou M + nº da mesa)", textos)
        self.assertNotIn("Mesa ou comanda (ex.: 5 ou C2)", textos)

    def test_numero_sem_letra_abre_a_comanda_e_o_produto_vai_pelo_codigo(self):
        self.posicao("123")
        self.assertEqual(self.situacao(), ("Comanda 123", "123"))
        self.lancar("1", 2)                                                    # código 1 = SKOL
        v = self.banco.um("SELECT modalidade, comanda, posicao FROM vendas")
        self.assertEqual((v["modalidade"], v["comanda"], v["posicao"]), ("mesa", 1, 123))
        self.assertEqual(self.cx.lbl_total.cget("text"), "17,60")              # 16,00 + 10% de serviço
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("123", "consumindo", "17,60")])
        self.assertTrue(self.itens_do_icone("123", "icone:comanda"))
        self.sem_travar()

    def test_codigo_de_produto_igual_ao_numero_de_uma_comanda_nao_troca_de_comanda(self):
        self.posicao("2"); self.lancar("1", 1)                                 # comanda 2 com uma SKOL
        self.posicao("7")                                                      # comanda 7, vazia
        self.cx.var_cod.set("2"); self.cx._enter_codigo(); self.cx.update()    # no código, 2 é a AGUA
        self.assertEqual(self.cx.produto["nome"], "AGUA")
        self.assertEqual(self.situacao(), ("Comanda 7", "7"))
        self.sem_travar()

    def test_c_ou_m_no_campo_do_codigo_troca_de_posicao(self):
        self.cx.var_cod.set("C9"); self.cx._enter_codigo(); self.cx.update()
        self.assertEqual(self.situacao(), ("Comanda 9", "9"))
        self.lancar("1", 1)
        self.cx.var_cod.set("M3"); self.cx._enter_codigo(); self.cx.update()
        self.assertEqual(self.situacao(), ("Mesa 3", "M3"))
        self.sem_travar()

    def test_mesa_leva_m_e_aparece_como_m5_nos_icones(self):
        self.posicao("M5"); self.lancar("1", 5)
        self.assertEqual(self.situacao(), ("Mesa 5", "M5"))
        self.assertEqual(self.cx.lbl_total.cget("text"), "44,00")             # 40,00 + 10% de serviço
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("M5", "consumindo", "44,00")])
        self.assertTrue(self.itens_do_icone("M5", "icone:mesa"))
        self.sem_travar()

    def test_comanda_e_mesa_com_o_mesmo_numero_convivem_e_o_clique_troca(self):
        self.posicao("2"); self.lancar("1", 1)
        self.posicao("M2"); self.lancar("2", 2)
        self.assertEqual([t[0] for t in self.tiles()], ["0", "M2", "2"])      # balcão, mesas e depois comandas
        self.clicar_no_icone("M2")
        self.assertEqual((self.situacao(), self.cx.lbl_total.cget("text")), (("Mesa 2", "M2"), "7,70"))
        self.clicar_no_icone("2")
        self.assertEqual((self.situacao(), self.cx.lbl_total.cget("text")), (("Comanda 2", "2"), "8,80"))
        self.clicar_no_icone("0")
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Balcão")
        self.sem_travar()

    def test_comanda_10000_abre_e_a_10001_e_avisada(self):
        self.posicao("10000")
        self.assertEqual(self.situacao(), ("Comanda 10000", "10000"))
        self.robo.quando("Dialogo", lambda w: w.destroy())
        self.posicao("10001")
        self.assertIn("Dialogo", self.robo.log)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas WHERE posicao = 10001"), 0)
        self.sem_travar()

    def test_pre_conta_e_pagamento_da_comanda_por_numero(self):
        self.posicao("55"); self.lancar("1", 2)
        textos = []
        self.robo.quando("Visualizador", lambda w: (textos.append(w.texto), w.destroy()))
        self.cx.pre_conta(); self.cx.update()
        self.assertIn("CONTA DA COMANDA", textos[0])
        self.assertIn("Comanda 55", textos[0])
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("55", "conta", "17,60")])
        self.posicao("55")
        self.pagar("Pix")
        v = self.banco.um("SELECT status, comanda, posicao FROM vendas")
        self.assertEqual((v["status"], v["comanda"], v["posicao"]), ("fechada", 1, 55))
        self.assertEqual(self.tiles(), [("0", "balcao", "")])
        self.sem_travar()

    def test_esc_volta_ao_campo_da_posicao_com_o_numero_selecionado(self):
        self.posicao("77"); self.lancar("1", 1)
        self.cx.ent_codigo.focus_set()
        self.cx._esc_codigo(); self.cx.update()
        self.assertEqual(self.foco(), str(self.cx.ent_pos))
        self.assertTrue(self.cx.ent_pos.selection_present())
        self.assertEqual(self.cx.var_pos.get(), "77")
        self.sem_travar()

    def test_teclado_nos_icones_aceita_digitos_e_a_letra_m(self):
        p = self.cx.painel_mesas
        self.posicao("3"); self.lancar("1", 1)
        p.focar("3")
        p._tecla(SimpleNamespace(keysym="m", char="m"))
        self.assertEqual((self.cx.var_pos.get(), self.foco()), ("M", str(self.cx.ent_pos)))
        p.focar("3")
        p._tecla(SimpleNamespace(keysym="5", char="5"))
        self.assertEqual(self.cx.var_pos.get(), "5")
        self.sem_travar()

    def test_f10_transfere_pelo_numero_e_pelo_m(self):
        self.posicao("2"); self.lancar("1", 1)
        perguntas = []

        def responde(destino):
            def acao(w):
                perguntas.append(self.textos(w))
                entradas(w)[0].insert(0, destino); clicar(w, "OK")
            return acao
        self.robo.quando("Dialogo", responde("M7"))
        self.cx.transferir_mesa(); self.cx.update()
        v = self.banco.um("SELECT comanda, posicao FROM vendas")
        self.assertEqual((v["comanda"], v["posicao"]), (0, 7))
        self.assertEqual(self.situacao(), ("Mesa 7", "M7"))
        self.assertTrue(any("ex.: 123 ou M5" in t for ts in perguntas for t in ts), perguntas)
        self.robo.quando("Dialogo", responde("321"))
        self.cx.transferir_mesa(); self.cx.update()
        v = self.banco.um("SELECT comanda, posicao FROM vendas")
        self.assertEqual((v["comanda"], v["posicao"]), (1, 321))
        self.assertEqual(self.situacao(), ("Comanda 321", "321"))
        self.sem_travar()

    def test_t_nos_icones_junta_varias_posicoes_digitando_numeros(self):
        p = self.cx.painel_mesas
        self.posicao("3"); self.lancar("1", 1)
        self.posicao("4"); self.lancar("2", 1)
        self.posicao("9"); self.lancar("1", 2)

        def digita(w):
            entradas(w)[0].insert(0, "3, 4"); clicar(w, "OK")
        self.robo.quando("Dialogo", digita)
        p.focar("9")
        p._tecla(SimpleNamespace(keysym="t", char="t")); self.cx.update()
        self.assertEqual(self.tiles(), [("0", "balcao", ""), ("9", "consumindo", "30,25")])
        self.sem_travar()

    def test_repique_pergunta_a_comanda_pelo_numero(self):
        self.posicao("5"); self.lancar("1", 1)
        self.posicao("0")                                                     # volta ao balcão: o repique pergunta a posição
        respostas = ["5", "3,00"]
        perguntas = []

        def preenche(w):
            perguntas.append(self.textos(w))
            entradas(w)[0].insert(0, respostas.pop(0)); clicar(w, "OK")
        self.robo.quando("Dialogo", preenche, vezes=2)
        self.cx.repique(); self.cx.update()
        r = self.banco.um("SELECT posicao, valor_cent, venda_id FROM repiques")
        comanda_5 = self.banco.valor("SELECT id FROM vendas WHERE comanda = 1 AND posicao = 5")
        self.assertEqual((r["posicao"], r["valor_cent"], r["venda_id"]), (5, 300, comanda_5))
        self.assertTrue(any("ex.: 123 ou M5" in t for t in perguntas[0]), perguntas)
        self.sem_travar()

    def test_loja_na_notacao_de_mesa_pergunta_mesa_ou_comanda(self):
        self.banco.cfg_set("posicao_padrao", "mesa")
        self.cx.destroy()
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()
        self.assertIn("Mesa ou comanda (ex.: 5 ou C2)", self.textos(self.cx))
        self.posicao("5"); self.lancar("1", 1)
        self.assertEqual(self.situacao(), ("Mesa 5", "5"))
        self.posicao("C5"); self.lancar("1", 1)
        self.assertEqual(self.situacao(), ("Comanda 5", "C5"))
        self.assertEqual([t[0] for t in self.tiles()], ["0", "5", "C5"])
        self.sem_travar()

    def test_tela_de_configuracoes_oferece_a_escolha_da_notacao(self):
        from src.ui import config_ui
        form = config_ui.abrir(self.root, self.ctx, "configuracoes")
        form.update()
        self.assertEqual(form.valor("posicao_padrao"), "comanda")
        form.definir("posicao_padrao", "mesa")
        self.robo.quando("Dialogo", lambda w: clicar(w, "OK"))
        form.gravar()
        self.assertEqual(self.banco.cfg("posicao_padrao"), "mesa")
        self.sem_travar()


class TesteComissaoDasGarotasNoCaixa(BaseUI):
    """O código 50 pela JANELA (config 'comissao_na_linha' desligada): na comanda 180 a janela já vem com a garota 180; o valor
    fica marcado no número dela. O modo padrão, na linha de entrada, está em tests/test_comissao_na_tela.py."""

    def setUp(self):
        super().setUp()
        self.banco.cfg_set("comissao_na_linha", "N")
        self.abrir_turno()
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()
        self.com = self.ctx.comissoes
        self.turno = self.ctx.turnos.atual()["id"]

    # ---------------------------------------------------------------- ajudantes
    def posicao(self, texto):
        self.cx.var_pos.set(texto); self.cx.chamar_mesa(); self.cx.update()

    def digitar_codigo(self, texto):
        self.cx.var_cod.set(texto); self.cx._enter_codigo(); self.cx.update()

    def cadastrar(self, numero, nome, ativa="S"):
        self.ctx.cadastros.salvar("garotas", {"numero": numero, "nome": nome, "ativo": ativa})

    def dar(self, garota, reais):
        return self.com.lancar(garota, round(reais * 100), self.turno, self.ctx.operador_id)

    @staticmethod
    def textos(janela):
        achados = []

        def varre(w):
            for f in w.winfo_children():
                if isinstance(f, ttk.Label):
                    achados.append(str(f.cget("text")))
                varre(f)
        varre(janela)
        return achados

    def dialogos(self, regras: dict, vezes: int = 400):
        """Responde aos diálogos pelo título. Cada valor é uma função(janela) ou o texto do botão que será clicado.
        Cada janela é tratada uma vez; as que não têm regra ficam com o vigia do robô. Cada chamada substitui a anterior."""
        self.robo.regras[:] = [r for r in self.robo.regras if r[0] != "Dialogo"]
        feitos = set()

        def acao(w):
            alvo = next((v for t, v in regras.items() if w.title().startswith(t)), None)
            if alvo is None or str(w) in feitos:
                return
            feitos.add(str(w))
            alvo(w) if callable(alvo) else clicar(w, alvo)
        self.robo.quando("Dialogo", acao, vezes=vezes)

    def lancando(self, numero=None, valor="25,00", visto=None):
        """Preenche a janela da comissão. O clique em Lançar é adiado: ele pode abrir uma pergunta e o robô só
        consegue responder depois que esta função devolver o controle."""
        def acao(w):
            ents = entradas(w)
            if visto is not None:
                visto["numero"], visto["textos"] = ents[0].get(), self.textos(w)
            if numero is not None:
                ents[0].delete(0, "end"); ents[0].insert(0, str(numero))
            ents[1].insert(0, valor)
            w.after(10, lambda: clicar(w, "Lançar"))
        return acao

    @staticmethod
    def desistindo_depois_de(botao):
        """Clica no botão da pergunta e fecha a janela de baixo (a da comissão), que continuaria esperando."""
        def acao(w):
            de_baixo = w.master
            clicar(w, botao)
            de_baixo.after(20, de_baixo.cancelar)
        return acao

    # ---------------------------------------------------------------- lançar
    def test_codigo_50_na_comanda_180_traz_o_numero_e_marca_a_comissao(self):
        visto = {}
        self.dialogos({"Comissão da garota": self.lancando(valor="25,00", visto=visto)})
        self.posicao("180")
        self.digitar_codigo("50")
        self.assertEqual(visto["numero"], "180")                                     # a comanda é a garota
        c = self.banco.um("SELECT garota, valor_cent, status, turno_id, operador_id FROM comissoes_garotas")
        self.assertEqual((c["garota"], c["valor_cent"], c["status"], c["turno_id"], c["operador_id"]),
                         (180, 2500, "pendente", self.turno, self.ctx.operador_id))
        self.assertIn("Comissão de R$ 25,00 lançada para a garota 180", self.cx.status.cget("text"))
        self.assertIn("A pagar a ela: R$ 25,00", self.cx.status.cget("text"))
        self.assertEqual(self.cx.var_cod.get(), "")
        self.assertIsNone(self.cx.produto)                                           # o 50 nunca vira produto
        self.assertEqual(self.cx.grade.total(), 1)                                   # mas a comissão aparece marcada na comanda
        self.assertEqual(self.cx.lbl_total.cget("text"), "0,00")                     # e não é venda: o total é só dos itens
        self.sem_travar()

    def test_cada_lancamento_soma_no_numero_da_garota(self):
        for reais in ("25,00", "30,00"):
            self.dialogos({"Comissão da garota": self.lancando(valor=reais)})
            self.posicao("180")
            self.digitar_codigo("50")
        self.assertEqual(self.com.pendente(180), 5500)
        self.assertIn("A pagar a ela: R$ 55,00", self.cx.status.cget("text"))
        self.sem_travar()

    def test_a_comanda_vazia_da_garota_nao_deixa_fantasma_mas_a_comissao_fica(self):
        self.dialogos({"Comissão da garota": self.lancando(valor="10,00")})
        self.posicao("180")
        self.digitar_codigo("50")
        self.posicao("0")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)
        self.assertEqual(self.com.pendente(180), 1000)
        self.sem_travar()

    def test_nome_da_garota_aparece_na_janela_e_na_comanda_dela(self):
        self.cadastrar(180, "MARIA")
        visto = {}
        self.dialogos({"Comissão da garota": self.lancando(valor="25,00", visto=visto)})
        self.posicao("180")
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Comanda 180 - MARIA")
        self.digitar_codigo("50")
        self.assertIn("MARIA", visto["textos"])
        self.assertIn("garota 180 MARIA", self.cx.status.cget("text"))
        self.posicao("181")
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Comanda 181")           # só a comanda da garota leva o nome
        self.sem_travar()

    def test_garota_inativa_nao_leva_o_nome_na_comanda(self):
        self.cadastrar(180, "MARIA", ativa="N")
        self.posicao("180")
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Comanda 180")

    def test_fora_de_comanda_a_janela_pergunta_o_numero(self):
        visto = {}
        self.dialogos({"Comissão da garota": self.lancando(numero=156, valor="40", visto=visto)})
        self.digitar_codigo("50")                                                    # no balcão
        self.assertEqual(visto["numero"], "")
        self.assertEqual(self.com.pendente(156), 4000)
        self.sem_travar()

    def test_numero_da_mesa_nao_e_sugerido_como_garota(self):
        visto = {}
        self.dialogos({"Comissão da garota": self.lancando(numero=156, valor="40", visto=visto)})
        self.posicao("M5")
        self.digitar_codigo("50")
        self.assertEqual(visto["numero"], "")
        self.sem_travar()

    # ---------------------------------------------------------------- perguntas de segurança
    def test_garota_nao_cadastrada_pergunta_quando_ja_ha_cadastro(self):
        self.cadastrar(180, "MARIA")
        self.dialogos({"Comissão da garota": self.lancando(numero=810, valor="25"),
                       "Garota não cadastrada": self.desistindo_depois_de("Não")})
        self.digitar_codigo("50")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM comissoes_garotas"), 0)    # engano de digitação (810 por 180)
        self.dialogos({"Comissão da garota": self.lancando(numero=810, valor="25"), "Garota não cadastrada": "Sim"})
        self.digitar_codigo("50")
        self.assertEqual(self.com.pendente(810), 2500)
        self.sem_travar()

    def test_sem_nenhuma_garota_cadastrada_nao_pergunta_nada(self):
        self.dialogos({"Comissão da garota": self.lancando(numero=810, valor="25")})
        self.digitar_codigo("50")
        self.assertEqual(self.com.pendente(810), 2500)
        self.sem_travar()

    def test_garota_inativa_pergunta_antes_de_lancar(self):
        self.cadastrar(180, "MARIA", ativa="N")
        self.dialogos({"Comissão da garota": self.lancando(numero=180, valor="25"),
                       "Garota inativa": self.desistindo_depois_de("Não")})
        self.digitar_codigo("50")
        self.assertEqual(self.com.pendente(180), 0)
        self.dialogos({"Comissão da garota": self.lancando(numero=180, valor="25"), "Garota inativa": "Sim"})
        self.digitar_codigo("50")
        self.assertEqual(self.com.pendente(180), 2500)
        self.sem_travar()

    def test_valor_alto_pede_confirmacao(self):
        self.dialogos({"Comissão da garota": self.lancando(numero=180, valor="2500"),
                       "Confirma o valor": self.desistindo_depois_de("Não")})        # 2500 no lugar de 25,00
        self.digitar_codigo("50")
        self.assertEqual(self.com.pendente(180), 0)
        self.dialogos({"Comissão da garota": self.lancando(numero=180, valor="800"), "Confirma o valor": "Sim"})
        self.digitar_codigo("50")
        self.assertEqual(self.com.pendente(180), 80000)
        self.sem_travar()

    def test_numero_e_valor_invalidos_avisam_na_propria_janela(self):
        mensagens = []

        def tenta(numero, valor):
            def acao(w):
                ents = entradas(w)
                ents[0].delete(0, "end"); ents[0].insert(0, numero)
                ents[1].delete(0, "end"); ents[1].insert(0, valor)

                def clicar_e_ver():
                    clicar(w, "Lançar")
                    mensagens.append([t for t in self.textos(w) if t])
                    w.cancelar()
                w.after(10, clicar_e_ver)
            return acao
        for numero, valor, esperado in (("abc", "10", "número da garota"), ("180", "abc", "Valor inválido"),
                                        ("180", "0", "Informe o valor"), ("0", "10", "vai de 1 a")):
            self.dialogos({"Comissão da garota": tenta(numero, valor)})
            self.digitar_codigo("50")
            self.assertTrue(any(esperado in t for t in mensagens[-1]), (numero, valor, mensagens[-1]))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM comissoes_garotas"), 0)
        self.sem_travar()

    def test_esc_na_janela_nao_lanca_nada(self):
        self.dialogos({"Comissão da garota": lambda w: w.after(10, w.cancelar)})
        self.posicao("180")
        self.digitar_codigo("50")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM comissoes_garotas"), 0)
        self.sem_travar()

    # ---------------------------------------------------------------- senha, código desligado, turno
    def test_operador_so_caixa_lanca_sem_senha_e_com_senha_quando_configurado(self):
        self.ctx.cadastros.salvar("operadores", {"nome": "BAR", "senha": "1", "nivel": "0"})
        self.ctx.operador = self.ctx.acesso.autenticar("BAR", "1")
        self.dialogos({"Comissão da garota": self.lancando(numero=180, valor="10")})
        self.digitar_codigo("50")
        self.assertEqual(self.com.pendente(180), 1000)                               # por padrão não pede senha
        self.banco.cfg_set("exigir_senha_comissao", "S")
        pedidas = []

        def senha(w):
            pedidas.append(w.title())
            entradas(w)[0].insert(0, "ADM"); clicar(w, "OK")
        self.dialogos({"Autorização": senha, "Comissão da garota": self.lancando(numero=180, valor="20")})
        self.digitar_codigo("50")
        self.assertEqual(pedidas, ["Autorização"])
        self.assertEqual(self.com.pendente(180), 3000)
        self.assertEqual(self.banco.valor("SELECT operador_id FROM comissoes_garotas ORDER BY id DESC LIMIT 1"), self.ctx.operador_id)
        self.sem_travar()

    def test_com_senha_exigida_desistir_da_senha_nao_abre_a_janela(self):
        self.ctx.cadastros.salvar("operadores", {"nome": "BAR", "senha": "1", "nivel": "0"})
        self.ctx.operador = self.ctx.acesso.autenticar("BAR", "1")
        self.banco.cfg_set("exigir_senha_comissao", "S")
        self.dialogos({"Autorização": lambda w: w.after(10, w.cancelar)})
        self.digitar_codigo("50")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM comissoes_garotas"), 0)
        self.sem_travar()

    def test_codigo_desligado_volta_a_ser_busca_de_produto(self):
        from src.controllers.config_controller import ConfigController
        ConfigController(self.banco).salvar_config({"codigo_comissao": ""})
        self.digitar_codigo("50")
        self.assertIn("não encontrado", self.cx.status.cget("text"))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM comissoes_garotas"), 0)
        self.sem_travar()

    def test_o_dono_pode_trocar_o_codigo(self):
        from src.controllers.config_controller import ConfigController
        ConfigController(self.banco).salvar_config({"codigo_comissao": "90"})
        self.dialogos({"Comissão da garota": self.lancando(numero=180, valor="10")})
        self.digitar_codigo("090")
        self.assertEqual(self.com.pendente(180), 1000)
        self.digitar_codigo("50")                                                    # o 50 já não é a comissão
        self.assertIn("não encontrado", self.cx.status.cget("text"))
        self.sem_travar()

    def test_produto_de_codigo_parecido_continua_sendo_vendido(self):
        self.digitar_codigo("2")                                                     # AGUA, código 2
        self.assertEqual(self.cx.produto["nome"], "AGUA")
        self.sem_travar()

    # ---------------------------------------------------------------- janela das comissões
    def abrir_comissoes(self):
        from src.ui.comissao_ui import JanelaComissoes
        self.cx.comissoes()
        janela = next(w for w in self.cx.winfo_children() if isinstance(w, JanelaComissoes))
        janela.update()
        return janela

    def test_botao_comissoes_esta_na_barra_do_caixa(self):
        nomes = [t[0] for t in self.cx.tarefas]
        self.assertIn("Comissões", nomes)
        self.assertEqual(nomes[-1], "Sair")
        self.assertEqual(len(self.cx.botoes_tarefa), len(self.cx.tarefas))

    def test_janela_lista_o_que_pagar_a_cada_garota(self):
        self.cadastrar(180, "MARIA")
        self.dar(180, 25); self.dar(180, 30); self.dar(156, 40)
        j = self.abrir_comissoes()
        self.assertEqual([[str(c) for c in j.grade.valores(i)] for i in j.grade.tree.get_children()],
                         [["156", "", "1", "40,00"], ["180", "MARIA", "2", "55,00"]])
        self.assertIn("R$ 95,00", j.lbl.cget("text"))
        j.grade.selecionar(180); j._mostrar_itens()
        self.assertEqual([j.itens.valores(i)[2] for i in j.itens.tree.get_children()], ["25,00", "30,00"])
        j.destroy()

    def test_janela_sem_nada_a_pagar_avisa(self):
        j = self.abrir_comissoes()
        self.assertEqual(j.grade.total(), 0)
        self.assertIn("Nenhuma comissão a pagar", j.lbl.cget("text"))
        self.dialogos({"Aviso": lambda w: clicar(w, "OK")})
        j.pagar()                                                                    # nenhuma garota escolhida
        j.destroy()
        self.sem_travar()

    def test_pagar_tira_do_caixa_e_mostra_o_recibo(self):
        self.cadastrar(180, "MARIA")
        self.dar(180, 25); self.dar(180, 30)
        esperado = self.ctx.turnos.resumo(self.turno)["esperado"]
        recibos = []
        self.robo.quando("Visualizador", lambda w: (recibos.append(w.texto), w.destroy()), vezes=5)
        self.dialogos({"Pagar comissão": "Pagar"})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.pagar(); j.update()
        self.assertEqual(self.com.pendente(180), 0)
        m = self.banco.um("SELECT tipo, valor_cent, descricao FROM movimentos_caixa")
        self.assertEqual((m["tipo"], m["valor_cent"], m["descricao"]), ("saida", 5500, "Comissão garota 180 MARIA"))
        self.assertEqual(self.ctx.turnos.resumo(self.turno)["esperado"], esperado - 5500)
        self.assertEqual(len(recibos), 2)                                    # o recibo e o comprovante da saída do caixa
        self.assertIn("RECIBO DE COMISSÃO", recibos[0])
        self.assertIn("Garota: 180 MARIA", recibos[0])
        self.assertIn("55,00", recibos[0])
        self.assertIn("SANGRIA", recibos[1])
        self.assertIn("Motivo: Comissão garota 180 MARIA", recibos[1])
        self.assertEqual(j.grade.total(), 0)
        self.assertIn("paga à garota 180", j.status.cget("text"))
        j.destroy()
        self.sem_travar()

    def test_pagar_fora_do_caixa_nao_registra_sangria(self):
        self.dar(180, 25)
        self.robo.quando("Visualizador", lambda w: w.destroy())

        def pagar_fora(w):
            [c for c in w.winfo_children()[0].winfo_children() if isinstance(c, ttk.Checkbutton)][0].invoke()
            clicar(w, "Pagar")
        self.dialogos({"Pagar comissão": pagar_fora})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.pagar()
        self.assertEqual(self.com.pendente(180), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)
        j.destroy()
        self.sem_travar()

    def test_desistir_do_pagamento_nao_muda_nada(self):
        self.dar(180, 25)
        self.dialogos({"Pagar comissão": "Cancelar"})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.pagar()
        self.assertEqual(self.com.pendente(180), 2500)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)
        j.destroy()
        self.sem_travar()

    def test_cancelar_um_lancamento_pela_janela(self):
        errado = self.dar(180, 999); self.dar(180, 25)
        self.dialogos({"Cancelar comissão": "Sim"})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.itens.selecionar(errado)
        j.cancelar()
        self.assertEqual(self.com.pendente(180), 2500)
        self.assertEqual(self.banco.valor("SELECT status FROM comissoes_garotas WHERE id = ?", (errado,)), "cancelada")
        self.assertEqual(j.itens.total(), 1)
        j.destroy()
        self.sem_travar()

    def test_lancar_pela_propria_janela(self):
        self.dialogos({"Comissão da garota": self.lancando(numero=156, valor="40")})
        j = self.abrir_comissoes()
        j.lancar()
        self.assertEqual(self.com.pendente(156), 4000)
        self.assertEqual(j.grade.total(), 1)
        self.assertIn("garota 156", j.status.cget("text"))
        j.destroy()
        self.sem_travar()

    def test_pagar_exige_senha_de_supervisor_do_operador_so_caixa(self):
        self.dar(180, 25)
        self.ctx.cadastros.salvar("operadores", {"nome": "BAR", "senha": "1", "nivel": "0"})
        self.ctx.operador = self.ctx.acesso.autenticar("BAR", "1")
        pedidas = []

        def senha(w):
            pedidas.append(w.title())
            entradas(w)[0].insert(0, "ADM"); clicar(w, "OK")
        self.robo.quando("Visualizador", lambda w: w.destroy(), vezes=5)
        self.dialogos({"Autorização": senha, "Pagar comissão": "Pagar"})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.pagar()
        self.assertEqual(pedidas, ["Autorização"])
        self.assertEqual(self.com.pendente(180), 0)
        j.destroy()
        self.sem_travar()

    # ---------------------------------------------------------------- relatório e cadastro
    def test_relatorio_mostra_as_comissoes_por_garota(self):
        from src.ui.relatorios_ui import abrir_relatorio
        self.cadastrar(180, "MARIA")
        self.dar(180, 25); self.dar(180, 30)
        j = abrir_relatorio(self.root, self.ctx, "comissao_garotas")
        j.update()
        texto = j.caixa.get("1.0", "end")
        for trecho in ("COMISSÃO DAS GAROTAS", "180", "MARIA", "55,00", "A pagar"):
            self.assertIn(trecho, texto)
        j.destroy()

    def test_cadastro_de_garotas_abre_e_grava_pelo_formulario(self):
        from src.ui.cadastros_tk import JanelaCadastro
        j = JanelaCadastro(self.root, self.ctx, "garotas")
        j.update()
        j.incluir()
        j.campos["numero"].var.set("180")
        j.campos["nome"].var.set("MARIA")
        j.gravar(); j.update()
        g = self.banco.um("SELECT numero, nome, ativo FROM garotas")
        self.assertEqual((g["numero"], g["nome"], g["ativo"]), (180, "MARIA", 1))
        self.assertEqual(j.grade.total(), 1)
        j.destroy()
        self.sem_travar()

    # ---------------------------------------------------------------- troca de turno
    def trocando_o_turno(self, textos: list, resposta: str):
        """Responde à troca de turno: digita o valor da gaveta e, na pergunta final, guarda o texto e clica em `resposta`."""
        def troca(w):
            campos = entradas(w)
            if campos:
                campos[0].delete(0, "end"); campos[0].insert(0, "100,00"); clicar(w, "OK")
            else:
                textos.append(self.textos(w)); clicar(w, resposta)
        return troca

    def test_troca_de_turno_avisa_da_comissao_a_pagar(self):
        self.dar(180, 25); self.dar(156, 40)
        textos = []
        self.dialogos({"Conferir maquininha": "Continuar", "Troca de turno": self.trocando_o_turno(textos, "Não")})
        self.cx.fechar_turno(); self.cx.update()
        aviso = " ".join(t for t in textos[0] if "Comissão" in t)
        self.assertIn("Comissão das garotas a pagar: R$ 65,00 (2 garota(s))", aviso)
        self.assertIn("botão Comissões", aviso)
        self.assertEqual(self.banco.valor("SELECT status FROM turnos"), "aberto")        # respondeu Não: o turno segue aberto
        self.sem_travar()

    def test_troca_de_turno_sem_comissao_pendente_nao_avisa(self):
        textos = []
        self.dialogos({"Conferir maquininha": "Continuar", "Troca de turno": self.trocando_o_turno(textos, "Não")})
        self.cx.fechar_turno(); self.cx.update()
        self.assertFalse([t for t in textos[0] if "Comissão" in t], textos)
        self.sem_travar()

    def test_painel_do_fechamento_mostra_o_total_de_comissao_lancado(self):
        self.dar(180, 25); self.dar(180, 30)
        vistos = []
        self.robo.quando("PainelFechamento", lambda w: (vistos.append(self.textos(w)), w.destroy()))
        self.dialogos({"Conferir maquininha": "Continuar", "Troca de turno": self.trocando_o_turno([], "Sim")})
        from unittest.mock import patch
        declarados = {r["tipo_id"]: 10000 if r["dinheiro"] else 0
                      for r in self.ctx.turnos.formas_conferencia(
                          self.ctx.turnos.atual()["id"], self.ctx.operador_id)}
        with patch("src.ui.fechamento_ui.coletar", return_value={
                "informados_por_forma": declarados, "justificativa": ""}):
            self.cx.fechar_turno(); self.cx.update()
        self.assertIn("Comissões das garotas", vistos[0])
        self.assertIn("55,00", vistos[0])
        self.assertEqual(self.banco.valor("SELECT status FROM turnos"), "fechado")
        self.sem_travar()

    # ---------------------------------------------------------------- impressora térmica
    def configurar_termica(self):
        import os
        import shutil
        from pathlib import Path
        pasta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, pasta, True)
        saida = os.path.join(pasta, "saida.prn")
        self.ctx.impressao.pasta_saida = lambda: Path(pasta)
        self.ctx.config.salvar_maquina({"modo_impressao": "termica", "impressora_termica_conexao": "arquivo",
                                        "impressora_termica_endereco": saida, "impressora_termica_gaveta": "S"})
        return Path(saida)

    def test_recibo_sai_na_termica_e_abre_a_gaveta_quando_o_dinheiro_sai_do_caixa(self):
        saida = self.configurar_termica()
        self.cadastrar(180, "MARIA"); self.dar(180, 25)
        self.dialogos({"Pagar comissão": "Pagar"})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.pagar()
        self.ctx.impressao.fila.processar()
        dados = saida.read_bytes()
        self.assertIn("RECIBO DE COMISSÃO".encode("cp850"), dados)
        self.assertIn(b"\x1bp", dados)                                               # a gaveta abriu
        j.destroy()
        self.sem_travar()

    def test_pagando_fora_do_caixa_o_recibo_sai_mas_a_gaveta_nao_abre(self):
        saida = self.configurar_termica()
        self.dar(180, 25)

        def pagar_fora(w):
            [c for c in w.winfo_children()[0].winfo_children() if isinstance(c, ttk.Checkbutton)][0].invoke()
            clicar(w, "Pagar")
        self.dialogos({"Pagar comissão": pagar_fora})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.pagar()
        self.ctx.impressao.fila.processar()
        dados = saida.read_bytes()
        self.assertIn("Pago fora do caixa.".encode("cp850"), dados)
        self.assertNotIn(b"\x1bp", dados)
        j.destroy()
        self.sem_travar()

    # ---------------------------------------------------------------- a comanda mostra o que foi marcado nela
    def linhas(self):
        return [[str(c) for c in self.cx.grade.valores(i)] for i in self.cx.grade.tree.get_children()]

    def lancar_item(self, cod, qtd):
        self.cx.var_cod.set(cod); self.cx._enter_codigo(); self.cx.update()
        self.cx.var_qtd.set(str(qtd)); self.cx.confirmar_item(); self.cx.update()

    def faixa_visivel(self):
        return self.cx.faixa.winfo_manager() == "pack"

    def test_comanda_da_garota_abre_mostrando_as_comissoes_marcadas(self):
        self.cadastrar(180, "MARIA")
        self.dar(180, 25); self.dar(180, 30)
        self.posicao("180")
        linhas = self.linhas()
        self.assertEqual([(l[0], l[1], l[3], l[4], l[5]) for l in linhas],
                         [("50", "COMISSÃO (a pagar)", "25,00", "1", "25,00"), ("50", "COMISSÃO (a pagar)", "30,00", "1", "30,00")])
        self.assertIn("ADM", linhas[0][6])
        self.assertEqual(self.cx.lbl_total.cget("text"), "0,00")                      # comissão não é venda
        self.assertTrue(self.faixa_visivel())
        self.assertIn("COMISSÃO MARCADA NA COMANDA 180 MARIA", self.cx.faixa.cget("text"))
        self.assertIn("A pagar: R$ 55,00", self.cx.faixa.cget("text"))
        self.sem_travar()

    def test_a_comissao_lancada_aparece_na_hora_na_comanda_da_tela(self):
        self.dialogos({"Comissão da garota": self.lancando(valor="25,00")})
        self.posicao("180")
        self.assertEqual(self.linhas(), [])
        self.assertFalse(self.faixa_visivel())
        self.digitar_codigo("50")
        self.assertEqual([(l[1], l[3]) for l in self.linhas()], [("COMISSÃO (a pagar)", "25,00")])
        self.assertIn("A pagar: R$ 25,00", self.cx.faixa.cget("text"))
        self.sem_travar()

    def test_comanda_que_sumiu_por_estar_vazia_reabre_mostrando_as_comissoes(self):
        self.dar(180, 25)
        self.posicao("180")
        self.posicao("0")                                                             # sai: a comanda vazia é descartada
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)
        self.posicao("180")                                                           # e abre de novo com a comissão à vista
        self.assertEqual([l[1] for l in self.linhas()], ["COMISSÃO (a pagar)"])
        self.sem_travar()

    def test_comanda_com_itens_e_comissao_mostra_os_dois_e_o_total_e_so_dos_itens(self):
        self.posicao("180")
        self.lancar_item("1", 1)                                                      # SKOL, R$ 8,00
        self.dar(180, 25)
        self.cx.recarregar()
        linhas = self.linhas()
        self.assertEqual([l[1] for l in linhas], ["SKOL", "COMISSÃO (a pagar)"])
        self.assertEqual(self.cx.lbl_total.cget("text"), "8,80")                      # 8,00 + 10% de serviço, sem a comissão
        self.assertTrue(self.faixa_visivel())
        self.sem_travar()

    def test_comissao_paga_neste_turno_fica_cinza_e_a_de_turno_anterior_nao_aparece(self):
        self.dar(180, 25)
        self.com.pagar(180, self.turno, self.ctx.operador_id)
        self.posicao("180")
        self.assertEqual([(l[1], l[3]) for l in self.linhas()], [("COMISSÃO (paga)", "25,00")])
        iid = self.cx.grade.tree.get_children()[0]
        self.assertIn("comissao_paga", self.cx.grade.tree.item(iid, "tags"))
        self.assertIn("A pagar: R$ 0,00", self.cx.faixa.cget("text"))
        self.assertIn("Paga neste turno: R$ 25,00", self.cx.faixa.cget("text"))
        self.dar(156, 10)                                                             # pendente do turno que vai fechar
        self.posicao("0")
        self.ctx.turnos.fechar(self.turno, self.ctx.operador_id, 7500)
        self.turno = self.ctx.turnos.abrir(self.ctx.operador_id, 2, 0)
        self.posicao("180")
        self.assertEqual(self.linhas(), [])                                           # a paga do turno anterior saiu da tela
        self.assertFalse(self.faixa_visivel())
        self.posicao("156")
        self.assertEqual([l[1] for l in self.linhas()], ["COMISSÃO (a pagar)"])       # a pendente continua, em qualquer turno
        self.sem_travar()

    def test_comissao_cancelada_some_da_comanda(self):
        errado = self.dar(180, 999)
        self.dar(180, 25)
        self.com.cancelar(errado, self.ctx.operador_id)
        self.posicao("180")
        self.assertEqual([l[3] for l in self.linhas()], ["25,00"])
        self.sem_travar()

    def test_mesa_com_o_mesmo_numero_da_garota_nao_mostra_a_comissao(self):
        self.dar(5, 10)                                                               # garota 5: não tem nada a ver com a mesa 5
        self.posicao("M5")
        self.lancar_item("1", 1)
        self.assertEqual([l[1] for l in self.linhas()], ["SKOL"])
        self.assertFalse(self.faixa_visivel())
        self.sem_travar()

    def test_comissao_marcada_por_engano_numa_comanda_de_cliente_fica_a_vista(self):
        self.dar(3, 10)                                                               # número errado: era da garota 130
        self.posicao("3")
        self.lancar_item("1", 1)
        self.assertEqual([l[1] for l in self.linhas()], ["SKOL", "COMISSÃO (a pagar)"])
        self.assertTrue(self.faixa_visivel())
        self.sem_travar()

    def test_comanda_sem_nenhuma_comissao_segue_como_antes(self):
        self.posicao("7")
        self.lancar_item("1", 2)
        self.assertEqual([l[1] for l in self.linhas()], ["SKOL"])
        self.assertFalse(self.faixa_visivel())
        self.assertEqual(self.cx.comissao_marcada, [])
        self.sem_travar()

    # ---------------------------------------------------------------- a linha da comissão é só leitura
    def test_linha_de_comissao_nao_se_muda_pela_lista_de_itens(self):
        marcada = self.dar(180, 25)
        self.posicao("180")
        self.cx.grade.selecionar(f"c{marcada}")
        avisos = []
        self.dialogos({"Aviso": lambda w: (avisos.append(self.textos(w)), clicar(w, "OK"))})
        self.cx.observacao_item()
        self.cx.cancelar_item_selecionado()
        self.cx.transferir_item()
        self.assertEqual(len(avisos), 3)
        self.assertTrue(all(any("botão Comissões" in t for t in a) for a in avisos), avisos)
        self.assertEqual(self.com.pendente(180), 2500)                                # nada mudou
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda"), 0)
        self.sem_travar()

    def test_cancelar_item_vai_para_o_ultimo_item_e_nao_para_a_comissao(self):
        self.posicao("180")
        self.lancar_item("1", 1); self.lancar_item("2", 1)
        self.dar(180, 25)
        self.cx.recarregar()
        self.cx._foco_grade(ultimo=True)
        escolhida = self.cx.grade.selecionado()
        self.assertTrue(str(escolhida).isdigit(), escolhida)
        self.assertEqual(self.cx.grade.valores(escolhida)[1], "AGUA")                 # o último item, não a comissão
        self.sem_travar()

    def test_pagar_na_comanda_que_so_tem_comissao_orienta_a_usar_o_botao(self):
        self.dar(180, 25)
        self.posicao("180")
        avisos = []
        self.dialogos({"Acertar a garota": "Não",                                    # comanda fora do cadastro: pergunta antes
                       "Aviso": lambda w: (avisos.append(self.textos(w)), clicar(w, "OK"))})
        self.cx.pagar()
        self.assertTrue(any("só tem comissão marcada" in t for t in avisos[0]), avisos)
        self.posicao("7")
        self.cx.pagar()
        self.assertTrue(any("Lance ao menos um item" in t for t in avisos[1]), avisos)       # comanda comum: aviso de sempre
        self.sem_travar()

    # ---------------------------------------------------------------- a janela das comissões atualiza a comanda da tela
    def test_pagar_pela_janela_atualiza_a_comanda_que_esta_na_tela(self):
        self.dar(180, 25)
        self.posicao("180")
        self.robo.quando("Visualizador", lambda w: w.destroy(), vezes=5)       # recibo e comprovante da saída
        self.dialogos({"Pagar comissão": "Pagar"})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.pagar()
        self.assertEqual([l[1] for l in self.linhas()], ["COMISSÃO (paga)"])
        self.assertIn("A pagar: R$ 0,00", self.cx.faixa.cget("text"))
        j.destroy()
        self.sem_travar()

    def test_cancelar_pela_janela_atualiza_a_comanda_que_esta_na_tela(self):
        errado = self.dar(180, 999)
        self.dar(180, 25)
        self.posicao("180")
        self.dialogos({"Cancelar comissão": "Sim"})
        j = self.abrir_comissoes()
        j.grade.selecionar(180); j._mostrar_itens()
        j.itens.selecionar(errado)
        j.cancelar()
        self.assertEqual([l[3] for l in self.linhas()], ["25,00"])
        j.destroy()
        self.sem_travar()

    def test_lancar_pela_janela_atualiza_a_comanda_que_esta_na_tela(self):
        self.posicao("156")
        self.dialogos({"Comissão da garota": self.lancando(numero=156, valor="40")})
        j = self.abrir_comissoes()
        j.lancar()
        self.assertEqual([l[3] for l in self.linhas()], ["40,00"])
        j.destroy()
        self.sem_travar()


class TesteTelegramNaTela(BaseUI):
    def setUp(self):
        super().setUp()
        from tests.test_telegram import TelegramFalso
        self.falso = TelegramFalso()
        self.ctx.telegram._http = self.falso

    def test_conectar_o_bot_gerar_codigo_e_ver_o_celular_aparecer(self):
        from src.ui import config_ui
        from tests.test_telegram import DONO, TOKEN
        j = config_ui.abrir(self.root, self.ctx, "telegram"); j.update()
        self.assertTrue(j.btn_codigo.instate(["disabled"]))           # sem token ainda não gera código
        self.assertIn("Ainda não há celular", j.lbl_status.cget("text"))
        j.var_token.set(TOKEN); j.conectar(); j.update()
        self.assertIn("@casa_bot", j.lbl_bot.cget("text"))
        self.assertFalse(j.btn_codigo.instate(["disabled"]))
        j.gerar_codigo(); j.update()
        codigo = self.ctx.telegram.codigo_pendente()
        self.assertEqual(j.lbl_codigo.cget("text"), f"/start {codigo}")
        self.falso.digitar(DONO, f"/start {codigo}", nome="Carlos")      # o dono manda o código pelo celular
        self.ctx.telegram.processar_atualizacoes(0)
        j._atualizar(); j.update()
        self.assertEqual([j.grade.valores(i)[0] for i in j.grade.tree.get_children()], ["Carlos"])
        self.assertEqual(j.lbl_codigo.cget("text"), "")                  # o código some depois de usado
        self.assertIn("Funcionando", j.lbl_status.cget("text"))
        self.robo.quando("Dialogo", lambda w: clicar(w, "OK"))
        j.testar(); j.update()
        self.assertIn("Teste do PDV", self.falso.textos(DONO)[-1])
        self.sem_travar()
        j.destroy()

    def test_token_errado_mostra_o_erro_e_nao_conecta(self):
        from src.ui import config_ui
        j = config_ui.abrir(self.root, self.ctx, "telegram"); j.update()
        vistos = []
        self.robo.quando("Dialogo", lambda w: (vistos.append(w.title()), w.destroy()))
        j.var_token.set("isso nao e um token"); j.conectar(); j.update()
        self.assertEqual(self.banco.cfg("telegram_token"), "")
        self.assertEqual(len(vistos), 1)
        self.sem_travar()
        j.destroy()

    def test_ligar_sem_parear_avisa_e_desliga_a_caixa(self):
        from src.ui import config_ui
        j = config_ui.abrir(self.root, self.ctx, "telegram"); j.update()
        self.robo.quando("Dialogo", lambda w: clicar(w, "OK"))
        j.var_ativo.set(True); j._alternar(); j.update()
        self.assertFalse(j.var_ativo.get())
        self.assertFalse(self.banco.cfg_bool("telegram_ativo"))
        self.sem_travar()
        j.destroy()

    def test_remover_celular_pela_tela(self):
        from src.ui import config_ui
        from tests.test_telegram import DONO, TOKEN
        self.ctx.telegram.salvar_token(TOKEN)
        self.banco.executar("INSERT INTO telegram_chats(chat_id, nome, criado_em) VALUES (?,?,?)", (DONO, "Carlos", "2026-10-03 21:00:00"))
        j = config_ui.abrir(self.root, self.ctx, "telegram"); j.update()
        j.grade.selecionar(DONO)
        self.robo.quando("Dialogo", lambda w: clicar(w, "Sim"))
        j.remover(); j.update()
        self.assertEqual(self.ctx.telegram.chats(), [])
        self.sem_travar()
        j.destroy()

    def test_menu_configuracoes_oferece_o_telegram_ao_dono(self):
        from src.ui.app import CONFIGURACOES
        self.assertIn("telegram", [c[0] for c in CONFIGURACOES])
        modulos = {m["modulo"] for m in self.ctx.acesso.modulos_permitidos(self.ctx.operador, "Configurações")}
        self.assertIn("cfg_telegram", modulos)


class TestePainelEstoqueUI(BaseUI):
    def test_visao_adega_filtra_sem_estoque_e_ponto_de_pedido(self):
        self.banco.executar("UPDATE produtos SET preco_gelada_cent = 1000 WHERE id = ?", (self.skol,))
        j = self._painel()
        j.v_visao.set("Adega")
        j.cb_visao.event_generate("<<ComboboxSelected>>")
        j.update()
        self.assertEqual(j.tree.get_children(), (str(self.skol),))
        self.assertIn("Alta", j.tree.item(str(self.skol), "values")[0])
        self.assertIn("Visão Adega", j.lbl_sub.cget("text"))
        self.assertEqual(j.cartoes["total"].valor.cget("text"), "1")
        j.filtrar("ponto")
        self.assertEqual(j.tree.get_children(), ())
        j.v_visao.set("Geral")
        j.atualizar()
        self.assertEqual(j.tree.get_children(), (str(self.agua),))
        j.destroy()

    def _menu_do(self, nome, senha):
        from src.ui.app import App
        app = App(self.banco)
        self.addCleanup(app.root.destroy)
        app.ctx.operador = app.ctx.acesso.autenticar(nome, senha)
        return app

    def _painel(self):
        from src.ui.estoque_ui import PainelEstoque
        self.banco.executar("UPDATE produtos SET qt_atual = 0 WHERE id = ?", (self.skol,))
        self.banco.executar("UPDATE produtos SET controla_estoque = 1, qt_atual = 4, estoque_minimo = 5 WHERE id = ?", (self.agua,))
        j = PainelEstoque(self.root, self.ctx)
        j.update()
        return j

    def test_painel_mostra_cartoes_lista_e_filtros(self):
        j = self._painel()
        self.assertEqual(j.tree.get_children(), (str(self.agua), str(self.skol)))      # em ordem de nome
        self.assertEqual([j.cartoes[c].valor.cget("text") for c in ("total", "sem", "ponto", "normal")], ["2", "1", "1", "0"])
        j.filtrar("sem"); j.update()
        self.assertEqual(j.tree.get_children(), (str(self.skol),))
        j.filtrar("todos")
        j.v_busca.set("agu"); j.update()
        self.assertEqual(j.tree.get_children(), (str(self.agua),))
        j.v_busca.set("xyz"); j.update()
        self.assertEqual(j.tree.get_children(), ())
        j.destroy()

    def test_selecionar_mostra_detalhe_e_registrar_entrada(self):
        j = self._painel()
        j.tree.selection_set(str(self.skol)); j.update()
        self.assertEqual(j.produto["id"], self.skol)
        self.assertIn("SKOL", j.d_nome.cget("text"))
        self.assertTrue(j.botoes["entrada"].ativo)
        self.assertTrue(j.registrar("entrada", 24)); j.update()
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 24)
        self.assertEqual(j.produto["qt_atual"], 24)                          # a seleção sobrevive à atualização
        self.assertEqual(len(j.hist.get_children()), 1)
        self.assertEqual(j.cartoes["sem"].valor.cget("text"), "0")
        j.destroy()

    def test_registrar_erro_de_negocio_nao_grava(self):
        from unittest import mock
        j = self._painel()
        j.tree.selection_set(str(self.skol)); j.update()
        with mock.patch.object(tema, "erro") as erro:
            self.assertFalse(j.registrar("saida", 5))                        # estoque zerado
        erro.assert_called_once()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque"), 0)
        j.destroy()

    def test_dialogo_de_quantidade_mostra_previa(self):
        j = self._painel()
        j.tree.selection_set(str(self.agua)); j.update()

        def preencher(dlg):
            ent = next(w for w in dlg.corpo.winfo_children() if w.winfo_class() == "TEntry")
            ent.insert(0, "6"); dlg.update()
            previa = [w.cget("text") for w in dlg.corpo.winfo_children() if w.winfo_class() == "TLabel"]
            self.assertIn("Vai ficar com 10 UN", previa)
            dlg.event_generate("<Return>")
        self.robo.quando("Dialogo", preencher)
        j.registrar_dialogo("entrada"); j.update()
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.agua,)), 10)
        self.sem_travar()
        j.destroy()

    def test_definir_minimo(self):
        from unittest import mock
        j = self._painel()
        j.tree.selection_set(str(self.agua)); j.update()
        with mock.patch.object(tema, "pedir_texto", return_value=7.5):
            j.definir_minimo()
        self.assertEqual(self.banco.valor("SELECT estoque_minimo FROM produtos WHERE id = ?", (self.agua,)), 7.5)
        j.destroy()

    def test_gerar_pedido_e_lista_de_compras(self):
        from unittest import mock
        from src.ui import estoque_ui
        forn = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        self.banco.executar("UPDATE produtos SET estoque_minimo = 5 WHERE id = ?", (self.skol,))
        j = self._painel()
        abertos = []
        j.novo_lancamento = lambda lid=None: abertos.append(lid)
        with mock.patch.object(tema, "escolher", return_value=forn):
            j.gerar_pedido(); j.update()
        pedido = self.ctx.estoque.lancamentos("pedido")[0]
        self.assertEqual((pedido["fornecedor"], abertos), ("AMBEV", [pedido["id"]]))
        from src.ui.lancamentos_ui import JanelaEstoque
        je = JanelaEstoque(self.root, self.ctx); je.carregar(pedido["id"]); je.update()
        self.assertEqual((je.grade.total(), je.v_tipo.get(), je.lanc_id), (2, "pedido", pedido["id"]))
        je.destroy()
        with mock.patch.object(estoque_ui, "Visualizador") as vis:
            j.lista_de_compras()
        self.assertIn("SKOL", vis.call_args.args[3])
        j.destroy()

    def test_produto_sem_controle_e_achado_e_comeca_a_controlar_pelo_painel(self):
        j = self._painel()
        self.banco.executar("UPDATE produtos SET controla_estoque = 0, qt_atual = 0 WHERE id = ?", (self.agua,))
        j.v_busca.set("agu"); j.update()
        self.assertEqual(j.tree.get_children(), (str(self.agua),))              # a busca acha mesmo sem controle
        j.tree.selection_set(str(self.agua)); j.update()
        self.assertEqual(j.produto["situacao"], "livre")
        self.assertIn("ainda não controla", j.d_info.cget("text"))
        self.assertFalse(j.botoes["saida"].ativo)
        self.assertFalse(j.botoes["descarte"].ativo)
        self.assertTrue(j.botoes["contagem"].ativo)
        self.assertTrue(j.registrar("contagem", 36)); j.update()
        row = self.banco.um("SELECT controla_estoque, qt_atual FROM produtos WHERE id = ?", (self.agua,))
        self.assertEqual((row["controla_estoque"], row["qt_atual"]), (1, 36))
        self.assertTrue(j.botoes["saida"].ativo)
        j.v_busca.set(""); j.filtrar("livre"); j.update()
        self.assertEqual(j.tree.get_children(), ())
        j.destroy()

    def test_editar_cadastro_abre_o_produto_selecionado(self):
        from src.ui.cadastros_tk import JanelaCadastro
        j = self._painel()
        j.tree.selection_set(str(self.agua)); j.update()
        j.editar_cadastro(); j.update()
        cadastro = next(w for w in j.winfo_children() if isinstance(w, JanelaCadastro))
        self.assertEqual(cadastro.id_atual, self.agua)
        cadastro.destroy(); j.destroy()

    def test_cadastro_do_produto_ajusta_o_estoque_e_liga_o_controle(self):
        from unittest import mock
        from src.ui.cadastros_tk import JanelaCadastro
        j = JanelaCadastro(self.root, self.ctx, "produtos"); j.update()
        j.grade.selecionar(self.agua); j.update()
        self.assertEqual(j.id_atual, self.agua)
        j.campos["nome"].set("AGUA MINERAL")                                      # edição ainda não gravada
        with mock.patch.object(tema, "pedir_texto", return_value=24.0):
            j._ajustar_estoque()
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.agua,)), 24)
        self.assertEqual(self.banco.valor("SELECT controla_estoque FROM produtos WHERE id = ?", (self.agua,)), 1)
        self.assertEqual(j.campos["nome"].get(), "AGUA MINERAL")                  # o que estava sendo digitado não se perde
        self.assertEqual(j.campos["controla_estoque"].get(), "S")
        with mock.patch.object(tema, "pedir_texto", return_value=0.0):
            j._ajustar_estoque()                                                 # zero é uma contagem válida
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.agua,)), 0)
        j.incluir()
        with mock.patch.object(tema, "aviso") as aviso:
            j._ajustar_estoque()
        aviso.assert_called_once()
        j.destroy()

    def test_painel_vazio_orienta_o_operador(self):
        from src.ui.estoque_ui import PainelEstoque
        self.banco.executar("UPDATE produtos SET controla_estoque = 0")
        j = PainelEstoque(self.root, self.ctx); j.update()
        self.assertEqual(j.tree.get_children(), ())
        self.assertIn("Nenhum produto controla estoque", j.lbl_vazio.cget("text"))
        j.destroy()

    def test_menu_abre_o_painel_e_cartoes_filtram(self):
        app = self._menu_do("adm", "adm")
        app.mostrar_menu(); app.root.update()
        app.cartoes["estoque_sem"].clique()
        j = app.janelas["lanc_estoque"]; j.update()
        self.assertEqual(j.filtro, "sem")
        app.cartoes["estoque_ponto"].clique()
        self.assertIs(app.janelas["lanc_estoque"], j)                       # a mesma janela, só troca o filtro
        self.assertEqual(j.filtro, "ponto")
        j.destroy()

    def test_lancamento_novo_pela_janela_mostra_tipos_e_dica(self):
        from src.ui.lancamentos_ui import JanelaEstoque
        j = JanelaEstoque(self.root, self.ctx); j.update()
        j.tipos["pedido"].escolher("pedido"); j.update()           # o que o clique no cartão chama
        self.assertEqual(j.v_tipo.get(), "pedido")
        self.assertIn("NÃO mexe no estoque", j.lbl_dica.cget("text"))
        j.v_forn.set(""); j.destroy()


class TesteImportarProdutosUI(BaseUI):
    def _arquivo(self, texto: str) -> str:
        pasta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, pasta, True)
        caminho = Path(pasta) / "produtos.csv"
        caminho.write_bytes(texto.encode("utf-8-sig"))
        return str(caminho)

    def test_botao_importar_aparece_em_tela_pequena(self):
        """Em notebook de 768 px a janela de 700 px saía da tela e o botão Importar (embaixo) sumia."""
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        with mock.patch.object(tk.Misc, "winfo_screenheight", return_value=768):
            j = JanelaImportarProdutos(self.root, self.ctx); j.update()
        self.addCleanup(j.destroy)
        j.carregar(self._arquivo("Código;Produto;Preço\n10;CAMPARI;45,00\n"))
        j.update(); j.update_idletasks()
        self.assertLessEqual(j.winfo_y() + j.winfo_height(), 768 - 70)                       # janela inteira dentro da tela
        b = j.b_importar
        self.assertLessEqual(b.winfo_rooty() + b.winfo_height(), j.winfo_rooty() + j.winfo_height())
        self.assertLess(b.winfo_rooty() - j.winfo_rooty(), 400)                              # no alto da janela, não no rodapé
        self.assertEqual(b.cget("text"), "Importar 1 produto(s)")

    def test_previa_confere_e_importa_com_confirmacao(self):
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        recarregou = []
        j = JanelaImportarProdutos(self.root, self.ctx, lambda: recarregou.append(1)); j.update()
        self.assertEqual(str(j.b_importar.cget("state")), "disabled")
        j.carregar(self._arquivo("Código;Produto;Preço;Comissão\n10;CAMPARI;45,00;15,00\n50;COMISSAO;1,00;\n;SEM CODIGO;5,00;\n1;SKOL;9,00;\n"))
        j.update()
        acoes = [j.grade.valores(i)[1] for i in j.grade.tree.get_children()]
        self.assertEqual(acoes, ["Criar", "Recusado", "Criar", "Atualizar"])       # 50 é da comissão; SKOL (código 1) já existe
        self.assertIn("2 para criar, 1 para atualizar, 1 recusados", j.lbl_resumo.cget("text"))
        self.assertIn("reservado", j.grade.valores(j.grade.tree.get_children()[1])[8])
        self.assertEqual(j.b_importar.cget("text"), "Importar 3 produto(s)")
        with mock.patch.object(tema, "confirmar", return_value=False):
            j.importar()
        self.assertIsNone(self.banco.um("SELECT 1 FROM produtos WHERE nome = 'CAMPARI'"))        # voltou: nada gravado
        with mock.patch.object(tema, "confirmar", return_value=True), mock.patch.object(tema, "mensagem") as msg:
            j.importar()
        self.assertIn("2 produto(s) criado(s), 1 atualizado(s)", msg.call_args.args[1])
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE nome = 'CAMPARI'"), 4500)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE nome = 'SKOL'"), 900)
        self.assertEqual(recarregou, [1])
        self.assertEqual(j.grade.total(), 0)
        j.destroy()

    def test_opcoes_mudam_a_previa(self):
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        j = JanelaImportarProdutos(self.root, self.ctx); j.update()
        j.carregar(self._arquivo("Produto;Preço\nA;1\nB;1\n"))
        j.v_codigo.set("sequencia"); j.v_inicio.set("48"); j.analisar()
        self.assertEqual([j.grade.valores(i)[2] for i in j.grade.tree.get_children()], ["48", "49"])
        j.v_atualizar.set(False); j.v_codigo.set("planilha"); j.analisar()
        j.destroy()

    def test_planilha_ruim_mostra_o_motivo_e_nao_trava(self):
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        j = JanelaImportarProdutos(self.root, self.ctx); j.update()
        with mock.patch.object(tema, "erro") as erro:
            j.carregar(self._arquivo("Preço;Qtd\n1;2\n"))
        self.assertIn("coluna do nome", erro.call_args.args[1])
        self.assertEqual(j.grade.total(), 0)
        j.destroy()

    def test_baixar_modelo_e_exportar_gravam_o_arquivo(self):
        from src.ui import importar_produtos_ui
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        j = JanelaImportarProdutos(self.root, self.ctx); j.update()
        pasta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, pasta, True)
        modelo, atuais = str(Path(pasta) / "modelo.csv"), str(Path(pasta) / "atuais.csv")
        with mock.patch.object(importar_produtos_ui.filedialog, "asksaveasfilename", side_effect=[modelo, atuais]), mock.patch.object(tema, "mensagem"):
            j.salvar_modelo()
            j.exportar()
        self.assertIn("Produto;Preço", Path(modelo).read_text(encoding="utf-8-sig"))
        self.assertIn("SKOL", Path(atuais).read_text(encoding="utf-8-sig"))
        j.destroy()

    def test_botao_importar_planilha_no_cadastro_de_produtos(self):
        from src.ui.cadastros_tk import JanelaCadastro
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        c = JanelaCadastro(self.root, self.ctx, "produtos"); c.update()
        c._importar_planilha(); c.update()
        self.assertTrue(any(isinstance(w, JanelaImportarProdutos) for w in c.winfo_children()))
        c.destroy()

    def _dialogo_nfe(self):
        from src.ui.importar_produtos_ui import JanelaImportarNFe, JanelaImportarProdutos
        arquivo = self._arquivo("""<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe321">
          <ide><mod>55</mod><nNF>321</nNF><dhEmi>2026-10-03T10:00:00-03:00</dhEmi></ide>
          <emit><CNPJ>98765432000199</CNPJ><xNome>Fornecedor Tk</xNome></emit>
          <det nItem="1"><prod><cProd>XX</cProd><cEAN>SEM GTIN</cEAN><xProd>REFRIGERANTE NOVO</xProd>
          <uCom>UN</uCom><qCom>1</qCom><vUnCom>2.50</vUnCom><vProd>2.50</vProd></prod></det>
        </infNFe></NFe></nfeProc>""")
        tela = JanelaImportarProdutos(self.root, self.ctx)
        self.addCleanup(tela.destroy)
        previa = tela.imp_nfe.analisar(arquivo)
        dialogo = JanelaImportarNFe(tela, previa)
        return tela, dialogo

    def test_importar_nfe_cria_produto_com_preco_manual(self):
        tela, dialogo = self._dialogo_nfe()
        dialogo.preco_novo.set("8,00")
        with mock.patch.object(tema, "confirmar", return_value=True), \
             mock.patch.object(tema, "mensagem"):
            dialogo.confirmar()
        produto = self.banco.um("SELECT * FROM produtos WHERE nome = 'REFRIGERANTE NOVO'")
        self.assertEqual((produto["preco_cent"], produto["ult_preco_cent"]), (800, 250))

    def test_importar_nfe_cancelada_nao_grava(self):
        tela, dialogo = self._dialogo_nfe()
        dialogo.preco_novo.set("8,00")
        with mock.patch.object(tema, "confirmar", return_value=False), \
             mock.patch.object(tela.imp_nfe, "importar") as importar:
            dialogo.confirmar()
        importar.assert_not_called()
        self.assertTrue(dialogo.winfo_exists())

    def test_importar_nfe_preco_invalido_nao_grava(self):
        tela, dialogo = self._dialogo_nfe()
        dialogo.preco_novo.set("inválido")
        with mock.patch.object(tema, "confirmar", return_value=True), \
             mock.patch.object(tema, "erro") as erro, \
             mock.patch.object(tela.imp_nfe, "importar") as importar:
            dialogo.confirmar()
        importar.assert_not_called()
        self.assertIn("Preço de venda inválido", erro.call_args.args[1])

    def test_importar_nfe_revalida_permissao_antes_de_gravar(self):
        tela, dialogo = self._dialogo_nfe()
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?", (self.ctx.operador_id,))
        self.banco.executar("UPDATE acessos SET nivel = 4 WHERE modulo = 'cad_produtos'")
        with mock.patch.object(tema, "erro") as erro, \
             mock.patch.object(tema, "confirmar") as confirmar, \
             mock.patch.object(tela.imp_nfe, "importar") as importar:
            dialogo.confirmar()
        confirmar.assert_not_called()
        importar.assert_not_called()
        self.assertIn("nível de acesso", erro.call_args.args[1])

    def test_escolher_nfe_valida_acesso_e_abre_previa(self):
        from src.ui import importar_produtos_ui
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        tela = JanelaImportarProdutos(self.root, self.ctx)
        self.addCleanup(tela.destroy)
        with mock.patch.object(importar_produtos_ui.filedialog, "askopenfilename", return_value="nota.xml"), \
             mock.patch.object(tela.imp_nfe, "analisar") as analisar, \
             mock.patch.object(importar_produtos_ui, "JanelaImportarNFe") as janela:
            tela.escolher_nfe()
        analisar.assert_called_once_with("nota.xml")
        janela.assert_called_once_with(tela, analisar.return_value)

    def test_escolher_nfe_operador_inativo_nao_analisa(self):
        from src.ui import importar_produtos_ui
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        tela = JanelaImportarProdutos(self.root, self.ctx)
        self.addCleanup(tela.destroy)
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.ctx.operador_id,))
        with mock.patch.object(importar_produtos_ui.filedialog, "askopenfilename", return_value="nota.xml"), \
             mock.patch.object(tela.imp_nfe, "analisar") as analisar, \
             mock.patch.object(tema, "erro") as erro:
            tela.escolher_nfe()
        analisar.assert_not_called()
        self.assertIn("Operador inativo", erro.call_args.args[1])
