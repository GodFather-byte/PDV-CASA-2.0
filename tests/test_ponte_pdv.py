"""Ponte do PDV com a central do fornecedor (src/sync/ponte.py): opt-in, só aplica licença assinada, sem vazar token."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import date
from unittest import mock

from src.controllers.config_controller import ConfigController
from src.core import ed25519, licenca
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao
from src.database.conexao import BancoDados
from src.sync import licenca_nuvem, ponte
from src.sync.sincronizador import Sincronizador
from src.versao import VERSAO
from tests.base import BaseTeste
from tests.test_atualizacoes import Resposta

SEMENTE = bytes(range(32))
OUTRA_SEMENTE = bytes(range(1, 33))
PUBLICA = ed25519.chave_publica(SEMENTE).hex()
TOKEN = "tok-caixa-SEGREDO-123456"
CAIXA = "3f2b8c1e-0d4a-4e8f-9b6c-1a2b3c4d5e6f"
LIC_ID = "11111111-2222-4333-8444-555555555555"
URL = "https://central.exemplo.invalid/v1/sincronizar"


def codigo(dias=30, loja="LOJA-1", semente=SEMENTE):
    return licenca.gerar_licenca(semente, loja, dias, date(2026, 10, 3))


class HttpPonte:
    """Falso compatível com requests: responde por rota e guarda as chamadas.

    Imita a regra da central para pedidos: POST repetido devolve a situação; o pedido só fica "atendida" quando o
    contato informa aplicada uma licença publicada (via `publicar`) DEPOIS do pedido."""

    def __init__(self, licenca_resp=None, contato=204, solicitacao=201, erro=None):
        self.licenca = licenca_resp if licenca_resp is not None else Resposta(404, {"detail": "sem código"})
        self.contato, self.solicitacao, self.erro = contato, solicitacao, erro
        self.chamadas = []
        self.pedidos = {}
        self.atende = {}

    def publicar(self, resposta):
        self.licenca = resposta
        self.atende[resposta.json()["id"]] = {p for p, s in self.pedidos.items() if s == "pendente"}

    def get(self, url, headers=None, timeout=None, params=None):
        self.chamadas.append(("GET", url, headers, None))
        if self.erro:
            raise self.erro
        return self.licenca

    def post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append(("POST", url, headers, json))
        if self.erro:
            raise self.erro
        if url.endswith("/solicitacoes"):
            if self.solicitacao not in (200, 201):
                return Resposta(self.solicitacao, {})
            situacao = self.pedidos.setdefault(json["id"], "pendente")
            return Resposta(self.solicitacao, {"id": json["id"], "situacao": situacao})
        for p in self.atende.get(json.get("licenca_aplicada_id"), ()):
            self.pedidos[p] = "atendida"
        return Resposta(self.contato, {})

    def rotas(self):
        return [(m, u.rsplit("/v1/", 1)[1]) for m, u, _, _ in self.chamadas]


class BasePonte(BaseTeste):
    def setUp(self):
        super().setUp()
        chave = mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA)
        chave.start()
        self.addCleanup(chave.stop)
        b = self.banco
        b.cfg_set("chave_loja", "LOJA-1")
        b.cfg_set("licenca_exigir", "S")
        b.cfg_set("api_url", URL)
        b.cfg_set("api_token", "")
        b.cfg_set(ponte.CHAVE_CAIXA_ID, CAIXA)
        b.cfg_set(ponte.CHAVE_TOKEN, TOKEN)
        b.cfg_set(ponte.CHAVE_ATIVA, "S")

    def publicada(self, cod, id_=LIC_ID):
        return Resposta(200, {"id": id_, "codigo": cod, "expira_em": "2026-11-02"})


class TesteDesligada(BaseTeste):
    def test_padrao_desligado_com_id_de_caixa_persistente(self):
        self.assertEqual(self.banco.cfg(ponte.CHAVE_ATIVA), "N")
        self.assertEqual(self.banco.cfg(ponte.CHAVE_TOKEN), "")
        caixa = self.banco.cfg(ponte.CHAVE_CAIXA_ID)
        self.assertEqual(ponte.uuid_valido(caixa), caixa)
        from src.database import sementes
        sementes.aplicar(self.banco)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_CAIXA_ID), caixa)     # não muda a cada abertura
        self.assertNotEqual(BancoDados(":memory:").cfg(ponte.CHAVE_CAIXA_ID), caixa)

    def test_desligada_nao_faz_rede_nem_muda_licenca_nuvem(self):
        http = HttpPonte()
        self.banco.cfg_set("api_url", URL)
        self.banco.cfg_set(ponte.CHAVE_TOKEN, TOKEN)
        self.assertIsNone(ponte.rodada(self.banco, http, forcar=True))
        self.assertEqual(http.chamadas, [])
        with self.assertRaises(ErroNegocio):
            ponte.solicitar_renovacao(self.banco, http)
        self.assertEqual(http.chamadas, [])
        self.banco.cfg_set("licenca_exigir", "S")
        self.assertTrue(licenca_nuvem.iniciar_consulta(self.banco))      # legado continua como antes

    def test_sincronizador_desligado_nao_chama_ponte(self):
        self.banco.cfg_set("api_url", URL)
        http = mock.Mock()
        http.get.side_effect = OSError("sem rede")
        Sincronizador(self.banco, http).rodada()
        self.assertFalse(any("/ponte/" in str(c) for c in http.get.call_args_list + http.post.call_args_list))


class TesteUrlEConfig(BasePonte):
    def test_https_obrigatorio_exceto_loopback(self):
        self.assertTrue(ponte.url_segura("https://central.exemplo.invalid"))
        for url in ("http://127.0.0.1:8000", "http://localhost/v1", "http://[::1]:9000"):
            self.assertTrue(ponte.url_segura(url), url)
        for url in ("http://central.exemplo.invalid", "ftp://x", "", "https://", "http://10.0.0.5"):
            self.assertFalse(ponte.url_segura(url), url)

    def test_rotas_derivadas_do_endereco_da_nuvem(self):
        self.assertEqual(ponte.url_ponte(URL, "licenca"), "https://central.exemplo.invalid/v1/ponte/licenca")
        self.assertEqual(ponte.url_ponte("https://c.invalid", "contato"), "https://c.invalid/v1/ponte/contato")

    def test_http_externo_e_configuracao_incompleta_nao_fazem_rede(self):
        http = HttpPonte()
        self.banco.cfg_set("api_url", "http://central.exemplo.invalid")
        r = ponte.rodada(self.banco, http, forcar=True)
        self.assertFalse(r.sucesso)
        self.assertIn("HTTPS", r.erro)
        self.banco.cfg_set("api_url", URL)
        self.banco.cfg_set(ponte.CHAVE_TOKEN, "")
        self.assertFalse(ponte.rodada(self.banco, http, forcar=True).sucesso)
        self.assertEqual(http.chamadas, [])

    def test_controller_valida_id_e_ativacao(self):
        cfg = ConfigController(self.banco)
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({ponte.CHAVE_CAIXA_ID: "caixa-1"})
        cfg.salvar_config({ponte.CHAVE_CAIXA_ID: CAIXA.upper()})
        self.assertEqual(self.banco.cfg(ponte.CHAVE_CAIXA_ID), CAIXA)
        self.banco.cfg_set(ponte.CHAVE_ATIVA, "N")
        self.banco.cfg_set(ponte.CHAVE_TOKEN, "")
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({ponte.CHAVE_ATIVA: "S"})
        self.assertEqual(self.banco.cfg(ponte.CHAVE_ATIVA), "N")             # desfeito
        cfg.salvar_config({ponte.CHAVE_ATIVA: "S", ponte.CHAVE_TOKEN: TOKEN})
        self.assertTrue(ponte.ativa(self.banco))
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({"api_url": "http://central.exemplo.invalid"})
        self.assertEqual(self.banco.cfg("api_url"), URL)
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({ponte.CHAVE_TOKEN: ""})                       # apagar o token com a ponte ligada
        self.assertEqual(self.banco.cfg(ponte.CHAVE_TOKEN), TOKEN)
        self.assertNotIn(TOKEN, str(ponte.estado(self.banco)))
        self.assertNotIn(TOKEN, ponte.resumo(self.banco))


class TesteRodada(BasePonte):
    def test_ativa_bloqueia_legado_inclusive_no_login(self):
        http = HttpPonte()
        self.banco.cfg_set("api_token", "token-da-loja")
        self.assertFalse(licenca_nuvem.iniciar_consulta(self.banco, forcar=True))
        self.assertFalse(licenca_nuvem.renovar(self.banco, http, forcar=True))
        self.assertEqual(http.chamadas, [])
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_TENTATIVA), "")

    def test_404_e_sucesso_sem_codigo_com_contato_e_espera(self):
        http = HttpPonte()
        r = ponte.rodada(self.banco, http)
        self.assertEqual(r, ponte.Resultado(True, "sem_licenca"))
        self.assertEqual(http.rotas(), [("GET", "ponte/licenca"), ("POST", "ponte/contato")])
        _, _, headers, corpo = http.chamadas[1]
        self.assertEqual(headers["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(corpo, {"versao": VERSAO, "licenca_aplicada_id": None})
        self.assertNotIn("id", corpo)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_SUCESSO), fmt.agora())
        self.assertIsNone(ponte.rodada(self.banco, http))                   # dentro da hora: sem nova chamada
        self.assertEqual(len(http.chamadas), 2)

    def test_aplica_licenca_publicada_e_marca_so_depois(self):
        cod = codigo(60)
        http = HttpPonte(self.publicada(cod))
        r = ponte.rodada(self.banco, http)
        self.assertEqual(r.licenca, "aplicada")
        self.assertEqual(self.banco.cfg("licenca_token"), cod)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_LICENCA_APLICADA), LIC_ID)
        self.assertEqual(http.chamadas[-1][3], {"versao": VERSAO, "licenca_aplicada_id": LIC_ID})
        r = ponte.rodada(self.banco, http, forcar=True)
        self.assertEqual(r.licenca, "ja_aplicada")

    def test_confirma_codigo_igual_e_valido_sem_reativar(self):
        cod = codigo(60)
        licenca.ativar(self.banco, cod)
        with mock.patch.object(licenca, "ativar") as ativar:
            r = ponte.rodada(self.banco, HttpPonte(self.publicada(" " + cod + "\n")))
        ativar.assert_not_called()
        self.assertEqual(r.licenca, "confirmada")
        self.assertEqual(self.banco.cfg(ponte.CHAVE_LICENCA_APLICADA), LIC_ID)

    def test_recusa_outra_loja_mais_curta_ou_adulterada_sem_confirmar(self):
        licenca.ativar(self.banco, codigo(60))
        atual = self.banco.cfg("licenca_token")
        for i, cod in enumerate((codigo(90, loja="OUTRA"), codigo(30), codigo(90, semente=OUTRA_SEMENTE),
                                 codigo(90)[:-3] + "AAA")):
            id_ = f"00000000-0000-4000-8000-00000000000{i}"
            with self.subTest(i=i):
                http = HttpPonte(self.publicada(cod, id_))
                r = ponte.rodada(self.banco, http, forcar=True)
                self.assertTrue(r.sucesso)                                    # recusa não é falha de comunicação
                self.assertEqual(r.licenca, "recusada")
                self.assertEqual(self.banco.cfg("licenca_token"), atual)
                self.assertEqual(self.banco.cfg(ponte.CHAVE_LICENCA_APLICADA), "")
                self.assertEqual(self.banco.cfg(ponte.CHAVE_LICENCA_RECUSADA), id_)
                self.assertTrue(self.banco.cfg(ponte.CHAVE_LICENCA_ERRO))
                self.assertEqual(http.chamadas[-1][3]["licenca_aplicada_id"], None)

    def test_resposta_malformada_e_token_recusado_sao_falhas(self):
        for resp, trecho in ((Resposta(200, {"id": "x", "codigo": "c"}), "id ou código"),
                             (Resposta(401, {}), "token deste caixa"), (Resposta(500, {}), "HTTP 500")):
            with self.subTest(trecho=trecho):
                r = ponte.rodada(self.banco, HttpPonte(resp), forcar=True)
                self.assertFalse(r.sucesso)
                self.assertIn(trecho, r.erro)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_FALHAS), "3")

    def test_falha_de_rede_redigida_com_espera_crescente_e_sem_legado(self):
        http = HttpPonte(erro=OSError(f"falhou com Authorization: Bearer {TOKEN} em {TOKEN}"))
        with self.assertLogs("pdv.ponte", "WARNING") as logs:
            r = ponte.rodada(self.banco, http)
        self.assertFalse(r.sucesso)
        for texto in (r.erro, self.banco.cfg(ponte.CHAVE_ERRO), "\n".join(logs.output)):
            self.assertNotIn(TOKEN, texto)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_FALHAS), "1")
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_TENTATIVA), "")
        self.assertIsNone(ponte.rodada(self.banco, http))                   # espera 1 minuto
        self.assertEqual(len(http.chamadas), 1)
        with mock.patch.object(fmt, "minutos_entre", return_value=1):
            self.assertFalse(ponte.rodada(self.banco, http).sucesso)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_FALHAS), "2")
        with mock.patch.object(fmt, "minutos_entre", return_value=1):
            self.assertIsNone(ponte.rodada(self.banco, http))               # agora espera 2 minutos

    def test_sincronizador_roda_ponte_sem_token_da_loja_e_sem_painel(self):
        http = HttpPonte()
        http.get = mock.Mock(side_effect=lambda url, **k: Resposta(404, {}) if "/ponte/" in url
                             else Resposta(200, {"versoes": []}))
        with mock.patch("src.sync.painel_envio.enviar") as painel:
            self.assertTrue(Sincronizador(self.banco, http).rodada())
        self.assertTrue(any("/ponte/licenca" in c.args[0] for c in http.get.call_args_list))
        self.assertTrue(self.banco.cfg(ponte.CHAVE_SUCESSO))
        painel.assert_called_once()           # o envio do painel segue com a regra própria (opt-in em painel_envio)
        self.assertNotIn("vendas", str(http.chamadas))

    def test_erro_inesperado_da_ponte_nao_derruba_a_sincronizacao(self):
        with mock.patch.object(ponte, "rodada", side_effect=RuntimeError("bug")), \
                mock.patch("src.sync.painel_envio.enviar"), \
                self.assertLogs("pdv.sync", "ERROR"):
            Sincronizador(self.banco, HttpPonte()).rodada()


class TesteResilienciaEDiagnostico(BasePonte):
    def test_falhas_seguidas_no_sync_nunca_caem_no_legado(self):
        licenca.ativar(self.banco, codigo(60))
        atual = self.banco.cfg("licenca_token")
        self.banco.cfg_set("api_token", "token-da-loja")              # mesmo com o legado configurado
        http = HttpPonte(erro=OSError("conexão recusada"))
        sync = Sincronizador(self.banco, http)
        with mock.patch.object(licenca_nuvem, "consultar_resultado") as legado, \
                mock.patch("src.sync.painel_envio.enviar"), self.assertLogs("pdv.ponte", "WARNING"):
            for _ in range(4):
                self.banco.cfg_set(ponte.CHAVE_TENTATIVA, "")          # simula o tempo de espera vencido
                sync.rodada()
            self.assertFalse(licenca_nuvem.renovar(self.banco, forcar=True))   # caminho do login
        legado.assert_not_called()
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_TENTATIVA), "")
        self.assertEqual(self.banco.cfg("licenca_token"), atual)       # nada prorrogado nem apagado
        e = ponte.estado(self.banco)
        self.assertEqual(e["falhas_seguidas"], 4)
        self.assertIn("conexão recusada", e["erro"])
        self.assertIn("4 falha(s) seguida(s)", ponte.resumo(self.banco))
        self.assertEqual(sum(1 for m, u, *_ in http.chamadas if u.endswith("/v1/ponte/licenca")), 4)

    def test_recupera_depois_da_falha_e_zera_diagnostico(self):
        ponte.rodada(self.banco, HttpPonte(erro=OSError("fora do ar")))
        self.assertEqual(ponte.estado(self.banco)["falhas_seguidas"], 1)
        r = ponte.rodada(self.banco, HttpPonte(self.publicada(codigo(60))), forcar=True)
        self.assertEqual(r, ponte.Resultado(True, "aplicada"))
        e = ponte.estado(self.banco)
        self.assertEqual((e["falhas_seguidas"], e["erro"]), (0, ""))
        self.assertEqual(e["ultimo_sucesso"], fmt.agora())

    def test_token_revogado_orienta_novo_id(self):
        r = ponte.rodada(self.banco, HttpPonte(Resposta(401, {})), forcar=True)
        self.assertIn("gere um novo ID do caixa", r.erro)
        self.assertNotIn(TOKEN, r.erro)

    def test_novo_caixa_gera_outro_uuid_apaga_token_e_desliga(self):
        licenca.ativar(self.banco, codigo(60))
        atual = self.banco.cfg("licenca_token")
        ponte.solicitar_renovacao(self.banco, HttpPonte(erro=OSError("x")))
        self.banco.cfg_set(ponte.CHAVE_LICENCA_APLICADA, LIC_ID)
        with self.assertLogs("pdv.ponte", "INFO") as logs:
            novo = ponte.novo_caixa(self.banco)
        self.assertNotEqual(novo, CAIXA)
        self.assertEqual(ponte.uuid_valido(novo), novo)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_CAIXA_ID), novo)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_TOKEN), "")
        self.assertFalse(ponte.ativa(self.banco))
        for chave in (ponte.CHAVE_LICENCA_APLICADA, ponte.CHAVE_SOLICITACAO, ponte.CHAVE_SOLICITACAO_ESTADO,
                      ponte.CHAVE_ERRO):
            self.assertEqual(self.banco.cfg(chave), "", chave)
        self.assertEqual(self.banco.cfg("licenca_token"), atual)       # a licença do caixa continua
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        http = HttpPonte()
        self.assertIsNone(ponte.rodada(self.banco, http, forcar=True))  # desligada até reaprovar: sem rede
        self.assertEqual(http.chamadas, [])
        cfg = ConfigController(self.banco)
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({ponte.CHAVE_ATIVA: "S"})                 # religar exige o token novo
        cfg.salvar_config({ponte.CHAVE_ATIVA: "S", ponte.CHAVE_TOKEN: "token-novo-aprovado"})
        ponte.rodada(self.banco, http, forcar=True)
        self.assertEqual(http.chamadas[0][2]["Authorization"], "Bearer token-novo-aprovado")

    def test_id_editavel_pela_configuracao(self):
        outro = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        ConfigController(self.banco).salvar_config({ponte.CHAVE_CAIXA_ID: outro})
        self.assertEqual(ponte.estado(self.banco)["caixa_id"], outro)


class TesteSolicitacao(BasePonte):
    def test_reusa_id_em_retentativas_e_reenvia_na_rodada(self):
        falha = HttpPonte(erro=OSError("sem rede"))
        sid = ponte.solicitar_renovacao(self.banco, falha)
        self.assertEqual(ponte.uuid_valido(sid), sid)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_SOLICITACAO_ESTADO), "pendente")
        self.assertEqual(ponte.solicitar_renovacao(self.banco, falha), sid)
        self.assertEqual([c[3] for c in falha.chamadas], [{"id": sid, "tipo": "renovacao"}] * 2)
        ok = HttpPonte()
        ponte.rodada(self.banco, ok, forcar=True)
        self.assertEqual(ok.rotas()[0], ("POST", "ponte/solicitacoes"))
        self.assertEqual(ok.chamadas[0][3], {"id": sid, "tipo": "renovacao"})
        self.assertEqual(self.banco.cfg(ponte.CHAVE_SOLICITACAO_ESTADO), "enviada")
        self.assertEqual(ponte.solicitar_renovacao(self.banco, ok), sid)   # aguardando: o mesmo id, só consulta
        self.assertEqual(ok.chamadas[-1][3], {"id": sid, "tipo": "renovacao"})
        self.assertEqual(ok.pedidos, {sid: "pendente"})
        self.assertEqual(self.banco.cfg(ponte.CHAVE_SOLICITACAO_ESTADO), "enviada")

    def _solicitacoes(self, http):
        return [c[3]["id"] for c in http.chamadas if c[1].endswith("/solicitacoes")]

    def test_dois_ciclos_de_renovacao(self):
        http = HttpPonte()
        cfg = lambda: self.banco.cfg(ponte.CHAVE_SOLICITACAO_ESTADO)
        # 1º ciclo: pedido, repetição e falha de rede não criam outro id
        sid1 = ponte.solicitar_renovacao(self.banco, http)
        self.assertEqual(ponte.solicitar_renovacao(self.banco, http), sid1)
        self.assertEqual(ponte.solicitar_renovacao(self.banco, HttpPonte(erro=OSError("sem rede"))), sid1)
        self.assertEqual((cfg(), len(http.pedidos)), ("enviada", 1))
        http.publicar(self.publicada(codigo(60), "aaaaaaaa-0000-4000-8000-000000000001"))
        self.assertEqual(ponte.rodada(self.banco, http, forcar=True), ponte.Resultado(True, "aplicada"))
        self.assertEqual((cfg(), http.pedidos[sid1]), ("atendida", "atendida"))
        antes = len(http.chamadas)
        ponte.rodada(self.banco, http, forcar=True)                    # atendido: nada de novo POST do pedido
        self.assertNotIn(("POST", "ponte/solicitacoes"), http.rotas()[antes:])
        # 2º ciclo: só agora nasce um id novo, também único apesar das falhas
        sid2 = ponte.solicitar_renovacao(self.banco, HttpPonte(erro=OSError("sem rede")))
        self.assertNotEqual(sid2, sid1)
        self.assertEqual(cfg(), "pendente")
        self.assertEqual(ponte.solicitar_renovacao(self.banco, HttpPonte(erro=OSError("sem rede"))), sid2)
        ponte.rodada(self.banco, http, forcar=True)                    # a sincronização entrega o pendente
        self.assertEqual((cfg(), http.pedidos[sid2]), ("enviada", "pendente"))
        http.publicar(self.publicada(codigo(90), "aaaaaaaa-0000-4000-8000-000000000002"))
        ponte.rodada(self.banco, http, forcar=True)
        self.assertEqual((cfg(), http.pedidos[sid2]), ("atendida", "atendida"))
        self.assertEqual(self.banco.cfg("licenca_token"), "".join(codigo(90).split()))
        sid3 = ponte.solicitar_renovacao(self.banco, http)
        self.assertNotIn(sid3, (sid1, sid2))
        self.assertEqual(set(http.pedidos), {sid1, sid2, sid3})       # três pedidos reais, nenhum duplicado

    def test_licenca_publicada_antes_do_pedido_nao_o_atende_nem_repete_consulta(self):
        http = HttpPonte()
        http.publicar(self.publicada(codigo(60)))
        sid = ponte.solicitar_renovacao(self.banco, http)
        ponte.rodada(self.banco, http, forcar=True)                    # aplica a licença antiga ao pedido
        self.assertEqual((self.banco.cfg(ponte.CHAVE_SOLICITACAO_ESTADO), http.pedidos[sid]), ("enviada", "pendente"))
        self.assertEqual(self._solicitacoes(http), [sid, sid])         # conferiu uma vez depois de aplicar
        ponte.rodada(self.banco, http, forcar=True)
        self.assertEqual(self._solicitacoes(http), [sid, sid])         # mesma licença: não pergunta de novo
        self.assertEqual(ponte.solicitar_renovacao(self.banco, http), sid)

    def test_falha_ao_conferir_atendimento_reconfere_na_proxima_rodada(self):
        http = HttpPonte()
        sid = ponte.solicitar_renovacao(self.banco, http)
        http.publicar(self.publicada(codigo(60)))
        http.solicitacao = 503
        r = ponte.rodada(self.banco, http, forcar=True)
        self.assertFalse(r.sucesso)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_SOLICITACAO_ESTADO), "enviada")
        http.solicitacao = 201
        ponte.rodada(self.banco, http, forcar=True)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_SOLICITACAO_ESTADO), "atendida")
        self.assertEqual(set(http.pedidos), {sid})

    def test_desligada_ou_mal_configurada_levanta(self):
        self.banco.cfg_set(ponte.CHAVE_TOKEN, "")
        with self.assertRaises(ErroValidacao):
            ponte.solicitar_renovacao(self.banco, HttpPonte())
        self.banco.cfg_set(ponte.CHAVE_ATIVA, "N")
        with self.assertRaises(ErroNegocio):
            ponte.solicitar_renovacao(self.banco, HttpPonte())


class TesteServicoPonte(unittest.TestCase):
    """Thread própria da ponte (antes do login, sem depender do --sync): banco em arquivo, sem Tk."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        chave = mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA)
        chave.start()
        self.addCleanup(chave.stop)
        self.caminho = os.path.join(self.dir, "pdv.db")
        self.banco = BancoDados(self.caminho)
        self.addCleanup(self.banco.fechar)
        for k, v in (("chave_loja", "LOJA-1"), ("api_url", URL), ("api_token", ""), (ponte.CHAVE_CAIXA_ID, CAIXA),
                     (ponte.CHAVE_TOKEN, TOKEN), (ponte.CHAVE_ATIVA, "S")):
            self.banco.cfg_set(k, v)

    def servico(self, http):
        s = ponte.ServicoPonte(self.caminho, http, intervalo=0.05)
        self.addCleanup(s.parar)
        return s

    def esperar(self, condicao, limite=6.0):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            if condicao():
                return True
            time.sleep(0.05)
        return False

    def test_recusa_banco_em_memoria(self):
        with self.assertRaises(ErroNegocio):
            ponte.ServicoPonte(":memory:")

    def test_aplica_licenca_sem_sync_e_para(self):
        http = HttpPonte(self.publicada())
        s = self.servico(http)
        self.assertFalse(s.ativo)
        s.iniciar()
        s.iniciar()                                                    # idempotente: uma thread só
        self.assertTrue(s.ativo)
        self.assertEqual(sum(1 for t in threading.enumerate() if t.name == "ponte-central"), 1)
        self.assertTrue(self.esperar(lambda: self.banco.cfg(ponte.CHAVE_LICENCA_APLICADA) == LIC_ID))
        self.assertEqual(self.banco.cfg("licenca_token"), "".join(codigo(60).split()))
        inicio = time.monotonic()
        s.parar(timeout=3)
        self.assertLess(time.monotonic() - inicio, 3)
        self.assertFalse(s.ativo)
        get = sum(1 for m, *_ in http.chamadas if m == "GET")
        time.sleep(0.2)
        self.assertEqual(sum(1 for m, *_ in http.chamadas if m == "GET"), get)  # parado: sem rede
        self.assertEqual(get, 1)                                       # dentro do intervalo de contato: uma vez só

    def publicada(self):
        return Resposta(200, {"id": LIC_ID, "codigo": codigo(60), "expira_em": "2026-12-02"})

    def test_desligada_nao_faz_rede(self):
        self.banco.cfg_set(ponte.CHAVE_ATIVA, "N")
        http = HttpPonte()
        s = self.servico(http)
        s.iniciar()
        time.sleep(0.3)
        self.assertTrue(s.ativo)
        self.assertEqual(http.chamadas, [])
        s.parar()
        self.assertFalse(s.ativo)

    def test_falha_registra_erro_sem_token_recua_e_sobrevive(self):
        http = HttpPonte(erro=OSError("recusada Bearer " + TOKEN))
        s = self.servico(http)
        with self.assertLogs("pdv.ponte", "WARNING") as logs:
            s.iniciar()
            self.assertTrue(self.esperar(lambda: s.ultimo_erro))
            time.sleep(0.3)
        self.assertTrue(s.ativo)                                       # erro de rede não mata a thread
        self.assertEqual(len(http.chamadas), 1)                        # recuo de 1 min: sem martelar a central
        self.assertNotIn(TOKEN, s.ultimo_erro + "".join(logs.output) + self.banco.cfg(ponte.CHAVE_ERRO))
        self.assertEqual(self.banco.cfg(ponte.CHAVE_FALHAS), "1")

    def test_erro_inesperado_e_logado_redigido_e_thread_continua(self):
        s = self.servico(HttpPonte())
        with mock.patch.object(ponte, "rodada", side_effect=RuntimeError("falhou " + TOKEN)), \
                self.assertLogs("pdv.ponte", "ERROR") as logs:
            s.iniciar()
            self.assertTrue(self.esperar(lambda: s.ultimo_erro))
            self.assertTrue(s.ativo)
        self.assertNotIn(TOKEN, s.ultimo_erro + "".join(logs.output))

    def test_banco_ausente_ou_ilegivel_fica_inativo_com_erro(self):
        ruim = os.path.join(self.dir, "pasta-que-nao-existe", "x", "pdv.db")
        s = ponte.ServicoPonte(ruim, HttpPonte())
        with mock.patch("src.database.conexao.BancoDados", side_effect=OSError("sem acesso")), \
                self.assertLogs("pdv.ponte", "ERROR"):
            s.iniciar()
            self.assertTrue(self.esperar(lambda: not s.ativo))
        self.assertIn("sem acesso", s.ultimo_erro)
        s.parar()


