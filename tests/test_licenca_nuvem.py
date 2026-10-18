"""Renovação automática da licença: a nuvem emite o código até a data paga e o PDV o aplica sozinho."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from unittest import mock

from src.core import ed25519, licenca
from src.database.conexao import BancoDados
from src.sync import licenca_nuvem
from src.sync.sincronizador import Sincronizador
from tests.base import BaseTeste
from tests.test_atualizacoes import HttpFalso, Resposta
from tests.test_nuvem import ADMIN, TOKENS, TestClient, cabecalho, lojas, nuvem, preparar_lojas

SEMENTE = bytes(range(32))
PUBLICA = ed25519.chave_publica(SEMENTE).hex()


class BaseChave(unittest.TestCase):
    """Chave do fornecedor de teste: em arquivo (como na nuvem) e como a chave pública embutida no PDV."""

    def setUp(self):
        super().setUp()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.arquivo_chave = os.path.join(pasta.name, "licenca_privada.key")
        with open(self.arquivo_chave, "w", encoding="ascii") as f:
            f.write(SEMENTE.hex() + "\n")
        for alvo in (mock.patch.dict(os.environ, {"PDV_LICENCA_CHAVE": self.arquivo_chave}),
                     mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA)):
            alvo.start()
            self.addCleanup(alvo.stop)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteEmissaoNaNuvem(BaseChave):
    def setUp(self):
        super().setUp()
        preparar_lojas()
        self.db = nuvem.SessionLocal()
        self.addCleanup(self.db.close)
        self.http = TestClient(nuvem.app)

    def pedir(self, headers=None):
        return self.http.get("/v1/licenca", headers=cabecalho() if headers is None else headers)

    def test_emite_ate_a_data_paga_para_a_loja_do_token(self):
        ate = date.today() + timedelta(days=30)
        lojas.definir_assinatura(self.db, "LOJA-1", ate)
        r = self.pedir()
        self.assertEqual(r.status_code, 200, r.text)
        lic = licenca.ler_licenca(r.json()["codigo"])
        self.assertEqual((lic["loja"], lic["expira_em"]), ("LOJA-1", ate))

    def test_sem_assinatura_vencida_ou_de_administrador_nao_emite(self):
        self.assertEqual(self.pedir().status_code, 404)
        lojas.definir_assinatura(self.db, "LOJA-1", date.today())
        self.assertEqual(self.pedir().status_code, 409)
        self.assertEqual(self.pedir(ADMIN).status_code, 403)
        lojas.definir_assinatura(self.db, "LOJA-1", None)                    # cancelada
        self.assertEqual(self.pedir().status_code, 404)

    def test_sem_a_chave_certa_do_fornecedor_nao_emite(self):
        lojas.definir_assinatura(self.db, "LOJA-1", date.today() + timedelta(days=30))
        with mock.patch.dict(os.environ, {"PDV_LICENCA_CHAVE": self.arquivo_chave + ".nao-existe"}):
            self.assertEqual(self.pedir().status_code, 503)
        with mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", "00" * 32):    # chave do PDV é outra
            self.assertEqual(self.pedir().status_code, 503)

    def test_linha_de_comando(self):
        saida = io.StringIO()
        with mock.patch.object(lojas, "SessionLocal", return_value=self.db), mock.patch.object(self.db, "close"), \
                redirect_stdout(saida):
            self.assertEqual(lojas.main(["assinatura", "LOJA-1", "2030-01-31"]), 0)
            self.assertEqual(lojas.main(["listar"]), 0)
            self.assertEqual(lojas.main(["assinatura", "LOJA-1", "31/01/2030"]), 1)
            self.assertEqual(lojas.main(["assinatura", "LOJA-1", "cancelar"]), 0)
        self.assertIn("paga até 31/01/2030", saida.getvalue())

    def test_listar_avisa_assinatura_vencida_ou_perto_de_vencer(self):
        from datetime import date
        from backend.lojas import situacao_assinatura
        hoje = date(2026, 10, 4)
        self.assertEqual(situacao_assinatura(None, hoje), "sem assinatura")
        self.assertEqual(situacao_assinatura("2026-10-03", hoje), "paga até 03/10/2026 (VENCIDA)")
        self.assertEqual(situacao_assinatura("2026-10-05", hoje), "paga até 05/10/2026 (vence em 1 dia)")
        self.assertEqual(situacao_assinatura("2026-10-09", hoje), "paga até 09/10/2026 (vence em 5 dias)")
        self.assertEqual(situacao_assinatura("2026-11-30", hoje), "paga até 30/11/2026")
        self.db.expire_all()
        self.assertIsNone(self.db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").one().licenca_ate)

    def test_o_pdv_renova_com_o_codigo_da_nuvem(self):
        banco = BancoDados(":memory:")                                      # relógio real: a nuvem usa a data de hoje
        self.addCleanup(banco.fechar)
        banco.cfg_set("licenca_exigir", "S")
        banco.cfg_set("api_url", "https://nuvem/v1/sincronizar")
        banco.cfg_set("api_token", TOKENS["LOJA-1"])
        ate = date.today() + timedelta(days=30)
        lojas.definir_assinatura(self.db, "LOJA-1", ate)
        http = mock.Mock()
        http.get = lambda url, **kw: self.http.get(url.replace("https://nuvem", ""), **kw)
        self.assertTrue(licenca_nuvem.renovar(banco, http))
        self.assertEqual(licenca.estado(banco).expira_em, ate)
        self.assertEqual(banco.cfg("chave_loja"), "LOJA-1")


class TesteRenovacaoNoPDV(BaseTeste, BaseChave):
    def setUp(self):
        BaseTeste.setUp(self)
        BaseChave.setUp(self)
        self.banco.cfg_set("licenca_exigir", "S")
        self.banco.cfg_set("api_url", "https://nuvem/v1/sincronizar")
        self.banco.cfg_set("api_token", "tok")

    def codigo(self, dias, loja="LOJA-1"):
        return licenca.gerar_licenca(SEMENTE, loja, dias, date(2026, 10, 3))

    def http(self, codigo):
        return HttpFalso(Resposta(200, {"codigo": codigo}))

    def test_renova_quando_estende_e_ignora_o_resto(self):
        self.assertTrue(licenca_nuvem.aplicar(self.banco, self.codigo(30)))
        self.assertFalse(licenca_nuvem.aplicar(self.banco, self.codigo(30)))      # o mesmo código
        self.assertFalse(licenca_nuvem.aplicar(self.banco, self.codigo(10)))      # mais curto
        self.assertFalse(licenca_nuvem.aplicar(self.banco, self.codigo(60, "OUTRA")))
        self.assertFalse(licenca_nuvem.aplicar(self.banco, "lixo"))
        self.assertFalse(licenca_nuvem.aplicar(self.banco, None))
        self.assertTrue(licenca_nuvem.aplicar(self.banco, self.codigo(60)))
        self.assertEqual(licenca.estado(self.banco).expira_em, date(2026, 12, 2))

    def test_consulta_a_cada_seis_horas_e_so_com_licenca_exigida(self):
        http = self.http(self.codigo(30))
        self.assertTrue(licenca_nuvem.renovar(self.banco, http))
        self.avancar(hours=5)
        licenca_nuvem.renovar(self.banco, http)
        self.assertEqual(len(http.chamadas), 1)
        self.assertFalse(licenca_nuvem.renovar(self.banco, self.http(self.codigo(30)), forcar=True))   # já tem esse
        self.banco.cfg_set("licenca_exigir", "N")
        sem = self.http(self.codigo(90))
        self.assertFalse(licenca_nuvem.renovar(self.banco, sem, forcar=True))
        self.assertEqual(sem.chamadas, [])

    def test_endereco_e_falhas(self):
        self.assertEqual(licenca_nuvem.url_licenca("https://n/v1/sincronizar"), "https://n/v1/licenca")
        for ruim in (OSError("sem rede"), Resposta(404, {"detail": "x"}), Resposta(200, ValueError()), Resposta(200, {})):
            with self.subTest(ruim=ruim):
                self.assertFalse(licenca_nuvem.renovar(self.banco, HttpFalso(ruim), forcar=True))

    def test_falha_de_rede_repete_em_minutos_progressivos_e_sucesso_reinicia_intervalo(self):
        http = HttpFalso(OSError("sem rede"))
        for intervalo in licenca_nuvem.RETENTATIVAS_MINUTOS:
            self.assertFalse(licenca_nuvem.renovar(self.banco, http))
            chamadas = len(http.chamadas)
            self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_CONSULTA), "")
            self.assertTrue(self.banco.cfg(licenca_nuvem.CHAVE_TENTATIVA))
            licenca_nuvem.renovar(self.banco, http)
            self.assertEqual(len(http.chamadas), chamadas)
            self.avancar(minutes=intervalo)
        bom = self.http(self.codigo(30))
        self.assertTrue(licenca_nuvem.renovar(self.banco, bom))
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_FALHAS), "0")
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_CONSULTA), self._hora["t"].strftime("%Y-%m-%d %H:%M:%S"))
        self.avancar(hours=5)
        self.assertFalse(licenca_nuvem.renovar(self.banco, bom))
        self.assertEqual(len(bom.chamadas), 1)
        self.avancar(hours=1)
        self.assertFalse(licenca_nuvem.renovar(self.banco, bom))
        self.assertEqual(len(bom.chamadas), 2)

    def test_falha_nao_substitui_horario_do_sucesso_e_nao_espera_seis_horas(self):
        bom = self.http(self.codigo(30))
        licenca_nuvem.renovar(self.banco, bom)
        ultimo_sucesso = self.banco.cfg(licenca_nuvem.CHAVE_CONSULTA)
        self.avancar(minutes=1)
        ruim = HttpFalso(OSError("sem rede"))
        licenca_nuvem.renovar(self.banco, ruim, forcar=True)
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_CONSULTA), ultimo_sucesso)
        self.avancar(minutes=1)
        licenca_nuvem.renovar(self.banco, ruim)
        self.assertEqual(len(ruim.chamadas), 2)

    def test_sem_assinatura_e_consulta_bem_sucedida_mas_erro_servidor_nao(self):
        for status in (404, 409):
            with self.subTest(status=status):
                http = HttpFalso(Resposta(status, {}))
                self.assertFalse(licenca_nuvem.renovar(self.banco, http, forcar=True))
                self.assertTrue(self.banco.cfg(licenca_nuvem.CHAVE_CONSULTA))
                self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_FALHAS), "0")
                self.avancar(minutes=30)
                self.assertFalse(licenca_nuvem.renovar(self.banco, http))
                self.assertEqual(len(http.chamadas), 1)
        http = HttpFalso(Resposta(503, {}))
        licenca_nuvem.renovar(self.banco, http, forcar=True)
        self.avancar(minutes=1)
        licenca_nuvem.renovar(self.banco, http)
        self.assertEqual(len(http.chamadas), 2)

    def test_consultar_preserva_api_codigo_ou_none(self):
        codigo = self.codigo(30)
        self.assertEqual(licenca_nuvem.consultar("https://nuvem/v1", "tok", self.http(codigo)), codigo)
        self.assertIsNone(licenca_nuvem.consultar("https://nuvem/v1", "tok", HttpFalso(OSError("sem rede"))))

    def test_indicador_preserva_ultimo_sucesso_e_mostra_erro_ate_novo_sucesso(self):
        licenca_nuvem.renovar(self.banco, self.http(self.codigo(30)))
        sucesso = self.banco.cfg("licenca_nuvem_sucesso_em")
        self.assertTrue(sucesso)
        self.assertEqual(sucesso, self.banco.cfg(licenca_nuvem.CHAVE_CONSULTA))
        self.assertEqual(self.banco.cfg("licenca_nuvem_erro"), "")
        self.avancar(minutes=1)
        licenca_nuvem.renovar(self.banco, HttpFalso(OSError("sem rede")), forcar=True)
        self.assertEqual(self.banco.cfg("licenca_nuvem_sucesso_em"), sucesso)
        self.assertIn("sem rede", self.banco.cfg("licenca_nuvem_erro"))
        self.avancar(minutes=1)
        licenca_nuvem.renovar(self.banco, HttpFalso(Resposta(503, {})))
        self.assertEqual(self.banco.cfg("licenca_nuvem_erro"), "HTTP 503")
        licenca_nuvem.renovar(self.banco, HttpFalso(Resposta(404, {})), forcar=True)
        self.assertNotEqual(self.banco.cfg("licenca_nuvem_sucesso_em"), sucesso)
        self.assertEqual(self.banco.cfg("licenca_nuvem_erro"), "")

    def test_erros_de_gravacao_e_aplicacao_nao_sao_silenciados(self):
        with mock.patch.object(self.banco, "cfg_set", side_effect=OSError("disco cheio")):
            with self.assertRaisesRegex(OSError, "disco cheio"):
                licenca_nuvem.renovar(self.banco, self.http(self.codigo(30)), forcar=True)
        with mock.patch.object(licenca_nuvem, "aplicar", side_effect=RuntimeError("falha ao ativar")):
            with self.assertRaisesRegex(RuntimeError, "falha ao ativar"):
                licenca_nuvem.renovar(self.banco, self.http(self.codigo(30)), forcar=True)

    def test_a_sincronizacao_renova(self):
        self.banco.cfg_set("chave_loja", "LOJA-1")
        Sincronizador(self.banco, self.http(self.codigo(30))).iniciar_loop(rodadas=1, dormir=lambda s: None)
        self.assertEqual(licenca.estado(self.banco).expira_em, date(2026, 11, 2))


if __name__ == "__main__":
    unittest.main()
