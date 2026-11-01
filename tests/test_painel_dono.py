"""Painel do dono no celular: o envio do PDV (src/sync/painel_envio.py) e a nuvem (backend/painel.py + app web)."""
from __future__ import annotations

import atexit
import io
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from src.controllers.perfil_controller import PerfilController
from src.sync import painel_envio
from src.sync.sincronizador import Sincronizador
from tests.test_caixa import BaseCaixa

_PASTA = tempfile.mkdtemp(prefix="pdv_painel_")
os.environ.setdefault("PDV_NUVEM_DB_URL", os.environ.get("PDV_TESTE_NUVEM_DB_URL")
                      or "sqlite:///" + (Path(_PASTA) / "nuvem.db").as_posix())
os.environ.setdefault("PDV_API_TOKEN", "token-de-teste")
try:
    from fastapi.testclient import TestClient
    from backend import lojas, painel
    from backend import main as nuvem
except (ImportError, RuntimeError):
    TestClient = nuvem = lojas = painel = None

atexit.register(lambda: shutil.rmtree(_PASTA, ignore_errors=True))

TOKENS = {"ADEGA-1": "token-da-adega-1", "ADEGA-2": "token-da-adega-2"}
ADMIN = {"Authorization": "Bearer token-de-teste"}


def cabecalho(loja="ADEGA-1"):
    return {"Authorization": f"Bearer {TOKENS[loja]}"}


class RespostaFalsa:
    def __init__(self, status=200, corpo=None):
        self.status_code = status
        self._corpo = corpo or {}

    def json(self):
        return self._corpo


class HttpFalso:
    """Confirma todos os uuids recebidos (ou só os que `confirmar` escolher) e guarda o que foi enviado."""

    def __init__(self, status=200, confirmar=None):
        self.status, self.confirmar, self.chamadas = status, confirmar, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append({"url": url, "corpo": json, "headers": headers})
        uuids = [v["uuid"] for v in json.get("vendas", [])]
        if self.confirmar is not None:
            uuids = self.confirmar(uuids)
        return RespostaFalsa(self.status, {"recebidas": len(uuids), "uuids": uuids})


class BasePainel(BaseCaixa):
    def setUp(self):
        super().setUp()
        PerfilController(self.banco, self.adm).aplicar("adega")
        self.banco.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.banco.cfg_set("api_token", TOKENS["ADEGA-1"])
        self.banco.cfg_set("chave_loja", "ADEGA-1")
        self.banco.cfg_set("painel_dono", "S")
        self.banco.executar("UPDATE produtos SET preco_gelada_cent = 1000, atacado_qtd = 6, preco_atacado_cent = 650 "
                            "WHERE id = ?", (self.skol,))

    def venda_fechada(self, *itens, forma="Dinheiro", **opcoes):
        vid = self.caixa.abrir_balcao()
        for pid, qtd in itens:
            self.caixa.adicionar_item(vid, pid, qtd, **opcoes)
        total = self.caixa.obter(vid)["total_cent"]
        self.pagar(vid, forma, total)
        return self.caixa.fechar(vid)

    def preparar_noite(self):
        """Fecha um turno com sangria e suprimento e abre outro com comandas e comissão pendente."""
        from src.controllers.comissao_controller import ComissaoController
        self.banco.cfg_set("usar_mesas", "S")
        self.turnos.movimentar(self.turno, self.adm, "saida", 1500, "malote")
        self.turnos.movimentar(self.turno, self.adm, "entrada", 400, "troco")
        self.venda_fechada((self.skol, 1))
        esperado = self.turnos.resumo(self.turno)["esperado"]
        self.turnos.fechar(self.turno, self.adm, esperado)
        self.turno = self.turnos.abrir(self.adm, 2, 5000)
        self.banco.inserir("garotas", {"numero": 12, "nome": "ANA", "ativo": 1})
        vid, _ = self.caixa.abrir_mesa(7, comanda=True)
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.caixa.abrir_mesa(12, comanda=True)
        self.caixa.abrir_mesa(13, comanda=True)
        ComissaoController(self.banco).lancar(12, 5000, self.turno, self.adm)
        self.banco.inserir("comissoes_garotas", {
            "garota": 13, "valor_cent": 1000, "turno_id": self.turno, "operador_id": self.adm,
            "criado_em": "2026-10-03 21:00:00", "status": "paga", "paga_em": "2026-10-03 21:00:00"})
        return {"esperado": esperado}


