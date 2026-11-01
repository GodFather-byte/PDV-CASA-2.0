"""Alertas operacionais: regras só leitura, permissões por seção e respostas do Telegram (sem rede, sem a central)."""
from __future__ import annotations

from unittest import mock

from src.controllers.acesso_controller import AcessoController
from src.controllers.alertas_controller import TODAS, AlertasController
from src.controllers.cadastro_controller import CadastroController
from src.core.erros import ErroPermissao
from tests.test_caixa import BaseCaixa


def retrato(banco) -> dict:
    """Todas as linhas de todas as tabelas: a consulta de alertas não pode mudar nada."""
    tabelas = [r["name"] for r in banco.todos("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return {t: [tuple(r) for r in banco.todos(f"SELECT * FROM {t}")] for t in tabelas}


class BaseAlertas(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.ctl = AlertasController(self.banco)

    def titulos(self, secoes=TODAS) -> list[str]:
        return [a["titulo"] for a in self.ctl.alertas(secoes)]

    def operador(self, nivel="0", nome="BAR") -> int:
        return CadastroController(self.banco).salvar("operadores", {"nome": nome, "senha": "1234", "nivel": nivel})


class TesteRegras(BaseAlertas):
    def test_casa_em_dia_nao_tem_alerta(self):
        self.assertEqual(self.ctl.alertas(), [])
        self.assertEqual(self.ctl.contagem([]), {"critico": 0, "aviso": 0, "info": 0, "total": 0})

    def test_estoque_zerado_e_no_ponto_de_pedido(self):
        self.novo_produto("GIN", 9000, estoque=True, qt=0)
        self.novo_produto("VODKA", 5000, estoque=True, qt=2, estoque_minimo="5")
        self.novo_produto("RUM", 5000, estoque=True, qt=20, estoque_minimo="5")
        lista = self.ctl.alertas({"estoque"})
        self.assertEqual([(a["nivel"], a["titulo"]) for a in lista],
                         [("critico", "Sem estoque: GIN"), ("aviso", "Abaixo do mínimo: VODKA")])
        self.assertIn("mínimo 5", lista[1]["detalhe"])
        self.assertEqual(self.ctl.contagem(lista)["total"], 2)

    def test_mesa_parada_segue_o_tempo_configurado(self):
        self.vender((self.skol, 1), mesa=5)
        self.avancar(minutes=20)
        self.assertEqual(self.ctl.mesas()["paradas"], [])
        self.avancar(minutes=15)
        m = self.ctl.mesas()
        self.assertEqual((m["abertas"], m["limite_min"]), (1, 30))
        self.assertEqual(len(m["paradas"]), 1)
        self.assertTrue(any("sem lançamento há 35 min" in t for t in self.titulos({"operacao"})))
        self.banco.cfg_set("tempo_inatividade_min", 0)        # 0 desliga, como no painel de mesas
        self.assertEqual(self.ctl.mesas()["paradas"], [])
        self.banco.cfg_set("tempo_inatividade_min", 30)
        self.banco.cfg_set("usar_mesas", "N")
        self.assertEqual(self.ctl.mesas(), {"ligado": False, "limite_min": 30, "abertas": 0, "paradas": []})

    def test_entregas_so_com_delivery_ligado(self):
        self.assertFalse(self.ctl.entregas()["ligado"])
        self.banco.cfg_set("usar_delivery", "S")
        self.assertEqual(self.ctl.entregas(), {"ligado": True, "abertas": 0, "mais_antiga_min": 0})

    def test_filas_de_impressao_telegram_e_nuvem(self):
        agora = "2026-10-03 21:00:00"
        for status, tentativas in (("erro", 3), ("pendente", 1), ("pendente", 0)):
            self.banco.inserir("fila_impressao", {"criado_em": agora, "nome": "cupom", "dados": b"x", "status": status,
                                                  "tentativas": tentativas, "ultimo_erro": "COM3 senha=segredo"})
        for chave, valor in (("painel_dono", "S"), ("api_url", "https://exemplo.invalido/v1/sincronizar"), ("api_token", "t")):
            self.banco.cfg_set(chave, valor)
        f = self.ctl.filas()
        self.assertEqual(f["impressao"], {"pendentes": 2, "falhando": 1, "erros": 1})
        self.assertTrue(f["nuvem"]["ligada"])
        self.assertNotIn("telegram", f)
        lista = self.ctl.alertas({"operacao"})
        cats = {a["categoria"] for a in lista}
        self.assertIn("impressao", cats)
        self.assertNotIn("telegram", cats)
        self.assertEqual(lista[0]["nivel"], "critico")
        self.assertFalse(any("segredo" in a["detalhe"] or "sem rede" in a["detalhe"] for a in lista))

    def test_nuvem_com_venda_pendente_e_erro(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Dinheiro", 800)
        self.caixa.fechar(vid)
        self.assertNotIn("nuvem", {a["categoria"] for a in self.ctl.alertas()})   # painel desligado: nada
        for chave, valor in (("painel_dono", "S"), ("api_url", "https://exemplo.invalido/v1/sincronizar"), ("api_token", "t")):
            self.banco.cfg_set(chave, valor)
        self.assertIn("1 venda(s) aguardando envio à nuvem", self.titulos())
        from src.sync import painel_envio
        self.banco.cfg_set(painel_envio.CHAVE_ULTIMO_ERRO, "HTTP 500")
        self.assertIn("Último envio ao painel na nuvem falhou", self.titulos())

    def test_integracoes_so_quando_em_preparacao_ou_invalidas(self):
        self.assertEqual(self.ctl.integracoes(), [])
        self.banco.cfg_set("integracao_nfce_estado", "preparacao")
        self.banco.cfg_set("integracao_ifood_estado", "quebrado")
        por_modulo = {i["modulo"]: i for i in self.ctl.integracoes()}
        self.assertIn("pendencias", por_modulo["nfce"])
        self.assertIn("erro", por_modulo["ifood"])
        self.assertIn("NFC-e em preparação (sem operação)", self.titulos())
        self.assertIn("iFood: configuração inválida", self.titulos())

    def test_alertas_nao_mostram_dinheiro(self):
        self.novo_produto("GIN", 9000, estoque=True, qt=0)
        self.vender((self.skol, 1), mesa=5)
        self.avancar(hours=2)
        for a in self.ctl.alertas():
            self.assertNotIn("R$", a["titulo"] + a["detalhe"])

    def test_consulta_nao_grava_nada(self):
        self.novo_produto("GIN", 9000, estoque=True, qt=0)
        self.vender((self.skol, 1), mesa=5)
        self.banco.inserir("fila_impressao", {"criado_em": "2026-10-03 21:00:00", "nome": "c", "dados": b"x"})
        self.banco.cfg_set("integracao_nfce_estado", "preparacao")
        self.avancar(hours=1)
        antes = retrato(self.banco)
        self.ctl.alertas()
        self.ctl.filas()
        self.ctl.secoes_permitidas(self.adm)
        self.assertEqual(retrato(self.banco), antes)


class TestePermissoes(BaseAlertas):
    def test_adm_ve_as_duas_secoes(self):
        self.assertEqual(self.ctl.exigir_secoes(self.adm), {"estoque", "operacao"})

    def test_sem_permissao_levanta(self):
        baixo = self.operador()
        with self.assertRaises(ErroPermissao):
            self.ctl.exigir_secoes(baixo)
        self.assertEqual(self.ctl.secoes_permitidas(None), set())
        self.assertEqual(self.ctl.secoes_permitidas(99999), set())

    def test_secoes_separadas_por_modulo(self):
        baixo = self.operador("1")
        acesso = AcessoController(self.banco)
        acesso.alterar_nivel_modulo("rel_estoque", 1)
        self.assertEqual(self.ctl.secoes_permitidas(baixo), {"estoque"})
        acesso.alterar_nivel_modulo("rel_estoque", 2)
        acesso.alterar_nivel_modulo("rel_informativos", 1)
        self.assertEqual(self.ctl.secoes_permitidas(baixo), {"operacao"})

    def test_secao_negada_nao_vaza_alerta(self):
        self.novo_produto("GIN", 9000, estoque=True, qt=0)
        self.banco.cfg_set("integracao_nfce_estado", "preparacao")
        self.assertEqual({a["categoria"] for a in self.ctl.alertas({"operacao"})}, {"integracoes"})
        self.assertEqual({a["categoria"] for a in self.ctl.alertas({"estoque"})}, {"estoque"})
        self.assertEqual(self.ctl.alertas(set()), [])

    def test_operador_desativado_perde_tudo(self):
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.adm,))
        self.assertEqual(self.ctl.secoes_permitidas(self.adm), set())


