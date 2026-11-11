"""Retaguarda na nuvem: o caixa sobe o espelho, o dono e o fornecedor pedem alterações e o caixa aplica pelas regras do PDV."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import unittest

from src.controllers.config_controller import CAMPOS_CONFIG
from src.controllers.retaguarda_controller import RetaguardaController
from src.database.sementes import CONFIG_PADRAO
from src.sync import painel_envio, retaguarda
from tests.base import BaseTeste
from tests.test_notas_dono import _Ponte
from tests.test_painel_dono import BaseNuvem, TestClient, cabecalho, nuvem

try:
    from backend import retaguarda as nuvem_retaguarda
except (ImportError, RuntimeError):
    nuvem_retaguarda = None


class TesteControleDoCaixa(BaseTeste):
    """Só o caixa: espelho e aplicação dos comandos, sem rede."""

    def setUp(self):
        super().setUp()
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.controle = RetaguardaController(self.banco)
        self.skol = self.novo_produto("SKOL", preco=800)

    def aplicar(self, ident, tipo, dados):
        return self.controle.aplicar({"id": ident, "tipo": tipo, "dados": dados, "resumo": "teste", "autor": "dono"})

    def produto(self, ident=None):
        return dict(self.banco.um("SELECT * FROM produtos WHERE id = ?", (ident or self.skol,)))

    def test_nasce_desligada_e_aparece_nas_configuracoes(self):
        self.assertEqual(CONFIG_PADRAO["retaguarda_nuvem"], "N")
        self.assertIn("retaguarda_nuvem", [c[0] for c in CAMPOS_CONFIG])

    def test_espelho_nao_leva_senha_token_nem_configuracao_da_nuvem(self):
        self.banco.cfg_set("api_token", "segredo-da-loja")
        espelho = self.controle.espelho()
        texto = json.dumps(espelho, default=str)
        self.assertNotIn("segredo-da-loja", texto)
        self.assertNotIn("senha", espelho["cadastro:operadores"]["campos"])
        chaves = {c["chave"] for c in espelho["esquema"]["config"]["campos"]}
        self.assertIn("permitir_venda_sem_estoque", chaves)
        self.assertFalse(chaves & {"api_token", "api_url", "chave_loja", "central_caixa_token", "retaguarda_nuvem", "pasta_backup"})
        for linha in self.banco.todos("SELECT senha FROM operadores"):
            self.assertNotIn(linha[0], texto)

    def test_espelho_traz_os_cadastros_com_dinheiro_em_centavos(self):
        espelho = self.controle.espelho()
        produtos = espelho["cadastro:produtos"]
        linha = dict(zip(produtos["campos"], next(l for l in produtos["linhas"] if l[0] == self.skol)))
        self.assertEqual((linha["nome"], linha["preco_cent"]), ("SKOL", 800))
        entidade = next(e for e in espelho["esquema"]["entidades"] if e["chave"] == "produtos")
        self.assertEqual(entidade["grupo"], "produtos")
        self.assertIn("subgrupos", espelho["esquema"]["lookups"])
        self.assertEqual(self.controle.resumo_secao(produtos), self.controle.resumo_secao(self.controle.linhas("produtos")))

    def test_modulo_desligado_tira_o_cadastro_do_espelho(self):
        self.banco.cfg_set("usar_garotas", "N")
        self.assertNotIn("cadastro:garotas", self.controle.espelho())
        self.banco.cfg_set("usar_garotas", "S")
        self.assertIn("cadastro:garotas", self.controle.espelho())

    def test_altera_preco_em_centavos_e_so_o_campo_enviado(self):
        r = self.aplicar(1, "cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": 950}})
        self.assertEqual(r, {"situacao": "aplicado", "detalhe": "", "novo_id": None})
        p = self.produto()
        self.assertEqual((p["preco_cent"], p["nome"]), (950, "SKOL"))

    def test_cria_produto_e_devolve_o_id_novo(self):
        base = self.produto()
        r = self.aplicar(2, "cadastro.salvar", {"entidade": "produtos", "valores": {
            "codigo": "777", "nome": "BRAHMA LATA", "subgrupo_id": base["subgrupo_id"], "unidade_id": base["unidade_id"],
            "preco_cent": 599}})
        self.assertEqual(r["situacao"], "aplicado", r)
        novo = self.produto(r["novo_id"])
        self.assertEqual((novo["nome"], novo["preco_cent"]), ("BRAHMA LATA", 599))

    def test_o_mesmo_comando_nao_aplica_duas_vezes(self):
        dados = {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": 950}}
        self.aplicar(3, "cadastro.salvar", dados)
        self.banco.executar("UPDATE produtos SET preco_cent = 1000 WHERE id = ?", (self.skol,))     # alteração posterior no caixa
        repetido = self.aplicar(3, "cadastro.salvar", dados)
        self.assertEqual(repetido["situacao"], "aplicado")
        self.assertEqual(self.produto()["preco_cent"], 1000)                                         # vale a mais recente

    def test_regra_do_pdv_recusa_com_o_motivo(self):
        casos = [("cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"nome": ""}}, "Informe"),
                 ("cadastro.salvar", {"entidade": "produtos", "id": 99999, "valores": {"nome": "X"}}, "não encontrado"),
                 ("cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"inventado": 1}}, "Campo desconhecido"),
                 ("cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": "9,50"}}, "centavos"),
                 ("cadastro.salvar", {"entidade": "tabela_que_nao_existe", "valores": {"nome": "X"}}, "desconhecido"),
                 ("config.salvar", {"valores": {"api_token": "outro"}}, "só pode ser alterada no próprio caixa"),
                 ("config.salvar", {"valores": {"retaguarda_nuvem": "N"}}, "só pode ser alterada no próprio caixa"),
                 ("estoque.movimento", {"produto_id": self.skol, "tipo": "roubo", "quantidade": 1}, "inválido"),
                 ("tipo.que.nao.existe", {}, "Atualize o programa")]
        for n, (tipo, dados, trecho) in enumerate(casos, start=10):
            r = self.aplicar(n, tipo, dados)
            self.assertEqual(r["situacao"], "recusado", (tipo, dados))
            self.assertIn(trecho, r["detalhe"], (tipo, dados))
        self.assertEqual(self.produto()["nome"], "SKOL")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retaguarda_comandos WHERE situacao = 'recusado'"), len(casos))

    def test_desligada_no_caixa_recusa_tudo(self):
        self.banco.cfg_set("retaguarda_nuvem", "N")
        r = self.aplicar(30, "cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": 1}})
        self.assertEqual(r["situacao"], "recusado")
        self.assertIn("desligada", r["detalhe"])
        self.assertEqual(self.produto()["preco_cent"], 800)

    def test_movimento_de_estoque_e_contagem(self):
        r = self.aplicar(40, "estoque.movimento", {"produto_id": self.skol, "tipo": "entrada", "quantidade": 24,
                                                   "descricao": "Compra do fim de semana"})
        self.assertEqual(r["situacao"], "aplicado", r)
        self.assertEqual(self.produto()["qt_atual"], 24)
        self.aplicar(41, "estoque.movimento", {"produto_id": self.skol, "tipo": "contagem", "quantidade": 20})
        self.assertEqual(self.produto()["qt_atual"], 20)
        falta = self.aplicar(42, "estoque.movimento", {"produto_id": self.skol, "tipo": "saida", "quantidade": 50})
        self.assertEqual(falta["situacao"], "recusado")
        self.assertIn("Só há", falta["detalhe"])

    def test_configuracao_permitida_e_alterada(self):
        self.banco.cfg_set("permitir_venda_sem_estoque", "N")
        r = self.aplicar(50, "config.salvar", {"valores": {"permitir_venda_sem_estoque": "S", "mensagem_rodape": "Volte sempre"}})
        self.assertEqual(r["situacao"], "aplicado", r)
        self.assertEqual((self.banco.cfg("permitir_venda_sem_estoque"), self.banco.cfg("mensagem_rodape")), ("S", "Volte sempre"))

    def test_operador_criado_pela_retaguarda_entra_com_a_senha(self):
        from src.controllers.acesso_controller import AcessoController
        r = self.aplicar(60, "cadastro.salvar", {"entidade": "operadores", "valores": {"nome": "CARLA", "senha": "abc123", "nivel": 1}})
        self.assertEqual(r["situacao"], "aplicado", r)
        self.assertEqual(AcessoController(self.banco).autenticar("CARLA", "abc123").nome, "CARLA")

    def test_contas_incluir_quitar_e_excluir(self):
        self.banco.cfg_set("usar_contas", "S")
        subplano = self.banco.valor("SELECT id FROM subplanos LIMIT 1")
        forma = self.banco.valor("SELECT id FROM tipos_pagamento LIMIT 1")
        r = self.aplicar(70, "conta.incluir", {"subplano_id": subplano, "tipo_pagamento_id": forma, "descricao": "Aluguel",
                                               "valor_cent": 250000, "dt_vencimento": "2026-10-10"})
        self.assertEqual(r["situacao"], "aplicado", r)
        conta = r["novo_id"]
        abertas = self.controle.financeiro()["contas"]
        self.assertEqual([(c["descricao"], c["valor_cent"], c["dt_quitacao"]) for c in abertas], [("Aluguel", 250000, None)])
        self.assertEqual(self.aplicar(71, "conta.quitar", {"id": conta, "data": "2026-10-03"})["situacao"], "aplicado")
        self.assertEqual(self.controle.financeiro()["contas"][0]["dt_quitacao"], "2026-10-03")
        self.assertEqual(self.aplicar(72, "conta.desfazer", {"id": conta})["situacao"], "aplicado")
        self.assertEqual(self.aplicar(73, "conta.excluir", {"id": conta})["situacao"], "aplicado")
        self.assertEqual(self.controle.financeiro()["contas"], [])
        self.banco.cfg_set("usar_contas", "N")
        self.assertEqual(self.aplicar(74, "conta.quitar", {"id": conta})["situacao"], "recusado")


@unittest.skipIf(TestClient is None or nuvem_retaguarda is None, "fastapi/httpx não instalados")
class TestePontaAPonta(BaseNuvem):
    """Caixa de teste falando com a API de verdade: espelho sobe, o dono pede, o caixa aplica e a página vê o resultado."""

    def setUp(self):
        super().setUp()
        with nuvem.SessionLocal() as db:
            db.query(nuvem_retaguarda.RetaguardaEspelho).delete()
            db.query(nuvem_retaguarda.RetaguardaComando).delete()
            db.commit()
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.dono = self.entrar()
        self.ponte = _Ponte(self.http)
        self.skol = self.novo_produto("ITAIPAVA", preco=800)

    def rodada(self, forcar=False):
        return retaguarda.sincronizar(self.banco, self.ponte, forcar=forcar)

    def pedir(self, tipo, dados, resumo="", sessao=None):
        return self.http.post("/v1/painel/retaguarda/comandos", json={"tipo": tipo, "dados": dados, "resumo": resumo},
                              headers=sessao or self.dono)

    def produtos(self, **filtros):
        r = self.http.get("/v1/painel/retaguarda/cadastro/produtos", params=filtros, headers=self.dono)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_desligada_nao_usa_a_rede(self):
        self.banco.cfg_set("retaguarda_nuvem", "N")
        self.assertIsNone(self.rodada())
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.banco.cfg_set("painel_dono", "N")
        self.assertIsNone(self.rodada())
        self.assertEqual(self.ponte.chamadas, [])

    def test_espelho_sobe_uma_vez_e_depois_so_o_que_mudou(self):
        antes = self.http.get("/v1/painel/retaguarda", headers=self.dono).json()
        self.assertEqual((antes["ligada"], antes["esquema"]), (False, None))
        primeira = self.rodada()
        self.assertGreater(primeira["secoes"], 5)
        visao = self.http.get("/v1/painel/retaguarda", headers=self.dono).json()
        self.assertTrue(visao["ligada"])
        self.assertIn("cadastro:produtos", visao["secoes"])
        self.ponte.chamadas.clear()
        self.assertEqual(self.rodada(), {"aplicados": 0, "avisados": 0, "secoes": 0})
        self.assertEqual(self.ponte.chamadas, [])                                   # nada mudou: não acorda a nuvem
        self.banco.executar("UPDATE produtos SET preco_cent = 850 WHERE id = ?", (self.skol,))
        self.assertEqual(self.rodada()["secoes"], 1)
        self.assertEqual([c[1].rsplit("/", 1)[-1] for c in self.ponte.chamadas], ["espelho"])

    def test_lista_com_busca_pagina_e_inativos(self):
        self.novo_produto("Tônica sem açúcar", preco=300, codigo="901")
        inativo = self.novo_produto("ITAIPAVA VELHA", preco=100, codigo="902")
        self.banco.executar("UPDATE produtos SET ativo = 0 WHERE id = ?", (inativo,))
        self.rodada()
        tudo = self.produtos()
        self.assertEqual(tudo["total"], tudo["encontradas"])
        nomes = lambda dados: [dict(zip(dados["campos"], l))["nome"] for l in dados["linhas"]]
        self.assertEqual(nomes(self.produtos(busca="tonica sem acucar")), ["Tônica sem açúcar"])
        self.assertEqual(sorted(nomes(self.produtos(busca="itaipava"))), ["ITAIPAVA", "ITAIPAVA VELHA"])
        self.assertEqual(nomes(self.produtos(busca="itaipava", inativos=0)), ["ITAIPAVA"])
        self.assertEqual(self.produtos(pagina=99)["linhas"], [])
        self.assertEqual(self.http.get("/v1/painel/retaguarda/cadastro/nao_existe", headers=self.dono).status_code, 404)

    def test_dono_altera_preco_e_o_caixa_aplica_na_proxima_rodada(self):
        self.rodada()
        r = self.pedir("cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": 990}},
                       "Produtos: ITAIPAVA, preço 9,90")
        self.assertEqual(r.status_code, 200, r.text)
        comando = r.json()["comando"]
        self.assertEqual((comando["situacao"], comando["autor"]), ("pendente", "dono"))
        self.assertEqual([c["id"] for c in self.produtos()["pendentes"]], [comando["id"]])
        painel_envio.enviar(self.banco, self.ponte)                                  # o envio do painel traz o aviso
        self.assertEqual(self.banco.cfg(retaguarda.CHAVE_AVISO), "S")
        resultado = self.rodada()
        self.assertEqual((resultado["aplicados"], resultado["secoes"]), (1, 1))
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.skol,)), 990)
        depois = self.produtos(busca="itaipava")
        self.assertEqual(dict(zip(depois["campos"], depois["linhas"][0]))["preco_cent"], 990)
        self.assertEqual(depois["pendentes"], [])
        historico = self.http.get("/v1/painel/retaguarda/comandos", headers=self.dono).json()["comandos"]
        self.assertEqual([(c["situacao"], c["resumo"]) for c in historico], [("aplicado", "Produtos: ITAIPAVA, preço 9,90")])
        self.assertEqual(self.banco.cfg(retaguarda.CHAVE_AVISO), "N")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retaguarda_comandos WHERE aviso_ok = 0"), 0)

    def test_recusa_do_caixa_volta_com_o_motivo(self):
        self.rodada()
        self.pedir("cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"nome": ""}})
        self.rodada(forcar=True)
        comando = self.http.get("/v1/painel/retaguarda/comandos", headers=self.dono).json()["comandos"][0]
        self.assertEqual(comando["situacao"], "recusado")
        self.assertIn("Informe", comando["detalhe"])

    def test_senha_do_operador_some_da_nuvem_depois_de_entregue(self):
        self.rodada()
        r = self.pedir("cadastro.salvar", {"entidade": "operadores", "valores": {"nome": "CARLA", "senha": "abc123", "nivel": 1}})
        self.assertNotIn("abc123", r.text)                                           # nem a resposta mostra a senha
        self.assertNotIn("abc123", self.http.get("/v1/painel/retaguarda/comandos", headers=self.dono).text)
        self.rodada(forcar=True)
        with nuvem.SessionLocal() as db:
            guardado = db.query(nuvem_retaguarda.RetaguardaComando).one()
            self.assertNotIn("abc123", guardado.dados)
            self.assertEqual((guardado.situacao, type(guardado.novo_id)), ("aplicado", int))
        from src.controllers.acesso_controller import AcessoController
        self.assertEqual(AcessoController(self.banco).autenticar("CARLA", "abc123").nome, "CARLA")

    def test_cancelar_so_enquanto_o_caixa_nao_buscou(self):
        self.rodada()
        comando = self.pedir("cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": 1}}).json()["comando"]
        self.assertEqual(self.http.delete(f"/v1/painel/retaguarda/comandos/{comando['id']}", headers=self.dono).status_code, 200)
        self.rodada(forcar=True)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.skol,)), 800)
        outro = self.pedir("cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": 2}}).json()["comando"]
        self.rodada(forcar=True)
        self.assertEqual(self.http.delete(f"/v1/painel/retaguarda/comandos/{outro['id']}", headers=self.dono).status_code, 409)

    def test_pedidos_invalidos_e_loja_sem_retaguarda(self):
        sem_espelho = self.pedir("cadastro.salvar", {"entidade": "produtos", "id": 1, "valores": {"preco_cent": 1}})
        self.assertEqual(sem_espelho.status_code, 409)
        self.assertIn("ainda não ligou", sem_espelho.json()["detail"])
        self.rodada()
        for corpo in ({"tipo": "apagar.tudo", "dados": {}}, {"tipo": "cadastro.salvar", "dados": "x"}, {"dados": {}}):
            self.assertEqual(self.http.post("/v1/painel/retaguarda/comandos", json=corpo, headers=self.dono).status_code, 422)
        grande = self.pedir("config.salvar", {"valores": {"mensagem_rodape": "x" * nuvem_retaguarda.LIMITE_COMANDO_BYTES}})
        self.assertEqual(grande.status_code, 413)

    def test_cada_loja_ve_e_altera_so_a_sua_e_o_caixa_nao_usa_rota_do_dono(self):
        self.rodada()
        outra = self.entrar("ADEGA-2", "senha-forte-2")
        self.assertFalse(self.http.get("/v1/painel/retaguarda", headers=outra).json()["ligada"])
        self.assertEqual(self.http.get("/v1/painel/retaguarda/cadastro/produtos", headers=outra).status_code, 404)
        comando = self.pedir("cadastro.salvar", {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": 5}}).json()["comando"]
        self.assertEqual(self.http.delete(f"/v1/painel/retaguarda/comandos/{comando['id']}", headers=outra).status_code, 404)
        self.assertEqual(self.http.get("/v1/retaguarda/comandos", headers=cabecalho("ADEGA-2")).json()["comandos"], [])
        self.assertEqual(self.http.get("/v1/painel/retaguarda", headers=cabecalho()).status_code, 401)   # token do caixa não é sessão
        self.assertEqual(self.http.get("/v1/retaguarda/comandos", headers=self.dono).status_code, 401)   # sessão não é token do caixa
        self.assertEqual(self.http.get("/v1/retaguarda/comandos").status_code, 401)
        ruim = self.http.post("/v1/retaguarda/espelho", json={"secao": "../../etc", "digital": "x", "dados": {}}, headers=cabecalho())
        self.assertEqual(ruim.status_code, 422)

    def test_pagina_e_servida_e_os_atalhos_existem(self):
        pagina = self.http.get("/retaguarda/")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("WillPDV Retaguarda", pagina.text)
        for arquivo in ("app.js", "estilo.css"):
            self.assertEqual(self.http.get(f"/retaguarda/{arquivo}").status_code, 200)
        self.assertNotIn("<script>", pagina.text)                                   # sem script embutido na página
        self.assertIn('href="/retaguarda/"', self.http.get("/painel/").text)
        self.assertIn("abrirRetaguarda", self.http.get("/central/").text)

    def test_envio_do_painel_so_avisa_quando_ha_alteracao(self):
        self.rodada()
        self.assertNotIn("retaguarda_pendentes", painel_envio.enviar(self.banco, self.ponte) or {})
        self.assertNotEqual(self.banco.cfg(retaguarda.CHAVE_AVISO), "S")

    def test_financeiro_sobe_e_o_dono_quita_a_conta(self):
        self.banco.cfg_set("usar_contas", "S")
        from src.controllers.contas_controller import ContasController
        conta = ContasController(self.banco).incluir(
            self.banco.valor("SELECT id FROM subplanos LIMIT 1"), "Energia",
            self.banco.valor("SELECT id FROM tipos_pagamento LIMIT 1"), 43210, "2026-10-08")[0]
        self.rodada()
        contas = self.http.get("/v1/painel/retaguarda/financeiro", headers=self.dono).json()["contas"]
        self.assertEqual([(c["id"], c["descricao"], c["valor_cent"]) for c in contas], [(conta, "Energia", 43210)])
        self.pedir("conta.quitar", {"id": conta, "data": "2026-10-03"}, "Contas: quitar Energia")
        self.assertEqual(len(self.http.get("/v1/painel/retaguarda/financeiro", headers=self.dono).json()["pendentes"]), 1)
        self.rodada(forcar=True)
        depois = self.http.get("/v1/painel/retaguarda/financeiro", headers=self.dono).json()
        self.assertEqual((depois["contas"][0]["dt_quitacao"], depois["pendentes"]), ("2026-10-03", []))


@unittest.skipIf(TestClient is None or nuvem_retaguarda is None, "fastapi/httpx não instalados")
class TesteFornecedor(BaseNuvem):
    """A central usa as mesmas rotas, com a sessão do fornecedor, em qualquer loja, e cada pedido entra na auditoria."""

    def setUp(self):
        super().setUp()
        from backend import central_fornecedor as central
        self.central = central
        with nuvem.SessionLocal() as db:
            for modelo in (nuvem_retaguarda.RetaguardaEspelho, nuvem_retaguarda.RetaguardaComando,
                           central.SessaoFornecedor, central.AuditoriaFornecedor):
                db.query(modelo).delete()
            db.commit()
        with central._trava:
            central._tentativas.clear()
        self.addCleanup(self._limpar)
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.skol = self.novo_produto("ITAIPAVA", preco=800)
        self.ponte = _Ponte(self.http)
        self.fornecedor = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(self.fornecedor.close)
        r = self.fornecedor.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"}, headers={"X-Central-Login": "1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.csrf = {"X-Central-CSRF": r.json()["csrf"]}

    def _limpar(self):
        with nuvem.SessionLocal() as db:
            for modelo in (self.central.SessaoFornecedor, self.central.AuditoriaFornecedor):
                db.query(modelo).delete()
            db.commit()

    def test_fornecedor_altera_a_loja_e_fica_na_auditoria(self):
        retaguarda.sincronizar(self.banco, self.ponte)
        base = "/v1/fornecedor/lojas/ADEGA-1/retaguarda"
        self.assertTrue(self.fornecedor.get(base).json()["ligada"])
        self.assertEqual(self.fornecedor.get(base + "/cadastro/produtos", params={"busca": "skol"}).json()["encontradas"], 1)
        corpo = {"tipo": "cadastro.salvar", "dados": {"entidade": "produtos", "id": self.skol, "valores": {"preco_cent": 1200}},
                 "resumo": "Produtos: ITAIPAVA, preço 12,00"}
        self.assertEqual(self.fornecedor.post(base + "/comandos", json=corpo).status_code, 403)       # sem CSRF não altera
        r = self.fornecedor.post(base + "/comandos", json=corpo, headers=self.csrf)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["comando"]["autor"], "fornecedor")
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.skol,)), 1200)
        self.assertEqual(self.banco.valor("SELECT autor FROM retaguarda_comandos"), "fornecedor")
        with nuvem.SessionLocal() as db:
            evento = db.query(self.central.AuditoriaFornecedor).filter_by(acao="retaguarda").one()
            self.assertEqual((evento.loja, evento.motivo), ("ADEGA-1", "cadastro.salvar: Produtos: ITAIPAVA, preço 12,00"))

    def test_sem_sessao_da_central_nao_entra_e_loja_inexistente_da_404(self):
        base = "/v1/fornecedor/lojas/ADEGA-1/retaguarda"
        self.assertEqual(self.http.get(base).status_code, 401)
        self.assertEqual(self.http.get(base, headers=self.entrar()).status_code, 401)        # sessão do dono não é a da central
        self.assertEqual(self.fornecedor.get("/v1/fornecedor/lojas/NAO-EXISTE/retaguarda").status_code, 404)


if __name__ == "__main__":
    unittest.main()