class TesteEnvioDoPdv(BasePainel):
    def test_desligado_nao_chama_a_nuvem(self):
        self.banco.cfg_set("painel_dono", "N")
        self.venda_fechada((self.skol, 1))
        http = HttpFalso()
        self.assertIsNone(painel_envio.enviar(self.banco, http))
        self.assertEqual(http.chamadas, [])
        self.assertEqual(painel_envio.pendentes(self.banco), 1)          # fica guardada para quando ligar

    def test_url_do_envio_fica_ao_lado_do_endereco_configurado(self):
        for url in ("https://nuvem.exemplo/v1/sincronizar", "https://nuvem.exemplo/", "https://nuvem.exemplo"):
            self.assertEqual(painel_envio.url_envio(url), "https://nuvem.exemplo/v1/painel/envio", url)

    def test_coleta_a_venda_com_itens_pagamentos_e_dia_operacional(self):
        self.banco.cfg_set("virada_dia_hora", 6)
        self._hora["t"] = self._hora["t"].replace(hour=2)                 # 02:00 do dia 3 ainda é a noite do dia 2
        v = self.venda_fechada((self.skol, 2), (self.agua, 1), forma="Pix")
        vendas = painel_envio.coletar_vendas(self.banco)
        self.assertEqual(len(vendas), 1)
        c = vendas[0]
        self.assertEqual((c["uuid"], c["cupom"], c["status"], c["modalidade"], c["posicao_rotulo"], c["dia"]),
                         (v["uuid"], v["cupom"], "fechada", "balcao", "Balcão", "2026-10-02"))
        self.assertEqual(c["total_cent"], 1950)
        self.assertEqual([(i["nome"], i["quantidade"], i["temperatura"], i["unidade"]) for i in c["itens"]],
                         [("SKOL", 2, "natural", "UN"), ("AGUA", 1, "natural", "UN")])
        self.assertEqual(c["pagamentos"], [{"tipo": "Pix", "valor_cent": 1950, "troco_cent": 0}])
        self.assertEqual(c["operador"], "ADM")

    def test_envia_marca_como_enviada_e_nao_repete(self):
        v = self.venda_fechada((self.skol, 1))
        http = HttpFalso()
        self.assertEqual(painel_envio.enviar(self.banco, http), {"vendas": 1, "lotes": 1})
        self.assertEqual(http.chamadas[0]["headers"], {"Authorization": f"Bearer {TOKENS['ADEGA-1']}"})
        self.assertEqual(self.banco.valor("SELECT sincronizado FROM vendas WHERE uuid = ?", (v["uuid"],)), 1)
        self.assertEqual(painel_envio.enviar(self.banco, http), {"vendas": 0, "lotes": 1})
        self.assertEqual(http.chamadas[1]["corpo"]["vendas"], [])            # só o retrato sobe de novo
        self.assertIn("caixa", http.chamadas[1]["corpo"]["retrato"])
        self.assertTrue(self.banco.cfg(painel_envio.CHAVE_ULTIMO_ENVIO))

    def test_so_marca_o_que_a_nuvem_confirmou_e_erro_nao_marca_nada(self):
        v1 = self.venda_fechada((self.skol, 1))
        v2 = self.venda_fechada((self.agua, 1))
        painel_envio.enviar(self.banco, HttpFalso(confirmar=lambda u: [v1["uuid"]]))
        marcas = dict(self.banco.todos("SELECT uuid, sincronizado FROM vendas"))
        self.assertEqual((marcas[v1["uuid"]], marcas[v2["uuid"]]), (1, 0))
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            painel_envio.enviar(self.banco, HttpFalso(status=503))
        self.assertEqual(self.banco.valor("SELECT sincronizado FROM vendas WHERE uuid = ?", (v2["uuid"],)), 0)
        self.assertIn("HTTP 503", self.banco.cfg(painel_envio.CHAVE_ULTIMO_ERRO))

    def test_venda_aberta_nao_sobe_e_cancelada_depois_de_enviada_sobe_de_novo(self):
        self.vender((self.skol, 1))                                           # aberta: fica no caixa
        v = self.venda_fechada((self.skol, 1))
        self.assertEqual([c["uuid"] for c in painel_envio.coletar_vendas(self.banco)], [v["uuid"]])
        painel_envio.enviar(self.banco, HttpFalso())
        self.caixa.cancelar_venda(v["id"], "cliente desistiu")
        de_novo = painel_envio.coletar_vendas(self.banco)
        self.assertEqual([(c["uuid"], c["status"], c["motivo_cancelamento"]) for c in de_novo],
                         [(v["uuid"], "cancelada", "cliente desistiu")])

    def test_envia_em_lotes_ate_esvaziar(self):
        for _ in range(3):
            self.venda_fechada((self.agua, 1))
        http = HttpFalso()
        with mock.patch.object(painel_envio, "LOTE", 2):
            self.assertEqual(painel_envio.enviar(self.banco, http), {"vendas": 3, "lotes": 2})
        self.assertEqual([len(c["corpo"]["vendas"]) for c in http.chamadas], [2, 1])

    def test_retrato_traz_caixa_estoque_caderneta_e_entregas(self):
        self.banco.executar("UPDATE produtos SET estoque_minimo = 10, qt_atual = 4 WHERE id = ?", (self.skol,))
        zerado = self.novo_produto("GELO", 500, estoque=True, qt=0)
        cli = self.cliente("MARIA", limite=50000)
        vid = self.caixa.abrir_caderneta(cli)
        self.caixa.adicionar_item(vid, self.agua, 2)
        self.caixa.fechar(vid)
        self.turnos.movimentar(self.turno, self.adm, "saida", 2000, "sangria")
        r = painel_envio.retrato(self.banco)
        self.assertEqual((r["caixa"]["turno_numero"], r["caixa"]["operador"], r["caixa"]["valor_inicial_cent"],
                          r["caixa"]["sangrias_cent"], r["caixa"]["esperado_gaveta_cent"]), (1, "ADM", 10000, 2000, 8000))
        self.assertEqual((r["estoque"]["controlados"], r["estoque"]["zerados"], r["estoque"]["abaixo_minimo_total"]), (2, 1, 2))
        self.assertEqual([p["nome"] for p in r["estoque"]["abaixo_minimo"]], ["GELO", "SKOL"])   # zerado primeiro
        self.assertEqual(r["estoque"]["abaixo_minimo"][1]["codigo"], self.banco.valor(
            "SELECT codigo FROM produtos WHERE id = ?", (self.skol,)).lstrip("0"))
        self.assertEqual(r["caderneta"], {"a_receber_cent": 700, "clientes_devendo": 1})
        self.assertEqual((r["entregas_pendentes"], r["vendas_pendentes_envio"], r["dia_operacional"]), (0, 1, "2026-10-03"))
        self.assertEqual(r["loja_nome"], "PDV")
        self.assertIsNotNone(zerado)
        self.assertEqual(r["comandas"], [])
        self.assertIn("faturamento_meses", r)
        self.assertEqual(len(r["faturamento_meses"]), 12)

    def test_retrato_sem_turno_aberto(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.assertIsNone(painel_envio.retrato(self.banco)["caixa"])

    def test_sincronizador_envia_o_painel_e_falha_nao_derruba_o_laco(self):
        self.venda_fechada((self.skol, 1))
        http = HttpFalso()
        with mock.patch("src.sync.atualizacoes.verificar", return_value=None), \
                mock.patch("src.sync.licenca_nuvem.renovar"):
            self.assertTrue(Sincronizador(self.banco, http=http).rodada())
        self.assertEqual(len(http.chamadas), 1)
        self.venda_fechada((self.agua, 1))  # outra mudança exige rede; caixa parado é tratado nos testes de ritmo
        with mock.patch("src.sync.atualizacoes.verificar", return_value=None), \
                mock.patch("src.sync.licenca_nuvem.renovar"), \
                mock.patch.object(painel_envio.log, "exception"), \
                mock.patch("src.sync.sincronizador.log.exception"):
            self.assertFalse(Sincronizador(self.banco, http=HttpFalso(status=500)).rodada())

    def test_retrato_leva_comandas_comissoes_fechamento_e_meses(self):
        noite = self.preparar_noite()
        r = painel_envio.retrato(self.banco)
        self.assertEqual([(c["numero"], c["garota"], c["devido_cent"]) for c in r["comandas"]],
                         [(7, False, 800), (12, True, 0), (13, False, 0)])
        self.assertTrue(r["comandas"][1]["rotulo"])
        linhas = {(c["garota"], c["nome"], c["valor_cent"], c["status"], c["dia"]) for c in r["comissoes"]["linhas"]}
        self.assertEqual(linhas, {(12, "ANA", 5000, "pendente", "2026-10-03"), (13, "", 1000, "paga", "2026-10-03")})
        self.assertEqual(r["comissoes"]["pendente_total_cent"], 5000)
        self.assertEqual(len(r["fechamentos"]), 1)
        f = r["fechamentos"][0]
        self.assertEqual((f["dia"], f["turno_numero"], f["resultado_cent"], f["sangrias_cent"], f["suprimentos_cent"],
                          f["esperado_cent"]), ("2026-10-03", 1, 0, 1500, 400, noite["esperado"]))
        self.assertEqual([(s["valor_cent"], s["descricao"], s["dia"]) for s in r["sangrias"]], [(1500, "malote", "2026-10-03")])
        outubro = next(m for m in r["faturamento_meses"] if m["mes"] == "2026-10")
        self.assertEqual((outubro["faturamento_cent"], outubro["quantidade"]), (800, 1))
        self.assertEqual(len(r["faturamento_meses"]), 12)
        self.assertEqual(r["caixa"]["turno_numero"], 2)

    def test_modulos_do_sistema_sabem_do_painel(self):
        from src.controllers.config_controller import CAMPOS_CONFIG
        from src.database.sementes import CONFIG_PADRAO
        self.assertEqual(CONFIG_PADRAO["painel_dono"], "N")
        self.assertIn("painel_dono", [c[0] for c in CAMPOS_CONFIG])


# ====================================================================== nuvem
def preparar_lojas():
    db = nuvem.SessionLocal()
    try:
        for tabela in (painel.devolucoes.PainelDevolucao, painel.PainelVenda, painel.PainelCaixa, painel.PainelSessao, painel.PainelAcesso):
            db.query(tabela).delete()
        db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja.in_(list(TOKENS))).delete(synchronize_session=False)
        for chave, token in TOKENS.items():
            db.add(nuvem.Loja(chave_loja=chave, nome=f"Adega {chave[-1]}", token_hash=nuvem.hash_token(token), ativa=True))
        db.commit()
    finally:
        db.close()
    painel.tentativas.acertou("ADEGA-1")
    painel.tentativas.acertou("ADEGA-2")
    painel._limpeza["ultima"] = time.monotonic()    # limpeza "recém-feita": só os testes de limpeza a querem (ultima = None)


