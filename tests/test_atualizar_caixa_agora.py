"""Botão "Atualizar o caixa agora" da central: pedido na memória da nuvem, caixa instala sem esperar o turno fechar."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.memoria_nuvem import MemoriaNuvem
from src.atualizacao import cliente
from src.core import formatacao as fmt
from src.sync import sincronizador as sinc
from tests.test_caixa import BaseCaixa
from tests.test_nuvem import TOKENS, TestClient, cabecalho, nuvem, preparar_lojas


class TesteMemoria(unittest.TestCase):
    def test_pedido_aparece_so_para_a_loja_e_o_numero_sobe(self):
        m = MemoriaNuvem()
        m.lembrar_token("t1", "LOJA-1")
        m.lembrar_token("t2", "LOJA-2")
        self.assertNotIn("atualizar", m.consultar_loja("t1"))
        primeiro = m.pedir_atualizacao("LOJA-1")
        self.assertEqual(m.consultar_loja("t1")["atualizar"], primeiro)
        self.assertNotIn("atualizar", m.consultar_loja("t2"))
        self.assertGreater(m.pedir_atualizacao("LOJA-1"), primeiro)

    def test_pedido_vence(self):
        import backend.memoria_nuvem as mod
        m = MemoriaNuvem()
        m.lembrar_token("t1", "LOJA-1")
        m.pedir_atualizacao("LOJA-1")
        with patch.object(mod, "TTL_ATUALIZAR_SEG", -1):
            self.assertNotIn("atualizar", m.consultar_loja("t1"))


class _Resposta:
    status_code = 200

    def __init__(self, dados):
        self._dados = dados

    def json(self):
        return self._dados


class TesteCaixa(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.banco.cfg_set("api_token", "token-x")
        self.http = Mock()
        self.http.get.return_value = _Resposta({"conhecido": True, "pedido": False, "atualizar": 1700000000})
        self.s = sinc.Sincronizador(self.banco, http=self.http)

    def test_imediata_instala_com_turno_aberto_mas_nao_com_venda_aberta(self):
        self.banco.cfg_set(cliente.CHAVE_CONSULTA, fmt.agora())
        cliente._gravar_estado(self.banco, {"versao": "99.0.0", "arquivo": "/pacote.exe"})
        cliente.adiar(self.banco, "99.0.0")
        instalar = Mock()
        self.assertEqual(cliente.rodada(self.banco, instalar=instalar)["acao"], "adiada")
        self.vender((self.skol, 1))
        resultado = cliente.rodada(self.banco, instalar=instalar, imediata=True)
        self.assertEqual(resultado["acao"], "esperar")
        self.assertIn("aberta", resultado["motivo"])
        self.banco.executar("UPDATE vendas SET status = 'cancelada' WHERE status = 'aberta'")
        self.assertTrue(self.banco.valor("SELECT COUNT(*) FROM turnos WHERE status = 'aberto'", (), 0))
        self.assertEqual(cliente.rodada(self.banco, instalar=instalar, imediata=True)["acao"], "instalar")
        instalar.assert_called_once()

    def test_pedido_da_central_consulta_na_hora_e_nao_repete(self):
        self.s._pedido_remoto()
        self.assertEqual(self.banco.cfg(sinc.CHAVE_ATUALIZAR_PENDENTE), "1700000000")
        with patch("src.atualizacao.cliente.rodada", return_value={"acao": "instalar"}) as rodada:
            self.s._atualizar_se_pedido()
        self.assertTrue(rodada.call_args.kwargs["forcar"])
        self.assertTrue(rodada.call_args.kwargs["imediata"])
        self.assertEqual(self.banco.cfg(sinc.CHAVE_ATUALIZAR_PENDENTE), "")
        self.assertEqual(self.banco.cfg(sinc.CHAVE_ATUALIZAR_ATENDIDO), "1700000000")
        self.s._ultima_sonda = 0
        self.s._pedido_remoto()                                  # o mesmo pedido ainda está na nuvem
        self.assertEqual(self.banco.cfg(sinc.CHAVE_ATUALIZAR_PENDENTE), "")

    def test_venda_aberta_mantem_o_pedido_sem_consultar_de_novo(self):
        self.s._pedido_remoto()
        with patch("src.atualizacao.cliente.rodada", return_value={"acao": "esperar", "motivo": "venda"}) as rodada:
            self.s._atualizar_se_pedido()
            self.s._atualizar_se_pedido()
        self.assertEqual([c.kwargs["forcar"] for c in rodada.call_args_list], [True, False])
        self.assertEqual(self.banco.cfg(sinc.CHAVE_ATUALIZAR_PENDENTE), "1700000000")

    def test_nuvem_sem_resposta_tenta_consultar_de_novo(self):
        self.s._pedido_remoto()
        with patch("src.atualizacao.cliente.rodada", return_value={"acao": "sem_resposta"}) as rodada:
            self.s._atualizar_se_pedido()
            self.s._atualizar_se_pedido()
        self.assertEqual([c.kwargs["forcar"] for c in rodada.call_args_list], [True, True])

    def test_consulta_automatica_agora_e_de_hora_em_hora(self):
        self.assertEqual(cliente.INTERVALO_HORAS, 1)


class TesteServicoDoPdvAberto(unittest.TestCase):
    def test_pdv_aberto_ouve_a_central_quando_a_sincronizacao_nao_roda_nele(self):
        import tempfile
        from pathlib import Path
        from threading import Event
        from src.atualizacao.servico import ServicoAtualizacao
        from src.database.conexao import BancoDados
        with tempfile.TemporaryDirectory() as pasta:
            caminho = str(Path(pasta) / "loja.db")
            banco = BancoDados(caminho)
            banco.cfg_set("sync_quase_tempo_real", "N")
            banco.fechar()
            ouviu = Event()
            with patch("src.atualizacao.servico.rodada"), \
                    patch.object(sinc.Sincronizador, "atender_central", side_effect=lambda *a: ouviu.set()):
                servico = ServicoAtualizacao(caminho)
                try:
                    servico.iniciar()
                    self.assertTrue(ouviu.wait(3))
                finally:
                    servico.parar()


@unittest.skipIf(TestClient is None, "Dependências da nuvem ausentes")
class TesteCentral(unittest.TestCase):
    def setUp(self):
        from backend import central_fornecedor as central
        preparar_lojas()
        with central._trava:
            central._tentativas.clear()
        self.http = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(self.http.close)
        r = self.http.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"}, headers={"X-Central-Login": "1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.csrf = r.json()["csrf"]

    def test_botao_chega_ao_caixa_da_loja_e_fica_na_auditoria(self):
        from backend import central_fornecedor as central
        loja = sorted(TOKENS)[0]
        r = self.http.post(f"/v1/fornecedor/lojas/{loja}/atualizar-agora", json={"motivo": "cliente sem tempo"},
                           headers={"X-Central-CSRF": self.csrf})
        self.assertEqual(r.status_code, 200, r.text)
        pedido = r.json()["pedido"]
        visto = self.http.get("/v1/sync/pedido", headers=cabecalho(loja)).json()
        self.assertEqual(visto.get("atualizar"), pedido)
        with nuvem.SessionLocal() as db:
            self.assertTrue(db.query(central.AuditoriaFornecedor).filter_by(acao="atualizar_caixa_agora", loja=loja).count())

    def test_sem_motivo_ou_loja_inexistente_recusa(self):
        r = self.http.post("/v1/fornecedor/lojas/NAO-EXISTE/atualizar-agora", json={"motivo": "x"},
                           headers={"X-Central-CSRF": self.csrf})
        self.assertEqual(r.status_code, 404)


@unittest.skipIf(TestClient is None, "Dependências da nuvem ausentes")
class TesteCacheVersao(unittest.TestCase):
    def test_cache_evita_o_banco_e_publicar_limpa(self):
        from backend import atualizacao_remota as ar
        ar.limpar_cache()
        self.addCleanup(ar.limpar_cache)
        with patch.object(ar, "ultima", return_value=None) as ultima:
            self.assertIsNone(ar.ultima_em_cache(None, "willpdv", "estavel"))
            self.assertIsNone(ar.ultima_em_cache(None, "willpdv", "estavel"))
            self.assertEqual(ultima.call_count, 1)
            ar.limpar_cache()
            ar.ultima_em_cache(None, "willpdv", "estavel")
            self.assertEqual(ultima.call_count, 2)


if __name__ == "__main__":
    unittest.main()
