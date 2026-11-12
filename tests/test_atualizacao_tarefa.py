"""Atualização sem a janela de administrador: pedido do operador, conferência do SISTEMA e o que fica visível."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.atualizacao import cliente, tarefa
from src.atualizacao.manifesto import assinar
from src.core import ed25519, formatacao as fmt
from src.database.conexao import BancoDados
from src.versao import VERSAO, chave

SEMENTE = bytes.fromhex("22" * 32)
PUBLICA = ed25519.chave_publica(SEMENTE).hex()
CONTEUDO = b"instalador de teste"
NOVA = ".".join(str(n) for n in (chave(VERSAO)[0] + 1, 0, 0))


def pacote(**extras):
    base = {"edicao": "willpdv", "canal": "estavel", "versao": NOVA,
            "sha256": hashlib.sha256(CONTEUDO).hexdigest(), "tamanho": len(CONTEUDO),
            "url": "https://arquivos.exemplo/willpdv.exe", "notas": "Correção.", "obrigatoria": 0, "minima": ""}
    base.update(extras)
    base["assinatura"] = assinar(SEMENTE, base)
    return base


class BasePasta(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        self.pasta = self.raiz / "ProgramData" / "WillPDV" / "atualizacao"
        self.instalador = self.raiz / "baixado.exe"
        self.instalador.write_bytes(CONTEUDO)
        self.programa = self.raiz / "Arquivos de Programas" / "WillPDV"
        self.programa.mkdir(parents=True)
        (self.programa / "WillPDV.exe").write_bytes(b"programa antigo")

    def pedir(self, **extras) -> str:
        _, ident = tarefa.preparar_pedido(self.instalador, pacote(**extras), self.pasta)
        return ident

    def aplicar(self, **kw):
        destino = self.raiz / "sistema"
        destino.mkdir(exist_ok=True)
        return tarefa.preparar_aplicacao(self.pasta, self.programa, "WillPDV.exe", kw.pop("instalada", VERSAO),
                                         kw.pop("edicao", "willpdv"), PUBLICA, destino)


class TestePedidoDaTarefa(BasePasta):
    def test_pedido_valido_vira_script_sem_banco_e_sem_abrir_janela(self):
        ident = self.pedir()
        script, devolvido = self.aplicar()
        self.assertEqual(devolvido, ident)
        texto = script.read_text(encoding="utf-8")
        self.assertIn("--confirmar-atualizacao", texto)
        self.assertIn("--sem-banco", texto)                       # o banco é do operador, não do SISTEMA
        self.assertNotIn('start ""', texto)                       # abriria o programa invisível, como SISTEMA
        self.assertIn(f"resultado-{ident}.txt", texto)
        self.assertIn("/VERYSILENT", texto)
        copia = self.raiz / "sistema" / f"willpdv-{NOVA}.exe"
        self.assertEqual(copia.read_bytes(), CONTEUDO)            # instala a cópia da pasta do SISTEMA
        self.assertEqual((self.raiz / "sistema" / "anterior" / "WillPDV.exe").read_bytes(), b"programa antigo")
        self.assertFalse((self.pasta / tarefa.PEDIDO).exists())    # pedido consumido: não instala duas vezes
        self.assertFalse((self.pasta / tarefa.PACOTE).exists())

    def _recusado(self, trecho, **kw):
        ident = kw.pop("ident", None)
        with self.assertRaisesRegex(tarefa.PedidoRecusado, trecho):
            self.aplicar(**kw)
        if ident:
            resultado = tarefa.arquivo_resultado(self.pasta, ident).read_text(encoding="utf-8")
            self.assertTrue(resultado.startswith("recusada:"), resultado)
            self.assertIn(trecho, resultado)

    def test_instalador_trocado_depois_do_pedido_e_recusado(self):
        ident = self.pedir()
        (self.pasta / tarefa.PACOTE).write_bytes(b"outro programa!!!!!")
        self._recusado("não confere", ident=ident)

    def test_pacote_de_outra_edicao_e_recusado(self):
        ident = self.pedir(edicao="willadega")
        self._recusado("outra edição", ident=ident)

    def test_versao_igual_ou_mais_velha_e_recusada(self):
        ident = self.pedir()
        self._recusado("não é mais nova", ident=ident, instalada=NOVA)

    def test_assinatura_alterada_e_recusada(self):
        ident = self.pedir()
        pedido = json.loads((self.pasta / tarefa.PEDIDO).read_text(encoding="utf-8"))
        pedido["url"] = "https://outro.exemplo/x.exe"
        (self.pasta / tarefa.PEDIDO).write_text(json.dumps(pedido), encoding="utf-8")
        self._recusado("assinatura", ident=ident)

    def test_id_do_pedido_nao_vira_caminho(self):
        self.pedir()
        pedido = json.loads((self.pasta / tarefa.PEDIDO).read_text(encoding="utf-8"))
        pedido["id"] = "..\\..\\Windows\\x"
        (self.pasta / tarefa.PEDIDO).write_text(json.dumps(pedido), encoding="utf-8")
        self._recusado("identificação")
        self.assertTrue(tarefa.arquivo_resultado(self.pasta, "recusado").is_file())

    def test_sem_pedido(self):
        self._recusado("sem pedido")

    def test_novo_pedido_apaga_resultado_antigo(self):
        tarefa.arquivo_resultado(self.pasta.parent, "x")
        self.pasta.mkdir(parents=True)
        (self.pasta / "resultado-velho.txt").write_text("instalada", encoding="utf-8")
        self.pedir()
        self.assertEqual(list(self.pasta.glob("resultado-*.txt")), [])

    def test_script_de_espera_reabre_o_programa_quando_sai_o_resultado(self):
        texto = tarefa.script_espera(self.pasta, "abcdef0123456789", self.programa, "WillPDV.exe", minutos=1)
        self.assertIn("resultado-abcdef0123456789.txt", texto)
        self.assertIn('start ""', texto)
        self.assertIn("--sync", texto)
        self.assertIn("for /L %%i in (1,1,12)", texto)

    def test_pedir_ao_windows(self):
        ok = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.assertTrue(tarefa.pedir_ao_windows(ok, "WillAdega"))
        self.assertEqual(ok.call_args.args[0], ["schtasks", "/Run", "/TN", "WillAdega Atualizacao"])
        recusado = mock.Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="Acesso negado."))
        self.assertFalse(tarefa.pedir_ao_windows(recusado, "WillAdega"))
        self.assertFalse(tarefa.pedir_ao_windows(mock.Mock(side_effect=OSError("sem schtasks")), "WillAdega"))

    def test_fora_do_programa_instalado_nao_aplica(self):
        self.assertEqual(tarefa.aplicar_como_sistema(), 2)


class TesteDisparo(BasePasta):
    def test_programa_instalado_usa_a_tarefa_e_cai_no_caminho_antigo_sem_ela(self):
        arquivo = self.raiz / f"willpdv-{NOVA}.exe"
        arquivo.write_bytes(CONTEUDO)
        arquivo.with_suffix(".json").write_text(json.dumps(pacote()), encoding="utf-8")
        abertos = []
        exe = self.programa / "WillPDV.exe"
        with mock.patch.object(tarefa, "pasta_pedidos", return_value=self.pasta), \
                mock.patch("sys.frozen", True, create=True), mock.patch("sys.executable", str(exe)), \
                mock.patch.object(cliente, "_windows", return_value=True), mock.patch("subprocess.Popen", side_effect=lambda *a, **k: abertos.append(a[0])), \
                mock.patch.object(tarefa, "pedir_ao_windows", return_value=True):
            ident = cliente.disparar_instalacao(arquivo)
        self.assertRegex(ident, r"^[a-f0-9]{16}$")
        self.assertEqual(abertos, [["cmd", "/c", str(self.pasta / f"esperar-{ident}.cmd")]])
        self.assertTrue((self.pasta / tarefa.PEDIDO).is_file())
        with mock.patch.object(tarefa, "pasta_pedidos", return_value=self.pasta), \
                mock.patch("sys.frozen", True, create=True), mock.patch("sys.executable", str(exe)), \
                mock.patch.object(cliente, "_windows", return_value=True), mock.patch("subprocess.Popen", side_effect=lambda *a, **k: abertos.append(a[0])), \
                mock.patch.object(tarefa, "pedir_ao_windows", return_value=False), \
                mock.patch.object(cliente, "copiar_instalacao"):
            antigo = cliente.disparar_instalacao(arquivo)
        self.assertEqual(antigo.name, "aplicar.cmd")                 # instalação sem a tarefa: o caminho de antes
        self.assertFalse((self.pasta / tarefa.PEDIDO).exists())       # não deixa pedido órfão para trás


class TesteSituacao(unittest.TestCase):
    def setUp(self):
        self.banco = BancoDados(":memory:")
        self.addCleanup(self.banco.fechar)
        self.banco.cfg_set("api_url", "https://nuvem.exemplo")

    def test_pacote_de_outra_edicao_nao_e_baixado(self):
        dados = {"disponivel": True, "pacote": pacote(edicao="willadega")}
        self.assertFalse(cliente.pacote_valido(dados, PUBLICA, "willpdv"))
        self.assertTrue(cliente.pacote_valido({"disponivel": True, "pacote": pacote()}, PUBLICA, "willpdv"))

    def test_motivo_da_resposta_sem_pacote(self):
        self.assertEqual(cliente.sem_pacote(None), "sem_resposta")
        self.assertEqual(cliente.sem_pacote({"disponivel": False, "pacote": None, "pausada": True}), "pausada")
        self.assertEqual(cliente.sem_pacote({"disponivel": False, "pacote": pacote()}), "em_dia")   # era "assinatura_invalida"
        self.assertEqual(cliente.sem_pacote({"disponivel": False, "instalacao_manual_necessaria": True}),
                         "instalacao_manual_necessaria")

    def test_nuvem_dormindo_tenta_de_novo_em_minutos_e_nao_em_horas(self):
        with mock.patch.object(cliente, "consultar", return_value=None):
            self.assertEqual(cliente.rodada(self.banco, http=object())["acao"], "sem_resposta")
        self.assertEqual(self.banco.cfg(cliente.CHAVE_CONSULTA), "")
        self.assertFalse(cliente.precisa_consultar(self.banco))                  # não martela a nuvem
        antes = (datetime.now() - timedelta(minutes=cliente.RETENTAR_MINUTOS + 1)).strftime("%Y-%m-%d %H:%M:%S")
        self.banco.cfg_set(cliente.CHAVE_FALHA_CONSULTA, antes)
        self.assertTrue(cliente.precisa_consultar(self.banco))                   # 15 minutos depois, de novo
        resposta = {"disponivel": False, "pacote": None}
        with mock.patch.object(cliente, "consultar", return_value=resposta):
            self.assertEqual(cliente.rodada(self.banco, http=object())["acao"], "em_dia")
        self.assertEqual(self.banco.cfg(cliente.CHAVE_FALHA_CONSULTA), "")
        self.assertFalse(cliente.precisa_consultar(self.banco))                  # respondeu: agora só em 6 horas

    def _turno(self, fechado_ha_min=None):
        quando = (datetime.now() - timedelta(minutes=fechado_ha_min or 0)).strftime("%Y-%m-%d %H:%M:%S")
        if fechado_ha_min is None:
            self.banco.executar("INSERT INTO turnos (numero, aberto_em) VALUES (1, ?)", (fmt.agora(),))
        else:
            self.banco.executar("INSERT INTO turnos (numero, aberto_em, fechado_em, status) VALUES (1, ?, ?, 'fechado')",
                                (quando, quando))

    def test_so_instala_sozinho_com_a_loja_parada(self):
        self.assertIsNone(cliente.motivo_automatico(self.banco))
        self._turno(fechado_ha_min=2)
        self.assertIn("fechou há pouco", cliente.motivo_automatico(self.banco))   # o fechamento ainda imprime
        self.banco.executar("UPDATE turnos SET fechado_em = ?", (
            (datetime.now() - timedelta(minutes=cliente.OCIOSO_MINUTOS + 1)).strftime("%Y-%m-%d %H:%M:%S"),))
        self.assertIsNone(cliente.motivo_automatico(self.banco))
        self.banco.executar("INSERT INTO fila_impressao (criado_em, nome, dados) VALUES (?, 'Fechamento', x'00')",
                            (fmt.agora(),))
        self.assertEqual(cliente.motivo_automatico(self.banco), "há impressão na fila")
        self.banco.executar("DELETE FROM fila_impressao")
        self._turno()
        self.assertIn("turno aberto", cliente.motivo_automatico(self.banco))
        self.assertIsNone(cliente.caixa_ocupado(self.banco))                      # pelo botão, o operador decide

    def test_tentativa_que_subiu_e_confirmada_na_abertura(self):
        self.banco.cfg_set(cliente.CHAVE_TENTATIVA, VERSAO)
        self.assertIsNone(cliente.conferir_tentativa(self.banco))
        self.assertEqual(self.banco.cfg(cliente.CHAVE_TENTATIVA), "")
        self.assertEqual(cliente.ultimo_resultado(self.banco)["situacao"], "instalada")
        self.assertIsNone(cliente.aviso(self.banco))

    def test_tentativa_que_nao_subiu_aparece_com_o_motivo(self):
        with tempfile.TemporaryDirectory() as raiz:
            pasta = Path(raiz)
            with mock.patch.object(tarefa, "pasta_pedidos", return_value=pasta):
                self.banco.cfg_set(cliente.CHAVE_TENTATIVA, NOVA)
                cliente.registrar_resultado(self.banco, NOVA, "em_andamento")
                dados = cliente.ultimo_resultado(self.banco)
                dados["pedido"] = "abcdef0123456789"
                self.banco.cfg_set(cliente.CHAVE_RESULTADO, json.dumps(dados))
                tarefa.arquivo_resultado(pasta, "abcdef0123456789").write_text("restaurada\n", encoding="utf-8")
                falha = cliente.conferir_tentativa(self.banco)
        self.assertEqual((falha["versao"], falha["situacao"]), (NOVA, "restaurada"))
        aviso = cliente.aviso(self.banco)
        self.assertTrue(aviso["falha"])
        self.assertIn("não foi concluída", aviso["motivo"])
        self.assertEqual(cliente.rodada(self.banco, instalar=lambda a: None)["acao"], "requer_conferencia")

    def test_atualizacao_travada_vai_no_envio_para_a_central(self):
        from src.sync.painel_envio import _atualizacao_travada
        self.assertIsNone(_atualizacao_travada(self.banco))
        self.banco.cfg_set(cliente.CHAVE_TENTATIVA, NOVA)
        cliente.registrar_resultado(self.banco, NOVA, "recusada", "assinatura inválida")
        self.assertEqual(_atualizacao_travada(self.banco)["situacao"], "recusada")

    def test_tentativa_sem_resultado_fica_como_nao_confirmada(self):
        self.banco.cfg_set(cliente.CHAVE_TENTATIVA, NOVA)
        falha = cliente.conferir_tentativa(self.banco)
        self.assertEqual(falha["situacao"], "nao_confirmada")

    def test_confirmacao_sem_banco_nao_abre_o_banco(self):
        with tempfile.TemporaryDirectory() as raiz:
            prova = Path(raiz) / "confirmacao.txt"
            with mock.patch("src.database.conexao.BancoDados", side_effect=AssertionError("abriu o banco")):
                self.assertEqual(cliente.confirmar_atualizacao(VERSAO, prova, sem_banco=True), 0)
            self.assertEqual(prova.read_text(encoding="utf-8").strip(), VERSAO)
            self.assertEqual(cliente.confirmar_atualizacao("0.0.1", prova, sem_banco=True), 1)


class TesteInstalador(unittest.TestCase):
    """Os três instaladores criam a tarefa do SISTEMA, a pasta dos pedidos e apagam a tarefa ao desinstalar."""

    def test_instaladores_criam_e_removem_a_tarefa(self):
        raiz = Path(__file__).resolve().parent.parent / "instalador"
        self.assertTrue((raiz / "tarefa_atualizacao.ps1").is_file())
        for nome in ("WillPDV.iss", "WillAdega.iss", "WillRestaurante.iss"):
            texto = (raiz / nome).read_text(encoding="utf-8-sig")
            self.assertIn("tarefa_atualizacao.ps1", texto, nome)
            self.assertIn("{commonappdata}", texto, nome)
            self.assertIn("users-modify", texto, nome)
            self.assertIn("[UninstallRun]", texto, nome)
            self.assertIn("Atualizacao", texto, nome)

    def test_script_da_tarefa_roda_como_sistema_e_libera_so_iniciar(self):
        texto = (Path(__file__).resolve().parent.parent / "instalador" / "tarefa_atualizacao.ps1").read_text(encoding="utf-8")
        self.assertIn("--aplicar-atualizacao", texto)
        self.assertIn("SYSTEM", texto)
        self.assertIn("(A;;GRGX;;;AU)", texto)                   # usuários podem iniciar (ler e executar), não alterar
        self.assertNotIn("GA;;;AU", texto)


if __name__ == "__main__":
    unittest.main()
