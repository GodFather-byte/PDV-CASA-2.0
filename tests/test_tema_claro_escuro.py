"""Modo claro e modo escuro: as paletas, a troca no lugar, a opção em Configurações e as telas abrindo nos dois modos."""
from __future__ import annotations

import re
import unittest
from unittest import mock

from src.core.erros import ErroValidacao
from src.ui import caixa_tema, menu_widgets, paleta, painel_mesas, tema
from tests.test_ui import BaseUI

MODOS = tuple(paleta.MODOS)


def luminancia(cor: str) -> float:
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(int(cor[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestePaletas(unittest.TestCase):
    def tearDown(self):
        paleta.aplicar(paleta.PADRAO)

    def test_os_dois_modos_definem_exatamente_as_mesmas_cores(self):
        for nome, tabela in (("COR", paleta.COR), ("PAL", paleta.PAL), ("CX", paleta.CX)):
            self.assertEqual(set(tabela["claro"]), set(tabela["escuro"]), nome)
        self.assertEqual(set(paleta.ESTADOS["claro"]), set(paleta.ESTADOS["escuro"]))
        for estado in paleta.ESTADOS["claro"]:
            self.assertEqual(set(paleta.ESTADOS["claro"][estado]), set(paleta.ESTADOS["escuro"][estado]), estado)

    def test_toda_cor_e_um_hexadecimal_valido(self):
        valida = re.compile(r"^#[0-9a-f]{6}$")
        for modo in MODOS:
            cores = [*paleta.COR[modo].values(), *paleta.PAL[modo].values(), *paleta.CX[modo].values(),
                     *(c for e in paleta.ESTADOS[modo].values() for c in e.values())]
            for cor in cores:
                self.assertRegex(cor, valida, f"{modo}: {cor}")

    def test_texto_e_destaques_se_leem_no_fundo_e_no_cartao_nos_dois_modos(self):
        for modo in MODOS:
            pal = paleta.PAL[modo]
            for fundo in ("fundo", "cartao"):
                for cor in ("texto", "suave", "mudo", "azul", "verde", "ambar", "vermelho", "violeta", "turquesa", "ardosia"):
                    self.assertGreaterEqual(contraste(pal[cor], pal[fundo]), 4.5, f"{modo}: {cor} sobre {fundo}")

    def test_telas_de_cadastro_texto_rotulos_e_botoes_se_leem(self):
        for modo in MODOS:
            c = paleta.COR[modo]
            for fundo in ("fundo", "painel", "campo"):
                self.assertGreaterEqual(contraste(c["texto"], c[fundo]), 7, f"{modo}: texto sobre {fundo}")
                for cor in ("suave", "rotulo", "ok", "perigo", "total", "troco"):
                    self.assertGreaterEqual(contraste(c[cor], c[fundo]), 4.5, f"{modo}: {cor} sobre {fundo}")
            for botao in ("marinho2", "marinho", "ok_fundo", "perigo_fundo", "btn_hover", "ok_hover", "perigo_hover"):
                self.assertGreaterEqual(contraste(c["sobre"], c[botao]), 4.5, f"{modo}: texto do botão {botao}")
            self.assertGreaterEqual(contraste(c["selecao_texto"], c["selecao"]), 4.5, f"{modo}: linha selecionada")
            for linha in ("ok_linha", "ponto_linha", "sem_linha"):
                self.assertGreaterEqual(contraste(c["texto"], c[linha]), 7, f"{modo}: texto na {linha}")

    def test_caixa_e_cartoes_das_comandas_se_leem(self):
        for modo in MODOS:
            cx = {**paleta.CX[modo], **{k: paleta.PAL[modo][k] for k in paleta.CX_DO_PAL}}
            for fundo in ("fundo", "cartao", "campo"):
                self.assertGreaterEqual(contraste(cx["texto"], cx[fundo]), 7, f"{modo}: texto sobre {fundo}")
                self.assertGreaterEqual(contraste(cx["suave"], cx[fundo]), 4.5, f"{modo}: suave sobre {fundo}")
            self.assertGreaterEqual(contraste(cx["sobre"], cx["verde"]), 4.5, f"{modo}: texto do botão Pagar")
            self.assertGreaterEqual(contraste(cx["sobre_marca"], cx["azul"]), 4.5, f"{modo}: letra da marca")
            self.assertGreaterEqual(contraste(cx["comissao_texto"], cx["fundo"]), 4.5, f"{modo}: comissão")
            self.assertGreaterEqual(contraste(cx["selecao_texto"], cx["selecao"]), 4.5, f"{modo}: seleção")
            for estado, e in paleta.ESTADOS[modo].items():
                self.assertGreaterEqual(contraste(e["texto"], e["fundo"]), 4.5, f"{modo}: cartão {estado}")
                self.assertGreaterEqual(contraste(cx["texto"], e["fundo"]), 7, f"{modo}: número no cartão {estado}")

    def test_aplicar_troca_o_conteudo_no_lugar_e_devolve_o_modo(self):
        ids = {id(d) for d in (tema.COR, menu_widgets.PAL, caixa_tema.CX, painel_mesas.ESTADOS)}
        self.assertEqual(paleta.aplicar("claro"), "claro")
        self.assertEqual(paleta.modo(), "claro")
        self.assertEqual(tema.COR["fundo"], paleta.COR["claro"]["fundo"])
        self.assertEqual(menu_widgets.PAL["fundo"], paleta.PAL["claro"]["fundo"])
        self.assertEqual(painel_mesas.ESTADOS["balcao"], paleta.ESTADOS["claro"]["balcao"])
        paleta.aplicar("escuro")
        self.assertEqual(tema.COR["fundo"], paleta.COR["escuro"]["fundo"])
        self.assertEqual({id(d) for d in (tema.COR, menu_widgets.PAL, caixa_tema.CX, painel_mesas.ESTADOS)}, ids)   # mesmos objetos

    def test_o_caixa_usa_os_mesmos_destaques_do_menu(self):
        for modo in MODOS:
            paleta.aplicar(modo)
            for chave in paleta.CX_DO_PAL:
                self.assertEqual(caixa_tema.CX[chave], menu_widgets.PAL[chave], f"{modo}: {chave}")

    def test_modo_desconhecido_vira_o_padrao(self):
        for lixo in (None, "", "roxo", "CLARO ", "Escuro"):
            self.assertIn(paleta.validar(lixo), MODOS)
        self.assertEqual(paleta.validar("roxo"), paleta.PADRAO)
        self.assertEqual(paleta.validar(" CLARO "), "claro")                 # maiúsculas e espaços não atrapalham
        self.assertEqual(paleta.aplicar("roxo"), paleta.PADRAO)

    def test_padrao_e_o_escuro(self):
        self.assertEqual(paleta.PADRAO, "escuro")


class TesteConfiguracaoDoModo(BaseUI):
    def test_valor_padrao_e_a_primeira_opcao_das_configuracoes(self):
        from src.controllers.config_controller import CAMPOS_CONFIG
        self.assertEqual(self.banco.cfg("tema_visual"), "escuro")
        primeiro = CAMPOS_CONFIG[0]
        self.assertEqual((primeiro[0], primeiro[2], primeiro[3]), ("tema_visual", "escolha", "Aparência"))
        self.assertEqual([o[0] for o in primeiro[4]], ["escuro", "claro"])

    def test_grava_as_duas_opcoes_e_recusa_outras(self):
        self.ctx.config.salvar_config({"tema_visual": "claro"})
        self.assertEqual(self.banco.cfg("tema_visual"), "claro")
        self.ctx.config.salvar_config({"tema_visual": "escuro"})
        self.assertEqual(self.banco.cfg("tema_visual"), "escuro")
        with self.assertRaises(ErroValidacao):
            self.ctx.config.salvar_config({"tema_visual": "roxo"})
        self.assertEqual(self.banco.cfg("tema_visual"), "escuro")

    def test_aplicar_da_configuracao_le_o_banco(self):
        self.banco.cfg_set("tema_visual", "claro")
        self.assertEqual(paleta.aplicar_da_configuracao(self.banco), "claro")
        self.banco.cfg_set("tema_visual", "defeito")                          # valor estranho no banco: cai no padrão
        self.assertEqual(paleta.aplicar_da_configuracao(self.banco), "escuro")

    def abrir_configuracoes(self):
        from src.ui import config_ui
        j = config_ui.abrir(self.root, self.ctx, "configuracoes")
        self.addCleanup(lambda: j.winfo_exists() and j.destroy())
        j.update()
        return j

    def test_escolher_claro_na_janela_e_gravar_aplica_na_hora(self):
        j = self.abrir_configuracoes()
        self.assertEqual(j.valor("tema_visual"), "escuro")                    # a janela mostra o modo atual
        j.definir("tema_visual", "claro")
        with mock.patch.object(tema, "mensagem") as msg:
            j.gravar()
        self.assertEqual(self.banco.cfg("tema_visual"), "claro")
        self.assertEqual(paleta.modo(), "claro")
        self.assertEqual(tema.COR["fundo"], paleta.COR["claro"]["fundo"])
        self.assertEqual(len(msg.call_args_list), 2)                          # "Configurações gravadas" e o aviso do visual
        self.assertIn("Modo claro", msg.call_args_list[1].args[1])

    def test_a_janela_principal_refaz_o_visual_quando_existe(self):
        j = self.abrir_configuracoes()
        chamadas = []
        self.ctx.ao_mudar_tema = chamadas.append
        j.definir("tema_visual", "claro")
        with mock.patch.object(tema, "mensagem"):
            j.gravar()
        self.assertEqual(chamadas, ["claro"])                                 # quem refaz é a janela principal

    def test_gravar_sem_mudar_o_modo_nao_refaz_nada(self):
        j = self.abrir_configuracoes()
        chamadas = []
        self.ctx.ao_mudar_tema = chamadas.append
        with mock.patch.object(tema, "mensagem") as msg:
            j.gravar()
        self.assertEqual(chamadas, [])
        self.assertEqual(len(msg.call_args_list), 1)                          # só "Configurações gravadas"
        self.assertEqual(paleta.modo(), "escuro")


class TesteMenuTrocaDeModo(BaseUI):
    def menu(self):
        from src.ui.app import App
        banco_tema = self.banco.cfg("tema_visual")
        app = App(self.banco)
        self.addCleanup(app.root.destroy)
        self.assertEqual(banco_tema, "escuro")
        app.ctx.operador = app.ctx.acesso.autenticar("adm", "adm")
        app.mostrar_menu(); app.root.update()
        return app

    def test_o_programa_abre_no_modo_gravado(self):
        from src.ui.app import App
        self.banco.cfg_set("tema_visual", "claro")
        app = App(self.banco)
        self.addCleanup(app.root.destroy)
        self.assertEqual(paleta.modo(), "claro")
        self.assertEqual(menu_widgets.PAL["fundo"], paleta.PAL["claro"]["fundo"])
        self.assertIsNotNone(app.ctx.ao_mudar_tema)

    def test_trocar_o_modo_refaz_o_menu_e_fecha_as_telas_abertas(self):
        app = self.menu()
        self.assertEqual(str(app.menu.cget("bg")), paleta.PAL["escuro"]["fundo"])
        app.abrir_cadastro("produtos"); app.root.update()
        app.abrir_config("loja"); app.root.update()
        janelas = list(app.janelas.values())
        self.assertEqual(len(janelas), 2)
        menu_antigo = app.menu
        app.aplicar_visual("claro"); app.root.update()
        self.assertEqual(paleta.modo(), "claro")
        self.assertEqual(app.janelas, {})
        self.assertFalse(any(j.winfo_exists() for j in janelas))
        self.assertIsNot(app.menu, menu_antigo)
        self.assertEqual(str(app.menu.cget("bg")), paleta.PAL["claro"]["fundo"])
        self.assertEqual(self.banco.valor("SELECT detalhe FROM log_eventos WHERE evento = 'tema_visual'"), "claro")

    def test_ida_e_volta_deixa_o_menu_como_estava(self):
        app = self.menu()
        app.aplicar_visual("claro"); app.root.update()
        app.aplicar_visual("escuro"); app.root.update()
        self.assertEqual(str(app.menu.cget("bg")), paleta.PAL["escuro"]["fundo"])
        self.assertEqual(set(app.botoes), {"Cadastros", "Caixa", "Lançamentos", "Relatórios", "Utilitários", "Configurações", "Saída"})

    def test_icones_do_menu_acompanham_o_modo(self):
        from src.ui.app import icones
        escuro = icones()["Cadastros"][1]
        paleta.aplicar("claro")
        self.assertNotEqual(icones()["Cadastros"][1], escuro)
        self.assertEqual(icones()["Cadastros"][1], paleta.PAL["claro"]["azul"])


class TesteTelasNosDoisModos(BaseUI):
    """Cada tela abre, sem erro, nos dois modos e usa as cores do modo (e não as do outro)."""

    def modos(self):
        for modo in MODOS:
            paleta.aplicar(modo)
            tema.aplicar_tema(self.root)
            yield modo

    def test_caixa_usa_as_cores_do_modo(self):
        from src.ui.caixa_ui import JanelaCaixa
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        for modo in self.modos():
            cx = JanelaCaixa(self.root, self.ctx)
            self.addCleanup(cx.destroy)
            cx.update()
            self.assertEqual(str(cx.cget("bg")), paleta.CX[modo]["fundo"], modo)
            self.assertEqual(str(cx.lbl_total.cget("bg")), paleta.CX[modo]["cartao"], modo)
            self.assertEqual(str(cx.lbl_total.cget("fg")), paleta.PAL[modo]["verde"], modo)
            self.assertEqual(str(cx.painel_mesas.canvas.cget("bg")), paleta.CX[modo]["fundo"], modo)
            cx.destroy()

    def test_cartoes_das_comandas_usam_a_paleta_do_modo(self):
        from src.ui.caixa_ui import JanelaCaixa
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        vid, _ = self.ctx.caixa.abrir_mesa(12, comanda=True)
        self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        for modo in self.modos():
            cx = JanelaCaixa(self.root, self.ctx)
            self.addCleanup(cx.destroy)
            cx.carregar_mesas(); cx.update()
            c = cx.painel_mesas.canvas
            fundo = c.find_withtag("t:12&&fundo")[0]
            self.assertEqual(str(c.itemcget(fundo, "fill")), paleta.ESTADOS[modo]["consumindo"]["fundo"], modo)
            cx.destroy()

    def test_login_usa_as_cores_do_modo(self):
        from src.ui.login import JanelaLogin
        for modo in self.modos():
            j = JanelaLogin(self.root, self.ctx, "Casa")
            self.addCleanup(j.destroy)
            j.update()
            self.assertEqual(str(j.cget("bg")), paleta.PAL[modo]["fundo"], modo)
            j.destroy()

    def test_telas_de_cadastro_e_de_configuracao_usam_as_cores_do_modo(self):
        from src.ui import config_ui
        from src.ui.cadastros_tk import JanelaCadastro
        for modo in self.modos():
            for criar in (lambda: JanelaCadastro(self.root, self.ctx, "produtos"),
                          lambda: config_ui.abrir(self.root, self.ctx, "configuracoes"),
                          lambda: config_ui.abrir(self.root, self.ctx, "acessos")):
                j = criar()
                self.addCleanup(j.destroy)
                j.update()
                self.assertEqual(str(j.cget("bg")), paleta.COR[modo]["fundo"], modo)
                j.destroy()

    def test_estoque_relatorio_e_visualizador_abrem(self):
        from src.ui.estoque_ui import PainelEstoque
        from src.ui.visualizador import Visualizador
        for modo in self.modos():
            e = PainelEstoque(self.root, self.ctx, "todos")
            self.addCleanup(e.destroy)
            e.update()
            self.assertEqual(str(e.cget("bg")), paleta.PAL[modo]["fundo"], modo)
            e.destroy()
            v = Visualizador(self.root, self.ctx, "Teste", "linha\nlinha", "x", modal=False)
            self.addCleanup(v.destroy)
            v.update()
            self.assertEqual(str(v.caixa.cget("bg")), paleta.COR[modo]["papel"], modo)
            self.assertEqual(str(v.caixa.cget("fg")), paleta.COR[modo]["texto"], modo)
            v.destroy()

    def test_estilos_ttk_seguem_o_modo(self):
        from tkinter import ttk
        estilo = ttk.Style(self.root)
        for modo in self.modos():
            self.assertEqual(estilo.lookup("TLabel", "background"), paleta.COR[modo]["fundo"], modo)
            self.assertEqual(estilo.lookup("TLabel", "foreground"), paleta.COR[modo]["texto"], modo)
            self.assertEqual(estilo.lookup("Treeview", "fieldbackground"), paleta.COR[modo]["campo"], modo)
            self.assertEqual(estilo.lookup("TEntry", "fieldbackground"), paleta.COR[modo]["campo"], modo)

    def test_nenhuma_tela_do_caixa_cai_em_cor_do_outro_modo(self):
        """Janela de pagamento (estilos do caixa) nos dois modos."""
        from src.ui.caixa_pagamento import JanelaPagamento
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        vid, _ = self.ctx.caixa.abrir_mesa(3, comanda=True)
        self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        for modo in self.modos():
            caixa_tema.aplicar(self.root)
            capturado = {}

            def olhar(j):
                j.update()
                capturado["bg"] = str(j.cget("bg"))
                j.destroy()
            with mock.patch.object(JanelaPagamento, "wait_window", lambda self_, *a: olhar(self_)):
                JanelaPagamento(self.root, self.ctx, vid)
            self.assertEqual(capturado["bg"], paleta.CX[modo]["fundo"], modo)


if __name__ == "__main__":
    unittest.main()