class _ClienteSemTimeout:
    """O TestClient não aceita `timeout`; o envio real (requests) usa. Este adaptador tira o argumento."""

    def __init__(self, http):
        self._http = http

    def post(self, url, json=None, headers=None, timeout=None):
        return self._http.post(url, json=json, headers=headers)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class BaseNuvem(BasePainel):
    """O PDV de teste ligado à API de verdade (TestClient), com as lojas ADEGA-1 e ADEGA-2 e o "hoje" da nuvem no dia do
    relógio dos testes (2026-10-03): a retenção compara o dia das vendas com a data do servidor, que sem isto seria a real."""

    def setUp(self):
        super().setUp()
        preparar_lojas()
        relogio = mock.patch.object(painel, "_hoje", return_value=date(2026, 10, 3))
        relogio.start()
        self.addCleanup(relogio.stop)
        self.http = TestClient(nuvem.app)
        self.banco.cfg_set("api_url", "http://testserver/v1/sincronizar")

    def entrar(self, loja="ADEGA-1", senha="senha-forte-1"):
        db = nuvem.SessionLocal()
        try:
            painel.definir_senha(db, loja, senha)
        finally:
            db.close()
        r = self.http.post("/v1/painel/login", json={"loja": loja, "senha": senha})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def subir(self, banco=None):
        return painel_envio.enviar(banco or self.banco, _ClienteSemTimeout(self.http))


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteNuvemPainel(BaseNuvem):
    def test_envios_concorrentes_do_mesmo_uuid_guardam_uma_venda(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.venda_fechada((self.skol, 1))
        lote = painel_envio.coletar_vendas(self.banco)
        largada = Barrier(2)

        def enviar():
            largada.wait(timeout=10)
            return self.http.post("/v1/painel/envio", json={"vendas": lote}, headers=cabecalho()).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(list(executor.map(lambda _: enviar(), range(2))), [200, 200])
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(painel.PainelVenda).filter_by(uuid=lote[0]["uuid"]).count(), 1)

    def test_modo_rapido_orienta_atualizacao_do_celular_em_cinco_segundos(self):
        sessao = self.entrar()
        for ligado, segundos in (("S", 5), ("N", 30)):
            self.banco.cfg_set("sync_quase_tempo_real", ligado)
            self.subir()
            r = self.http.get("/v1/painel/resumo", headers=sessao)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["atualizacao_seg"], segundos)

    def test_cancelamento_durante_http_continua_pendente_e_sobe_na_proxima_rodada(self):
        v = self.venda_fechada((self.skol, 1))
        http = self.http
        caixa = self.caixa

        class CancelarDuranteResposta:
            def post(self, url, json=None, headers=None, timeout=None):
                resposta = http.post(url, json=json, headers=headers)
                caixa.cancelar_venda(v["id"], "Cancelado durante o envio")
                return resposta

        self.assertEqual(painel_envio.enviar(self.banco, CancelarDuranteResposta())["vendas"], 0)
        self.assertEqual(painel_envio.pendentes(self.banco), 1)
        self.assertEqual(self.subir()["vendas"], 1)
        with nuvem.SessionLocal() as db:
            linha = db.query(painel.PainelVenda).filter_by(uuid=v["uuid"]).one()
            self.assertEqual(linha.status, "cancelada")
        self.assertEqual(painel_envio.pendentes(self.banco), 0)

    def test_confirmacao_estranha_nao_retira_outra_venda_da_fila(self):
        primeira = self.venda_fechada((self.skol, 1))
        segunda = self.venda_fechada((self.agua, 1))
        with mock.patch.object(painel_envio, "LOTE", 1):
            resultado = painel_envio.enviar(self.banco, HttpFalso(confirmar=lambda _: [segunda["uuid"]]))
        self.assertEqual(resultado, {"vendas": 0, "lotes": 1})
        self.assertEqual(painel_envio.pendentes(self.banco), 2)
        self.assertNotEqual(primeira["uuid"], segunda["uuid"])

    def test_lote_repetido_e_resposta_atrasada_nao_ressuscitam_cancelamento(self):
        v = self.venda_fechada((self.skol, 1))
        original = painel_envio.coletar_vendas(self.banco)[0]
        for lote in ([original, original], [original]):
            r = self.http.post("/v1/painel/envio", json={"vendas": lote}, headers=cabecalho())
            self.assertEqual(r.status_code, 200, r.text)
        self.caixa.cancelar_venda(v["id"], "Cancelada")
        self.subir()
        r = self.http.post("/v1/painel/envio", json={"vendas": [original]}, headers=cabecalho())
        self.assertEqual(r.status_code, 200, r.text)
        with nuvem.SessionLocal() as db:
            linhas = db.query(painel.PainelVenda).filter_by(uuid=v["uuid"]).all()
            self.assertEqual(len(linhas), 1)
            self.assertEqual(linhas[0].status, "cancelada")

    def test_desativar_revoga_todas_as_sessoes_mesmo_apos_reativar(self):
        sessao = self.entrar()
        with nuvem.SessionLocal() as db:
            lojas.definir_ativa(db, "ADEGA-1", False)
            self.assertEqual(db.query(painel.PainelSessao).filter_by(chave_loja="ADEGA-1").count(), 0)
            lojas.definir_ativa(db, "ADEGA-1", True)
        for rota in ("resumo", "produtos", "vendas", "historico"):
            self.assertEqual(self.http.get(f"/v1/painel/{rota}", headers=sessao).status_code, 401, rota)

    def test_sessao_tambem_recusa_loja_desativada_fora_do_cli(self):
        sessao = self.entrar()
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter_by(chave_loja="ADEGA-1").update({"ativa": False})
            db.commit()
        for rota in ("resumo", "produtos", "vendas", "historico"):
            self.assertEqual(self.http.get(f"/v1/painel/{rota}", headers=sessao).status_code, 401, rota)

    def test_login_recusa_campos_excessivos_sem_guardar_chaves(self):
        for chave, senha in (("x" * 65, "senha"), ("ADEGA-1", "s" * 129)):
            r = self.http.post("/v1/painel/login", json={"loja": chave, "senha": senha})
            self.assertEqual(r.status_code, 422)

    # ---- envio
    def test_pdv_envia_e_a_nuvem_guarda_sem_duplicar(self):
        v = self.venda_fechada((self.skol, 2))
        self.assertEqual(self.subir(), {"vendas": 1, "lotes": 1})
        self.assertEqual(self.subir(), {"vendas": 0, "lotes": 1})
        self.caixa.cancelar_venda(v["id"], "erro de digitação")
        self.subir()
        db = nuvem.SessionLocal()
        try:
            linhas = db.query(painel.PainelVenda).filter_by(chave_loja="ADEGA-1").all()
            self.assertEqual([(l.uuid, l.status, l.motivo_cancelamento) for l in linhas],
                             [(v["uuid"], "cancelada", "erro de digitação")])
            self.assertEqual(db.query(painel.PainelCaixa).filter_by(chave_loja="ADEGA-1").count(), 1)
        finally:
            db.close()

    def test_envio_exige_token_da_loja(self):
        self.assertEqual(self.http.post("/v1/painel/envio", json={"vendas": []}).status_code, 401)
        self.assertEqual(self.http.post("/v1/painel/envio", json={"vendas": []}, headers=ADMIN).status_code, 403)
        r = self.http.post("/v1/painel/envio", json={"vendas": [{"uuid": "x", "status": "aberta"}, "lixo", {"uuid": ""}]},
                           headers=cabecalho())
        self.assertEqual((r.status_code, r.json()), (200, {"recebidas": 0, "uuids": []}))
        self.assertEqual(self.http.post("/v1/painel/envio", json={"vendas": "nao"}, headers=cabecalho()).status_code, 422)

    # ---- senha e sessão
    def test_sem_senha_definida_o_dono_nao_entra(self):
        r = self.http.post("/v1/painel/login", json={"loja": "ADEGA-1", "senha": "qualquer"})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "Loja ou senha inválida."))
        self.assertEqual(self.http.post("/v1/painel/login", json={"loja": "", "senha": ""}).status_code, 422)

    def test_admin_define_a_senha_e_loja_desativada_nao_entra(self):
        r = self.http.post("/v1/admin/lojas/ADEGA-1/painel", json={}, headers=ADMIN)
        self.assertEqual(r.status_code, 200)
        senha = r.json()["senha"]
        self.assertRegex(senha, r"^[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}$")
        self.assertEqual(self.http.post("/v1/admin/lojas/ADEGA-1/painel", json={}, headers=cabecalho()).status_code, 403)
        self.assertEqual(self.http.post("/v1/admin/lojas/NAO-EXISTE/painel", json={}, headers=ADMIN).status_code, 404)
        self.assertEqual(self.http.post("/v1/admin/lojas/ADEGA-1/painel", json={"senha": "curta"}, headers=ADMIN).status_code, 422)
        self.assertEqual(self.http.post("/v1/painel/login", json={"loja": "ADEGA-1", "senha": senha}).status_code, 200)
        lojas.definir_ativa(nuvem.SessionLocal(), "ADEGA-1", False)
        self.assertEqual(self.http.post("/v1/painel/login", json={"loja": "ADEGA-1", "senha": senha}).status_code, 401)

    def test_pdv_pode_definir_a_senha_com_o_token_da_loja(self):
        r = self.http.post("/v1/painel/senha", json={"senha": "minha-senha-nova"}, headers=cabecalho())
        self.assertEqual((r.status_code, r.json()["senha"]), (200, None))      # senha informada não é devolvida
        self.assertEqual(self.http.post("/v1/painel/login", json={"loja": "ADEGA-1", "senha": "minha-senha-nova"}).status_code, 200)

    def test_trocar_a_senha_derruba_as_sessoes_e_sair_invalida_o_token(self):
        sessao = self.entrar()
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=sessao).status_code, 200)
        db = nuvem.SessionLocal()
        painel.definir_senha(db, "ADEGA-1", "outra-senha-forte")
        db.close()
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=sessao).status_code, 401)
        sessao = self.entrar(senha="outra-senha-forte")
        self.assertEqual(self.http.post("/v1/painel/sair", headers=sessao).status_code, 200)
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=sessao).status_code, 401)

    def test_sessao_vencida_e_token_da_loja_nao_abrem_o_painel(self):
        sessao = self.entrar()
        db = nuvem.SessionLocal()
        db.query(painel.PainelSessao).update({"expira_em": "2000-01-01 00:00:00"})
        db.commit()
        db.close()
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=sessao).status_code, 401)
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=cabecalho()).status_code, 401)

    def test_muitas_tentativas_bloqueiam_a_loja_por_um_tempo(self):
        self.entrar()
        for _ in range(painel.TENTATIVAS_LOGIN):
            self.assertEqual(self.http.post("/v1/painel/login", json={"loja": "ADEGA-1", "senha": "errada"}).status_code, 401)
        r = self.http.post("/v1/painel/login", json={"loja": "ADEGA-1", "senha": "senha-forte-1"})
        self.assertEqual(r.status_code, 429)
        self.assertFalse(painel.tentativas.bloqueada("ADEGA-1", agora=painel.time.monotonic() + painel.JANELA_LOGIN_SEG + 1))
        self.assertTrue(painel.conferir_senha("abc12345", painel.gerar_hash_senha("abc12345")))
        self.assertFalse(painel.conferir_senha("ABC12345", painel.gerar_hash_senha("abc12345")))
        self.assertFalse(painel.conferir_senha("x", None))

    # ---- consultas
    def test_resumo_do_dia_soma_vendas_formas_produtos_e_atacado(self):
        self.venda_fechada((self.skol, 6), forma="Pix")                        # atacado: 6 x 6,50 = 39,00
        self.venda_fechada((self.skol, 1), (self.agua, 1), temperatura="natural")
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, self.skol, 2, temperatura="gelada")      # 2 x 10,00
        self.pagar(vid, "Dinheiro", 2000)
        self.caixa.fechar(vid)
        cancelada = self.venda_fechada((self.agua, 3))
        self.caixa.cancelar_venda(cancelada["id"], "teste")
        self.subir()
        r = self.http.get("/v1/painel/resumo", headers=self.entrar()).json()
        self.assertEqual((r["dia"], r["loja"]["nome"]), ("2026-10-03", "PDV"))
        self.assertEqual(r["vendas"], {"faturamento_cent": 3900 + 1150 + 2000, "quantidade": 3, "ticket_medio_cent": 2350,
                                       "bruto_cent": 7050, "devolucoes_cent": 0, "liquido_cent": 7050,
                                       "desconto_cent": 0, "itens": 4, "canceladas": 1, "canceladas_cent": 1050})
        self.assertEqual(r["formas"], [{"tipo": "Pix", "valor_cent": 3900}, {"tipo": "Dinheiro", "valor_cent": 3150}])
        self.assertEqual(r["modalidades"], [{"modalidade": "balcao", "quantidade": 3, "valor_cent": 7050}])
        skol = next(p for p in r["produtos"] if p["nome"] == "SKOL")
        self.assertEqual((skol["quantidade"], skol["valor_cent"], skol["geladas"], skol["naturais"]), (9, 3900 + 800 + 2000, 2, 7))
        self.assertEqual(r["atacado_economia_cent"], 6 * 150)
        self.assertEqual(r["por_hora"], [{"hora": "21", "valor_cent": 7050, "quantidade": 3}])
        self.assertEqual(r["caixa"]["turno_numero"], 1)
        self.assertEqual(r["estoque"]["controlados"], 1)
        self.assertEqual(r["dias"], ["2026-10-03"])
        self.assertIsNotNone(r["atualizado_em"])
        self.assertLessEqual(r["atraso_min"], 1)

    def test_uma_loja_nao_ve_a_outra(self):
        self.venda_fechada((self.skol, 1))
        self.subir()
        outra = self.entrar("ADEGA-2", "senha-da-outra-loja")
        r = self.http.get("/v1/painel/resumo", headers=outra).json()
        self.assertEqual((r["loja"]["chave"], r["vendas"]["quantidade"], r["atualizado_em"], r["caixa"]), ("ADEGA-2", 0, None, None))
        self.assertEqual(self.http.get("/v1/painel/vendas", headers=outra).json()["total"], 0)
        self.assertEqual(self.http.get("/v1/painel/resumo", params={"dia": "2026-10-03"}, headers=self.entrar()).json()["vendas"]["quantidade"], 1)

    def test_lista_de_vendas_paginada_com_itens_e_dia_invalido(self):
        for _ in range(3):
            self.venda_fechada((self.skol, 1))
        self.subir()
        sessao = self.entrar()
        with mock.patch.object(painel, "VENDAS_POR_PAGINA", 2):
            r1 = self.http.get("/v1/painel/vendas", headers=sessao).json()
            r2 = self.http.get("/v1/painel/vendas", params={"pagina": 2}, headers=sessao).json()
            r9 = self.http.get("/v1/painel/vendas", params={"pagina": 9}, headers=sessao).json()
        self.assertEqual((r1["total"], r1["paginas"], len(r1["vendas"]), len(r2["vendas"]), r9["pagina"]), (3, 2, 2, 1, 2))
        self.assertEqual([v["cupom"] for v in r1["vendas"]], [3, 2])                 # mais recente primeiro
        venda = r1["vendas"][0]
        self.assertEqual(venda["itens"][0]["nome"], "SKOL")
        self.assertEqual(venda["pagamentos"][0]["tipo"], "Dinheiro")
        self.assertEqual(self.http.get("/v1/painel/vendas", params={"dia": "ontem"}, headers=sessao).status_code, 422)
        self.assertEqual(self.http.get("/v1/painel/resumo", params={"dia": "2026-13-01"}, headers=sessao).status_code, 422)

    def test_resumo_entrega_comandas_comissoes_fechamento_e_meses(self):
        self.preparar_noite()
        self.subir()
        r = self.http.get("/v1/painel/resumo", headers=self.entrar()).json()
        self.assertEqual(r["dia_operacional"], "2026-10-03")
        self.assertTrue(r["comandas_sincronizadas"])
        self.assertFalse(r["comandas_parciais"])
        self.assertEqual([(c["numero"], c["garota"], c["devido_cent"]) for c in r["comandas"]],
                         [(7, False, 800), (12, True, 0), (13, False, 0)])
        self.assertEqual(r["comissoes"]["pendente_total_cent"], 5000)
        self.assertEqual(sorted((c["garota"], c["status"]) for c in r["comissoes"]["linhas"]),
                         [(12, "pendente"), (13, "paga")])
        self.assertTrue(r["movimento_sincronizado"])
        self.assertEqual(r["fechamentos"][0]["resultado_cent"], 0)
        self.assertEqual(r["sangrias"][0]["descricao"], "malote")
        self.assertEqual(r["meses_origem"], "caixa")
        self.assertFalse(r["meses_parcial"])
        outubro = next(m for m in r["faturamento_meses"] if m["mes"] == "2026-10")
        self.assertEqual(outubro["faturamento_cent"], 800)
        outra = self.http.get("/v1/painel/resumo", headers=self.entrar("ADEGA-2", "senha-da-outra-loja")).json()
        self.assertEqual((outra["comandas"], outra["comissoes"]["linhas"], outra["fechamentos"], outra["sangrias"]),
                         ([], [], [], []))

    def test_ranking_por_periodo_e_so_da_loja(self):
        self.venda_fechada((self.skol, 2))
        self.avancar(days=3)
        self.venda_fechada((self.agua, 4))
        self.subir()
        sessao = self.entrar()
        self.assertEqual(self.http.get("/v1/painel/produtos", headers=cabecalho()).status_code, 401)
        self.assertEqual(self.http.get("/v1/painel/produtos", params={"periodo": "ano"}, headers=sessao).status_code, 422)
        hoje = self.http.get("/v1/painel/produtos", params={"periodo": "hoje"}, headers=sessao).json()
        self.assertEqual((hoje["de"], hoje["ate"], [(p["nome"], p["quantidade"], p["valor_cent"]) for p in hoje["produtos"]]),
                         ("2026-10-06", "2026-10-06", [("AGUA", 4, 1400)]))
        semana = self.http.get("/v1/painel/produtos", params={"periodo": "7d"}, headers=sessao).json()
        self.assertEqual(semana["de"], "2026-09-30")
        self.assertEqual([(p["nome"], p["quantidade"], p["valor_cent"]) for p in semana["produtos"]],
                         [("SKOL", 2, 1600), ("AGUA", 4, 1400)])
        outra = self.http.get("/v1/painel/produtos", headers=self.entrar("ADEGA-2", "senha-da-outra-loja")).json()
        self.assertEqual(outra["produtos"], [])

    def test_pdv_antigo_usa_as_vendas_guardadas_no_grafico_mensal(self):
        self.http.post("/v1/painel/envio", json={
            "vendas": [{"uuid": "venda-antiga-1", "status": "fechada", "dia": "2026-10-03", "total_cent": 500,
                        "desconto_cent": 0, "modalidade": "balcao",
                        "itens": [{"nome": "GELO", "quantidade": 2, "total_cent": 500, "cancelado": 0}],
                        "pagamentos": []}],
            "retrato": {"terminal_id": "velho", "terminal": 1, "loja_nome": "Adega",
                        "dia_operacional": "2026-10-03", "momento": "2026-10-03 21:00:00", "caixa": None,
                        "estoque": {"controlados": 0, "zerados": 0, "abaixo_minimo": []},
                        "caderneta": {"a_receber_cent": 0, "clientes_devendo": 0},
                        "entregas_pendentes": 0, "vendas_pendentes_envio": 0},
        }, headers=cabecalho())
        r = self.http.get("/v1/painel/resumo", headers=self.entrar()).json()
        self.assertFalse(r["comandas_sincronizadas"])
        self.assertFalse(r["movimento_sincronizado"])
        self.assertEqual(r["meses_origem"], "nuvem")
        self.assertTrue(r["meses_parcial"])
        outubro = next(m for m in r["faturamento_meses"] if m["mes"] == "2026-10")
        self.assertEqual((outubro["faturamento_cent"], outubro["quantidade"]), (500, 1))
        self.assertEqual(len(r["faturamento_meses"]), 12)
        rank = self.http.get("/v1/painel/produtos", params={"periodo": "hoje"}, headers=self.entrar()).json()
        self.assertEqual(rank["produtos"][0]["nome"], "GELO")

    def test_meses_de_dois_caixas_se_somam(self):
        def corpo(terminal_id, cent, qtd):
            return {"vendas": [], "retrato": {
                "terminal_id": terminal_id, "terminal": 1 if terminal_id == "cx-a" else 2,
                "dia_operacional": "2026-10-03", "momento": "2026-10-03 21:00:00",
                "estoque": {"controlados": 0, "zerados": 0, "abaixo_minimo": []},
                "comandas": [], "comissoes": {"linhas": [], "pendente_total_cent": 0},
                "fechamentos": [], "sangrias": [],
                "faturamento_meses": [{"mes": "2026-10", "faturamento_cent": cent, "quantidade": qtd}],
            }}
        self.assertEqual(self.http.post("/v1/painel/envio", json=corpo("cx-a", 100, 1), headers=cabecalho()).status_code, 200)
        self.assertEqual(self.http.post("/v1/painel/envio", json=corpo("cx-b", 50, 2), headers=cabecalho()).status_code, 200)
        r = self.http.get("/v1/painel/resumo", headers=self.entrar()).json()
        outubro = next(m for m in r["faturamento_meses"] if m["mes"] == "2026-10")
        self.assertEqual((outubro["faturamento_cent"], outubro["quantidade"], r["meses_parcial"], r["comandas_parciais"]),
                         (150, 3, False, False))

    def test_historico_por_dia_com_dias_sem_venda_zerados(self):
        self.venda_fechada((self.skol, 1))
        self.avancar(days=2)
        self.venda_fechada((self.skol, 2))
        c = self.venda_fechada((self.agua, 1))
        self.caixa.cancelar_venda(c["id"])
        self.subir()
        r = self.http.get("/v1/painel/historico", params={"dias": 4}, headers=self.entrar()).json()["dias"]
        self.assertEqual([(d["dia"], d["faturamento_cent"], d["quantidade"], d["canceladas"]) for d in r],
                         [("2026-10-02", 0, 0, 0), ("2026-10-03", 800, 1, 0), ("2026-10-04", 0, 0, 0), ("2026-10-05", 1600, 1, 1)])

    def test_app_web_e_servido_pela_api(self):
        r = self.http.get("/painel/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertEqual(self.http.get("/painel", follow_redirects=False).status_code, 307)
        manifesto = self.http.get("/painel/manifest.webmanifest")
        self.assertEqual(manifesto.status_code, 200)
        self.assertEqual(manifesto.json()["start_url"], "/painel/")
        self.assertEqual(self.http.get("/painel/icones/icone-192.png").headers["content-type"], "image/png")
        self.assertEqual(self.http.get("/painel/sw.js").status_code, 200)
        self.assertEqual(self.http.get("/painel/app.js").status_code, 200)

    def test_comando_de_linha_define_a_senha(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            self.assertEqual(lojas.main(["painel", "ADEGA-2"]), 0)
            self.assertEqual(lojas.main(["painel", "ADEGA-2", "senha-escolhida"]), 0)
            self.assertEqual(lojas.main(["painel", "ADEGA-2", "curta"]), 1)
            self.assertEqual(lojas.main(["painel", "NAO-EXISTE"]), 1)
        self.assertIn("/painel/", saida.getvalue())
        self.assertEqual(self.http.post("/v1/painel/login", json={"loja": "ADEGA-2", "senha": "senha-escolhida"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
