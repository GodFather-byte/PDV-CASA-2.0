"""WillPDV Licenças (programa separado do fornecedor): chave, emissão mensal/permanente/teste, histórico, tela e autoteste."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from licenciador import autoteste, nucleo
from licenciador.nucleo import ErroLicenciador, Historico
from src.core import ed25519, licenca
from src.database.conexao import BancoDados

RAIZ = Path(__file__).resolve().parents[1]
HOJE = date(2026, 10, 9)


def _tk_disponivel() -> bool:
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


class BaseLicenciador(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="pdv_lic_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.pasta, ignore_errors=True))
        self.chave = self.pasta / "licenca_privada.key"
        self.publica = nucleo.criar_chave(self.chave)
        # a chave de teste faz o papel da chave que vai dentro do PDV
        patcher = mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", self.publica)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.historico = Historico(self.pasta / "historico.json")


class TesteChave(BaseLicenciador):
    def test_criar_nao_sobrescreve_e_o_arquivo_e_o_mesmo_do_cli(self):
        with self.assertRaisesRegex(ErroLicenciador, "Já existe"):
            nucleo.criar_chave(self.chave)
        from tools import gerar_licenca
        self.assertEqual(ed25519.chave_publica(gerar_licenca._ler_semente(self.chave)).hex(), self.publica)

    def test_estados_da_chave(self):
        self.assertTrue(nucleo.estado_chave(self.chave).pronta)
        sumida = nucleo.estado_chave(self.pasta / "nao_existe.key")
        self.assertFalse(sumida.existe)
        self.assertIn("Ainda não há chave", sumida.mensagem)
        estragada = self.pasta / "estragada.key"
        estragada.write_text("isto nao e uma chave", encoding="ascii")
        e = nucleo.estado_chave(estragada)
        self.assertTrue(e.existe and not e.legivel and not e.pronta)
        outra = self.pasta / "outra.key"
        nucleo.criar_chave(outra)
        with mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", "00" * 32):
            e = nucleo.estado_chave(self.chave)
        self.assertTrue(e.legivel and not e.confere and not e.pronta)
        self.assertIn("NÃO é a do PDV", e.mensagem)

    def test_importar_recusa_arquivo_errado_e_so_troca_com_confirmacao(self):
        destino = self.pasta / "dest" / "licenca_privada.key"
        lixo = self.pasta / "lixo.txt"
        lixo.write_text("nada a ver", encoding="ascii")
        with self.assertRaises(ErroLicenciador):
            nucleo.importar_chave(lixo, destino)
        self.assertTrue(nucleo.importar_chave(self.chave, destino).pronta)             # primeira vez: copia
        outra = self.pasta / "outra.key"
        nucleo.criar_chave(outra)
        with self.assertRaisesRegex(ErroLicenciador, "Já existe"):
            nucleo.importar_chave(outra, destino)                                       # já existe: pede confirmação
        nucleo.importar_chave(outra, destino, substituir=True)
        self.assertEqual(destino.read_text(), outra.read_text())
        self.assertEqual(destino.with_suffix(".key.bak").read_text(), self.chave.read_text())   # a antiga fica guardada

    def test_backup_da_chave(self):
        copia = nucleo.backup_chave(self.pasta, self.chave)
        self.assertEqual(copia.read_text(), self.chave.read_text())
        with self.assertRaises(ErroLicenciador):
            nucleo.backup_chave(self.pasta, self.pasta / "nao_existe.key")


class TesteEmissao(BaseLicenciador):
    def test_validade_por_mes_de_calendario_permanente_e_teste(self):
        self.assertEqual(nucleo.validade("mensal", 1, HOJE), date(2026, 11, 9))
        self.assertEqual(nucleo.validade("mensal", 12, HOJE), date(2027, 10, 9))
        self.assertEqual(nucleo.validade("mensal", 1, date(2026, 1, 31)), date(2026, 2, 28))      # fim de mês não estoura
        self.assertEqual((nucleo.validade("permanente", 0, HOJE) - HOJE).days, licenca.MAX_DIAS)
        self.assertEqual(nucleo.validade("teste", 7, HOJE), date(2026, 10, 16))
        for tipo, qtd in (("mensal", 0), ("mensal", nucleo.MAX_MESES + 1), ("teste", 0), ("teste", nucleo.MAX_DIAS_TESTE + 1), ("xyz", 1)):
            with self.assertRaises(ErroLicenciador, msg=(tipo, qtd)):
                nucleo.validade(tipo, qtd, HOJE)

    def test_mensal_e_aceita_pelo_pdv(self):
        e = nucleo.emitir("BOATE-ESTRELA", "mensal", 1, self.chave, HOJE)
        self.assertEqual((e.loja, e.expira_em, e.descricao), ("BOATE-ESTRELA", date(2026, 11, 9), "Mensal (1 mês)"))
        banco = BancoDados(":memory:")
        self.addCleanup(banco.fechar)
        for chave, valor in (("licenca_exigir", "S"), ("licenca_token", e.codigo), ("chave_loja", "boate-estrela")):
            banco.cfg_set(chave, valor)
        estado = licenca.estado(banco, HOJE)                       # o mesmo teste que o caixa faz na entrada
        self.assertEqual((estado.situacao, estado.dias), ("ok", 31))
        self.assertEqual(licenca.estado(banco, date(2026, 11, 10)).situacao, "carencia")      # venceu ontem: carência
        self.assertEqual(licenca.estado(banco, date(2026, 11, 20)).situacao, "bloqueada")

    def test_permanente_nao_vence_na_vida_util(self):
        e = nucleo.emitir("CASA-VERDE", "permanente", 0, self.chave, HOJE)
        self.assertEqual((e.expira_em - e.emitida_em).days, licenca.MAX_DIAS)
        self.assertEqual(e.descricao, "Permanente")
        banco = BancoDados(":memory:")
        self.addCleanup(banco.fechar)
        for chave, valor in (("licenca_exigir", "S"), ("licenca_token", e.codigo)):
            banco.cfg_set(chave, valor)
        estado = licenca.estado(banco, date(2036, 10, 9))
        self.assertEqual(estado.situacao, "ok")                    # dez anos depois ainda vale

    def test_teste_de_7_dias(self):
        e = nucleo.emitir("LOJA-NOVA", "teste", 7, self.chave, HOJE)
        self.assertEqual((e.expira_em - e.emitida_em).days, 7)
        self.assertEqual(e.descricao, "Teste (7 dias)")

    def test_recusa_loja_vazia_e_chave_que_nao_e_a_do_pdv(self):
        for loja in ("", "   "):
            with self.assertRaisesRegex(ErroLicenciador, "nome"):
                nucleo.emitir(loja, "mensal", 1, self.chave, HOJE)
        with mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", "00" * 32), self.assertRaisesRegex(ErroLicenciador, "NÃO é a do PDV"):
            nucleo.emitir("X", "mensal", 1, self.chave, HOJE)
        with self.assertRaisesRegex(ErroLicenciador, "Ainda não há chave"):
            nucleo.emitir("X", "mensal", 1, self.pasta / "nao_existe.key", HOJE)

    def test_loja_com_espacos_sobrantes_e_normalizada(self):
        self.assertEqual(nucleo.emitir("  Boate   Estrela ", "mensal", 1, self.chave, HOJE).loja, "Boate Estrela")

    def test_conferir_codigo(self):
        e = nucleo.emitir("BOATE", "mensal", 1, self.chave, HOJE)
        r = nucleo.conferir(e.codigo, HOJE)
        self.assertEqual((r["loja"], r["dias"], r["permanente"]), ("BOATE", 31, False))
        self.assertIn("Válida", r["situacao"])
        self.assertEqual(nucleo.conferir(e.codigo, date(2026, 12, 1))["situacao"], "Vencida")
        self.assertTrue(nucleo.conferir(nucleo.emitir("P", "permanente", 0, self.chave, HOJE).codigo, HOJE)["permanente"])
        adulterado = e.codigo[:-4] + ("AAAA" if not e.codigo.endswith("AAAA") else "BBBB")
        with self.assertRaises(ErroLicenciador):
            nucleo.conferir(adulterado, HOJE)
        with self.assertRaises(ErroLicenciador):
            nucleo.conferir("isso não é um código", HOJE)

    def test_mensagem_pronta_para_o_cliente(self):
        e = nucleo.emitir("BOATE", "mensal", 1, self.chave, HOJE)
        m = nucleo.mensagem_para_o_cliente(e)
        self.assertIn(e.codigo, m)
        self.assertIn("válida até 09/11/2026", m)
        self.assertIn("Código de licença", m)
        self.assertIn("sem vencimento", nucleo.mensagem_para_o_cliente(nucleo.emitir("P", "permanente", 0, self.chave, HOJE)))


class TesteHistorico(BaseLicenciador):
    def emitir(self, loja, tipo, qtd, quando):
        e = nucleo.emitir(loja, tipo, qtd, self.chave, quando)
        self.historico.adicionar(e)
        return e

    def test_guarda_lista_e_remove(self):
        e = self.emitir("A", "mensal", 1, HOJE)
        self.assertEqual([d["codigo"] for d in self.historico.todas()], [e.codigo])
        self.assertEqual(self.historico.lojas(), ["A"])
        self.historico.remover(e.codigo)
        self.assertEqual(self.historico.todas(), [])

    def test_uma_linha_por_loja_com_a_licenca_mais_nova_e_quem_vence_primeiro_no_alto(self):
        self.emitir("BOATE", "mensal", 1, date(2026, 8, 1))          # antiga (vencida)
        self.emitir("BOATE", "mensal", 1, date(2026, 10, 1))         # renovação: vale até 01/11
        self.emitir("BAR", "mensal", 1, date(2026, 9, 5))            # venceu em 05/10
        self.emitir("CASA", "permanente", 0, date(2026, 7, 1))
        self.emitir("LOUNGE", "mensal", 1, date(2026, 9, 12))        # vence em 12/10: faltam 3 dias
        linhas = self.historico.situacao_das_lojas(HOJE)
        self.assertEqual([l["loja"] for l in linhas], ["BAR", "LOUNGE", "BOATE", "CASA"])
        self.assertEqual([l["situacao"] for l in linhas], ["Vencida", "Vence em 3 dias", "Em dia", "Permanente"])

    def test_arquivo_estragado_nao_derruba_o_programa(self):
        self.historico.arquivo.write_text("{ nao e json", encoding="utf-8")
        self.assertEqual(self.historico.todas(), [])
        self.emitir("A", "mensal", 1, HOJE)                          # e dá para voltar a gravar por cima
        self.assertEqual(len(self.historico.todas()), 1)


@unittest.skipUnless(_tk_disponivel(), "sem ambiente gráfico")
class TesteTela(BaseLicenciador):
    def setUp(self):
        super().setUp()
        from licenciador.tela import Janela
        self.janela = Janela(self.chave, self.historico)
        self.addCleanup(self.janela.destroy)
        self.janela.update()

    def test_gerar_mensal_mostra_o_codigo_e_guarda_no_historico(self):
        j = self.janela
        j.var_loja.set("BOATE-ESTRELA")
        j.var_tipo.set("mensal"); j.var_qtd.set("2"); j.atualizar_validade()
        self.assertIn("Válida até", j.lbl_validade.cget("text"))
        j.gerar(); j.update()
        codigo = j.txt_codigo.get("1.0", "end").strip()
        self.assertTrue(codigo.startswith("PDVL1."))
        self.assertEqual(licenca.ler_licenca(codigo)["loja"], "BOATE-ESTRELA")
        self.assertEqual(len(self.historico.todas()), 1)
        self.assertEqual(j.grade.total(), 1)
        self.assertFalse(j.btn_copiar.instate(["disabled"]))
        j.copiar(lambda e: e.codigo, "ok")
        self.assertEqual(j.clipboard_get(), codigo)

    def test_permanente_desliga_a_quantidade_e_mostra_sem_vencimento(self):
        j = self.janela
        j.var_tipo.set("permanente"); j.atualizar_validade()
        self.assertTrue(j.spin.instate(["disabled"]))
        self.assertIn("Sem vencimento", j.lbl_validade.cget("text"))
        j.var_loja.set("CASA"); j.gerar(); j.update()
        self.assertEqual(self.historico.todas()[0]["tipo"], "permanente")

    def test_quantidade_invalida_avisa_na_hora_e_loja_vazia_mostra_erro(self):
        j = self.janela
        j.var_tipo.set("mensal"); j.var_qtd.set("0"); j.atualizar_validade()
        self.assertIn("1 a", j.lbl_validade.cget("text"))
        j.var_qtd.set("1"); j.atualizar_validade()
        with mock.patch("src.ui.tema.erro") as erro:
            j.gerar()
        erro.assert_called_once()
        self.assertEqual(self.historico.todas(), [])

    def test_renovar_preenche_o_formulario_com_a_ultima_licenca(self):
        e = nucleo.emitir("BAR", "mensal", 3, self.chave, HOJE)
        self.historico.adicionar(e)
        j = self.janela
        j.atualizar_lojas()
        j.grade.selecionar(e.codigo)
        j.renovar(); j.update()
        self.assertEqual((j.var_loja.get(), j.var_tipo.get(), j.var_qtd.get()), ("BAR", "mensal", "3"))

    def test_conferir_pela_tela(self):
        e = nucleo.emitir("BAR", "mensal", 1, self.chave)
        j = self.janela
        j.txt_conferir.insert("1.0", e.codigo)
        j.conferir()
        self.assertIn("Loja: BAR", j.lbl_conferido.cget("text"))
        j.txt_conferir.delete("1.0", "end"); j.txt_conferir.insert("1.0", "lixo")
        j.conferir()
        self.assertNotIn("Loja:", j.lbl_conferido.cget("text"))

    def test_sem_chave_o_botao_de_gerar_fica_desligado_com_aviso(self):
        from licenciador.tela import Janela
        j = Janela(self.pasta / "nao_existe.key", self.historico)
        self.addCleanup(j.destroy)
        j.update()
        self.assertTrue(j.btn_gerar.instate(["disabled"]))
        self.assertIn("Ainda não há chave", j.aviso_chave.cget("text"))
        self.assertFalse(j.btn_criar.instate(["disabled"]))          # dá para criar quando não existe
        self.assertTrue(self.janela.btn_criar.instate(["disabled"]))  # e não quando já existe

    def test_remover_do_historico(self):
        e = nucleo.emitir("BAR", "mensal", 1, self.chave)
        self.historico.adicionar(e)
        j = self.janela
        j.atualizar_lojas(); j.grade.selecionar(e.codigo)
        with mock.patch("src.ui.tema.confirmar", return_value=True):
            j.remover()
        self.assertEqual(self.historico.todas(), [])


@unittest.skipUnless(_tk_disponivel(), "sem ambiente gráfico")
class TesteVencimentos(BaseLicenciador):
    def emitir(self, loja, tipo, qtd, quando):
        self.historico.adicionar(nucleo.emitir(loja, tipo, qtd, self.chave, quando))

    def test_separa_vencidas_de_quem_vence_em_breve_e_ignora_permanente_e_em_dia(self):
        self.emitir("BAR", "mensal", 1, date(2026, 9, 5))            # venceu em 05/10
        self.emitir("LOUNGE", "mensal", 1, date(2026, 9, 12))        # vence em 12/10: faltam 3 dias
        self.emitir("HOJE", "mensal", 1, date(2026, 9, 9))           # vence em 09/10: hoje
        self.emitir("BOATE", "mensal", 1, date(2026, 10, 1))         # em dia
        self.emitir("CASA", "permanente", 0, date(2026, 7, 1))
        resumo = nucleo.resumo_vencimentos(self.historico, HOJE)
        self.assertEqual(resumo["vencidas"], ["BAR"])
        self.assertEqual(resumo["vencendo"], [("HOJE", 0), ("LOUNGE", 3)])

    def test_texto_do_aviso(self):
        self.emitir("BAR", "mensal", 1, date(2026, 9, 5))
        self.emitir("LOUNGE", "mensal", 1, date(2026, 9, 12))
        texto = nucleo.texto_do_aviso(nucleo.resumo_vencimentos(self.historico, HOJE))
        self.assertIn("1 licença vencida: BAR", texto)
        self.assertIn("LOUNGE (3 dias)", texto)

    def test_sem_nada_a_renovar_o_aviso_some(self):
        self.emitir("BOATE", "mensal", 1, date(2026, 10, 1))
        self.assertEqual(nucleo.texto_do_aviso(nucleo.resumo_vencimentos(self.historico, HOJE)), "")


class TesteBackup(BaseLicenciador):
    SENHA = "uma-senha-bem-longa"

    def setUp(self):
        super().setUp()
        self.nuvem = self.pasta / "meu-drive"
        self.nuvem.mkdir()
        self.historico.adicionar(nucleo.emitir("BAR", "mensal", 1, self.chave, HOJE))

    def test_historico_vai_para_a_subpasta_com_a_data_e_fica_igual(self):
        arquivo = nucleo.backup_historico(self.nuvem, self.historico, HOJE)
        self.assertEqual(arquivo, self.nuvem / nucleo.PASTA_BACKUP / "historico-2026-10-09.json")
        self.assertEqual(arquivo.read_bytes(), self.historico.arquivo.read_bytes())
        self.assertEqual(list(arquivo.parent.glob(".*.tmp")), [])

    def test_no_mesmo_dia_a_copia_e_trocada_e_as_mais_antigas_saem(self):
        for dia in range(1, 6):
            nucleo.backup_historico(self.nuvem, self.historico, date(2026, 10, dia), manter=3)
        nucleo.backup_historico(self.nuvem, self.historico, date(2026, 10, 5), manter=3)
        nomes = sorted(p.name for p in (self.nuvem / nucleo.PASTA_BACKUP).iterdir())
        self.assertEqual(nomes, ["historico-2026-10-03.json", "historico-2026-10-04.json", "historico-2026-10-05.json"])

    def test_recusa_historico_vazio_e_pasta_que_nao_existe(self):
        with self.assertRaisesRegex(ErroLicenciador, "Ainda não há licenças"):
            nucleo.backup_historico(self.nuvem, Historico(self.pasta / "vazio.json"), HOJE)
        with self.assertRaisesRegex(ErroLicenciador, "Google Drive"):
            nucleo.backup_historico(self.pasta / "nao_existe", self.historico, HOJE)

    def test_chave_so_vai_criptografada_e_volta_igual(self):
        arquivo = nucleo.backup_chave_protegido(self.nuvem, self.SENHA, self.chave)
        self.assertEqual(arquivo.name, "licenca_privada.key.pdvbkp")
        semente = self.chave.read_text(encoding="ascii").strip()
        self.assertNotIn(semente.encode("ascii"), arquivo.read_bytes())
        destino = self.pasta / "outra" / "licenca_privada.key"
        estado = nucleo.restaurar_chave_protegida(arquivo, self.SENHA, destino)
        self.assertTrue(estado.pronta)
        self.assertEqual(destino.read_text(encoding="ascii"), self.chave.read_text(encoding="ascii"))

    def test_senha_errada_ou_curta_e_arquivo_alterado_sao_recusados(self):
        with self.assertRaisesRegex(ErroLicenciador, "12 a 1024"):
            nucleo.backup_chave_protegido(self.nuvem, "curta", self.chave)
        arquivo = nucleo.backup_chave_protegido(self.nuvem, self.SENHA, self.chave)
        destino = self.pasta / "restaurada.key"
        with self.assertRaisesRegex(ErroLicenciador, "Senha incorreta"):
            nucleo.restaurar_chave_protegida(arquivo, "outra-senha-longa-demais", destino)
        self.assertFalse(destino.exists())
        dados = bytearray(arquivo.read_bytes())
        dados[-20] ^= 1
        arquivo.write_bytes(bytes(dados))
        with self.assertRaises(ErroLicenciador):
            nucleo.restaurar_chave_protegida(arquivo, self.SENHA, destino)

    def test_restaurar_chave_nao_troca_a_existente_sem_confirmacao(self):
        arquivo = nucleo.backup_chave_protegido(self.nuvem, self.SENHA, self.chave)
        with self.assertRaisesRegex(ErroLicenciador, "Já existe"):
            nucleo.restaurar_chave_protegida(arquivo, self.SENHA, self.chave)
        nucleo.restaurar_chave_protegida(arquivo, self.SENHA, self.chave, substituir=True)

    def test_restaurar_historico_guarda_o_atual_e_recusa_lixo_e_codigo_de_outra_chave(self):
        copia = nucleo.backup_historico(self.nuvem, self.historico, HOJE)
        novo = Historico(self.pasta / "novo" / "historico.json")
        self.assertEqual(nucleo.restaurar_historico(copia, novo), 1)
        self.assertEqual([d["loja"] for d in novo.todas()], ["BAR"])
        self.assertEqual(nucleo.restaurar_historico(copia, novo), 1)
        self.assertTrue(novo.arquivo.with_suffix(".json.bak").exists())
        lixo = self.pasta / "lixo.json"
        lixo.write_text("{ nao e json", encoding="utf-8")
        with self.assertRaisesRegex(ErroLicenciador, "não é um backup"):
            nucleo.restaurar_historico(lixo, novo)
        lixo.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ErroLicenciador, "nenhuma licença"):
            nucleo.restaurar_historico(lixo, novo)
        with mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", ed25519.chave_publica(bytes(range(32))).hex()):
            with self.assertRaisesRegex(ErroLicenciador, "não confere"):
                nucleo.restaurar_historico(copia, novo)
        self.assertEqual(len(novo.todas()), 1)               # nada foi trocado pelo backup recusado

    def test_configuracao_guarda_e_arquivo_estragado_volta_ao_padrao(self):
        config = nucleo.Configuracao(self.pasta / "config.json")
        self.assertIsNone(config.pasta_backup)
        self.assertTrue(config.backup_automatico)
        config.definir(pasta_backup=self.nuvem, backup_automatico=False)
        outra = nucleo.Configuracao(self.pasta / "config.json")
        self.assertEqual((outra.pasta_backup, outra.backup_automatico), (self.nuvem, False))
        config.arquivo.write_text("{ nao e json", encoding="utf-8")
        self.assertIsNone(config.pasta_backup)

    def test_acha_a_pasta_do_google_drive_quando_ela_existe(self):
        casa = self.pasta / "casa"
        (casa / "Meu Drive").mkdir(parents=True)
        with mock.patch.object(Path, "home", return_value=casa):
            self.assertIn(casa / "Meu Drive", nucleo.pastas_do_google_drive())
        with mock.patch.object(Path, "home", return_value=self.pasta / "vazia"):
            self.assertNotIn(self.pasta / "vazia" / "Meu Drive", nucleo.pastas_do_google_drive())


@unittest.skipUnless(_tk_disponivel(), "sem ambiente gráfico")
class TesteTelaBackup(BaseLicenciador):
    def setUp(self):
        super().setUp()
        from licenciador.tela import Janela
        self.nuvem = self.pasta / "drive"
        self.nuvem.mkdir()
        self.janela = Janela(self.chave, self.historico)
        self.addCleanup(self.janela.destroy)
        self.janela.update()

    def emitir_pela_tela(self, loja="BAR"):
        self.janela.var_loja.set(loja)
        self.janela.var_tipo.set("mensal"); self.janela.var_qtd.set("1")
        self.janela.gerar(); self.janela.update()

    def copias(self):
        pasta = self.nuvem / nucleo.PASTA_BACKUP
        return sorted(pasta.glob("historico-*.json")) if pasta.exists() else []

    def test_tem_cinco_abas_e_sem_pasta_nao_copia_nada(self):
        self.assertEqual(len(self.janela.abas.tabs()), 5)
        self.assertTrue(self.janela.btn_backup_agora.instate(["disabled"]))
        self.emitir_pela_tela()
        self.assertEqual(self.copias(), [])

    def test_emitir_guarda_o_historico_sozinho_na_pasta_escolhida(self):
        with mock.patch("licenciador.tela.filedialog.askdirectory", return_value=str(self.nuvem)):
            self.janela.escolher_pasta_backup()
        self.assertEqual(self.janela.config.pasta_backup, self.nuvem)
        self.emitir_pela_tela()
        self.assertEqual(len(self.copias()), 1)
        self.assertIn("Histórico guardado", self.janela.lbl_backup.cget("text"))
        self.assertTrue(self.janela.config.ultimo_backup)

    def test_automatico_desligado_nao_copia(self):
        self.janela.config.definir(pasta_backup=self.nuvem)
        self.janela.var_auto.set(False); self.janela.mudar_automatico()
        self.emitir_pela_tela()
        self.assertEqual(self.copias(), [])

    def test_pasta_que_sumiu_avisa_mas_nao_atrapalha_a_emissao(self):
        self.janela.config.definir(pasta_backup=self.pasta / "sumiu")
        self.emitir_pela_tela()
        self.assertEqual(len(self.historico.todas()), 1)
        self.assertIn("Não consegui guardar", self.janela.lbl_backup.cget("text"))

    def test_backup_agora_guarda_historico_e_chave_criptografada(self):
        self.historico.adicionar(nucleo.emitir("BAR", "mensal", 1, self.chave, HOJE))
        self.janela.config.definir(pasta_backup=self.nuvem)
        senhas = iter(["uma-senha-bem-longa", "uma-senha-bem-longa"])
        with mock.patch("src.ui.tema.pedir_texto", side_effect=lambda *a, **k: next(senhas)), \
                mock.patch("src.ui.tema.mensagem"):
            self.janela.backup_agora()
        self.assertEqual(len(self.copias()), 1)
        self.assertTrue((self.nuvem / nucleo.PASTA_BACKUP / "licenca_privada.key.pdvbkp").exists())

    def test_senhas_diferentes_nao_guardam_a_chave(self):
        self.historico.adicionar(nucleo.emitir("BAR", "mensal", 1, self.chave, HOJE))
        self.janela.config.definir(pasta_backup=self.nuvem)
        senhas = iter(["uma-senha-bem-longa", "outra-senha-bem-longa"])
        with mock.patch("src.ui.tema.pedir_texto", side_effect=lambda *a, **k: next(senhas)), \
                mock.patch("src.ui.tema.erro") as erro, mock.patch("src.ui.tema.mensagem"):
            self.janela.backup_agora()
        erro.assert_called_once()
        self.assertFalse((self.nuvem / nucleo.PASTA_BACKUP / "licenca_privada.key.pdvbkp").exists())

    def test_faixa_de_aviso_aparece_para_licenca_vencida_e_some_ao_renovar(self):
        self.assertFalse(self.janela.aviso_venc.winfo_ismapped())
        self.historico.adicionar(nucleo.emitir("BAR", "mensal", 1, self.chave, date(2020, 1, 1)))
        self.janela.atualizar_lojas(); self.janela.update()
        self.assertIn("vencida", self.janela.aviso_venc.cget("text"))
        self.assertTrue(self.janela.aviso_venc.winfo_ismapped())
        self.emitir_pela_tela("BAR")
        self.assertFalse(self.janela.aviso_venc.winfo_ismapped())


class TesteAutoteste(unittest.TestCase):
    def test_lista_de_modulos_cobre_o_pacote_licenciador(self):
        reais = {".".join(p.relative_to(RAIZ).with_suffix("").parts) for p in (RAIZ / "licenciador").glob("*.py")
                 if p.name not in ("__init__.py", "app.py")}
        self.assertEqual(sorted(reais - set(autoteste.MODULOS)), [])

    def test_executar_devolve_zero_e_escreve_o_relatorio(self):
        with tempfile.TemporaryDirectory() as pasta:
            saida = Path(pasta) / "r.txt"
            self.assertEqual(autoteste.executar(str(saida)), 0)
            texto = saida.read_text(encoding="utf-8")
        self.assertIn("RESULTADO: TUDO CERTO", texto)
        for etapa in ("módulos", "assinatura", "backup", "tela"):
            self.assertIn(f"OK    {etapa}:", texto)

    def test_linha_de_comando(self):
        with tempfile.TemporaryDirectory() as pasta:
            saida = Path(pasta) / "r.txt"
            r = subprocess.run([sys.executable, "-m", "licenciador.app", "--autoteste", str(saida)], cwd=RAIZ,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("TUDO CERTO", saida.read_text(encoding="utf-8"))


class TesteNaoVaiNoPdv(unittest.TestCase):
    def test_pdv_nao_importa_o_licenciador_nem_conhece_o_arquivo_da_chave_privada(self):
        for caminho in (RAIZ / "src").rglob("*.py"):
            texto = caminho.read_text(encoding="utf-8")
            self.assertNotIn("import licenciador", texto, caminho)
            self.assertNotIn("from licenciador", texto, caminho)
            self.assertNotIn("licenca_privada", texto, caminho)


if __name__ == "__main__":
    unittest.main()
