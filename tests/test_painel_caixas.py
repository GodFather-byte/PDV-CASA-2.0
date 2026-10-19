"""Painel do dono com mais de um caixa por loja: cada caixa se identifica e a nuvem guarda o retrato de cada um."""
from __future__ import annotations

import itertools
import re
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.controllers.caixa_controller import CaixaController
from src.controllers.cadastro_controller import CadastroController
from src.controllers.config_controller import ConfigController
from src.controllers.turno_controller import TurnoController
from src.database.conexao import BancoDados
from src.sync import painel_envio
from tests.base import BaseTeste
from tests.test_painel_dono import (TOKENS, BasePainel, BaseNuvem, TestClient, cabecalho, nuvem, painel)


class OutroCaixa:
    """Um segundo PDV da mesma loja: banco próprio (cada caixa tem o seu), terminal 2 e turno aberto."""

    def __init__(self, teste, terminal=2, descricao="Bar", computador="PC-BAR", fundo=5000):
        self.teste = teste
        self.banco = BancoDados(":memory:")
        teste.addCleanup(self.banco.fechar)
        self.banco.cfg_set("terminal", terminal)
        ConfigController(self.banco).salvar_maquina({"descricao": descricao, "nome_computador": computador}, terminal)
        for chave, valor in (("api_url", "http://testserver/v1/sincronizar"), ("api_token", TOKENS["ADEGA-1"]),
                             ("chave_loja", "ADEGA-1"), ("painel_dono", "S")):
            self.banco.cfg_set(chave, valor)
        self.adm = self.banco.valor("SELECT id FROM operadores WHERE nome = 'ADM'")
        self.turnos = TurnoController(self.banco)
        self.turno = self.turnos.abrir(self.adm, 1, fundo)
        self.caixa = CaixaController(self.banco, self.adm)
        self.produto = BaseTeste.novo_produto(SimpleNamespace(banco=self.banco), "HEINEKEN", 1200)

    def vender(self, quantidade=1):
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, self.produto, quantidade)
        total = self.caixa.obter(vid)["total_cent"]
        self.caixa.adicionar_pagamento(vid, self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'"), total)
        return self.caixa.fechar(vid)

    def devedor(self, nome="PEDRO", limite=50000, quantidade=1):
        cliente = CadastroController(self.banco).salvar(
            "clientes", {"numero_consulta": nome[:3], "nome": nome, "limite_cent": f"{limite / 100:.2f}"})
        vid = self.caixa.abrir_caderneta(cliente)
        self.caixa.adicionar_item(vid, self.produto, quantidade)
        return self.caixa.fechar(vid)


def retrato_manual(terminal_id, terminal=1, rotulo="Caixa 1", computador="PC", **extra):
    """O retrato como um PDV o monta, mas escrito à mão: para casos que não precisam de um banco inteiro."""
    retrato = {
        "terminal_id": terminal_id, "terminal": terminal, "terminal_rotulo": rotulo, "terminal_computador": computador,
        "loja_nome": "Adega", "dia_operacional": "2026-10-03", "momento": "2026-10-03 21:00:00", "caixa": None,
        "estoque": {"controlados": 0, "zerados": 0, "abaixo_minimo": []},
        "caderneta": {"a_receber_cent": 0, "clientes_devendo": 0}, "entregas_pendentes": 0, "vendas_pendentes_envio": 0,
    }
    retrato.update(extra)
    return retrato


def turno_manual(numero=1, operador="ADM", esperado=10000):
    return {"turno_numero": numero, "operador": operador, "aberto_em": "2026-10-03 18:00:00", "valor_inicial_cent": 10000,
            "recebido_cent": 0, "esperado_gaveta_cent": esperado, "sangrias_cent": 0, "suprimentos_cent": 0, "tc": 0,
            "tm_cent": 0, "cancelamentos": 0, "recebimentos": []}


# ------------------------------------------------------------ o PDV se identifica
class TesteIdentidadeDoCaixa(BasePainel):
    def test_o_id_nasce_uma_vez_e_fica_no_banco(self):
        primeiro = painel_envio.id_do_caixa(self.banco)
        self.assertRegex(primeiro, r"^[0-9a-f]{16}$")
        self.assertEqual(painel_envio.id_do_caixa(self.banco), primeiro)
        self.assertEqual(self.banco.cfg(painel_envio.CHAVE_CAIXA_ID), primeiro)

    def test_cada_banco_tem_o_seu_id(self):
        outro = BancoDados(":memory:")
        self.addCleanup(outro.fechar)
        self.assertNotEqual(painel_envio.id_do_caixa(self.banco), painel_envio.id_do_caixa(outro))

    def test_banco_copiado_para_outro_computador_ganha_id_proprio(self):
        original = painel_envio.id_do_caixa(self.banco)
        with mock.patch.object(painel_envio.socket, "gethostname", return_value="OUTRO-COMPUTADOR"):
            copia = painel_envio.id_do_caixa(self.banco)
            self.assertNotEqual(copia, original)
            self.assertEqual(painel_envio.id_do_caixa(self.banco), copia)         # e fica estável nele

    def test_retrato_e_vendas_carregam_a_identidade(self):
        self.venda_fechada((self.skol, 1))
        r = painel_envio.retrato(self.banco)
        self.assertEqual((r["terminal_id"], r["terminal"], r["terminal_rotulo"]),
                         (painel_envio.id_do_caixa(self.banco), 1, "Caixa 1"))
        self.assertTrue(r["terminal_computador"])
        self.assertEqual([v["terminal_id"] for v in painel_envio.coletar_vendas(self.banco)], [r["terminal_id"]])

    def test_rotulo_e_computador_vem_do_cadastro_da_maquina(self):
        ConfigController(self.banco).salvar_maquina({"descricao": "Entrada", "nome_computador": "PC-PORTARIA"})
        r = painel_envio.retrato(self.banco)
        self.assertEqual((r["terminal_rotulo"], r["terminal_computador"]), ("Entrada", "PC-PORTARIA"))
        ConfigController(self.banco).salvar_maquina({"descricao": "", "nome_computador": ""})
        r = painel_envio.retrato(self.banco)
        self.assertEqual(r["terminal_rotulo"], "Caixa 1")
        self.assertEqual(r["terminal_computador"], painel_envio.socket.gethostname())


# --------------------------------------------------- a nuvem guarda um retrato por caixa
@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteVariosCaixasNaNuvem(BaseNuvem):
    def caixas_na_nuvem(self, loja="ADEGA-1"):
        db = nuvem.SessionLocal()
        try:
            return sorted((c.terminal_id, c.terminal) for c in db.query(painel.PainelCaixa).filter_by(chave_loja=loja))
        finally:
            db.close()

    def enviar_manual(self, retrato, loja="ADEGA-1", vendas=None):
        r = self.http.post("/v1/painel/envio", json={"vendas": vendas or [], "retrato": retrato,
                                                     "enviado_em": "2026-10-03 21:00:00"}, headers=cabecalho(loja))
        self.assertEqual(r.status_code, 200, r.text)

    def resumo(self, loja="ADEGA-1", senha="senha-forte-1"):
        return self.http.get("/v1/painel/resumo", headers=self.entrar(loja, senha)).json()

    # ---- dois PDVs de verdade
    def test_dois_caixas_nao_se_sobrescrevem(self):
        self.venda_fechada((self.skol, 2))
        bar = OutroCaixa(self)
        bar.vender(3)
        self.subir()
        self.subir(bar.banco)
        self.subir()                                        # o primeiro fala de novo por último: não apaga o do bar
        r = self.resumo()
        self.assertEqual(len(self.caixas_na_nuvem()), 2)
        self.assertEqual([(c["terminal"], c["rotulo"], c["computador"]) for c in r["caixas"]][1], (2, "Bar", "PC-BAR"))
        balcao, bar_ = r["caixas"]
        self.assertEqual((balcao["caixa"]["esperado_gaveta_cent"], bar_["caixa"]["esperado_gaveta_cent"]),
                         (10000 + 1600, 5000 + 3600))      # cada gaveta com o seu dinheiro
        self.assertEqual((balcao["caixa"]["turno_numero"], bar_["caixa"]["turno_numero"]), (1, 1))
        self.assertNotEqual(balcao["id"], bar_["id"])
        self.assertEqual(r["vendas"]["quantidade"], 2)                              # as vendas dos dois somam
        self.assertEqual(r["vendas"]["faturamento_cent"], 1600 + 3600)

    def test_resumo_antigo_continua_valendo_com_varios_caixas(self):
        """O app que ainda não conhece `caixas` lê os campos de sempre: turno, estoque, caderneta e entregas somados."""
        cli = self.cliente("MARIA", limite=50000)
        vid = self.caixa.abrir_caderneta(cli)
        self.caixa.adicionar_item(vid, self.agua, 2)
        self.caixa.fechar(vid)                                      # R$ 7,00 na caderneta do balcão
        bar = OutroCaixa(self)
        bar.devedor("PEDRO", quantidade=1)                          # R$ 12,00 na do bar
        self.subir()
        self.subir(bar.banco)
        r = self.resumo()
        self.assertEqual(r["caderneta"], {"a_receber_cent": 700 + 1200, "clientes_devendo": 2})
        self.assertEqual(r["caixa"]["turno_numero"], 1)
        self.assertEqual(r["caixa"]["esperado_gaveta_cent"], 10000)                 # o primeiro caixa com turno aberto
        self.assertEqual(r["estoque"]["controlados"], 1)                            # o balcão controla estoque (SKOL)
        self.assertEqual((r["caixas"][0]["caderneta"]["a_receber_cent"], r["caixas"][1]["caderneta"]["a_receber_cent"]),
                         (700, 1200))
        self.assertLessEqual(r["atraso_min"], 1)

    def test_vendas_trazem_de_qual_caixa_saiu_cada_uma(self):
        self.venda_fechada((self.skol, 1))
        bar = OutroCaixa(self)
        bar.vender(1)
        self.subir()
        self.subir(bar.banco)
        sessao = self.entrar()
        ids = {c["id"] for c in self.http.get("/v1/painel/resumo", headers=sessao).json()["caixas"]}
        vendas = self.http.get("/v1/painel/vendas", headers=sessao).json()["vendas"]
        self.assertEqual({v["terminal_id"] for v in vendas}, ids)
        self.assertEqual(len(vendas), 2)

    # ---- casos pelo retrato escrito à mão
    def test_cada_loja_ve_so_os_seus_caixas(self):
        self.enviar_manual(retrato_manual("a1"), "ADEGA-1")
        self.enviar_manual(retrato_manual("b1", rotulo="Outra"), "ADEGA-2")
        self.assertEqual(self.caixas_na_nuvem("ADEGA-1"), [("a1", 1)])
        r = self.resumo("ADEGA-2", "senha-da-outra-loja")
        self.assertEqual([c["id"] for c in r["caixas"]], ["b1"])

    def test_pdv_sem_identificacao_entra_como_um_caixa_so(self):
        antigo = retrato_manual("x", caixa=turno_manual())
        for chave in ("terminal_id", "terminal", "terminal_rotulo", "terminal_computador"):
            antigo.pop(chave)
        self.enviar_manual(antigo)
        self.enviar_manual(antigo)
        self.assertEqual(self.caixas_na_nuvem(), [(painel.CAIXA_LEGADO, 1)])
        r = self.resumo()
        self.assertEqual([(c["id"], c["rotulo"]) for c in r["caixas"]], [("unico", "Caixa 1")])
        self.assertEqual(r["caixa"]["turno_numero"], 1)

    def test_id_malformado_vira_o_caixa_legado(self):
        for ruim in ("com espaço", "x" * 41, "../etc", "", None, {"a": 1}, ["b"]):
            self.enviar_manual(retrato_manual(ruim))
        self.assertEqual(self.caixas_na_nuvem(), [("unico", 1)])

    def test_pdv_atualizado_substitui_o_retrato_que_o_antigo_deixou(self):
        antigo = retrato_manual("x")
        antigo.pop("terminal_id")
        self.enviar_manual(antigo)
        db = nuvem.SessionLocal()
        db.query(painel.PainelCaixa).update({"recebido_em": (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")})
        db.commit()
        db.close()
        self.enviar_manual(retrato_manual("novo"))
        self.assertEqual(self.caixas_na_nuvem(), [("novo", 1)])                     # o "unico" parado não vira caixa fantasma

    def test_pdv_antigo_que_ainda_fala_continua_sendo_um_caixa(self):
        antigo = retrato_manual("x")
        antigo.pop("terminal_id")
        self.enviar_manual(antigo)
        self.enviar_manual(retrato_manual("novo", terminal=2))
        self.assertEqual(self.caixas_na_nuvem(), [("novo", 2), ("unico", 1)])       # os dois falando: nenhum some

    def test_passando_do_limite_sai_o_caixa_mais_parado(self):
        contador = itertools.count()
        relogio = lambda: f"2026-10-03 21:{next(contador):02d}:00"
        with mock.patch.object(painel, "MAX_CAIXAS_POR_LOJA", 3), mock.patch.object(painel, "_agora", relogio):
            for n in range(1, 5):
                self.enviar_manual(retrato_manual(f"c{n}", terminal=n))
        self.assertEqual([c[0] for c in self.caixas_na_nuvem()], ["c2", "c3", "c4"])    # o c1 falou há mais tempo

    def test_estoque_de_cada_caixa_fica_no_seu_e_o_resumo_usa_o_que_controla(self):
        sem_controle = retrato_manual("a", terminal=1)
        com_controle = retrato_manual("b", terminal=2, estoque={"controlados": 5, "zerados": 1, "abaixo_minimo": [
            {"codigo": "1", "nome": "GELO", "qt_atual": 0, "estoque_minimo": 5, "unidade": "UN"}]})
        self.enviar_manual(sem_controle)
        self.enviar_manual(com_controle)
        r = self.resumo()
        self.assertEqual(r["estoque"]["controlados"], 5)                             # o primeiro que controla estoque
        self.assertEqual([c["estoque"]["controlados"] for c in r["caixas"]], [0, 5])

    def test_ordem_dos_caixas_segue_o_terminal_e_depois_o_nome(self):
        self.enviar_manual(retrato_manual("z", terminal=3, rotulo="Terceiro"))
        self.enviar_manual(retrato_manual("m", terminal=1, rotulo="Bar"))
        self.enviar_manual(retrato_manual("k", terminal=1, rotulo="Adega"))
        self.assertEqual([c["rotulo"] for c in self.resumo()["caixas"]], ["Adega", "Bar", "Terceiro"])

    def test_caixas_sem_retrato_algum(self):
        r = self.resumo("ADEGA-2", "senha-da-outra-loja")
        self.assertEqual((r["caixas"], r["caixa"], r["estoque"]["controlados"], r["entregas_pendentes"]), ([], None, 0, 0))
        self.assertEqual(r["caderneta"], {"a_receber_cent": 0, "clientes_devendo": 0})

    def test_retrato_corrompido_nao_derruba_o_resumo(self):
        self.enviar_manual(retrato_manual("a"))
        db = nuvem.SessionLocal()
        db.query(painel.PainelCaixa).update({"dados": "isto não é json"})
        db.commit()
        db.close()
        r = self.resumo()
        self.assertEqual([(c["id"], c["caixa"]) for c in r["caixas"]], [("a", None)])

    def test_tabela_antiga_de_retratos_e_descartada(self):
        from sqlalchemy import inspect, text
        with painel.engine.begin() as con:
            con.execute(text("CREATE TABLE IF NOT EXISTS painel_retratos (id INTEGER PRIMARY KEY, chave_loja VARCHAR)"))
        self.assertTrue(inspect(painel.engine).has_table("painel_retratos"))
        painel._descartar_retratos_antigos()
        self.assertFalse(inspect(painel.engine).has_table("painel_retratos"))
        painel._descartar_retratos_antigos()                                          # sem a tabela, não faz nada


# --------------------------------------------------------------- o app do celular, sem navegador
class TesteAppWebConsistente(unittest.TestCase):
    PASTA = Path(__file__).resolve().parent.parent / "backend" / "painel_web"

    def test_todo_id_que_o_app_procura_existe_no_html(self):
        """Trocar o cartão do caixa por uma lista de cartões não pode deixar um `$("...")` apontando para o vazio: o app
        inteiro pararia no primeiro `null.hidden`."""
        js = (self.PASTA / "app.js").read_text(encoding="utf-8")
        html = (self.PASTA / "index.html").read_text(encoding="utf-8")
        usados = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', js))
        existentes = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', html))
        self.assertGreater(len(usados), 40)
        self.assertEqual(sorted(usados - existentes), [])


if __name__ == "__main__":
    unittest.main()
