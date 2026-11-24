"""Caixa adicional se atualiza junto: o principal, ao recusar por versão, informa a versão dele e a nuvem; o adicional
baixa exatamente essa versão (assinatura e SHA-256 conferidos), manda instalar e não entra em laço se falhar."""
import hashlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from src.atualizacao import adicional, cliente
from src.database import rede
from src.versao import VERSAO
from tests.test_rede_caixas import BaseRede


def anunciar(versao):
    real = rede._Canal.enviar

    def enviar(canal, mensagem):
        if mensagem.get("o") == "ola":
            mensagem = {**mensagem, "versao": versao}
        return real(canal, mensagem)
    return mock.patch.object(rede._Canal, "enviar", enviar)


class TesteProtocolo(BaseRede):
    def test_principal_mais_novo_informa_versao_nuvem_e_loja(self):
        self.principal.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.principal.cfg_set("api_token", "segredo-que-nao-pode-ir")
        self.principal.cfg_set("chave_loja", "CASA-VERDE")
        with anunciar("0.0.1"), self.assertRaises(rede.ErroVersaoDiferente) as erro:
            self.adicional()
        e = erro.exception
        self.assertEqual((e.versao_principal, e.nuvem, e.loja),
                         (VERSAO, "https://nuvem.exemplo/v1/sincronizar", "CASA-VERDE"))
        self.assertIn("mesma versão", str(e))
        self.assertNotIn("segredo", repr(vars(e)))
        with mock.patch.object(adicional, "VERSAO", "0.0.1"):           # o adicional de verdade está na velha
            self.assertTrue(adicional.pode_atualizar(e))

    def test_outra_recusa_continua_erro_comum(self):
        with self.assertRaises(rede.ErroLigacao) as erro:
            self.adicional(terminal=1)                     # número do principal: não é questão de versão
        self.assertNotIsInstance(erro.exception, rede.ErroVersaoDiferente)


class _Resposta:
    def __init__(self, status=200, dados=None, conteudo=b""):
        self.status_code, self._dados, self.content = status, dados, conteudo

    def json(self):
        return self._dados


class TesteAtualizarAdicional(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)
        self.binario = b"instalador da versao nova"
        self.erro = rede.ErroVersaoDiferente("versões diferentes", "99.0.0", "https://nuvem.exemplo/v1/sincronizar",
                                             "CASA-VERDE")
        self.pacote = {"edicao": cliente.edicao_atual(), "versao": "99.0.0", "url": "/download/x.exe",
                       "sha256": hashlib.sha256(self.binario).hexdigest(), "tamanho": len(self.binario),
                       "assinatura": "a", "canal": "estavel", "notas": "", "obrigatoria": 0, "minima": ""}
        self.http = mock.Mock()
        self.http.get.side_effect = self.responder
        conferir = mock.patch.object(cliente, "pacote_valido", side_effect=lambda d, *a, **k: bool(d.get("pacote")))
        conferir.start()
        self.addCleanup(conferir.stop)

    def responder(self, url, params=None, timeout=None):
        if url.endswith("/v1/atualizacao/ultima"):
            self.consulta = params
            return _Resposta(dados={"disponivel": True, "pacote": self.pacote})
        self.baixado = url
        return _Resposta(conteudo=self.binario)

    def test_baixa_a_versao_do_principal_confere_e_manda_instalar(self):
        instalar = mock.Mock()
        r = adicional.atualizar(self.erro, self.http, instalar, self.pasta)
        self.assertEqual(r["acao"], "instalar", r)
        self.assertEqual(self.consulta["loja"], "CASA-VERDE")
        self.assertEqual(self.baixado, "https://nuvem.exemplo/download/x.exe")
        arquivo = instalar.call_args.args[0]
        self.assertEqual(arquivo.read_bytes(), self.binario)
        self.assertTrue(arquivo.with_suffix(".json").is_file())       # a tarefa do SISTEMA confere de novo

    def test_nao_repete_em_laco_e_tentar_de_novo_libera(self):
        instalar = mock.Mock()
        adicional.atualizar(self.erro, self.http, instalar, self.pasta)
        self.assertEqual(adicional.atualizar(self.erro, self.http, instalar, self.pasta)["acao"], "ja_tentou")
        depois = datetime.now() + timedelta(minutes=31)
        self.assertEqual(adicional.atualizar(self.erro, self.http, instalar, self.pasta, agora=depois)["acao"], "instalar")
        adicional.esquecer_tentativa(self.pasta)
        self.assertEqual(adicional.atualizar(self.erro, self.http, instalar, self.pasta)["acao"], "instalar")

    def test_so_instala_a_mesma_versao_do_principal(self):
        self.pacote["versao"] = "99.0.1"
        instalar = mock.Mock()
        r = adicional.atualizar(self.erro, self.http, instalar, self.pasta)
        self.assertEqual(r["acao"], "versao_indisponivel")
        instalar.assert_not_called()

    def test_arquivo_adulterado_nao_instala(self):
        self.binario = b"outra coisa"                    # o SHA-256 do pacote não bate mais
        instalar = mock.Mock()
        with self.assertRaises(RuntimeError):
            adicional.atualizar(self.erro, self.http, instalar, self.pasta)
        instalar.assert_not_called()

    def test_principal_mais_antigo_pede_para_atualizar_o_principal(self):
        velho = rede.ErroVersaoDiferente("x", "0.0.1", "https://n", "")
        self.assertFalse(adicional.pode_atualizar(velho))
        r = adicional.atualizar(velho, self.http, mock.Mock(), self.pasta)
        self.assertEqual(r["acao"], "principal_antigo")
        self.assertIn("Atualize o caixa principal", r["mensagem"])

    def test_nuvem_fora_do_ar(self):
        self.http.get.side_effect = OSError("sem rede")
        self.assertEqual(adicional.atualizar(self.erro, self.http, mock.Mock(), self.pasta)["acao"], "sem_resposta")


