"""Dono com várias lojas: vincular pela senha, ver o resumo de todas e trocar de loja no mesmo painel."""
import unittest

from tests.test_painel_dono import BaseNuvem, TestClient, cabecalho, nuvem, painel

try:
    from backend import painel_lojas
except (ImportError, RuntimeError):
    painel_lojas = None


@unittest.skipIf(TestClient is None or painel_lojas is None, "fastapi/httpx não instalados")
class TesteVariasLojas(BaseNuvem):
    def setUp(self):
        super().setUp()
        with nuvem.SessionLocal() as db:
            db.query(painel_lojas.PainelGrupo).delete()
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja == "ADEGA-3").delete()
            db.add(nuvem.Loja(chave_loja="ADEGA-3", nome="Adega 3", token_hash=nuvem.hash_token("token-adega-3"), ativa=True))
            db.commit()
            painel.definir_senha(db, "ADEGA-2", "senha-forte-2")
            painel.definir_senha(db, "ADEGA-3", "senha-forte-3")
        for chave in ("ADEGA-2", "ADEGA-3"):
            painel.tentativas.acertou(chave)
        self.addCleanup(self._limpar)
        self.dono = self.entrar()

    def _limpar(self):
        with nuvem.SessionLocal() as db:
            db.query(painel_lojas.PainelGrupo).delete()
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja == "ADEGA-3").delete()
            db.commit()

    def lojas(self, sessao=None):
        r = self.http.get("/v1/painel/lojas", headers=sessao or self.dono)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def vincular(self, loja="ADEGA-2", senha="senha-forte-2", sessao=None):
        return self.http.post("/v1/painel/lojas/vincular", json={"loja": loja, "senha": senha}, headers=sessao or self.dono)

    def trocar(self, loja, sessao=None):
        return self.http.post("/v1/painel/lojas/trocar", json={"loja": loja}, headers=sessao or self.dono)

    def test_dono_de_uma_loja_ve_so_a_sua(self):
        dados = self.lojas()
        self.assertEqual([(l["chave"], l["atual"]) for l in dados["lojas"]], [("ADEGA-1", True)])
        self.assertEqual(dados["total"], {"hoje_cent": 0, "vendas_hoje": 0, "mes_cent": 0})

    def test_vincular_exige_a_senha_da_outra_loja(self):
        for corpo, status in (({"loja": "ADEGA-2", "senha": "errada"}, 403), ({"loja": "NAO-EXISTE", "senha": "x"}, 403),
                              ({"loja": "ADEGA-2"}, 422), ({"senha": "x"}, 422), ({"loja": "ADEGA-1", "senha": "senha-forte-1"}, 409)):
            r = self.http.post("/v1/painel/lojas/vincular", json=corpo, headers=self.dono)
            self.assertEqual(r.status_code, status, corpo)
        self.assertEqual(len(self.lojas()["lojas"]), 1)
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=self.dono).status_code, 200)   # senha errada não gasta a sessão
        self.assertEqual(self.http.post("/v1/painel/lojas/vincular", json={"loja": "ADEGA-2", "senha": "senha-forte-2"}).status_code, 401)
        self.assertEqual(self.vincular(sessao=cabecalho()).status_code, 401)            # token do caixa não é sessão do dono

    def test_muitas_senhas_erradas_bloqueiam_o_vinculo_como_no_login(self):
        for _ in range(8):
            self.vincular(senha="errada")
        self.assertEqual(self.vincular().status_code, 429)
        painel.tentativas.acertou("ADEGA-2")

    def test_vinculadas_aparecem_juntas_com_os_numeros_de_cada_uma_e_o_total(self):
        self.venda_fechada((self.skol, 2))                                              # R$ 16,00 na ADEGA-1
        self.subir()
        r = self.vincular()
        self.assertEqual(r.status_code, 200, r.text)
        dados = r.json()
        self.assertEqual([(l["chave"], l["nome"], l["atual"]) for l in dados["lojas"]],
                         [("ADEGA-1", "Adega 1", True), ("ADEGA-2", "Adega 2", False)])
        uma, duas = dados["lojas"]
        self.assertEqual((uma["hoje_cent"], uma["vendas_hoje"], uma["mes_cent"], uma["dia"]), (1600, 1, 1600, "2026-10-03"))
        self.assertEqual((duas["hoje_cent"], duas["mes_cent"], duas["atualizado_em"]), (0, 0, None))
        self.assertEqual(dados["total"], {"hoje_cent": 1600, "vendas_hoje": 1, "mes_cent": 1600})
        self.assertEqual(self.vincular().status_code, 409)                              # já está no painel
        outro_lado = self.lojas(self.entrar("ADEGA-2", "senha-forte-2"))               # o vínculo vale dos dois lados
        self.assertEqual([(l["chave"], l["atual"]) for l in outro_lado["lojas"]], [("ADEGA-2", True), ("ADEGA-1", False)])

    def test_trocar_abre_sessao_da_outra_loja_e_encerra_a_atual(self):
        self.venda_fechada((self.skol, 1))
        self.subir()
        self.vincular()
        r = self.trocar("ADEGA-2")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["loja"], {"chave": "ADEGA-2", "nome": "Adega 2"})
        nova = {"Authorization": f"Bearer {r.json()['token']}"}
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=self.dono).status_code, 401)   # a sessão antiga acabou
        resumo = self.http.get("/v1/painel/resumo", headers=nova).json()
        self.assertEqual(resumo["loja"]["chave"], "ADEGA-2")
        self.assertEqual(resumo["vendas"]["faturamento_cent"], 0)                        # números da ADEGA-2, não da 1
        volta = self.trocar("ADEGA-1", nova)
        self.assertEqual(volta.json()["loja"]["chave"], "ADEGA-1")

    def test_nao_troca_para_loja_fora_do_grupo_nem_desativada(self):
        self.assertEqual(self.trocar("ADEGA-2").status_code, 404)
        self.assertEqual(self.trocar("ADEGA-1").status_code, 404)                        # já é a atual
        self.assertEqual(self.trocar("").status_code, 404)
        self.vincular()
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter_by(chave_loja="ADEGA-2").update({"ativa": False})
            db.commit()
        self.assertEqual(self.trocar("ADEGA-2").status_code, 404)
        self.assertEqual([l["chave"] for l in self.lojas()["lojas"]], ["ADEGA-1"])       # desativada some da lista
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=self.dono).status_code, 200)   # a sessão não foi gasta

    def test_tres_lojas_juntam_os_grupos_e_remover_separa(self):
        self.vincular()
        tres = self.entrar("ADEGA-3", "senha-forte-3")
        self.assertEqual(self.vincular("ADEGA-1", "senha-forte-1", tres).status_code, 200)   # entra no grupo que já existia
        self.assertEqual([l["chave"] for l in self.lojas()["lojas"]], ["ADEGA-1", "ADEGA-2", "ADEGA-3"])
        self.assertEqual(self.http.delete("/v1/painel/lojas/ADEGA-1", headers=self.dono).status_code, 409)   # a atual não sai
        self.assertEqual(self.http.delete("/v1/painel/lojas/OUTRA", headers=self.dono).status_code, 404)
        r = self.http.delete("/v1/painel/lojas/ADEGA-3", headers=self.dono)
        self.assertEqual([l["chave"] for l in r.json()["lojas"]], ["ADEGA-1", "ADEGA-2"])
        self.assertEqual([l["chave"] for l in self.lojas(tres)["lojas"]], ["ADEGA-3"])
        self.assertEqual(self.trocar("ADEGA-1", tres).status_code, 404)
        self.http.delete("/v1/painel/lojas/ADEGA-2", headers=self.dono)
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(painel_lojas.PainelGrupo).count(), 0)              # grupo de uma loja só deixa de existir

    def test_painel_reune_no_maximo_o_limite_de_lojas(self):
        from unittest import mock
        self.vincular()
        with mock.patch.object(painel_lojas, "MAXIMO_LOJAS", 2):
            cheio = self.vincular("ADEGA-3", "senha-forte-3")
        self.assertEqual(cheio.status_code, 409)
        self.assertIn("no máximo 2 lojas", cheio.json()["detail"])
