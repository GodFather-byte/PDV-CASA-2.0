"""A janela do Tk para o dono trocar a senha do painel (Configurações > botão "Senha do painel do dono...")."""
from __future__ import annotations

import re
import threading
import unittest
from tkinter import ttk
from unittest import mock
from urllib.parse import urlparse

from src.ui import config_ui
from tests.test_painel_dono import TOKENS, TestClient, nuvem, painel, preparar_lojas
from tests.test_ui import BaseUI
from tests.ui_robo import botoes, clicar, entradas


def rotulos(janela) -> str:
    achados = []

    def varre(w):
        for f in w.winfo_children():
            if isinstance(f, ttk.Label):
                achados.append(str(f.cget("text")))
            varre(f)
    varre(janela)
    return " ".join(achados)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteSenhaDoPainelNaTela(BaseUI):
    TITULO = "Senha do painel do dono"

    def setUp(self):
        super().setUp()
        preparar_lojas()
        self.api = TestClient(nuvem.app)
        self.banco.cfg_set("api_url", "http://testserver/v1/sincronizar")
        self.banco.cfg_set("api_token", TOKENS["ADEGA-1"])
        self.chamadas, self.mensagens, self.senhas, self.confirmacoes = [], [], [], []
        rede = mock.patch("requests.post", side_effect=self._post)
        rede.start()
        self.addCleanup(rede.stop)
        self.robo.quando("Dialogo", self._responder, vezes=2000)

    def _post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append(url)
        return self.api.post(urlparse(url).path, json=json, headers=headers)

    def _responder(self, w):
        titulo, texto = w.title(), rotulos(w)
        if titulo == "Aguarde":
            return                                              # a janelinha de espera fecha sozinha quando a nuvem responde
        if titulo == self.TITULO and entradas(w):               # um pedido de senha
            valor = (self.confirmacoes if "de novo" in texto else self.senhas).pop(0)
            campo = entradas(w)[0]
            campo.delete(0, "end")
            campo.insert(0, valor)
            clicar(w, "OK")
            return
        self.mensagens.append((titulo, texto))                  # aviso ou erro: lê e fecha
        clicar(w, "OK")

    def abrir(self):
        j = config_ui.abrir(self.root, self.ctx, "configuracoes")
        j.update()
        return j

    def trocar(self):
        j = self.abrir()
        config_ui.trocar_senha_painel(j, self.ctx)
        j.update()
        self.sem_travar()

    def pode_entrar(self, senha, loja="ADEGA-1"):
        return self.api.post("/v1/painel/login", json={"loja": loja, "senha": senha}).status_code == 200

    def eventos(self):
        return self.banco.todos("SELECT operador_id, detalhe FROM log_eventos WHERE evento = 'painel_senha_trocada'")

    def test_botao_fica_na_barra_das_configuracoes(self):
        j = self.abrir()
        textos = [str(b.cget("text")) for b in botoes(j)]
        self.assertIn("Senha do painel do dono...", textos)
        self.assertIn("Perfil do estabelecimento...", textos)

    def test_senha_escolhida_com_confirmacao_vale_na_nuvem_e_fica_no_log(self):
        self.senhas, self.confirmacoes = ["senha-do-dono-1"], ["senha-do-dono-1"]
        self.trocar()
        self.assertTrue(self.pode_entrar("senha-do-dono-1"))
        self.assertEqual(len(self.chamadas), 1)
        self.assertEqual(self.mensagens[-1][0], self.TITULO)
        self.assertIn("Senha do painel trocada", self.mensagens[-1][1])
        self.assertIn("entrar de novo", self.mensagens[-1][1])
        self.assertNotIn("senha-do-dono-1", self.mensagens[-1][1])
        self.assertEqual([(e["operador_id"], e["detalhe"]) for e in self.eventos()],
                         [(self.ctx.operador_id, "senha escolhida pelo operador")])

    def test_em_branco_mostra_a_senha_gerada_uma_vez(self):
        self.senhas = [""]
        self.trocar()
        mostrada = re.search(r"[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}", self.mensagens[-1][1])
        self.assertIsNotNone(mostrada, self.mensagens)
        self.assertIn("não aparece de novo", self.mensagens[-1][1])
        self.assertTrue(self.pode_entrar(mostrada.group(0)))
        self.assertEqual([e["detalhe"] for e in self.eventos()], ["senha gerada pela nuvem"])
        self.assertEqual(self.confirmacoes, [])                  # em branco não pede confirmação

    def test_senha_curta_fica_na_janela_com_o_erro_e_aceita_a_corrigida(self):
        self.senhas, self.confirmacoes = ["curta", "senha-do-dono-2"], ["senha-do-dono-2"]
        self.trocar()
        self.assertTrue(self.pode_entrar("senha-do-dono-2"))
        self.assertEqual(len(self.chamadas), 1)                  # a curta nem foi para a nuvem

    def test_confirmacao_diferente_nao_troca_ate_digitar_igual(self):
        self.senhas, self.confirmacoes = ["senha-do-dono-3"], ["senha-diferente", "senha-do-dono-3"]
        self.trocar()
        self.assertTrue(self.pode_entrar("senha-do-dono-3"))
        self.assertEqual(self.confirmacoes, [])

    def test_cancelar_em_qualquer_pedido_nao_chama_a_nuvem(self):
        j = self.abrir()
        self.robo.regras.clear()
        self.robo.quando("Dialogo", lambda w: w.destroy(), vezes=1)                       # Esc no primeiro pedido
        config_ui.trocar_senha_painel(j, self.ctx)
        self.assertEqual((self.chamadas, self.eventos()), ([], []))
        self.robo.regras.clear()

        def so_a_primeira(w):
            if entradas(w) and "de novo" not in rotulos(w):
                entradas(w)[0].insert(0, "senha-do-dono-4")
                clicar(w, "OK")
            else:
                w.destroy()                                                                # cancela a confirmação
        self.robo.quando("Dialogo", so_a_primeira, vezes=10)
        config_ui.trocar_senha_painel(j, self.ctx)
        self.assertEqual((self.chamadas, self.eventos()), ([], []))
        self.sem_travar()

    def test_token_recusado_mostra_o_erro_e_a_senha_antiga_continua(self):
        self.banco.cfg_set("api_token", "token-que-nao-existe")
        self.senhas, self.confirmacoes = ["senha-do-dono-5"], ["senha-do-dono-5"]
        db = nuvem.SessionLocal()
        painel.definir_senha(db, "ADEGA-1", "senha-antiga-1")
        db.close()
        self.trocar()
        self.assertIn("não reconheceu o token", self.mensagens[-1][1])
        self.assertIn("NÃO foi trocada", self.mensagens[-1][1])
        self.assertTrue(self.pode_entrar("senha-antiga-1"))
        self.assertEqual(self.eventos(), [])

    def test_sem_nuvem_configurada_avisa_sem_pedir_senha(self):
        self.banco.cfg_set("api_token", "")
        self.senhas = ["nao-deve-ser-pedida"]
        self.trocar()
        self.assertIn("Preencha o endereço da nuvem e o token", self.mensagens[-1][1])
        self.assertEqual((self.senhas, self.chamadas), (["nao-deve-ser-pedida"], []))

    def test_grava_o_que_esta_na_tela_antes_de_usar_o_endereco_e_o_token(self):
        j = self.abrir()
        j.vars["api_token"].set(TOKENS["ADEGA-1"])
        self.banco.cfg_set("api_token", "")                       # no banco ainda não tem; na tela o operador acabou de digitar
        self.senhas, self.confirmacoes = ["senha-do-dono-6"], ["senha-do-dono-6"]
        config_ui.trocar_senha_painel(j, self.ctx)
        self.assertEqual(self.banco.cfg("api_token"), TOKENS["ADEGA-1"])
        self.assertTrue(self.pode_entrar("senha-do-dono-6"))
        self.sem_travar()

    def test_a_tela_nao_trava_enquanto_a_nuvem_demora(self):
        liberar = threading.Event()
        original = self._post

        def devagar(url, json=None, headers=None, timeout=None):
            liberar.wait(3)
            return original(url, json=json, headers=headers, timeout=timeout)
        batidas = []
        j = self.abrir()
        self.senhas, self.confirmacoes = ["senha-do-dono-7"], ["senha-do-dono-7"]

        def contar():
            batidas.append(1)                                     # o laço do Tk continua rodando durante a espera
            if len(batidas) == 8:
                liberar.set()
            j.after(50, contar)
        j.after(50, contar)
        with mock.patch("requests.post", side_effect=devagar):
            config_ui.trocar_senha_painel(j, self.ctx)
        self.assertGreaterEqual(len(batidas), 8)
        self.assertTrue(self.pode_entrar("senha-do-dono-7"))
        self.sem_travar()


if __name__ == "__main__":
    unittest.main()