class TesteTelas(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def test_dialogo_roda_a_atualizacao_sem_travar_e_avisa(self):
        from src.ui_qt import rede_caixas
        erro = rede.ErroVersaoDiferente("x", "99.0.0", "https://n", "")
        with mock.patch.object(rede_caixas.QMessageBox, "information") as aviso:
            r = rede_caixas.atualizar_adicional(None, erro, executar=lambda e: {"acao": "instalar", "mensagem": "ok"})
        self.assertEqual(r["acao"], "instalar")
        aviso.assert_called_once()

    def test_falha_vira_mensagem(self):
        from src.ui_qt import rede_caixas

        def falhar(_):
            raise RuntimeError("disco cheio")
        r = rede_caixas.atualizar_adicional(None, rede.ErroVersaoDiferente("x", "99.0.0", "https://n", ""), falhar)
        self.assertEqual(r["acao"], "falha")
        self.assertIn("disco cheio", r["mensagem"])

    def test_vigia_do_adicional_atualiza_sem_perguntar_na_tela_de_entrada(self):
        from src.ui_qt import app as modulo
        falso = mock.Mock()
        falso._finalizada = False
        falso._atualizando_adicional = False
        falso.ctx.operador = None
        falso.banco.valor.side_effect = rede.ErroVersaoDiferente("x", "99.0.0", "https://n", "")
        falso._atualizar_adicional_em_uso = lambda e: modulo.App._atualizar_adicional_em_uso(falso, e)
        with mock.patch("src.ui_qt.rede_caixas.atualizar_adicional", return_value={"acao": "instalar"}) as atualizar, \
                mock.patch.object(modulo.QMessageBox, "question") as pergunta:
            modulo.App._vigiar_principal(falso)
        pergunta.assert_not_called()
        atualizar.assert_called_once()
        falso.finalizar.assert_called_once()
        falso.aplicacao.quit.assert_called_once()

    def test_com_operador_pergunta_e_respeita_o_nao(self):
        from src.ui_qt import app as modulo
        falso = mock.Mock()
        falso._atualizando_adicional = False
        falso.ctx.operador = object()
        with mock.patch("src.ui_qt.rede_caixas.atualizar_adicional") as atualizar, \
                mock.patch.object(modulo.QMessageBox, "question", return_value=modulo.QMessageBox.StandardButton.No):
            feito = modulo.App._atualizar_adicional_em_uso(falso, rede.ErroVersaoDiferente("x", "99.0.0", "https://n", ""))
        self.assertFalse(feito)
        atualizar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
