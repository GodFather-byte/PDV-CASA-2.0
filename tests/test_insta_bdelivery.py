"""Insta-BDelivery: a vitrine de delivery manda pedido para o caixa e recebe o cardápio, ao lado do canal da nuvem."""
from __future__ import annotations

from src.controllers.config_controller import CAMPOS_CONFIG
from src.controllers.pedido_online_controller import marca, resumo
from src.sync import cardapio_envio, insta_bdelivery as insta, pedidos_online as rede
from tests.test_pedido_online import BasePedido

NUVEM = "https://nuvem.exemplo"
VITRINE = "https://vitrine.exemplo/api/pdv"


class _Resposta:
    def __init__(self, status, corpo):
        self.status_code, self._corpo = status, corpo

    def json(self):
        return self._corpo


class HttpDoisCanais:
    """Responde pela nuvem e pela vitrine, guardando cada chamada. `fora` tira um dos dois do ar."""

    def __init__(self, na_nuvem=(), na_vitrine=(), fora=()):
        self.na_nuvem, self.na_vitrine, self.fora, self.chamadas = list(na_nuvem), list(na_vitrine), set(fora), []

    def _responder(self, metodo, url, corpo, headers):
        canal = "vitrine" if url.startswith(VITRINE) else "nuvem"
        self.chamadas.append((metodo, url, corpo, (headers or {}).get("Authorization")))
        if canal in self.fora:
            return _Resposta(500, {"detail": f"{canal} fora do ar"})
        if metodo == "GET":
            return _Resposta(200, {"pedidos": self.na_vitrine if canal == "vitrine" else self.na_nuvem})
        return _Resposta(200, {"situacao": "aceito", "produtos": len((corpo or {}).get("produtos") or [])})

    def get(self, url, headers=None, timeout=None):
        return self._responder("GET", url, None, headers)

    def post(self, url, json=None, headers=None, timeout=None):
        return self._responder("POST", url, json, headers)

    def para(self, canal):
        prefixo = VITRINE if canal == "vitrine" else NUVEM
        return [c for c in self.chamadas if c[1].startswith(prefixo)]


class BaseInsta(BasePedido):
    def setUp(self):
        super().setUp()
        for chave, valor in (("api_url", f"{NUVEM}/v1/sincronizar"), ("api_token", "tk-nuvem"),
                             (insta.CHAVE_URL, VITRINE + "/"), (insta.CHAVE_TOKEN, "ibd_chave")):
            self.banco.cfg_set(chave, valor)


