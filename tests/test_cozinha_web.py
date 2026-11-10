"""Cozinha web: PIN, leitura, transições concorrentes, revogação e serviço local."""
import json
import tempfile
from pathlib import Path
from contextlib import contextmanager
from src.cozinha.servidor import ServidorCozinha
from src.cozinha.servico import configurar, ServicoCozinha
from src.database.conexao import BancoDados
from tests.test_caixa import BaseCaixa

 
@contextmanager
def banco_arquivo(caminho):
    banco = BancoDados(caminho, semear=False)
    try:
        yield banco
    finally:
        banco.fechar()


class TesteCozinhaWeb(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_cozinha_bar", "S")
        self.banco.executar("UPDATE subgrupos SET impressora_remota = 1")
        self.vid, _ = self.caixa.abrir_mesa(1)
        self.item = self.caixa.adicionar_item(self.vid, self.skol, 1, observacao="Sem cebola")
        configurar(self.banco, True, 8766, "123456", self.adm, self.adm)
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.arquivo = str(Path(self.pasta.name) / "cozinha.db")
        self.banco.copiar_para(self.arquivo)
        self.servidor = ServidorCozinha(self.arquivo, 0, "127.0.0.1")
        self.cabecalho = {"Content-Type": "application/json", "X-Cozinha-Acao": "1",
                          "Host": "127.0.0.1", "Origin": "http://127.0.0.1"}

    def chamar(self, caminho, dados=None, cabecalho=None):
        status, headers, corpo = self.servidor.tratar("GET" if dados is None else "POST",
            "/cozinha/api/" + caminho, cabecalho or self.cabecalho,
            b"" if dados is None else json.dumps(dados).encode(), "127.0.0.1")
        return status, dict(headers), json.loads(corpo)

    def entrar(self, modo="operacao"):
        status, headers, _ = self.chamar("entrar", {"pin": "123456", "modo": modo})
        self.assertEqual(status, 200)
        self.cabecalho["Cookie"] = headers["Set-Cookie"].split(";", 1)[0]

    def test_fila_privada_sem_dados_financeiros(self):
        self.assertEqual(self.chamar("fila")[0], 401)
        self.entrar()
        status, _, dados = self.chamar("fila")
        self.assertEqual(status, 200)
        self.assertEqual(dados["itens"][0]["id"], self.item)
        self.assertEqual(dados["itens"][0]["observacao"], "Sem cebola")
        for campo in ("preco_unit_cent", "total_cent", "cliente", "telefone", "comissao_cent", "custo_cent"):
            self.assertNotIn(campo, dados["itens"][0])

    def test_transicao_explicita_impede_duplo_avanco(self):
        self.entrar()
        acao = {"item_id": self.item, "de": "pendente", "para": "em_preparo"}
        self.assertEqual(self.chamar("preparo", acao)[0], 200)
        self.assertEqual(self.chamar("preparo", acao)[0], 409)
        acao.update(de="em_preparo", para="entregue")
        self.assertEqual(self.chamar("preparo", acao)[0], 200)
        self.assertEqual(self.chamar("fila")[2]["itens"], [])
        with banco_arquivo(self.arquivo) as banco:
            self.assertEqual(banco.valor("SELECT preparo_operador_id FROM itens_venda WHERE id = ?", (self.item,)), self.adm)
            self.assertEqual(banco.valor("SELECT status FROM vendas WHERE id = ?", (self.vid,)), "aberta")

    def test_tv_nao_muda_preparo_e_origem_externa_nao_entra(self):
        self.entrar("tv")
        self.assertEqual(self.chamar("preparo", {"item_id": self.item, "de": "pendente", "para": "em_preparo"})[0], 403)
        externo = {**self.cabecalho, "Origin": "http://outro.example"}
        self.assertEqual(self.chamar("entrar", {"pin": "123456"}, externo)[0], 403)

    def test_pin_e_operador_revogados_invalidam_acesso(self):
        self.entrar()
        with banco_arquivo(self.arquivo) as banco:
            configurar(banco, True, 8766, "654321", self.adm, self.adm)
        self.assertEqual(self.chamar("fila")[0], 401)
        with banco_arquivo(self.arquivo) as banco:
            banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.adm,))
        self.assertEqual(self.chamar("fila")[0], 403)

    def test_item_cancelado_nao_pode_ser_marcado(self):
        self.entrar()
        with banco_arquivo(self.arquivo) as banco:
            banco.executar("UPDATE itens_venda SET cancelado = 1 WHERE id = ?", (self.item,))
        self.assertEqual(self.chamar("preparo", {"item_id": self.item, "de": "pendente", "para": "em_preparo"})[0], 409)

    def test_http_real_e_servico_desligam_sem_ocupar_porta(self):
        import urllib.request
        self.servidor.iniciar()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.servidor.porta}/cozinha/", timeout=5) as r:
                self.assertEqual(r.status, 200)
                self.assertIn(b"PIN", r.read())
        finally:
            self.servidor.parar()
        self.assertFalse(self.servidor.ativo)
        servico = ServicoCozinha(self.arquivo, host="127.0.0.1")
        # O módulo desligado nunca abre servidor, mesmo com PIN salvo.
        with banco_arquivo(self.arquivo) as banco:
            banco.cfg_set("usar_cozinha_bar", "N")
        servico._sincronizar()
        self.assertIsNone(servico._servidor)
        servico.parar()

    def test_pin_incorreto_tem_limite_de_tentativas(self):
        for _ in range(5):
            self.chamar("entrar", {"pin": "999999"})
        self.assertEqual(self.chamar("entrar", {"pin": "123456"})[0], 429)
