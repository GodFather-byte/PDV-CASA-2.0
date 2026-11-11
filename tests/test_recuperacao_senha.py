"""Senha de gerente esquecida: pedido do caixa, liberação assinada pelo fornecedor e senha nova."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src.controllers.acesso_controller import AcessoController
from src.core import ed25519, licenca, recuperacao_senha as rec
from src.core.erros import ErroNegocio
from tests.base import BaseTeste

SEMENTE = bytes.fromhex("33" * 32)
PUBLICA = ed25519.chave_publica(SEMENTE)
OUTRA = bytes.fromhex("44" * 32)
AGORA = datetime(2026, 10, 3, 22, 0, 0)          # o relógio fixo dos testes


class BaseRecuperacao(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("chave_loja", "ADEGA-1")
        chave = patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA.hex())
        chave.start()
        self.addCleanup(chave.stop)
        self.adm = self.operador_adm()

    def liberar(self, pedido=None, loja="ADEGA-1", semente=SEMENTE, agora=AGORA, horas=24):
        return rec.gerar_liberacao(semente, loja, pedido or rec.pedido_atual(self.banco), agora=agora, horas=horas)

    def entra(self, senha, nome="ADM"):
        try:
            AcessoController(self.banco).autenticar(nome, senha)
            return True
        except ErroNegocio:
            return False


class TestePedido(BaseRecuperacao):
    def test_pedido_e_curto_sem_letras_ambiguas_e_o_mesmo_enquanto_vale(self):
        pedido = rec.pedido_atual(self.banco)
        self.assertEqual(len(pedido), 8)
        self.assertTrue(set(pedido) <= set(rec.ALFABETO))
        self.assertFalse(set("01OI") & set(rec.ALFABETO))
        self.assertEqual(rec.pedido_atual(self.banco), pedido)                   # reabrir a tela não troca o pedido
        self.assertEqual(rec.formatar_pedido(pedido), f"{pedido[:4]}-{pedido[4:]}")
        self.assertEqual(rec.normalizar_pedido(f" {pedido[:4].lower()} - {pedido[4:]} "), pedido)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'senha_recuperacao_pedida'"), 1)

    def test_pedido_vencido_da_lugar_a_um_novo(self):
        pedido = rec.pedido_atual(self.banco, AGORA)
        depois = AGORA + timedelta(hours=rec.HORAS_PEDIDO, minutes=1)
        self.assertNotEqual(rec.pedido_atual(self.banco, depois), pedido)
        self.banco.cfg_set(rec.CHAVE_PEDIDO, "lixo")
        self.assertEqual(len(rec.pedido_atual(self.banco)), 8)                   # configuração estragada não trava a tela


class TesteLiberacao(BaseRecuperacao):
    def test_liberacao_certa_troca_a_senha_e_vale_uma_vez(self):
        codigo = self.liberar()
        self.assertTrue(codigo.startswith("PDVR1."))
        self.assertEqual(rec.conferir(self.banco, codigo)["loja"], "ADEGA-1")
        self.assertEqual(rec.redefinir(self.banco, codigo, self.adm, "nova123"), "ADM")
        self.assertTrue(self.entra("nova123"))
        self.assertFalse(self.entra("ADM"))
        with self.assertRaises(rec.RecuperacaoInvalida) as erro:                # o pedido foi consumido
            rec.redefinir(self.banco, codigo, self.adm, "outra1")
        self.assertIn("pedido", str(erro.exception).lower())
        self.assertTrue(self.entra("nova123"))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'senha_recuperada'"), 1)

    def test_recusa_assinatura_de_outra_chave_codigo_adulterado_e_texto_qualquer(self):
        pedido = rec.pedido_atual(self.banco)
        falsa = self.liberar(semente=OUTRA)
        boa = self.liberar()
        cabeca, carga, assinatura = boa.split(".")
        outra_carga = rec.gerar_liberacao(SEMENTE, "ADEGA-2", pedido, agora=AGORA).split(".")[1]
        for codigo in (falsa, f"{cabeca}.{outra_carga}.{assinatura}", boa[:-4], "PDVL1.abc.def", "", "qualquer coisa"):
            with self.assertRaises(rec.RecuperacaoInvalida, msg=codigo[:20]):
                rec.conferir(self.banco, codigo)
        self.assertTrue(self.entra("ADM"))                                       # nada mudou

    def test_recusa_outra_loja_outro_pedido_e_prazo_vencido(self):
        casos = [(self.liberar(loja="ADEGA-2"), "outra loja"),
                 (self.liberar(pedido="ABCDEFGH"), "outro pedido"),
                 (self.liberar(agora=AGORA - timedelta(hours=30)), "venceu")]
        for codigo, trecho in casos:
            with self.assertRaises(rec.RecuperacaoInvalida) as erro:
                rec.conferir(self.banco, codigo)
            self.assertIn(trecho, str(erro.exception))
        boa = self.liberar()
        with self.assertRaises(rec.RecuperacaoInvalida) as erro:                # o pedido do caixa venceu antes de usar
            rec.conferir(self.banco, boa, AGORA + timedelta(hours=rec.HORAS_PEDIDO + 1))
        self.assertIn("pedido deste caixa venceu", str(erro.exception))

    def test_liberacao_valida_exige_gerente_ativo_e_senha_dentro_da_regra(self):
        caixa = self.novo_operador("CAIXA", nivel=1) if hasattr(self, "novo_operador") else None
        if caixa is None:
            from src.controllers.cadastro_controller import CadastroController
            caixa = CadastroController(self.banco).salvar("operadores", {"nome": "CAIXA", "senha": "segredo1", "nivel": "1", "ativo": "S"})
        codigo = self.liberar()
        self.assertEqual([g["nome"] for g in rec.gerentes(self.banco)], ["ADM"])
        for operador, senha in ((caixa, "nova123"), (self.adm, ""), (self.adm, "com espaço"), (self.adm, "x" * 11), (self.adm, "adm")):
            with self.assertRaises(ErroNegocio):
                rec.redefinir(self.banco, codigo, operador, senha)
        self.assertTrue(self.entra("ADM"))
        self.assertEqual(rec.redefinir(self.banco, codigo, self.adm, "nova123"), "ADM")   # o erro não gastou o pedido

    def test_troca_tira_o_bloqueio_por_senha_errada(self):
        for _ in range(8):
            self.entra("errada")
        with self.assertRaises(ErroNegocio) as erro:
            AcessoController(self.banco).autenticar("ADM", "ADM")
        self.assertNotIn("Incorreta", str(erro.exception))                       # bloqueado, mesmo com a senha certa
        rec.redefinir(self.banco, self.liberar(), self.adm, "nova123")
        self.assertTrue(self.entra("nova123"))

    def test_instalacao_sem_chave_de_loja_usa_so_o_pedido(self):
        self.banco.cfg_set("chave_loja", "")
        codigo = self.liberar(loja="")
        self.assertEqual(rec.redefinir(self.banco, codigo, self.adm, "nova123"), "ADM")

    def test_fornecedor_recusa_pedido_mal_digitado_e_prazo_fora_do_limite(self):
        for pedido, horas in (("ABC", 24), ("", 24), ("ABCDEFGH", 0), ("ABCDEFGH", 73)):
            with self.assertRaises(ValueError):
                rec.gerar_liberacao(SEMENTE, "ADEGA-1", pedido, horas=horas)

    def test_ferramenta_do_fornecedor_assina_com_a_chave_do_arquivo(self):
        from tools import gerar_licenca
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "chave.key"
            arquivo.write_text(SEMENTE.hex(), encoding="ascii")
            saida = io.StringIO()
            with redirect_stdout(saida):
                gerar_licenca.recuperar_senha(arquivo, "ADEGA-1", rec.formatar_pedido(rec.pedido_atual(self.banco)), 24)
            codigo = saida.getvalue().strip().splitlines()[-1]
            self.assertEqual(rec.redefinir(self.banco, codigo, self.adm, "nova123"), "ADM")
            arquivo.write_text(OUTRA.hex(), encoding="ascii")
            with self.assertRaises(SystemExit):
                gerar_licenca.recuperar_senha(arquivo, "ADEGA-1", "ABCDEFGH", 24)


try:
    from tests.test_nuvem import TestClient, cabecalho, nuvem, preparar_lojas
    from backend import central_fornecedor as central, recuperacao_senha as nuvem_rec
except (ImportError, RuntimeError):
    TestClient = None


@unittest.skipIf(TestClient is None, "Dependências da nuvem ausentes")
class TesteCentralLiberaSenha(BaseRecuperacao):
    def setUp(self):
        super().setUp()
        preparar_lojas()
        self.banco.cfg_set("chave_loja", "LOJA-1")
        with nuvem.SessionLocal() as db:
            for modelo in (central.SessaoFornecedor, central.AuditoriaFornecedor, nuvem_rec.LiberacaoSenha):
                db.query(modelo).delete()
            db.commit()
        with central._trava:
            central._tentativas.clear()
        semente = patch.object(nuvem, "semente_licenca", return_value=SEMENTE)
        semente.start()
        self.addCleanup(semente.stop)
        self.http = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(self.http.close)
        r = self.http.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"}, headers={"X-Central-Login": "1"})
        self.csrf = r.json()["csrf"]
        self.banco.cfg_set("api_url", "https://testserver/v1/sincronizar")
        self.banco.cfg_set("api_token", cabecalho("LOJA-1")["Authorization"].removeprefix("Bearer "))

    def liberar_na_central(self, pedido, loja="LOJA-1", motivo="Dono ligou do número cadastrado"):
        return self.http.post(f"/v1/fornecedor/lojas/{loja}/recuperar-senha", json={"pedido": pedido, "motivo": motivo},
                              headers={"X-Central-CSRF": self.csrf})

    def ponte(self):
        http = self.http

        class Ponte:
            def get(self, url, params=None, headers=None, timeout=None):
                return http.get(url, params=params, headers=headers)
        return Ponte()

    def test_central_assina_o_caixa_busca_e_troca_a_senha(self):
        from src.sync import recuperacao_senha as busca
        pedido = rec.pedido_atual(self.banco)
        self.assertIsNone(busca.buscar_liberacao(self.banco, pedido, self.ponte()))      # ainda não liberado
        r = self.liberar_na_central(rec.formatar_pedido(pedido).lower())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["pedido"], rec.formatar_pedido(pedido))
        codigo = busca.buscar_liberacao(self.banco, pedido, self.ponte())
        self.assertEqual(codigo, r.json()["codigo"])
        self.assertEqual(rec.redefinir(self.banco, codigo, self.adm, "nova123"), "ADM")
        with nuvem.SessionLocal() as db:
            evento = db.query(central.AuditoriaFornecedor).filter_by(acao="recuperar_senha").one()
            self.assertEqual(evento.loja, "LOJA-1")
            self.assertIn("Dono ligou", evento.motivo)
            self.assertNotIn(codigo, evento.motivo)

    def test_outra_loja_nao_busca_a_liberacao_e_pedido_errado_nao_acha(self):
        pedido = rec.pedido_atual(self.banco)
        self.liberar_na_central(pedido)
        da_outra = self.http.get("/v1/recuperacao-senha", params={"pedido": pedido}, headers=cabecalho("LOJA-2"))
        self.assertEqual(da_outra.status_code, 404)
        self.assertEqual(self.http.get("/v1/recuperacao-senha", params={"pedido": "ABCDEFGH"}, headers=cabecalho()).status_code, 404)
        self.assertEqual(self.http.get("/v1/recuperacao-senha", params={"pedido": pedido}).status_code, 401)
        self.assertEqual(self.http.get("/v1/recuperacao-senha", params={"pedido": pedido},
                                       headers={"Authorization": "Bearer token-de-teste"}).status_code, 403)

    def test_central_exige_login_motivo_pedido_valido_e_chave_pronta(self):
        pedido = rec.pedido_atual(self.banco)
        sem_login = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(sem_login.close)
        self.assertEqual(sem_login.post("/v1/fornecedor/lojas/LOJA-1/recuperar-senha", json={"pedido": pedido, "motivo": "x"}).status_code, 401)
        self.assertEqual(self.liberar_na_central(pedido, motivo="").status_code, 422)
        self.assertEqual(self.liberar_na_central("ABC").status_code, 422)
        self.assertEqual(self.liberar_na_central(pedido, loja="NAO-EXISTE").status_code, 404)
        with patch.object(nuvem, "semente_licenca", return_value=None):
            sem_chave = self.liberar_na_central(pedido)
        self.assertEqual(sem_chave.status_code, 409)
        self.assertIn("tools.gerar_licenca recuperar-senha", sem_chave.json()["detail"])

    def test_liberacao_nova_substitui_a_anterior_da_loja(self):
        self.liberar_na_central("ABCDEFGH")
        self.liberar_na_central("JKLMNPQR")
        with nuvem.SessionLocal() as db:
            self.assertEqual([l.pedido for l in db.query(nuvem_rec.LiberacaoSenha).filter_by(chave_loja="LOJA-1")], ["JKLMNPQR"])


class TesteTelaEsqueciSenha(BaseRecuperacao):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def dialogo(self):
        from src.controllers.contexto import Contexto
        from src.ui_qt.esqueci_senha import DialogoEsqueciSenha
        dialogo = DialogoEsqueciSenha(Contexto(self.banco))
        self.addCleanup(dialogo.deleteLater)
        self.addCleanup(dialogo.close)
        return dialogo

    def test_tela_mostra_o_pedido_e_so_libera_a_senha_nova_com_o_codigo_certo(self):
        dialogo = self.dialogo()
        self.assertEqual(dialogo.rotulo_pedido.text(), rec.formatar_pedido(rec.pedido_atual(self.banco)))
        self.assertFalse(dialogo.btn_gravar.isEnabled())
        self.assertFalse(dialogo.btn_nuvem.isVisibleTo(dialogo))                 # sem nuvem configurada, só o código colado
        self.assertFalse(dialogo.gravar())
        dialogo.codigo.setPlainText(self.liberar(semente=OUTRA))
        self.assertFalse(dialogo.conferir())
        self.assertIn("assinatura", dialogo.mensagem.text())
        dialogo.codigo.setPlainText(self.liberar())
        self.assertTrue(dialogo.conferir())
        self.assertTrue(dialogo.btn_gravar.isEnabled())
        dialogo.nova.setText("nova123")
        dialogo.confirmar.setText("outra")
        self.assertFalse(dialogo.gravar())
        self.assertIn("não são iguais", dialogo.mensagem.text())
        dialogo.confirmar.setText("nova123")
        self.assertTrue(dialogo.gravar())
        self.assertEqual(dialogo.operador, "ADM")
        self.assertTrue(self.entra("nova123"))

    def test_buscar_na_nuvem_preenche_e_confere_ou_explica(self):
        self.banco.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.banco.cfg_set("api_token", "token")
        dialogo = self.dialogo()
        self.assertTrue(dialogo.btn_nuvem.isVisibleTo(dialogo))
        codigo = self.liberar()

        class Resposta:
            def __init__(self, status, corpo=None):
                self.status_code, self._corpo = status, corpo

            def json(self):
                return self._corpo

        class Nuvem:
            def __init__(self, resposta):
                self.resposta = resposta

            def get(self, *a, **k):
                if isinstance(self.resposta, Exception):
                    raise self.resposta
                return self.resposta

        self.assertFalse(dialogo.buscar_na_nuvem(Nuvem(Resposta(404))))
        self.assertIn("ainda não liberou", dialogo.mensagem.text())
        self.assertFalse(dialogo.buscar_na_nuvem(Nuvem(OSError("sem rede"))))
        self.assertIn("Sem conexão", dialogo.mensagem.text())
        self.assertTrue(dialogo.buscar_na_nuvem(Nuvem(Resposta(200, {"codigo": codigo}))))
        self.assertTrue(dialogo.btn_gravar.isEnabled())

    def test_login_tem_o_botao_e_preenche_o_gerente_depois_da_troca(self):
        from PySide6.QtWidgets import QDialog
        from src.controllers.contexto import Contexto
        from src.ui_qt import esqueci_senha
        from src.ui_qt.login import JanelaLogin
        janela = JanelaLogin(Contexto(self.banco))
        self.addCleanup(janela.deleteLater)
        self.addCleanup(janela.close)
        self.assertEqual(janela.btn_esqueci.text(), "Esqueci a senha")

        class Trocada:
            operador = "ADM"

            def __init__(self, ctx, parent=None):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch.object(esqueci_senha, "DialogoEsqueciSenha", Trocada):
            janela.esqueci_a_senha()
        self.assertEqual(janela.usuario.currentText(), "ADM")
        self.assertIn("Senha de ADM trocada", janela.mensagem.text())
