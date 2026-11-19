"""Suporte remoto (RustDesk): achar o programa, ler o ID, abrir, e o ID que segue para a central do fornecedor."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.controllers.utilitario_controller import UtilitarioController
from src.core import suporte_remoto
from src.core.erros import ErroNegocio
from src.sync import painel_envio
from tests.base import BaseTeste


def resposta(saida: str):
    return subprocess.CompletedProcess(["rustdesk", "--get-id"], 0, stdout=saida, stderr="")


class TesteRustDesk(BaseTeste):
    def setUp(self):
        super().setUp()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)
        # Nada do computador que roda o teste entra na procura: só as pastas de mentira.
        limpo = {k: v for k, v in os.environ.items()
                 if k not in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA")}
        ambiente = mock.patch.dict(os.environ, {**limpo, "ProgramFiles": str(self.pasta / "Programas")}, clear=True)
        ambiente.start()
        self.addCleanup(ambiente.stop)
        which = mock.patch("src.core.suporte_remoto.shutil.which", return_value=None)
        which.start()
        self.addCleanup(which.stop)
        self.util = UtilitarioController(self.banco)

    def instalar(self) -> Path:
        executavel = self.pasta / "Programas" / "RustDesk" / "rustdesk.exe"
        executavel.parent.mkdir(parents=True)
        executavel.write_bytes(b"simulado")
        return executavel

    # ------------------------------------------------------------- procurar
    def test_acha_na_pasta_de_programas_e_ignora_o_que_nao_existe(self):
        self.assertIsNone(suporte_remoto.localizar())
        self.assertFalse(self.util.rustdesk_instalado())
        executavel = self.instalar()
        self.assertEqual(suporte_remoto.localizar(), executavel)
        self.assertTrue(self.util.rustdesk_instalado())

    def test_programa_de_comunicacao_so_vale_quando_aponta_para_o_rustdesk(self):
        portatil = self.pasta / "rustdesk-1.4.7-x86_64.exe"
        portatil.write_bytes(b"simulado")
        outro = self.pasta / "TeamViewer.exe"
        outro.write_bytes(b"simulado")
        self.assertIsNone(suporte_remoto.localizar(str(outro)))
        self.assertEqual(suporte_remoto.localizar(f"  {portatil}  "), portatil)
        self.banco.cfg_set("programa_comunicacao", str(portatil))
        self.assertTrue(self.util.rustdesk_instalado())

    # ------------------------------------------------------------------- ID
    def test_id_valido_e_formatado(self):
        for texto, esperado in (("123456789", "123456789"), (" 123 456 789\r\n", "123456789"),
                                ("1234567890", "1234567890"), ("minha-loja_01", "minha-loja_01"),
                                ("", ""), (None, ""), ("12345", ""), ("<script>alert(1)</script>", ""),
                                ("erro: serviço parado", ""), ("-123456789", ""), ("1" * 33, "")):
            with self.subTest(texto=texto):
                self.assertEqual(suporte_remoto.id_valido(texto), esperado)
        self.assertEqual(suporte_remoto.formatar_id("123456789"), "123 456 789")
        self.assertEqual(suporte_remoto.formatar_id("1234567890"), "1 234 567 890")
        self.assertEqual(suporte_remoto.formatar_id("minha-loja_01"), "minha-loja_01")

    def test_le_o_id_perguntando_ao_rustdesk_sem_travar_o_caixa(self):
        executavel = self.instalar()
        with mock.patch("src.core.suporte_remoto.subprocess.run", return_value=resposta("\n123456789\n")) as rodar:
            self.assertEqual(suporte_remoto.ler_id(executavel), "123456789")
        argumentos, opcoes = rodar.call_args
        self.assertEqual(argumentos[0], [str(executavel), "--get-id"])
        self.assertEqual(opcoes["timeout"], suporte_remoto.TEMPO_LIMITE)
        self.assertTrue(opcoes["capture_output"])           # no Windows o RustDesk só responde com a saída num cano
        for falha in (subprocess.TimeoutExpired("rustdesk", 4), OSError("acesso negado")):
            with self.subTest(falha=falha), mock.patch("src.core.suporte_remoto.subprocess.run", side_effect=falha):
                self.assertEqual(suporte_remoto.ler_id(executavel), "")
        for lixo in ("", "Erro ao falar com o serviço", "\n\n"):
            with self.subTest(lixo=lixo), mock.patch("src.core.suporte_remoto.subprocess.run", return_value=resposta(lixo)):
                self.assertEqual(suporte_remoto.ler_id(executavel), "")

    def test_id_lido_fica_guardado_so_para_este_computador(self):
        self.instalar()
        self.assertEqual(suporte_remoto.id_guardado(self.banco), "")
        with mock.patch("src.core.suporte_remoto.subprocess.run", return_value=resposta("123456789\n")), \
                mock.patch("src.core.suporte_remoto.socket.gethostname", return_value="CAIXA-01"):
            self.assertEqual(self.util.obter_id_rustdesk(), "123456789")
            self.assertEqual(suporte_remoto.id_guardado(self.banco), "123456789")
            self.assertEqual(painel_envio.retrato(self.banco)["rustdesk_id"], "123456789")
        self.assertEqual(self.banco.cfg("rustdesk_id"), "123456789|CAIXA-01")
        # O banco restaurado em outro computador não leva o ID velho para a central.
        with mock.patch("src.core.suporte_remoto.socket.gethostname", return_value="CAIXA-NOVO"):
            self.assertEqual(suporte_remoto.id_guardado(self.banco), "")
            self.assertEqual(painel_envio.retrato(self.banco)["rustdesk_id"], "")

    def test_sem_resposta_nao_apaga_o_id_e_caixa_adicional_nao_guarda(self):
        self.instalar()
        with mock.patch("src.core.suporte_remoto.socket.gethostname", return_value="CAIXA-01"):
            suporte_remoto.guardar_id(self.banco, "123456789")
            with mock.patch("src.core.suporte_remoto.subprocess.run", return_value=resposta("")):
                self.assertEqual(self.util.obter_id_rustdesk(), "")
            self.assertEqual(suporte_remoto.id_guardado(self.banco), "123456789")
            # Num caixa adicional as configurações são as do principal: o ID de lá não pode ser trocado pelo daqui.
            with mock.patch("src.core.suporte_remoto.subprocess.run", return_value=resposta("987654321")), \
                    mock.patch.object(self.banco, "remoto", True, create=True):
                self.assertEqual(self.util.obter_id_rustdesk(), "987654321")
            self.assertEqual(suporte_remoto.id_guardado(self.banco), "123456789")

    def test_sem_o_programa_nao_ha_id(self):
        with mock.patch("src.core.suporte_remoto.subprocess.run") as rodar:
            self.assertEqual(self.util.obter_id_rustdesk(), "")
        rodar.assert_not_called()

    # ---------------------------------------------------------------- abrir
    def test_abre_o_programa_e_registra_no_log(self):
        executavel = self.instalar()
        with mock.patch("src.core.suporte_remoto.subprocess.Popen") as abrir:
            self.util.abrir_rustdesk()
        abrir.assert_called_once_with([str(executavel)])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'suporte_remoto'"), 1)

    def test_sem_o_programa_explica_como_instalar(self):
        with mock.patch("src.core.suporte_remoto.subprocess.Popen") as abrir:
            with self.assertRaisesRegex(ErroNegocio, "não está instalado.*rustdesk.com.*Programa de comunicação"):
                self.util.abrir_rustdesk()
        abrir.assert_not_called()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'suporte_remoto'"), 0)

    def test_falha_ao_abrir_vira_mensagem_clara(self):
        self.instalar()
        with mock.patch("src.core.suporte_remoto.subprocess.Popen", side_effect=OSError("acesso negado")):
            with self.assertRaisesRegex(ErroNegocio, "Não foi possível abrir o RustDesk: acesso negado"):
                self.util.abrir_rustdesk()


if __name__ == "__main__":
    unittest.main()