class TesteCanais(BaseInsta):
    def test_campos_na_aba_nuvem_e_a_chave_e_segredo(self):
        campos = {c[0]: c for c in CAMPOS_CONFIG}
        self.assertEqual((campos[insta.CHAVE_URL][2], campos[insta.CHAVE_URL][3]), ("texto", "Nuvem"))
        self.assertEqual((campos[insta.CHAVE_TOKEN][2], campos[insta.CHAVE_TOKEN][3]), ("segredo", "Nuvem"))

    def test_cada_canal_liga_sozinho_e_o_endereco_perde_a_barra_final(self):
        self.assertEqual(rede.fontes(self.banco), [("", NUVEM, "tk-nuvem"), ("insta", VITRINE, "ibd_chave")])
        self.banco.cfg_set("api_token", "")
        self.assertTrue(rede.ligado(self.banco))
        self.assertEqual(rede.fontes(self.banco), [("insta", VITRINE, "ibd_chave")])
        self.banco.cfg_set(insta.CHAVE_TOKEN, "")
        self.assertFalse(rede.ligado(self.banco))
        self.assertEqual(rede.fontes(self.banco), [])
        self.banco.cfg_set(insta.CHAVE_TOKEN, "ibd_chave")
        self.banco.cfg_set("pedido_online", "N")                 # módulo desligado: nenhum canal
        self.assertFalse(rede.ligado(self.banco))

    def test_busca_junta_os_canais_e_o_da_vitrine_ganha_id_negativo(self):
        http = HttpDoisCanais(na_nuvem=[{"id": 31, "numero": 5, "nome": "Maria"}],
                              na_vitrine=[{"id": 5, "numero": 5, "nome": "Paula"}])
        pedidos, erro = rede.consultar_fontes(rede.fontes(self.banco), http)
        self.assertEqual(erro, "")
        self.assertEqual([(p["id"], p["numero"], p.get("canal", "")) for p in pedidos], [(31, 5, ""), (-5, 5, "insta")])
        self.assertEqual(http.para("vitrine")[0][1], f"{VITRINE}/v1/pedidos-online")
        self.assertEqual(http.para("vitrine")[0][3], "Bearer ibd_chave")
        self.assertEqual(http.para("nuvem")[0][3], "Bearer tk-nuvem")
        self.assertEqual(rede.novos(self.banco, http), pedidos)

    def test_um_canal_fora_do_ar_nao_esconde_o_outro(self):
        http = HttpDoisCanais(na_nuvem=[{"id": 31, "numero": 5}], na_vitrine=[{"id": 5, "numero": 5}], fora={"vitrine"})
        pedidos, erro = rede.consultar_fontes(rede.fontes(self.banco), http)
        self.assertEqual([p["id"] for p in pedidos], [31])
        self.assertIn("vitrine fora do ar", erro)
        self.assertEqual([p["id"] for p in rede.novos(self.banco, http)], [31])
        tudo_fora = HttpDoisCanais(fora={"vitrine", "nuvem"})
        with self.assertRaisesRegex(RuntimeError, "fora do ar"):
            rede.novos(self.banco, tudo_fora)

    def test_resposta_torta_da_vitrine_vira_erro_e_nao_derruba_a_busca(self):
        http = HttpDoisCanais(na_nuvem=[{"id": 31, "numero": 5}], na_vitrine=[{"sem_numero": True}])
        pedidos, erro = rede.consultar_fontes(rede.fontes(self.banco), http)
        self.assertEqual([p["id"] for p in pedidos], [31])
        self.assertIn("resposta inesperada", erro)

    def test_resposta_do_caixa_vai_para_o_canal_do_pedido(self):
        http = HttpDoisCanais()
        rede.aceitar(self.banco, -5, http)
        rede.recusar(self.banco, -6, "Produto em falta", http)
        rede.atualizar_situacao(self.banco, -5, "saiu", http=http)
        rede.aceitar(self.banco, 31, http)
        self.assertEqual([(c[1], c[2]) for c in http.para("vitrine")], [
            (f"{VITRINE}/v1/pedidos-online/5/aceitar", {}),
            (f"{VITRINE}/v1/pedidos-online/6/recusar", {"motivo": "Produto em falta"}),
            (f"{VITRINE}/v1/pedidos-online/5/situacao", {"situacao": "saiu", "motivo": ""})])
        self.assertTrue(all(c[3] == "Bearer ibd_chave" for c in http.para("vitrine")))
        self.assertEqual([(c[1], c[3]) for c in http.para("nuvem")],
                         [(f"{NUVEM}/v1/pedidos-online/31/aceitar", "Bearer tk-nuvem")])


class TesteImportarDaVitrine(BaseInsta):
    def test_mesmo_numero_nos_dois_canais_vira_duas_entregas(self):
        da_nuvem = self.ctrl.importar(self.pedido(id=31))
        da_vitrine = self.ctrl.importar(insta.normalizar(self.pedido(id=7, telefone="11955554444")))
        self.assertNotEqual(da_nuvem["venda_id"], da_vitrine["venda_id"])
        venda = self.caixa.obter(da_vitrine["venda_id"])
        self.assertTrue(venda["mensagem"].startswith("Pedido Insta #7 · "))
        self.assertEqual(venda["pedido_online_id"], -7)
        self.assertEqual(self.caixa.obter(da_nuvem["venda_id"])["pedido_online_id"], 31)
        de_novo = self.ctrl.importar(insta.normalizar(self.pedido(id=7, telefone="11955554444")))
        self.assertEqual((de_novo["venda_id"], de_novo["ja_existia"]), (da_vitrine["venda_id"], True))
        self.assertEqual(self.ctrl.ja_importado(7, -7, "insta"), da_vitrine["venda_id"])
        self.assertEqual(self.ctrl.ja_importado(7, 31), da_nuvem["venda_id"])
        self.assertIsNone(self.ctrl.ja_importado(8, -8, "insta"))

    def test_marca_e_resumo_dizem_o_canal(self):
        self.assertEqual((marca(7), marca(7, "insta")), ("Pedido online #7", "Pedido Insta #7"))
        self.assertTrue(resumo(insta.normalizar(self.pedido())).startswith("Insta #7 · JOAO"))
        self.assertTrue(resumo(self.pedido()).startswith("#7 · JOAO"))

    def test_aviso_de_saiu_e_cancelado_sobe_para_a_vitrine(self):
        r = self.ctrl.importar(insta.normalizar(self.pedido(id=7)))
        http = HttpDoisCanais()
        rede.empurrar_avisos(self.banco, http)                                   # aceito, ainda não confirmado
        self.assertEqual([c[1] for c in http.para("vitrine")], [f"{VITRINE}/v1/pedidos-online/7/aceitar"])
        self.assertEqual(http.para("nuvem"), [])
        rede.empurrar_avisos(self.banco, http)
        self.assertEqual(len(http.chamadas), 1)                                  # confirmado: não repete
        self.caixa.marcar_aviso_online(r["venda_id"], "saiu")
        fora = HttpDoisCanais(fora={"vitrine"})
        rede.empurrar_avisos(self.banco, fora)                                   # sem resposta: fica na fila
        rede.empurrar_avisos(self.banco, http)
        self.assertEqual(http.para("vitrine")[-1][1:3],
                         (f"{VITRINE}/v1/pedidos-online/7/situacao", {"situacao": "saiu", "motivo": ""}))
        self.assertEqual(self.banco.valor("SELECT pedido_online_aviso_ok FROM vendas WHERE id = ?", (r["venda_id"],)), 1)


