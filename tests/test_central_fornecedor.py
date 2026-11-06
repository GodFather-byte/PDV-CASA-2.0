"""Acesso do fornecedor, isolamento das lojas, suporte e transferência de emissão."""
from datetime import date, timedelta
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests.test_nuvem import TestClient, nuvem, preparar_lojas, cabecalho, ADMIN
from backend import central_fornecedor as central, licencas_fornecedor as emissao, ponte
from backend import cobranca_mercadopago as cobranca
from src.core import ed25519, licenca

SEMENTE = bytes.fromhex("33" * 32)
PUBLICA = ed25519.chave_publica(SEMENTE).hex()


@unittest.skipIf(TestClient is None, "Dependências da nuvem ausentes")
class TesteCentralFornecedor(unittest.TestCase):
    def setUp(self):
        preparar_lojas()
        with nuvem.SessionLocal() as db:
            for modelo in (central.SessaoFornecedor, central.AuditoriaFornecedor, central.ChamadoFornecedor,
                           emissao.EmissaoNuvem, ponte.PonteCaixa, ponte.PonteLicenca, ponte.PonteLoja,
                           cobranca.Cobranca, cobranca.Plano):
                db.query(modelo).delete()
            db.commit()
        with central._trava:
            central._tentativas.clear()
        chave_real = patch.object(nuvem, "semente_licenca", return_value=None)
        chave_real.start()
        self.addCleanup(chave_real.stop)
        self.http = TestClient(nuvem.app, base_url="https://testserver")
        self.csrf = self.login()

    def tearDown(self):
        self.http.close()
        with nuvem.SessionLocal() as db:
            for modelo in (central.SessaoFornecedor, central.AuditoriaFornecedor, central.ChamadoFornecedor,
                           emissao.EmissaoNuvem, ponte.PonteCaixa, ponte.PonteLicenca, ponte.PonteLoja,
                           cobranca.Cobranca, cobranca.Plano):
                db.query(modelo).delete()
            db.commit()

    def login(self, credencial="token-de-teste"):
        r = self.http.post("/v1/fornecedor/login", json={"credencial": credencial}, headers={"X-Central-Login": "1"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["csrf"]

    def post(self, rota, dados):
        return self.http.post("/v1/fornecedor" + rota, json=dados, headers={"X-Central-CSRF": self.csrf})

    def test_cookie_protegido_hash_no_banco_e_logout_revoga(self):
        valor = self.http.cookies.get(central.COOKIE)
        with nuvem.SessionLocal() as db:
            s = db.query(central.SessaoFornecedor).one()
            self.assertNotEqual(s.token_hash, valor)
        self.assertEqual(self.http.get("/v1/fornecedor/lojas").status_code, 200)
        self.assertEqual(self.post("/sair", {}).status_code, 200)
        self.http.cookies.set(central.COOKIE, valor)
        self.assertEqual(self.http.get("/v1/fornecedor/lojas").status_code, 401)

    def test_cliente_e_admin_bearer_nao_substituem_sessao_e_ponte_nao_colide(self):
        self.http.cookies.clear()
        for headers in (cabecalho(), ADMIN, {}):
            self.assertEqual(self.http.get("/v1/fornecedor/lojas", headers=headers).status_code, 401)
        # A rota da central antiga continua com o próprio contrato e autenticação.
        self.assertNotEqual(self.http.get("/v1/central/lojas").status_code, 200)

    def test_csrf_obrigatorio_e_token_rotacionado_revoga_sessoes(self):
        dados = {"nome": "Alterada", "ativa": False, "motivo": "teste"}
        self.assertEqual(self.http.post("/v1/fornecedor/lojas/LOJA-1/alterar", json=dados).status_code, 403)
        with patch.dict(os.environ, {"PDV_API_TOKEN": "credencial-rotacionada"}):
            self.assertEqual(self.http.get("/v1/fornecedor/lojas").status_code, 401)

    def test_sessao_expirada_e_recusada(self):
        with nuvem.SessionLocal() as db:
            db.query(central.SessaoFornecedor).update({"expira_em": "2000-01-01 00:00:00"})
            db.commit()
        self.assertEqual(self.http.get("/v1/fornecedor/lojas").status_code, 401)

    def test_login_limita_tentativas_cookie_http_only_e_nao_cache(self):
        r = self.http.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"}, headers={"X-Central-Login": "1"})
        self.assertIn("HttpOnly", r.headers["set-cookie"])
        self.assertIn("Secure", r.headers["set-cookie"])
        self.assertIn("SameSite=strict", r.headers["set-cookie"])
        self.assertEqual(r.headers["cache-control"], "no-store")
        for _ in range(6):
            self.assertEqual(self.http.post("/v1/fornecedor/login", json={"credencial": "errada"}, headers={"X-Central-Login": "1"}).status_code, 401)
        self.assertEqual(self.http.post("/v1/fornecedor/login", json={"credencial": "errada"}, headers={"X-Central-Login": "1"}).status_code, 429)

    def test_cadastro_token_unico_e_auditoria_sem_segredo(self):
        r = self.post("/lojas", {"chave": "NOVA", "nome": "Nova loja", "motivo": "Contrato"})
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        self.assertNotIn(token, self.http.get("/v1/fornecedor/lojas").text)
        eventos = self.http.get("/v1/fornecedor/auditoria").text
        self.assertIn("criar_loja", eventos)
        self.assertNotIn(token, eventos)

    def test_chamado_ciclo_e_isolamento_por_loja(self):
        r = self.post("/lojas/LOJA-1/chamados", {"titulo": "Erro ao abrir", "descricao": "Passos para reproduzir"})
        self.assertEqual(r.status_code, 200, r.text)
        ident = r.json()["id"]
        r = self.post(f"/chamados/{ident}", {"estado": "resolvido", "resolucao": "Atualização validada"})
        self.assertEqual(r.json()["estado"], "resolvido")
        self.assertEqual(self.http.get("/v1/fornecedor/lojas/LOJA-2").json()["chamados"], [])
        self.assertEqual(self.post("/lojas/INEXISTENTE/chamados", {"titulo": "Erro", "descricao": "teste"}).status_code, 404)

    def test_cobrancas_paginadas_e_filtradas_por_loja(self):
        with nuvem.SessionLocal() as db:
            for i in range(52):
                db.add(cobranca.Cobranca(id=str(i), plano="p", chave_loja="LOJA-1", chave_vencimento=str(i),
                                        valor_cent=9900, vencimento="2027-01-01", status="pendente",
                                        criada_em=central.agora(), consultada_em=central.agora()))
            db.commit()
        r = self.http.get("/v1/fornecedor/lojas/LOJA-1/cobrancas").json()
        self.assertEqual(len(r["cobrancas"]), 50)
        self.assertTrue(r["mais"])
        self.assertEqual(len(self.http.get("/v1/fornecedor/lojas/LOJA-1/cobrancas?pagina=2").json()["cobrancas"]), 2)
        self.assertEqual(self.http.get("/v1/fornecedor/lojas/LOJA-2/cobrancas").json()["cobrancas"], [])
        self.assertEqual(self.http.get("/v1/fornecedor/lojas/LOJA-1/cobrancas?pagina=0").status_code, 422)

    def preparar_ponte(self, dias=20):
        codigo = licenca.gerar_licenca(SEMENTE, "LOJA-1", dias, date.today())
        with nuvem.SessionLocal() as db:
            db.add(ponte.PonteLoja(chave_loja="LOJA-1", modo_ponte=True, ativado_em=central.agora()))
            db.add(ponte.PonteLicenca(id=str(uuid4()), chave_loja="LOJA-1", codigo=codigo,
                                     emitida_em=date.today().isoformat(), expira_em=(date.today()+timedelta(days=dias)).isoformat(),
                                     publicada_em=central.agora()))
            db.commit()
        return codigo

    def test_migracao_recusa_sem_chave_e_preserva_prazo_quando_configurada(self):
        self.preparar_ponte()
        dados = {"confirmacao": "LOJA-1", "motivo": "Transferência validada"}
        with patch.object(nuvem, "semente_licenca", return_value=None):
            self.assertEqual(self.post("/lojas/LOJA-1/migrar-emissao", dados).status_code, 409)
        with patch.object(nuvem, "semente_licenca", return_value=SEMENTE), patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA):
            self.assertEqual(self.post("/lojas/LOJA-1/migrar-emissao", dados).status_code, 200)
            lojas = self.http.get("/v1/fornecedor/lojas").json()["lojas"]
            loja = next(l for l in lojas if l["chave"] == "LOJA-1")
            self.assertEqual(loja["emissao"], "nuvem")
            self.assertEqual(loja["paga_ate"], (date.today()+timedelta(days=20)).isoformat())

    def test_ponte_opt_in_renova_na_nuvem_sem_pc_e_nao_retrocede(self):
        antigo = self.preparar_ponte()
        with nuvem.SessionLocal() as db:
            db.add(emissao.EmissaoNuvem(loja="LOJA-1", habilitada_em=central.agora()))
            db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").update({"licenca_ate": (date.today()+timedelta(days=50)).isoformat()})
            db.commit()
        with patch.object(nuvem, "semente_licenca", return_value=SEMENTE), patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA):
            r = self.http.get("/v1/licenca", headers=cabecalho())
            self.assertEqual(r.status_code, 200, r.text)
            self.assertNotEqual(r.json()["codigo"], antigo)
            self.assertEqual(licenca.ler_licenca(r.json()["codigo"], bytes.fromhex(PUBLICA))["loja"], "LOJA-1")
            self.assertEqual(self.http.get("/v1/licenca", headers=cabecalho()).json(), r.json())
            with nuvem.SessionLocal() as db:
                db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").update({"licenca_ate": (date.today()+timedelta(days=5)).isoformat()})
                db.commit()
            self.assertEqual(self.http.get("/v1/licenca", headers=cabecalho()).json(), r.json())

    def test_ponte_sem_opt_in_continua_usando_codigo_local(self):
        codigo = self.preparar_ponte()
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").update({"licenca_ate": "2099-01-01"})
            db.commit()
        self.assertEqual(self.http.get("/v1/licenca", headers=cabecalho()).json()["codigo"], codigo)

    def test_manifesto_sem_assinatura_e_recusado_e_diagnostico_nao_executa_comandos(self):
        r = self.post("/atualizacoes", {"motivo": "Correção", "pacote": {"edicao": "willpdv", "canal": "estavel", "versao": "9.9.9", "sha256": "ab"*32, "tamanho": 4, "url": "https://exemplo.com/setup.exe"}})
        self.assertEqual(r.status_code, 422)
        r = self.http.get("/v1/fornecedor/lojas/LOJA-1/diagnostico")
        self.assertEqual(r.status_code, 200)
        self.assertIn("não confiáveis", r.json()["texto"])
        self.assertEqual(self.post("/lojas/LOJA-1/executar", {"comando": "qualquer"}).status_code, 404)

    def test_aprovar_caixa_credencial_unica_revogacao_e_renovacao_ponte(self):
        ident = str(uuid4())
        r = self.post("/lojas/LOJA-1/caixas", {"caixa_id": ident, "motivo": "Instalação"})
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        self.assertNotIn(token, self.http.get("/v1/fornecedor/lojas/LOJA-1").text)
        self.assertEqual(self.post("/lojas/LOJA-1/caixas", {"caixa_id": ident, "motivo": "Duplicado"}).status_code, 409)
        self.assertEqual(self.post(f"/lojas/LOJA-2/caixas/{ident}/revogar", {"motivo": "Outra loja"}).status_code, 404)
        self.preparar_ponte()
        with nuvem.SessionLocal() as db:
            db.add(emissao.EmissaoNuvem(loja="LOJA-1", habilitada_em=central.agora()))
            db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").update({"licenca_ate": (date.today()+timedelta(days=60)).isoformat()})
            db.commit()
        with patch.object(nuvem, "semente_licenca", return_value=SEMENTE), patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA):
            r = self.http.get("/v1/ponte/licenca", headers={"Authorization": "Bearer " + token})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["expira_em"], (date.today()+timedelta(days=60)).isoformat())
        self.assertEqual(self.post(f"/lojas/LOJA-1/caixas/{ident}/revogar", {"motivo": "Troca de PC"}).status_code, 200)
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers={"Authorization": "Bearer " + token}).status_code, 403)