class TesteHttpUrllib(unittest.TestCase):
    def test_converte_http_error_e_recusa_redirecionamento(self):
        cliente = ponte.HttpUrllib()
        erro = urllib.error.HTTPError("https://x.invalid", 404, "nf", {}, None)
        with mock.patch.object(cliente, "_abrir", side_effect=erro):
            self.assertEqual(cliente.get("https://x.invalid/v1/ponte/licenca").status_code, 404)
        handler = ponte._SemRedirecionar()
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "http://outro.invalid"))


if os.environ.get("QT_QPA_PLATFORM") is None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
try:
    from PySide6.QtWidgets import QApplication, QLineEdit
except ImportError:                                    # pragma: no cover - Qt opcional
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 não instalado")
class TesteTelaQt(BasePonte):
    def setUp(self):
        super().setUp()
        from src.controllers.contexto import Contexto
        from src.ui_qt.configuracoes import SECOES, JanelaConfiguracoes
        self.app = QApplication.instance() or QApplication([])
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.banco.cfg_set(ponte.CHAVE_ATIVA, "N")
        self.janela = JanelaConfiguracoes(self.ctx)
        self.addCleanup(self.janela.close)
        self.janela.abas.setCurrentIndex(SECOES.index("nuvem"))

    def test_token_do_caixa_oculto_copiar_id_e_apagar(self):
        campo = self.janela.campos["nuvem"][ponte.CHAVE_TOKEN]
        self.assertEqual(campo.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(campo.text(), "")
        self.assertNotIn(TOKEN, repr(self.janela._originais))
        self.assertTrue(self.janela.salvar())
        self.assertEqual(self.banco.cfg(ponte.CHAVE_TOKEN), TOKEN)          # vazio mantém
        campo.setText("novo-token-caixa")
        self.assertTrue(self.janela.salvar())
        self.assertEqual(self.banco.cfg(ponte.CHAVE_TOKEN), "novo-token-caixa")
        self.assertEqual(campo.text(), "")
        self.assertEqual(self.janela.copiar_id_caixa(), CAIXA)
        self.assertEqual(QApplication.clipboard().text(), CAIXA)
        self.janela.apagar_token_caixa.setChecked(True)
        self.assertTrue(self.janela.salvar())
        self.assertEqual(self.banco.cfg(ponte.CHAVE_TOKEN), "")
        self.assertEqual(self.banco.cfg("api_token"), "")

    def test_gerar_novo_id_pede_confirmacao_e_desliga(self):
        from PySide6.QtWidgets import QMessageBox
        self.banco.cfg_set(ponte.CHAVE_ATIVA, "S")
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertIsNone(self.janela.gerar_novo_id_caixa())
        self.assertEqual(self.banco.cfg(ponte.CHAVE_CAIXA_ID), CAIXA)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            novo = self.janela.gerar_novo_id_caixa()
        self.assertNotEqual(novo, CAIXA)
        self.assertEqual(self.janela.campos["nuvem"][ponte.CHAVE_CAIXA_ID].text(), novo)
        self.assertFalse(self.janela.campos["nuvem"][ponte.CHAVE_ATIVA].isChecked())
        self.assertEqual(QApplication.clipboard().text(), novo)
        self.assertEqual(self.banco.cfg(ponte.CHAVE_TOKEN), "")
        self.assertFalse(ponte.ativa(self.banco))
        self.assertTrue(self.janela.salvar())                          # salvar depois não desfaz nada
        self.assertEqual(self.banco.cfg(ponte.CHAVE_CAIXA_ID), novo)

    def test_ligar_sem_token_mostra_erro_e_nao_grava(self):
        self.banco.cfg_set(ponte.CHAVE_TOKEN, "")
        self.janela.campos["nuvem"][ponte.CHAVE_ATIVA].setChecked(True)
        self.assertFalse(self.janela.salvar())
        self.assertIn("token do caixa", self.janela.mensagem.text())
        self.assertFalse(ponte.ativa(self.banco))


if __name__ == "__main__":
    unittest.main()