class TesteCardapioNaVitrine(BaseInsta):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("cardapio_digital", "S")

    def test_catalogo_sobe_para_os_dois_e_so_reenvia_o_que_mudou(self):
        http = HttpDoisCanais()
        self.assertTrue(cardapio_envio.precisa_enviar(self.banco))
        resultado = cardapio_envio.enviar(self.banco, http)
        self.assertTrue(resultado["enviado"])
        self.assertEqual([c[1] for c in http.chamadas], [f"{NUVEM}/v1/cardapio/envio", f"{VITRINE}/v1/cardapio/envio"])
        corpo = http.para("vitrine")[0][2]
        self.assertTrue(any(p.get("codigo") == self.cod_skol for p in corpo["produtos"]))
        self.assertEqual(http.para("vitrine")[0][3], "Bearer ibd_chave")
        self.assertFalse(cardapio_envio.precisa_enviar(self.banco))
        cardapio_envio.enviar(self.banco, http)
        self.assertEqual(len(http.chamadas), 2)                                  # nada mudou: não chama ninguém
        self.banco.cfg_set(insta.CHAVE_TOKEN, "ibd_outra")                       # chave nova: só a vitrine recebe
        self.assertTrue(cardapio_envio.precisa_enviar(self.banco))
        cardapio_envio.enviar(self.banco, http)
        self.assertEqual([c[1] for c in http.chamadas[2:]], [f"{VITRINE}/v1/cardapio/envio"])
        self.assertEqual(http.chamadas[-1][3], "Bearer ibd_outra")

    def test_vitrine_fora_do_ar_nao_segura_a_nuvem_e_tenta_de_novo(self):
        fora = HttpDoisCanais(fora={"vitrine"})
        self.assertTrue(cardapio_envio.enviar(self.banco, fora)["enviado"])      # a nuvem publicou
        self.assertEqual(self.banco.cfg(insta.CHAVE_HASH), "")
        self.assertTrue(cardapio_envio.precisa_enviar(self.banco))
        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            cardapio_envio.enviar_insta(self.banco, fora)
        http = HttpDoisCanais()
        cardapio_envio.enviar(self.banco, http)
        self.assertEqual([c[1] for c in http.chamadas], [f"{VITRINE}/v1/cardapio/envio"])
        self.assertFalse(cardapio_envio.precisa_enviar(self.banco))

    def test_nuvem_fora_do_ar_nao_segura_a_vitrine(self):
        fora = HttpDoisCanais(fora={"nuvem"})
        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            cardapio_envio.enviar(self.banco, fora)
        self.assertEqual(len(fora.para("vitrine")), 1)
        self.assertNotEqual(self.banco.cfg(insta.CHAVE_HASH), "")

    def test_sem_endereco_ou_chave_a_vitrine_fica_de_fora(self):
        self.banco.cfg_set(insta.CHAVE_URL, "")
        http = HttpDoisCanais()
        self.assertIsNone(cardapio_envio.enviar_insta(self.banco, http))
        cardapio_envio.enviar(self.banco, http)
        self.assertEqual(http.para("vitrine"), [])
        self.assertFalse(cardapio_envio.insta_precisa_enviar(self.banco))