@unittest.skipIf(TestClient is None, "Dependências da nuvem ausentes")
class TesteProgramaDaLojaECorrecoes(TesteCentralFornecedor):
    """Correções da revisão: programa da loja na licença da nuvem, limites da validade e login sem bloqueio geral."""

    def chave(self):
        return patch.object(nuvem, "semente_licenca", return_value=SEMENTE), patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA)

    def ponte_da_edicao(self, edicao, dias=20):
        codigo = licenca.gerar_licenca(SEMENTE, "LOJA-1", dias, date.today(), edicao)
        with nuvem.SessionLocal() as db:
            db.add(ponte.PonteLoja(chave_loja="LOJA-1", modo_ponte=True, ativado_em=central.agora()))
            db.add(ponte.PonteLicenca(id=str(uuid4()), chave_loja="LOJA-1", codigo=codigo,
                                     emitida_em=date.today().isoformat(),
                                     expira_em=(date.today() + timedelta(days=dias)).isoformat(),
                                     publicada_em=central.agora()))
            db.commit()
        return codigo

    def validade(self, dias):
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").update(
                {"licenca_ate": (date.today() + timedelta(days=dias)).isoformat()})
            db.commit()

    def edicao(self, codigo):
        return licenca.ler_licenca(codigo, bytes.fromhex(PUBLICA))["edicao"]

    def test_loja_will_adega_recebe_licenca_da_will_adega_pelo_caminho_antigo(self):
        r = self.post("/lojas/LOJA-1/alterar", {"motivo": "Vendida a Will Adega", "nome": "Loja 1", "ativa": True,
                                                "edicao": "willadega"})
        self.assertEqual(r.status_code, 200, r.text)
        loja = next(l for l in self.http.get("/v1/fornecedor/lojas").json()["lojas"] if l["chave"] == "LOJA-1")
        self.assertEqual(loja["edicao"], "willadega")
        self.validade(30)
        a, b = self.chave()
        with a, b:
            codigo = self.http.get("/v1/licenca", headers=cabecalho()).json()["codigo"]
            emitido = self.post("/lojas/LOJA-1/emitir-licenca", {"motivo": "Instalação"}).json()
        self.assertEqual(self.edicao(codigo), "willadega")
        self.assertEqual((self.edicao(emitido["codigo"]), emitido["programa"]), ("willadega", "Will Adega"))
        self.assertEqual(self.post("/lojas/LOJA-1/alterar", {"motivo": "x", "nome": "Loja 1", "ativa": True,
                                                              "edicao": "boate"}).status_code, 422)

    def test_cadastro_escolhe_o_programa_e_sem_escolha_e_willpdv(self):
        self.assertEqual(self.post("/lojas", {"chave": "ADEGA-9", "nome": "Adega", "motivo": "Venda",
                                              "edicao": "willadega"}).status_code, 200)
        self.assertEqual(self.post("/lojas", {"chave": "BOATE-9", "nome": "Boate", "motivo": "Venda"}).status_code, 200)
        r = self.http.get("/v1/fornecedor/lojas").json()
        programas = {l["chave"]: l["edicao"] for l in r["lojas"]}
        self.assertEqual((programas["ADEGA-9"], programas["BOATE-9"]), ("willadega", "willpdv"))
        self.assertIn({"chave": "willadega", "nome": "Will Adega"}, r["edicoes"])
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja.in_(["ADEGA-9", "BOATE-9"])).delete(synchronize_session=False)
            db.commit()

    def test_migracao_herda_o_programa_do_codigo_local_e_renova_com_ele(self):
        self.ponte_da_edicao("willadega")
        a, b = self.chave()
        with a, b:
            r = self.post("/lojas/LOJA-1/migrar-emissao", {"confirmacao": "LOJA-1", "motivo": "Transferência"})
            self.assertEqual(r.status_code, 200, r.text)
            self.validade(50)                                  # pagamento confirmado estende
            novo = self.http.get("/v1/licenca", headers=cabecalho()).json()
        self.assertEqual(novo["expira_em"], (date.today() + timedelta(days=50)).isoformat())
        self.assertEqual(self.edicao(novo["codigo"]), "willadega")

    def test_migracao_recusa_programa_divergente(self):
        self.ponte_da_edicao("willadega")
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").update({"edicao": "willpdv"})
            db.commit()
        a, b = self.chave()
        with a, b:
            r = self.post("/lojas/LOJA-1/migrar-emissao", {"confirmacao": "LOJA-1", "motivo": "Transferência"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Will Adega", r.json()["detail"])
        with nuvem.SessionLocal() as db:
            self.assertIsNone(db.get(emissao.EmissaoNuvem, "LOJA-1"))

    def test_validade_manual_nao_reduz_nem_passa_de_cem_anos(self):
        self.validade(60)
        curta = (date.today() + timedelta(days=1)).isoformat()
        r = self.post("/lojas/LOJA-1/assinatura-manual", {"validade": curta, "motivo": "erro de digitação"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("não reduz", r.json()["detail"])
        r = self.post("/lojas/LOJA-1/assinatura-manual", {"validade": "2200-01-01", "motivo": "permanente"})
        self.assertEqual(r.status_code, 422)
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").one().licenca_ate,
                             (date.today() + timedelta(days=60)).isoformat())

    def test_validade_alem_do_limite_ja_gravada_nao_derruba_a_consulta(self):
        self.validade(40000)                                   # gravada por versão anterior ou à mão no banco
        a, b = self.chave()
        with a, b:
            r = self.http.get("/v1/licenca", headers=cabecalho())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["expira_em"], (date.today() + timedelta(days=licenca.MAX_DIAS)).isoformat())

    def test_sem_chave_na_nuvem_o_caixa_continua_com_o_codigo_atual(self):
        antigo = self.preparar_ponte()
        a, b = self.chave()
        with a, b:
            self.assertEqual(self.post("/lojas/LOJA-1/migrar-emissao",
                                       {"confirmacao": "LOJA-1", "motivo": "x"}).status_code, 200)
        self.validade(90)
        r = self.http.get("/v1/licenca", headers=cabecalho())    # chave sumiu da nuvem (semente None no setUp)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["codigo"], antigo)

    def test_login_nao_bloqueia_todo_mundo_quando_a_memoria_enche(self):
        with central._trava:
            for i in range(2500):
                central._tentativas[f"10.0.{i // 250}.{i % 250}"].append(central.time.monotonic())
        self.http.cookies.clear()
        self.login()
        self.assertLessEqual(len(central._tentativas), 2000)

    def test_cadastro_devolve_codigo_de_instalacao_que_funciona(self):
        from src.core import codigo_instalacao
        r = self.post("/lojas", {"chave": "ADEGA-7", "nome": "Adega 7", "motivo": "Venda", "edicao": "willadega"}).json()
        dados = codigo_instalacao.ler(r["codigo_instalacao"])
        self.assertEqual(dados, {"url": "https://testserver", "chave": "ADEGA-7", "token": r["token"]})
        self.assertNotEqual(self.http.get("/v1/licenca", headers={"Authorization": "Bearer " + r["token"]}).status_code, 401)
        with patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://willpdv-nuvem-6sp0.onrender.com/"}):
            r = self.post("/lojas/ADEGA-7/novo-token", {"motivo": "PC novo", "confirmacao": "ADEGA-7"}).json()
        self.assertEqual(codigo_instalacao.ler(r["codigo_instalacao"])["url"], "https://willpdv-nuvem-6sp0.onrender.com")
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter_by(chave_loja="ADEGA-7").delete()
            db.commit()

    def test_novo_token_exige_confirmacao_e_derruba_o_antigo(self):
        self.assertEqual(self.post("/lojas/LOJA-1/novo-token", {"motivo": "x", "confirmacao": "LOJA-2"}).status_code, 422)
        self.assertNotEqual(self.http.get("/v1/licenca", headers=cabecalho()).status_code, 401)
        r = self.post("/lojas/LOJA-1/novo-token", {"motivo": "Token vazou", "confirmacao": "LOJA-1"})
        self.assertEqual(r.status_code, 200, r.text)
        novo = r.json()["token"]
        self.assertEqual(self.http.get("/v1/licenca", headers=cabecalho()).status_code, 401)
        self.assertNotEqual(self.http.get("/v1/licenca", headers={"Authorization": "Bearer " + novo}).status_code, 401)
        eventos = self.http.get("/v1/fornecedor/auditoria").json()["eventos"]
        self.assertEqual(eventos[0]["acao"], "novo_token")
        self.assertNotIn(novo, json.dumps(eventos))

    def test_senha_do_painel_do_dono_sem_terminal(self):
        from backend import painel
        r = self.post("/lojas/LOJA-1/senha-painel", {"motivo": "Dono pediu"})
        self.assertEqual(r.status_code, 200, r.text)
        senha = r.json()["senha"]
        with nuvem.SessionLocal() as db:
            guardado = db.query(painel.PainelAcesso).filter_by(chave_loja="LOJA-1").one().senha_hash
        self.assertTrue(painel.conferir_senha(senha, guardado))
        self.assertNotIn(senha, json.dumps(self.http.get("/v1/fornecedor/auditoria").json()))
        self.assertEqual(self.post("/lojas/NAO-EXISTE/senha-painel", {"motivo": "x"}).status_code, 404)

    def test_kit_de_implantacao_com_instalador_codigo_qr_e_senha(self):
        from backend import painel
        from src.core import codigo_instalacao
        self.post("/lojas/LOJA-1/alterar", {"motivo": "Adega", "nome": "Adega do Zé", "ativa": True, "edicao": "willadega"})
        self.assertEqual(self.post("/lojas/LOJA-1/kit", {"motivo": "x", "confirmacao": "LOJA-2"}).status_code, 422)
        r = self.post("/lojas/LOJA-1/kit", {"motivo": "Implantação", "confirmacao": "LOJA-1"})
        self.assertEqual(r.status_code, 200, r.text)
        kit = r.json()
        self.assertTrue(kit["qr_instalacao"].startswith("<svg"))
        self.assertIn("ultima-versao-adega/WillAdega-Instalador.exe", kit["kit"])
        self.assertIn("KIT DE IMPLANTAÇÃO — Will Adega", kit["kit"])
        self.assertIn(kit["codigo_instalacao"], kit["kit"])
        self.assertIn(f"Senha: {kit['senha_painel']}", kit["kit"])
        self.assertIn("NÃO FISCAL", kit["kit"])
        self.assertIn("https://testserver/painel/", kit["kit"])
        novo = codigo_instalacao.ler(kit["codigo_instalacao"])["token"]
        self.assertEqual(self.http.get("/v1/licenca", headers=cabecalho()).status_code, 401)         # token antigo caiu
        self.assertNotEqual(self.http.get("/v1/licenca", headers={"Authorization": "Bearer " + novo}).status_code, 401)
        with nuvem.SessionLocal() as db:
            guardado = db.query(painel.PainelAcesso).filter_by(chave_loja="LOJA-1").one().senha_hash
        self.assertTrue(painel.conferir_senha(kit["senha_painel"], guardado))
        auditoria = json.dumps(self.http.get("/v1/fornecedor/auditoria").json())
        self.assertIn("kit_implantacao", auditoria)
        self.assertNotIn(kit["senha_painel"], auditoria)
        self.assertNotIn(novo, auditoria)
        with patch.dict(os.environ, {"PDV_INSTALADOR_WILLADEGA": "https://downloads.exemplo/adega.exe"}):
            r = self.post("/lojas/LOJA-1/kit", {"motivo": "Outro PC", "confirmacao": "LOJA-1"}).json()
        self.assertEqual(r["instalador"], "https://downloads.exemplo/adega.exe")

    def test_qr_no_cadastro_e_politica_de_imagem(self):
        r = self.post("/lojas", {"chave": "ADEGA-8", "nome": "Adega 8", "motivo": "Venda", "edicao": "willadega"})
        self.assertTrue(r.json()["qr_instalacao"].startswith("<svg"))
        self.assertIn("img-src 'self' data:", self.http.get("/central/").headers["content-security-policy"])
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter_by(chave_loja="ADEGA-8").delete()
            db.commit()

    def test_assinar_ate_limita_a_cem_anos(self):
        codigo, expira = emissao.assinar_ate(SEMENTE, "LOJA-1", date(2400, 1, 1), "willadega", date(2026, 11, 6))
        self.assertEqual(expira, (date(2026, 11, 6) + timedelta(days=licenca.MAX_DIAS)).isoformat())
        self.assertEqual(self.edicao(codigo), "willadega")


for _nome in [n for n in dir(TesteCentralFornecedor) if n.startswith("test_")]:
    if _nome not in TesteProgramaDaLojaECorrecoes.__dict__:
        setattr(TesteProgramaDaLojaECorrecoes, _nome, None)      # os testes da base já rodam na classe deles
