"""Devoluções no painel, entrega incremental e estado local da sincronização."""
import json
from contextlib import closing
import os
from unittest import mock
from uuid import uuid4

from tests.test_painel_dono import BaseNuvem, HttpFalso, RespostaFalsa, _ClienteSemTimeout, cabecalho, nuvem, painel
from src.core.erros import ErroNegocio
from src.sync import devolucoes_envio, painel_envio, painel_ritmo, painel_status


class TesteMelhoriasPainel(BaseNuvem):
    def devolver(self, venda, quantidade=1, estoque=True, uid=None):
        item = self.caixa.itens(venda["id"])[0]
        return self.caixa.devolver(venda["id"], [{"item_id": item["id"], "quantidade": quantidade,
                                  "retorna_estoque": estoque}], "Devolução de teste", self.adm,
                                  "dinheiro_gaveta", uid or str(uuid4()))

    def test_custo_e_reembolso_seguem_historico_e_dia_da_devolucao(self):
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 300 WHERE id = ?", (self.skol,))
        venda = self.venda_fechada((self.skol, 1))
        self.subir()
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 999 WHERE id = ?", (self.skol,))
        self.avancar(days=1)
        self.devolver(venda)
        registros = devolucoes_envio.coletar(self.banco)
        self.assertEqual(registros[0]["itens"][0]["custo_recuperado_cent"], 300)
        self.assertTrue(registros[0]["custo_completo"])
        self.subir()
        self.assertEqual(devolucoes_envio.pendentes(self.banco), 0)
        sessao = self.entrar()
        original = self.http.get("/v1/painel/resumo?dia=2026-10-03", headers=sessao).json()
        posterior = self.http.get("/v1/painel/resumo?dia=2026-10-04", headers=sessao).json()
        self.assertEqual(original["vendas"]["liquido_cent"], 800)
        self.assertEqual(posterior["vendas"]["bruto_cent"], 0)
        self.assertEqual(posterior["vendas"]["devolucoes_cent"], 800)
        self.assertEqual(posterior["vendas"]["liquido_cent"], -800)
        self.assertEqual(posterior["devolucoes"]["custo_recuperado_cent"], 300)
        self.assertEqual(self.caixa.obter(venda["id"])["total_cent"], 800)
        historico = self.http.get("/v1/painel/historico?dias=2", headers=sessao).json()["dias"]
        self.assertEqual([d["liquido_cent"] for d in historico], [800, -800])

    def test_limpeza_preserva_fila_ate_confirmacao_da_nuvem(self):
        from src.controllers.utilitario_controller import UtilitarioController
        venda = self.venda_fechada((self.skol, 1))
        util = UtilitarioController(self.banco, self.adm)
        alvo = "date(fechada_em) < ?"
        self.assertNotIn(venda["id"], util._vendas_limpaveis(alvo, "2026-10-05"))
        self.subir()
        self.devolver(venda)
        self.assertNotIn(venda["id"], util._vendas_limpaveis(alvo, "2026-10-05"))
        self.subir()
        self.assertIn(venda["id"], util._vendas_limpaveis(alvo, "2026-10-05"))

    def test_fracoes_rateiam_custo_e_comissao_sem_perder_centavos(self):
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 1, aceita_decimal = 1 WHERE id = ?", (self.skol,))
        venda = self.venda_fechada((self.skol, 1))
        self.banco.executar("UPDATE itens_venda SET comissao_cent = 1 WHERE venda_id = ?", (venda["id"],))
        for qtd in (0.3333, 0.3333, 0.3334):
            self.devolver(venda, qtd)
        registros = devolucoes_envio.coletar(self.banco)
        self.assertEqual(sum(r["itens"][0]["custo_recuperado_cent"] for r in registros), 1)
        self.assertEqual(sum(r["itens"][0]["comissao_ajuste_cent"] for r in registros), 1)
        self.assertEqual(sum(r["valor_cent"] for r in registros), 800)

    def test_sem_retorno_nao_recupera_custo_e_legado_nao_inventa_custo(self):
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 300 WHERE id = ?", (self.skol,))
        venda = self.venda_fechada((self.skol, 2))
        self.devolver(venda, estoque=False)
        self.banco.executar("DELETE FROM itens_venda_custos")  # representa cupom fechado em versão anterior
        self.devolver(venda)
        registros = devolucoes_envio.coletar(self.banco)
        self.assertEqual(registros[0]["itens"][0]["custo_recuperado_cent"], 0)
        self.assertIsNone(registros[1]["itens"][0]["custo_recuperado_cent"])
        self.assertFalse(registros[1]["custo_completo"])

    def test_produto_sem_baixa_de_estoque_nao_declara_custo_recuperado(self):
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 100 WHERE id = ?", (self.agua,))
        venda = self.venda_fechada((self.agua, 1))
        self.devolver(venda, estoque=True)
        self.assertEqual(devolucoes_envio.coletar(self.banco)[0]["itens"][0]["custo_recuperado_cent"], 0)

    def test_migracao_32_preserva_cupom_sem_inventar_custo_antigo(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from src.database.conexao import BancoDados
        venda = self.venda_fechada((self.skol, 1))
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "legado.db"
            self.banco.copiar_para(str(arquivo))
            with closing(sqlite3.connect(arquivo)) as con, con:
                gatilhos = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger' "
                                                     "AND name LIKE 'painel_revisao_%'")]
                for nome in gatilhos:
                    con.execute(f'DROP TRIGGER "{nome}"')
                for tabela in ("itens_venda_custos", "painel_devolucoes_enviadas", "painel_revisao"):
                    con.execute(f"DROP TABLE {tabela}")
                con.execute("PRAGMA user_version = 32")
            migrado = BancoDados(str(arquivo))
            try:
                self.assertEqual(migrado.valor("PRAGMA user_version"), 33)
                self.assertEqual(migrado.valor("SELECT total_cent FROM vendas WHERE uuid = ?", (venda["uuid"],)), 800)
                self.assertEqual(migrado.valor("SELECT COUNT(*) FROM itens_venda_custos"), 0)
                self.assertEqual(migrado.todos("PRAGMA foreign_key_check"), [])
                self.assertEqual(len(list(Path(pasta).glob("*.antes-migracao-v32-*.bak"))), 1)
            finally:
                migrado.fechar()

    def test_interrupcao_abrupta_nao_deixa_cancelamento_pela_metade(self):
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        from src.database.conexao import BancoDados
        venda = self.venda_fechada((self.skol, 1))
        estoque = self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,))
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "interrupcao.db"
            self.banco.copiar_para(str(arquivo))
            programa = ("import os, sys\nfrom src.database.conexao import BancoDados\n"
                        "from src.controllers.caixa_controller import CaixaController\n"
                        "b=BancoDados(sys.argv[1], semear=False)\n"
                        "with b.transacao():\n"
                        " CaixaController(b,int(sys.argv[3])).cancelar_venda(int(sys.argv[2]), 'Teste isolado')\n"
                        " os._exit(99)\n")
            r = subprocess.run([sys.executable, "-c", programa, str(arquivo), str(venda["id"]), str(self.adm)],
                               capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 99, r.stderr)
            reaberto = BancoDados(str(arquivo))
            try:
                self.assertEqual(reaberto.valor("SELECT status FROM vendas WHERE uuid = ?", (venda["uuid"],)), "fechada")
                self.assertEqual(reaberto.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), estoque)
                self.assertEqual(reaberto.valor("PRAGMA integrity_check"), "ok")
            finally:
                reaberto.fechar()

    def test_devolucao_repetida_e_imutavel_na_nuvem_e_isolada_por_loja(self):
        venda = self.venda_fechada((self.skol, 1))
        d = self.devolver(venda)
        registro = devolucoes_envio.coletar(self.banco)[0]
        for _ in range(2):
            r = self.http.post("/v1/painel/envio", json={"devolucoes": [registro, registro]}, headers=cabecalho())
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["devolucoes_uuids"], [d["uuid"]])
        adulterado = {**registro, "valor_cent": registro["valor_cent"] + 1}
        self.assertEqual(self.http.post("/v1/painel/envio", json={"devolucoes": [adulterado]},
                                       headers=cabecalho()).status_code, 409)
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(painel.devolucoes.PainelDevolucao).count(), 1)
            self.assertEqual(db.query(painel.devolucoes.PainelDevolucao).filter_by(chave_loja="ADEGA-2").count(), 0)

    def test_nuvem_antiga_nao_confirma_devolucao_e_fila_permanece(self):
        venda = self.venda_fechada((self.skol, 1))
        self.devolver(venda)
        with self.assertRaisesRegex(RuntimeError, "não confirmou"):
            painel_envio.enviar(self.banco, HttpFalso())
        self.assertEqual(devolucoes_envio.pendentes(self.banco), 1)
        self.assertIn("atualize a nuvem", self.banco.cfg(painel_envio.CHAVE_ULTIMO_ERRO))
        self.subir()
        self.assertEqual(devolucoes_envio.pendentes(self.banco), 0)

    def test_caixa_parado_envia_batimento_sem_recalcular_retrato_a_cada_ciclo(self):
        chamadas = []
        http = _ClienteSemTimeout(self.http)

        class Espiao:
            def post(self, url, **kw):
                chamadas.append(kw["json"])
                return http.post(url, **kw)

        espiao = Espiao()
        with mock.patch.object(painel_envio, "retrato", wraps=painel_envio.retrato) as calcular:
            painel_ritmo.enviar_se_preciso(self.banco, espiao, relogio=lambda: 0)
            with nuvem.SessionLocal() as db:
                antes = json.loads(db.query(painel.PainelCaixa).one().dados)
            for segundo in range(5, 45, 5):
                painel_ritmo.enviar_se_preciso(self.banco, espiao, relogio=lambda: segundo)
            self.assertEqual(calcular.call_count, 1)
            self.assertEqual(len(chamadas), 1)
            painel_ritmo.enviar_se_preciso(self.banco, espiao, relogio=lambda: 45)
            self.assertEqual(len(chamadas), 1)
            painel_ritmo.enviar_se_preciso(self.banco, espiao, relogio=lambda: 45, forcar_batimento=True)
        self.assertEqual(len(chamadas), 2)
        self.assertIn("heartbeat", chamadas[1])
        self.assertNotIn("retrato", chamadas[1])
        with nuvem.SessionLocal() as db:
            depois = json.loads(db.query(painel.PainelCaixa).one().dados)
        self.assertEqual(antes["estoque"], depois["estoque"])
        self.banco.executar("UPDATE produtos SET qt_atual = 0 WHERE id = ?", (self.skol,))
        painel_ritmo.enviar_se_preciso(self.banco, espiao, relogio=lambda: 50)
        self.assertIn("retrato", chamadas[-1])
        self.assertGreater(chamadas[-1]["retrato"]["estoque"]["zerados"], 0)

    def test_retrato_apagado_na_nuvem_e_reposto_apos_batimento(self):
        http = _ClienteSemTimeout(self.http)
        painel_ritmo.enviar_se_preciso(self.banco, http, relogio=lambda: 0)
        with nuvem.SessionLocal() as db:
            db.query(painel.PainelCaixa).delete()
            db.commit()
        painel_ritmo.enviar_se_preciso(self.banco, http, relogio=lambda: 45, forcar_batimento=True)
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(painel.PainelCaixa).count(), 1)

    def test_mudanca_durante_http_invalida_cache_na_rodada_seguinte(self):
        chamadas = []
        cliente = _ClienteSemTimeout(self.http)
        banco = self.banco
        produto = self.skol

        class MudarDuranteResposta:
            def post(self, url, **kw):
                chamadas.append(kw["json"])
                resposta = cliente.post(url, **kw)
                if len(chamadas) == 1:
                    banco.executar("UPDATE produtos SET qt_atual = 0 WHERE id = ?", (produto,))
                return resposta

        http = MudarDuranteResposta()
        painel_ritmo.enviar_se_preciso(banco, http, relogio=lambda: 0)
        painel_ritmo.enviar_se_preciso(banco, http, relogio=lambda: 5)
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(chamadas[0]["retrato"]["estoque"]["zerados"], 0)
        self.assertEqual(chamadas[1]["retrato"]["estoque"]["zerados"], 1)

    def test_lotes_completos_nao_repetem_retrato_nem_fazem_envio_vazio_final(self):
        self.venda_fechada((self.skol, 1))
        self.venda_fechada((self.agua, 1))
        http = HttpFalso()
        with mock.patch.object(painel_envio, "LOTE", 1):
            r = painel_envio.enviar(self.banco, http)
        self.assertEqual(r, {"vendas": 2, "lotes": 2})
        self.assertIn("retrato", http.chamadas[0]["corpo"])
        self.assertNotIn("retrato", http.chamadas[1]["corpo"])

    def test_batimento_sem_confirmacao_nao_atualiza_sucesso_e_retoma_envio_completo(self):
        painel_ritmo.enviar_se_preciso(self.banco, _ClienteSemTimeout(self.http), relogio=lambda: 0)
        ultimo = self.banco.cfg(painel_envio.CHAVE_ULTIMO_ENVIO)
        self.avancar(minutes=1)
        with self.assertRaises(RuntimeError):
            painel_ritmo.enviar_se_preciso(self.banco, HttpFalso(status=503), relogio=lambda: 45,
                                           forcar_batimento=True)
        self.assertEqual(self.banco.cfg(painel_envio.CHAVE_ULTIMO_ENVIO), ultimo)
        http = HttpFalso()
        painel_ritmo.enviar_se_preciso(self.banco, http, relogio=lambda: 50)
        self.assertIn("retrato", http.chamadas[0]["corpo"])
        self.assertEqual(self.banco.cfg(painel_envio.CHAVE_ULTIMO_ERRO), "")

    def test_estado_mostra_pendencias_falha_e_atraso_sem_expor_token(self):
        self.venda_fechada((self.skol, 1))
        r = painel_status.situacao(self.banco)
        self.assertEqual(r["vendas_pendentes"], 1)
        with self.assertRaises(RuntimeError):
            painel_envio.enviar(self.banco, HttpFalso(status=503))
        r = painel_status.situacao(self.banco)
        self.assertEqual(r["estado"], "falha")
        self.assertNotIn(self.banco.cfg("api_token"), r["texto"] + r["erro"])
        self.subir()
        self.assertEqual(painel_status.situacao(self.banco)["estado"], "em_dia")
        self.avancar(minutes=4)
        self.assertEqual(painel_status.situacao(self.banco)["estado"], "em_dia")
        self.avancar(minutes=16)
        self.assertEqual(painel_status.situacao(self.banco)["estado"], "atrasado")

    def test_versao_publica_so_expoe_sha_valido(self):
        with mock.patch.dict(os.environ, {"RENDER_GIT_COMMIT": "a" * 40}):
            self.assertEqual(self.http.get("/v1/versao").json()["commit"], "a" * 40)
        with mock.patch.dict(os.environ, {"RENDER_GIT_COMMIT": "valor-que-nao-e-um-commit"}):
            self.assertIsNone(self.http.get("/v1/versao").json()["commit"])
