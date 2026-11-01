"""Porteiro no celular: consulta somente leitura da comanda, PIN e página na rede local."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers.cadastro_controller import CadastroController
from src.controllers.caixa_controller import CaixaController
from src.controllers.config_controller import ConfigController
from src.controllers.turno_controller import TurnoController
from src.core import seguranca
from src.core.erros import ErroNegocio, ErroValidacao
from src.database.conexao import BancoDados
from src.porteiro.consulta import consultar
from src.porteiro.servico import definir_pin, descrever, png_qr, urls_publicas
from src.porteiro.servidor import ServidorPorteiro, pasta_web
from tests.test_caixa import BaseCaixa

RAIZ = Path(__file__).resolve().parents[1]
PIN = "2468"


class TesteConsulta(BaseCaixa):
    def comanda(self, numero=7, itens=((None, 1),)):
        vid, _ = self.caixa.abrir_mesa(numero, comanda=True)
        for pid, qtd in itens:
            self.caixa.adicionar_item(vid, self.skol if pid is None else pid, qtd)
        return vid

    def test_comanda_com_consumo_esta_devendo_com_servico_e_itens(self):
        self.comanda()
        r = consultar(self.banco, "7")
        self.assertEqual(r["situacao"], "devendo")
        self.assertEqual(r["titulo"], "DEVENDO")
        self.assertEqual(r["devido_cent"], 880)          # 8,00 + 10% de serviço
        self.assertEqual(r["valor_txt"], "R$ 8,80")
        nomes = [i["nome"] for i in r["itens"]]
        self.assertEqual(nomes, ["SKOL", "Serviço"])
        self.assertEqual(r["itens"][0]["total_cent"], 800)
        self.assertEqual(r["itens"][1]["total_cent"], 80)
        self.assertIn("Comanda 7", r["cabecalho"])
        self.assertEqual(r["fonte"], "caixa")
        self.assertIn("agora, no caixa", r["origem_txt"])

    def test_pagamento_parcial_mostra_o_que_falta(self):
        vid = self.comanda()
        self.pagar(vid, "Dinheiro", 400)
        r = consultar(self.banco, "7")
        self.assertEqual((r["situacao"], r["devido_cent"], r["pago_cent"]), ("devendo", 480, 400))
        self.assertIn("R$ 4,80", r["detalhe"])
        self.assertIn("R$ 4,00", r["detalhe"])

    def test_item_pago_na_divisao_sai_da_lista_e_o_servico_continua(self):
        vid = self.comanda()
        item = self.caixa.itens(vid)[0]["id"]
        self.caixa.pagar_itens(vid, self.tipo("Dinheiro"), [(item, 1)])
        r = consultar(self.banco, "7")
        self.assertEqual(r["devido_cent"], 80)
        self.assertEqual([i["nome"] for i in r["itens"]], ["Serviço"])

    def test_valor_quitado_sem_fechar_libera(self):
        vid = self.comanda()
        self.pagar(vid, "Dinheiro", 880)
        r = consultar(self.banco, "7")
        self.assertEqual((r["situacao"], r["motivo"], r["devido_cent"]), ("liberada", "quitada", 0))
        self.assertEqual(self.caixa.obter(vid)["status"], "aberta")

    def test_conta_fechada_libera_e_a_reaberta_volta_a_dever(self):
        vid = self.comanda()
        self.pagar(vid, "Dinheiro", 880)
        fechada = self.caixa.fechar(vid)
        r = consultar(self.banco, "7")
        self.assertEqual(r["situacao"], "liberada")
        self.assertEqual(r["motivo"], "paga")
        self.assertIn(f"cupom {fechada['cupom']}", r["detalhe"])
        self.comanda()
        de_novo = consultar(self.banco, "7")
        self.assertEqual(de_novo["situacao"], "devendo")
        self.assertEqual(de_novo["devido_cent"], 880)

    def test_vazia_cancelada_e_sem_registro_liberam(self):
        vid, _ = self.caixa.abrir_mesa(3, comanda=True)
        self.assertEqual(consultar(self.banco, "3")["motivo"], "vazia")
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.caixa.cancelar_venda(vid, "cliente desistiu")
        self.assertEqual(consultar(self.banco, "3")["motivo"], "cancelada")
        self.assertEqual(consultar(self.banco, "99")["motivo"], "sem_registro")
        self.assertEqual(consultar(self.banco, "99")["situacao"], "liberada")

    def test_mesa_e_comanda_com_o_mesmo_numero_nao_se_misturam(self):
        self.comanda(5)
        mesa, _ = self.caixa.abrir_mesa(5)
        self.caixa.adicionar_item(mesa, self.agua, 1)
        comanda = consultar(self.banco, "5")
        outra = consultar(self.banco, "M5")
        self.assertEqual(comanda["devido_cent"], 880)
        self.assertEqual(outra["nome"], "Mesa 5")
        self.assertNotEqual(outra["devido_cent"], comanda["devido_cent"])
        self.assertIn("AGUA", [i["nome"] for i in outra["itens"]])

    def test_apelido_aparece_e_a_consumacao_entra_no_valor(self):
        vid = self.comanda()
        self.caixa.definir_apelido(vid, "Carlos")
        self.banco.cfg_set("consumacao_minima", "20")
        r = consultar(self.banco, "7")
        self.assertIn("Carlos", r["cabecalho"])
        self.assertEqual(r["devido_cent"], 2080)          # 8,00 + serviço 0,80 + consumação até 20,00
        self.assertIn("Consumação mínima", [i["nome"] for i in r["itens"]])

    def test_consulta_nao_grava_nem_atualiza_o_total_da_venda(self):
        vid = self.comanda()
        self.banco.executar("UPDATE vendas SET total_cent = 1 WHERE id = ?", (vid,))
        antes = self._retrato()
        r = consultar(self.banco, "7")
        self.assertEqual(r["devido_cent"], 880)
        self.assertEqual(self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (vid,)), 1)
        self.assertEqual(self.caixa.obter(vid)["status"], "aberta")
        self.assertEqual(self._retrato(), antes)

    def test_lista_omite_comanda_da_garota_e_a_consulta_do_numero_continua(self):
        from src.controllers.comissao_controller import ComissaoController
        from src.core import formatacao as fmt
        from src.porteiro.consulta import listar_abertas, retrato
        self.comanda(7)
        self.comanda(12)
        self.comanda(13)
        self.caixa.abrir_mesa(5)
        ComissaoController(self.banco).lancar(12, 5000, self.turno, self.adm)
        self.banco.inserir("comissoes_garotas", {
            "garota": 13, "valor_cent": 1000, "turno_id": self.turno, "operador_id": self.adm,
            "criado_em": fmt.agora(), "status": "paga", "paga_em": fmt.agora()})
        antes = self._retrato()
        lista = listar_abertas(self.banco)
        self.assertEqual([c["numero"] for c in lista["comandas"]], [7, 13])
        self.assertTrue(lista["comandas"][0]["aberta_em"])
        self.assertTrue(lista["comandas"][0]["aberta_txt"])
        self.assertEqual(lista["fonte"], "caixa")
        self.assertNotIn("itens", lista["comandas"][0])
        marcas = {p["numero"]: p["garota"] for p in retrato(self.banco)["posicoes"]}
        self.assertTrue(marcas[12])
        self.assertFalse(marcas[7])
        self.assertFalse(marcas[5])
        vista = consultar(self.banco, "12")
        self.assertEqual(vista["situacao"], "devendo")
        self.assertTrue(vista["garota"])
        self.assertEqual(self._retrato(), antes)

    def test_numero_invalido(self):
        with self.assertRaises(ErroNegocio):
            consultar(self.banco, "abc")
        with self.assertRaises(ErroNegocio):
            consultar(self.banco, "0")

    def _retrato(self):
        return (
            self.banco.valor("SELECT COUNT(*) FROM vendas"),
            self.banco.valor("SELECT COUNT(*) FROM itens_venda"),
            self.banco.valor("SELECT COUNT(*) FROM pagamentos_venda"),
            self.banco.valor("SELECT COUNT(*) FROM log_eventos"),
        )


class TesteNuvemLocal(BaseCaixa):
    def test_retrato_so_traz_o_que_esta_aberto_e_nao_grava(self):
        from src.porteiro.consulta import frescura, retrato
        vid, _ = self.caixa.abrir_mesa(7, comanda=True)
        self.caixa.adicionar_item(vid, self.skol, 1)
        pago, _ = self.caixa.abrir_mesa(8, comanda=True)
        self.caixa.adicionar_item(pago, self.skol, 1)
        self.pagar(pago, "Dinheiro", self.caixa.obter(pago)["total_cent"])
        self.caixa.fechar(pago)
        antes = self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (vid,))
        foto = retrato(self.banco)
        self.assertEqual([p["numero"] for p in foto["posicoes"]], [7])
        self.assertEqual(foto["posicoes"][0]["devido_cent"], 880)
        self.assertNotIn("fonte", foto["posicoes"][0])
        self.assertEqual(self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (vid,)), antes)
        from src.core import formatacao as fmt
        self._hora["t"] = self.agora.replace(second=30)
        fresco = frescura("2026-10-03 21:00:00", fmt.agora())
        self.assertEqual(fresco["atualizado"], "atualizado há 30s")
        self.assertEqual(fresco["fonte"], "nuvem")

    def test_envio_leva_o_hash_e_nao_repete_a_mesma_foto(self):
        import json
        from src.porteiro.nuvem_envio import enviar_se_preciso, zerar_envio
        definir_pin(self.banco, PIN)
        self.banco.cfg_set("porteiro_ativo", "S")
        self.banco.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.banco.cfg_set("api_token", "token-da-loja")
        self.banco.cfg_set("chave_loja", "BOATE")
        vid, _ = self.caixa.abrir_mesa(7, comanda=True)
        self.caixa.adicionar_item(vid, self.skol, 1)

        class Http:
            def __init__(self):
                self.chamadas = []

            def post(self, url, json=None, headers=None, timeout=None):
                self.chamadas.append({"url": url, "corpo": json, "headers": headers})
                return type("R", (), {"status_code": 200})()

        http = Http()
        zerar_envio()
        self.assertTrue(enviar_se_preciso(self.banco, http, relogio=lambda: 100, forcar=True)["enviado"])
        self.assertEqual(http.chamadas[0]["url"], "https://nuvem.exemplo/v1/porteiro/retrato")
        self.assertEqual(http.chamadas[0]["headers"]["Authorization"], "Bearer token-da-loja")
        corpo = http.chamadas[0]["corpo"]
        self.assertNotIn("pin", corpo)
        self.assertTrue(corpo["pin_hash"].startswith("pbkdf2$"))
        self.assertNotIn(PIN, json.dumps(corpo["posicoes"]))
        self.assertEqual(corpo["posicoes"][0]["numero"], 7)
        self.assertFalse(enviar_se_preciso(self.banco, http, relogio=lambda: 110)["enviado"])
        self.assertEqual(len(http.chamadas), 1)


class TestePinEPagina(BaseCaixa):
    def test_pin_grava_hash_e_nao_o_numero(self):
        definir_pin(self.banco, PIN)
        guardado = self.banco.cfg("porteiro_pin_hash")
        self.assertNotIn(PIN, guardado)
        self.assertTrue(seguranca.conferir(PIN, guardado))
        self.assertFalse(seguranca.conferir("0000", guardado))
        detalhe = self.banco.valor("SELECT detalhe FROM log_eventos WHERE evento = 'porteiro_pin'")
        self.assertNotIn(PIN, detalhe)
        with self.assertRaises(ErroNegocio):
            definir_pin(self.banco, "12")
        with self.assertRaises(ErroValidacao):
            ConfigController(self.banco).salvar_config({"porteiro_porta": "80"})
        ConfigController(self.banco).salvar_config({"porteiro_ativo": "S", "porteiro_porta": "8765"})
        self.assertIn("/porteiro", descrever(self.banco))

    def test_arquivos_da_pwa_e_o_qr(self):
        pasta = pasta_web()
        for nome in ("index.html", "app.js", "estilo.css", "manifest.webmanifest", "sw.js",
                     "icones/icone-192.png", "icones/icone-512.png",
                     "icones/icone-maskable-192.png", "icones/icone-maskable-512.png"):
            self.assertTrue((pasta / nome).is_file(), nome)
        html = (pasta / "index.html").read_text(encoding="utf-8")
        self.assertIn('lang="pt-BR"', html)
        self.assertIn("manifest.webmanifest", html)
        js = (pasta / "app.js").read_text(encoding="utf-8")
        self.assertIn("dados.titulo", js)
        self.assertIn('register("sw.js")', js)
        css = (pasta / "estilo.css").read_text(encoding="utf-8")
        self.assertIn("liberada", css)
        self.assertIn("devendo", css)
        self.assertIn("/porteiro/api/", (pasta / "sw.js").read_text(encoding="utf-8"))
        manifesto = json.loads((pasta / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifesto["lang"], "pt-BR")
        self.assertEqual(manifesto["start_url"], "./")
        self.assertIn("serviceWorker", js)
        png = (pasta / "icones" / "icone-192.png").read_bytes()
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertTrue(png_qr(urls_publicas(8765)[0]).startswith(b"\x89PNG"))
        build = (RAIZ / "build_pdv.py").read_text(encoding="utf-8")
        self.assertIn("porteiro_web", build)
        self.assertIn("segno", build)


class TesteHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.caminho = str(Path(self.tmp.name) / "loja.db")
        self.banco = BancoDados(self.caminho)
        self.addCleanup(self.banco.fechar)
        self.adm = self.banco.valor("SELECT id FROM operadores WHERE nome = 'ADM'")
        self.caixa = CaixaController(self.banco, self.adm)
        TurnoController(self.banco).abrir(self.adm, 1, 10000)
        cad = CadastroController(self.banco)
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        un = self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
        self.skol = cad.salvar("produtos", {
            "codigo": cad.proximo_codigo_produto(), "nome": "SKOL", "subgrupo_id": sub,
            "unidade_id": un, "preco_cent": "8,00", "controla_estoque": "N"})
        vid, _ = self.caixa.abrir_mesa(7, comanda=True)
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.venda = vid
        definir_pin(self.banco, PIN)
        self.servidor = ServidorPorteiro(self.caminho, 0, "127.0.0.1")
        self.servidor.iniciar()
        self.addCleanup(self.servidor.parar)
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def url(self, caminho):
        return f"http://127.0.0.1:{self.servidor.porta}{caminho}"

    def pedir(self, metodo, caminho, corpo=None, opener=None):
        data = None if corpo is None else json.dumps(corpo).encode()
        req = urllib.request.Request(self.url(caminho), data=data, method=metodo)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with (opener or self.opener).open(req, timeout=5) as resp:
                bruto = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            bruto = exc.read()
            status = exc.code
        try:
            dados = json.loads(bruto.decode() or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            dados = None
        return status, dados, bruto

    def cru(self, pedido: bytes) -> bytes:
        with socket.create_connection(("127.0.0.1", self.servidor.porta), timeout=5) as s:
            s.settimeout(5)
            s.sendall(pedido)
            s.shutdown(socket.SHUT_WR)
            pedacos = []
            while True:
                bloco = s.recv(4096)
                if not bloco:
                    break
                pedacos.append(bloco)
            return b"".join(pedacos)

    def test_pin_sessao_consulta_e_somente_leitura(self):
        status, dados, _ = self.pedir("GET", "/porteiro/api/consulta?q=7")
        self.assertEqual(status, 401)
        status, _, _ = self.pedir("GET", "/porteiro/api/abertas")
        self.assertEqual(status, 401)
        for _ in range(4):
            status, dados, bruto = self.pedir("POST", "/porteiro/api/entrar", {"pin": "0000"})
            self.assertEqual(status, 401)
            self.assertNotIn(b"0000", bruto)
        status, _, _ = self.pedir("POST", "/porteiro/api/entrar", {"pin": "0000"})
        self.assertEqual(status, 429)
        status, _, _ = self.pedir("POST", "/porteiro/api/entrar", {"pin": PIN})
        self.assertEqual(status, 429)
        self.servidor.sessoes.zerar("127.0.0.1")
        status, dados, _ = self.pedir("POST", "/porteiro/api/entrar", {"pin": PIN})
        self.assertEqual((status, dados.get("ok")), (200, True))
        antes = self.banco.um("SELECT status, total_cent FROM vendas WHERE id = ?", (self.venda,))
        itens_antes = self.banco.valor("SELECT COUNT(*) FROM itens_venda")
        pagamentos_antes = self.banco.valor("SELECT COUNT(*) FROM pagamentos_venda")
        status, dados, _ = self.pedir("GET", "/porteiro/api/consulta?q=7")
        self.assertEqual(status, 200)
        self.assertEqual(dados["situacao"], "devendo")
        self.assertEqual(dados["devido_cent"], 880)
        status, lista, _ = self.pedir("GET", "/porteiro/api/abertas")
        self.assertEqual(status, 200)
        self.assertEqual([c["numero"] for c in lista["comandas"]], [7])
        self.assertNotIn("uuid", dados)
        self.assertNotIn("venda_id", dados)
        sem_cookie = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        status, _, _ = self.pedir("GET", "/porteiro/api/consulta?q=7", opener=sem_cookie)
        self.assertEqual(status, 401)
        status, _, _ = self.pedir("POST", "/porteiro/api/fechar", {})
        self.assertEqual(status, 404)
        self.assertIn(b"405", self.cru(
            b"DELETE /porteiro/api/consulta?q=7 HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").split(b"\r\n", 1)[0])
        depois = self.banco.um("SELECT status, total_cent FROM vendas WHERE id = ?", (self.venda,))
        self.assertEqual((antes["status"], antes["total_cent"]), (depois["status"], depois["total_cent"]))
        self.assertEqual(itens_antes, self.banco.valor("SELECT COUNT(*) FROM itens_venda"))
        self.assertEqual(pagamentos_antes, self.banco.valor("SELECT COUNT(*) FROM pagamentos_venda"))

    def test_pagina_redireciona_e_nao_vaza_arquivo(self):
        inicio = self.cru(b"GET /porteiro HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertTrue(inicio.startswith(b"HTTP/1.1 302"))
        self.assertIn(b"Location: /porteiro/\r\n", inicio)
        status, _, html = self.pedir("GET", "/porteiro/")
        self.assertEqual(status, 200)
        self.assertIn(b"pt-BR", html)
        self.assertIn(b"manifest.webmanifest", html)
        icone = urllib.request.urlopen(self.url("/porteiro/icones/icone-192.png"), timeout=5).read()
        self.assertTrue(icone.startswith(b"\x89PNG"))
        vazou = self.cru(b"GET /porteiro/%2e%2e/%2e%2e/src/porteiro/servidor.py HTTP/1.1\r\nHost: x\r\n"
                         b"Connection: close\r\n\r\n")
        self.assertTrue(vazou.startswith(b"HTTP/1.1 404"))
        self.assertNotIn(b"ServidorPorteiro", vazou)

    def test_servico_sobe_e_desce_com_a_configuracao(self):
        from src.porteiro.servico import ServicoPorteiro
        self.servidor.parar()
        self.banco.cfg_set("porteiro_ativo", "S")
        self.banco.cfg_set("porteiro_porta", "39471")
        servico = ServicoPorteiro(self.caminho, intervalo=0.1, host="127.0.0.1")
        servico.iniciar()
        self.addCleanup(servico.parar)
        self.assertTrue(self._esperar(lambda: servico._servidor is not None and servico._servidor.ativo))
        with urllib.request.urlopen("http://127.0.0.1:39471/porteiro/api/saude", timeout=3) as resp:
            self.assertEqual(json.loads(resp.read())["ok"], True)
        self.banco.cfg_set("porteiro_ativo", "N")
        self.assertTrue(self._esperar(lambda: servico._servidor is None))
        with self.assertRaises(OSError):
            urllib.request.urlopen("http://127.0.0.1:39471/porteiro/api/saude", timeout=2)

    def _esperar(self, condicao, segundos=3):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            if condicao():
                return True
            time.sleep(0.05)
        return False


class TesteJanela(BaseCaixa):
    def setUp(self):
        super().setUp()
        from PySide6.QtWidgets import QApplication
        self.aplicacao = QApplication.instance() or QApplication([])
        from src.controllers.contexto import Contexto
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.autenticar("ADM", "ADM")

    def test_janela_mostra_o_endereco_e_o_qr_sem_gravar_o_pin(self):
        from src.ui_qt.porteiro import JanelaPorteiro
        janela = JanelaPorteiro(self.ctx)
        self.addCleanup(janela.close)
        janela.ativo.setChecked(True)
        janela.pin.setText(PIN)
        janela.pin2.setText("9999")
        janela.salvar()
        self.assertIn("não conferem", janela.mensagem.text())
        self.assertFalse(self.banco.cfg("porteiro_pin_hash"))
        janela.pin.setText("12")
        janela.pin2.setText("12")
        janela.salvar()
        self.assertIn("4 a 8", janela.mensagem.text())
        janela.porta.setText("80")
        janela.pin.setText(PIN)
        janela.pin2.setText(PIN)
        janela.salvar()
        self.assertIn("1024", janela.mensagem.text())
        self.assertFalse(self.banco.cfg("porteiro_pin_hash"))
        janela.porta.setText("8765")
        janela.salvar()
        self.assertIn("http://", janela.lbl_enderecos.text())
        self.assertIn("/porteiro", janela.lbl_enderecos.text())
        self.assertIsNotNone(janela.qr.pixmap())
        self.assertFalse(janela.qr.pixmap().isNull())
        guardado = self.banco.cfg("porteiro_pin_hash")
        self.assertNotIn(PIN, guardado)
        self.assertTrue(seguranca.conferir(PIN, guardado))
        self.assertEqual(self.banco.cfg("porteiro_ativo"), "S")

    def test_menu_mostra_o_atalho_e_a_adega_esconde(self):
        from src.core import edicao
        from src.ui_qt.app import App, JanelaPrincipal
        from unittest.mock import patch
        app = App(self.banco, self.aplicacao)
        app.ctx.operador = self.ctx.operador
        janela = JanelaPrincipal(app)
        janela._fechamento_autorizado = True          # close() sem isto abre um diálogo e a suíte para
        self.addCleanup(janela.close)
        self.addCleanup(app.finalizar)
        self.assertFalse(janela.botoes["porteiro"].isHidden())
        self.assertIn("desligado", janela.linha_porteiro.text())
        with patch.dict(os.environ, {"PDV_EDICAO": "ea_superacoes"}):
            edicao.preparar(self.banco)
            janela.atualizar()
        self.assertTrue(janela.botoes["porteiro"].isHidden())
        self.assertTrue(janela.linha_porteiro.isHidden())
