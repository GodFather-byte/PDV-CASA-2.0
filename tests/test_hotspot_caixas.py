"""Caixas conectados sem depender do Wi-Fi da loja: o principal anuncia todos os endereços (inclusive o do Wi-Fi
próprio), o adicional guarda e tenta primeiro o que funcionou, e o serviço religa o hotspot do Windows."""
from __future__ import annotations

import json
import subprocess
from unittest import mock

from src.database import rede
from src.hardware import hotspot_windows as hs
from tests.base import BaseTeste


class _Saida:
    def __init__(self, dados, erro=""):
        self.stdout = json.dumps(dados) if isinstance(dados, dict) else dados
        self.stderr = erro


class TesteEnderecos(BaseTeste):
    def test_wifi_proprio_vem_primeiro_e_localhost_fica_de_fora(self):
        with mock.patch("socket.gethostname", return_value="CAIXA1"), \
             mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.0.10", 0)),
                                                             (2, 1, 6, "", ("192.168.137.1", 0)),
                                                             (2, 1, 6, "", ("127.0.0.1", 0))]), \
             mock.patch("socket.socket") as falso:
            falso.return_value.__enter__.return_value.getsockname.return_value = ("192.168.0.10", 0)
            self.assertEqual(rede.enderecos_locais(), ["192.168.137.1", "192.168.0.10", "CAIXA1"])

    def test_juntar_enderecos_sem_repetir(self):
        self.assertEqual(rede.juntar_enderecos(["192.168.0.10", "CAIXA1"], ["192.168.137.1", "192.168.0.10", "127.0.0.1"]),
                         ["192.168.0.10", "CAIXA1", "192.168.137.1"])
        self.assertEqual(rede.juntar_enderecos(["a"], "não é lista"), ["a"])


class TesteHotspot(BaseTeste):
    def test_ler_e_ligar_interpretam_o_powershell(self):
        executar = mock.Mock(return_value=_Saida({"suportado": True, "ligado": True, "ssid": "WILL-CAIXAS",
                                                  "senha": "12345678", "conectados": 1, "sem_desligamento": False}))
        estado = hs.ligar(executar)
        self.assertTrue(estado["ligado"])
        self.assertIn("StartTetheringAsync", executar.call_args[0][0][-1])
        texto = hs.descrever(estado)
        self.assertIn('"WILL-CAIXAS"', texto)
        self.assertIn("Conectar automaticamente", texto)
        self.assertIn("desativar automaticamente", texto)            # sem permissão de admin: orienta a desmarcar
        quebrado = hs.ler(mock.Mock(return_value=_Saida("", "Classe não registrada")))
        self.assertFalse(quebrado["ligado"])
        self.assertIn("Classe não registrada", quebrado["erro"])
        falhou = hs.ler(mock.Mock(side_effect=subprocess.TimeoutExpired("powershell", 40)))
        self.assertIn("PowerShell", falhou["erro"])

    def test_servico_religa_so_com_a_opcao_ligada(self):
        import tempfile
        from pathlib import Path
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        caminho = str(Path(pasta.name) / "loja.db")
        from src.database.conexao import BancoDados
        banco = BancoDados(caminho)
        banco.fechar()
        executar = mock.Mock(side_effect=[_Saida({"suportado": True, "ligado": False}),
                                          _Saida({"suportado": True, "ligado": True, "ssid": "X", "senha": "Y"})])
        servico = hs.ServicoHotspot(caminho, executar=executar)
        self.assertIsNone(servico.rodada())                          # opção desligada: não mexe no Windows
        executar.assert_not_called()
        banco = BancoDados(caminho)
        banco.cfg_set(hs.CHAVE_LIGADO, "S")
        banco.fechar()
        estado = servico.rodada()                                    # estava desligado: liga
        self.assertTrue(estado["ligado"])
        self.assertEqual(executar.call_count, 2)
        banco = BancoDados(caminho)
        self.assertEqual(hs.estado_guardado(banco)["ssid"], "X")
        banco.fechar()

    def test_fora_do_windows_nao_faz_nada(self):
        with mock.patch.object(hs.sys, "platform", "linux"):
            self.assertFalse(hs.ler()["suportado"])
