"""Licença mensal offline: assinatura Ed25519, prazos (aviso, carência, bloqueio) e ferramenta do fornecedor."""
from __future__ import annotations

import contextlib
import io
import random
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from src.controllers.turno_controller import TurnoController
from src.core import ed25519, licenca
from src.core.erros import ErroNegocio
from src.core.licenca import LicencaExpirada, LicencaInvalida
from tests.base import BaseTeste

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:  # a biblioteca só serve de referência cruzada; o PDV não depende dela
    Ed25519PrivateKey = None


class TesteEd25519(unittest.TestCase):
    def test_vetores_do_rfc_8032(self):
        vetores = [
            ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
             "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
             "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
            ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
             "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
             "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
        ]
        for semente, publica, mensagem, assinatura in vetores:
            with self.subTest(mensagem=mensagem):
                semente, publica, mensagem, assinatura = map(bytes.fromhex, (semente, publica, mensagem, assinatura))
                self.assertEqual(ed25519.chave_publica(semente), publica)
                self.assertEqual(ed25519.assinar(semente, mensagem), assinatura)
                self.assertTrue(ed25519.verificar(publica, mensagem, assinatura))

    @unittest.skipIf(Ed25519PrivateKey is None, "biblioteca 'cryptography' não instalada")
    def test_confere_com_a_biblioteca_de_referencia(self):
        acaso = random.Random(2026)
        for i in range(8):
            semente, mensagem = acaso.randbytes(32), acaso.randbytes(i * 13)
            ref = Ed25519PrivateKey.from_private_bytes(semente)
            publica = ref.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self.assertEqual(ed25519.chave_publica(semente), publica)
            self.assertEqual(ed25519.assinar(semente, mensagem), ref.sign(mensagem))
            self.assertTrue(ed25519.verificar(publica, mensagem, ref.sign(mensagem)))

    def test_rejeita_adulteracao_e_entradas_malformadas(self):
        semente = bytes(range(32))
        publica, assinatura = ed25519.chave_publica(semente), ed25519.assinar(semente, b"loja")
        self.assertTrue(ed25519.verificar(publica, b"loja", assinatura))
        self.assertFalse(ed25519.verificar(publica, b"loja2", assinatura))
        self.assertFalse(ed25519.verificar(publica, b"loja", assinatura[:-1] + bytes([assinatura[-1] ^ 1])))
        self.assertFalse(ed25519.verificar(ed25519.chave_publica(bytes(32)), b"loja", assinatura))
        for publica_ruim, assinatura_ruim in [(b"", assinatura), (publica, b""), (publica, assinatura[:63]),
                                              (b"\xff" * 32, assinatura), (publica, b"\xff" * 64)]:
            self.assertFalse(ed25519.verificar(publica_ruim, b"loja", assinatura_ruim))


class TesteLicenca(BaseTeste):
    SEMENTE = bytes(range(32))
    HOJE = date(2026, 10, 3)

    def setUp(self):
        super().setUp()
        self.publica = ed25519.chave_publica(self.SEMENTE)
        self.banco.cfg_set("licenca_exigir", "S")

    def codigo(self, dias=30, loja="LOJA-1", emitida=None):
        return licenca.gerar_licenca(self.SEMENTE, loja, dias, emitida or self.HOJE)

    def ativar(self, codigo=None, **kw):
        return licenca.ativar(self.banco, self.codigo() if codigo is None else codigo,
                              hoje=kw.pop("hoje", self.HOJE), chave_publica=self.publica, **kw)

    def estado(self, hoje):
        return licenca.estado(self.banco, hoje=hoje, chave_publica=self.publica)

    # ------------------------------------------------------------ exigência
    def test_no_codigo_fonte_so_exige_quando_ligada(self):
        self.banco.cfg_set("licenca_exigir", "")
        self.assertFalse(licenca.exigida(self.banco))
        self.assertEqual(self.estado(self.HOJE).situacao, "desativada")
        self.assertFalse(self.estado(self.HOJE).bloqueia)
        self.banco.cfg_set("licenca_exigir", "S")
        self.assertTrue(licenca.exigida(self.banco))

    def test_no_executavel_sempre_exige_e_o_banco_nao_desliga(self):
        self.banco.cfg_set("licenca_exigir", "N")
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertTrue(licenca.exigida(self.banco))
            self.assertEqual(self.estado(self.HOJE).situacao, "sem_licenca")

    def test_sem_licenca_bloqueia(self):
        e = self.estado(self.HOJE)
        self.assertEqual(e.situacao, "sem_licenca")
        self.assertTrue(e.bloqueia)
        self.assertIn("Nenhuma licença", e.mensagem)

    # -------------------------------------------------------------- ativação
    def test_ativar_guarda_o_codigo_e_a_chave_da_loja(self):
        lic = self.ativar()
        self.assertEqual((lic["loja"], lic["expira_em"]), ("LOJA-1", date(2026, 11, 2)))
        self.assertEqual(self.banco.cfg("chave_loja"), "LOJA-1")
        self.assertEqual(self.banco.cfg("licenca_ultimo_uso"), "2026-10-03")
        self.assertEqual(self.estado(self.HOJE).situacao, "ok")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'licenca_ativada'"), 1)

    def test_codigo_colado_com_espacos_e_quebras_de_linha(self):
        codigo = self.codigo()
        colado = "  " + codigo[:40] + "\n" + codigo[40:90] + " \r\n" + codigo[90:] + "\n"
        self.assertEqual(self.ativar(colado)["loja"], "LOJA-1")
        self.assertEqual(self.banco.cfg("licenca_token"), codigo)

    def test_rejeita_codigo_adulterado_de_outra_chave_ou_ilegivel(self):
        codigo = self.codigo()
        corpo, assinatura = codigo.rsplit(".", 1)
        adulterado = corpo[:-3] + ("AAA" if not corpo.endswith("AAA") else "BBB") + "." + assinatura
        de_outra_chave = licenca.gerar_licenca(bytes(32), "LOJA-1", 30, self.HOJE)
        for ruim in ("", "lixo", "PDVL1.abc", adulterado, de_outra_chave, codigo + ".x", "XYZ" + codigo):
            with self.subTest(codigo=ruim[:20]):
                with self.assertRaises(LicencaInvalida):
                    self.ativar(ruim)
        self.assertEqual(self.banco.cfg("licenca_token"), "")

    def test_rejeita_licenca_de_outra_loja(self):
        self.banco.cfg_set("chave_loja", "OUTRA")
        with self.assertRaisesRegex(LicencaInvalida, "outra|LOJA-1"):
            self.ativar()
        self.assertEqual(self.banco.cfg("chave_loja"), "OUTRA")

    def test_rejeita_licenca_vencida_e_mais_antiga_que_a_atual(self):
        with self.assertRaises(LicencaExpirada):
            self.ativar(self.codigo(dias=5, emitida=date(2026, 9, 1)))
        self.ativar(self.codigo(dias=30))
        with self.assertRaisesRegex(LicencaInvalida, "mais antiga"):
            self.ativar(self.codigo(dias=10))
        self.ativar(self.codigo(dias=30))                        # repetir o mesmo código é inofensivo
        self.assertEqual(self.ativar(self.codigo(dias=60))["expira_em"], date(2026, 12, 2))

    # ------------------------------------------------------------- prazos
    def test_aviso_carencia_e_bloqueio_pelas_datas(self):
        self.ativar(self.codigo(dias=7))                         # vale até 10/10/2026, inclusive
        casos = [
            (date(2026, 10, 3), "aviso", "vence em 7 dias"),
            (date(2026, 10, 9), "aviso", "vence em 1 dia "),
            (date(2026, 10, 10), "aviso", "vence hoje"),
            (date(2026, 10, 11), "carencia", "mais 5 dias"),
            (date(2026, 10, 15), "carencia", "mais 1 dia;"),
            (date(2026, 10, 16), "bloqueada", "carência terminou"),
        ]
        for hoje, situacao, trecho in casos:
            with self.subTest(hoje=hoje):
                e = self.estado(hoje)
                self.assertEqual(e.situacao, situacao)
                self.assertEqual(e.bloqueia, situacao == "bloqueada")
                self.assertEqual(e.avisa, situacao in ("aviso", "carencia"))
                if trecho:
                    self.assertIn(trecho, e.mensagem)

    def test_editar_o_banco_nao_estende_o_prazo(self):
        self.ativar(self.codigo(dias=7))
        self.banco.cfg_set("licenca_expira_em", "2099-01-01")       # chave que o PDV nem lê mais
        self.banco.cfg_set("licenca_ultimo_uso", "2000-01-01")
        self.assertEqual(self.estado(date(2026, 12, 1)).situacao, "bloqueada")
        self.banco.cfg_set("licenca_token", self.codigo(dias=3650).replace("A", "B", 1))   # código adulterado
        self.assertEqual(self.estado(self.HOJE).situacao, "sem_licenca")

    def test_banco_de_outra_loja_nao_aproveita_a_licenca(self):
        self.ativar()
        self.banco.cfg_set("chave_loja", "OUTRA")
        e = self.estado(self.HOJE)
        self.assertEqual(e.situacao, "sem_licenca")
        self.assertIn("outra loja", e.mensagem)

    def test_relogio_voltado_nao_reabre_o_prazo(self):
        self.ativar(self.codigo(dias=7))
        for dia in range(4, 21):                                    # uso diário até 20/10 (a licença venceu em 10/10)
            licenca.registrar_uso(self.banco, hoje=date(2026, 10, dia))
        self.assertEqual(self.banco.cfg("licenca_ultimo_uso"), "2026-10-20")
        self.assertEqual(self.estado(date(2026, 10, 1)).situacao, "bloqueada")

    def test_apagar_a_data_vista_nao_reabre_o_prazo(self):
        """O movimento da loja também vale como data vista: apagar `licenca_ultimo_uso` e voltar o relógio não basta."""
        self.ativar(self.codigo(dias=7))                                    # vence em 10/10
        self.banco.inserir("turnos", {"numero": 1, "terminal": 1, "aberto_em": "2026-10-20 20:00:00",
                                      "valor_inicial_cent": 0, "cupom_inicial": 1, "status": "fechado"})
        self.banco.executar("DELETE FROM config WHERE chave = 'licenca_ultimo_uso'")
        self.assertEqual(self.estado(date(2026, 10, 1)).situacao, "bloqueada")
        self.banco.executar("DELETE FROM turnos")
        self.banco.inserir("vendas", {"uuid": "x", "aberta_em": "2026-10-20 21:00:00", "fechada_em": "2026-10-20 21:30:00",
                                      "status": "fechada", "cupom": 1})
        self.assertEqual(self.estado(date(2026, 10, 1)).situacao, "bloqueada")
        self.assertEqual(self.estado(date(2026, 10, 1)).dias, -10)          # conta a partir de 20/10, a data da venda

    def test_data_errada_no_futuro_nao_trava_a_loja_de_vez(self):
        self.ativar(self.codigo(dias=30))
        licenca.registrar_uso(self.banco, hoje=date(2030, 1, 1))        # alguém digitou o ano errado e entrou
        self.assertEqual(self.banco.cfg("licenca_ultimo_uso"), "2026-10-06")   # avança no máximo 3 dias por uso
        self.assertEqual(self.estado(date(2026, 10, 4)).situacao, "ok")     # relógio corrigido: tudo normal
        self.assertEqual(self.ativar(self.codigo(dias=60), hoje=date(2026, 10, 4))["expira_em"], date(2026, 12, 2))

    def test_ultimo_uso_avanca_no_maximo_tres_dias_por_vez_e_nunca_recua(self):
        for hoje, esperado in [(date(2026, 10, 3), "2026-10-03"), (date(2026, 10, 4), "2026-10-04"),
                               (date(2026, 10, 20), "2026-10-07"), (date(2026, 10, 20), "2026-10-10"),
                               (date(2026, 10, 1), "2026-10-10")]:
            licenca.registrar_uso(self.banco, hoje=hoje)
            self.assertEqual(self.banco.cfg("licenca_ultimo_uso"), esperado)

    def test_renovacao_menor_so_e_recusada_se_a_licenca_guardada_ainda_valida(self):
        self.ativar(self.codigo(dias=365))
        with self.assertRaisesRegex(LicencaInvalida, "mais antiga"):
            self.ativar(self.codigo(dias=30))
        outra = ed25519.chave_publica(bytes(range(1, 33)))           # chave do fornecedor trocada: o código guardado não valida mais
        novo = licenca.gerar_licenca(bytes(range(1, 33)), "LOJA-1", 30, self.HOJE)
        lic = licenca.ativar(self.banco, novo, hoje=self.HOJE, chave_publica=outra)
        self.assertEqual(lic["expira_em"], date(2026, 11, 2))

    def test_turno_so_isenta_se_for_recente(self):
        isenta = lambda turno, hoje=self.HOJE: licenca.turno_vale_como_isencao(self.banco, turno, hoje=hoje)
        self.assertTrue(isenta({"aberto_em": "2026-10-03 20:00:00"}))
        self.assertTrue(isenta({"aberto_em": "2026-10-02 22:00:00"}))      # turno da noite anterior, ainda aberto
        self.assertFalse(isenta({"aberto_em": "2026-10-01 22:00:00"}))     # esquecido há 2 dias
        self.assertFalse(isenta({"aberto_em": "2026-01-01 08:00:00"}))     # linha antiga inserida à mão
        self.assertFalse(isenta(None))
        self.assertFalse(isenta({}))
        self.assertFalse(isenta({"aberto_em": "lixo"}))
        licenca.registrar_uso(self.banco, hoje=date(2026, 10, 5))           # a data vista avança junto
        self.assertFalse(isenta({"aberto_em": "2026-10-03 20:00:00"}, hoje=self.HOJE))

    def test_usa_o_relogio_do_sistema_quando_nao_recebe_a_data(self):
        self.ativar(self.codigo(dias=7))                         # o relógio dos testes marca 03/10/2026
        self.assertEqual(licenca.estado(self.banco, chave_publica=self.publica).situacao, "aviso")
        self.avancar(days=9)
        self.assertEqual(licenca.estado(self.banco, chave_publica=self.publica).situacao, "carencia")

    # ------------------------------------------------------ chave embutida
    def test_chave_publica_embutida_nao_e_a_de_teste_nem_vazia(self):
        embutida = bytes.fromhex(licenca.CHAVE_PUBLICA_HEX)
        self.assertEqual(len(embutida), 32)
        self.assertNotEqual(embutida, bytes(32))
        self.assertNotEqual(embutida, self.publica)
        with self.assertRaises(LicencaInvalida):                 # código assinado por outra chave
            licenca.ler_licenca(self.codigo())

    # ------------------------------------------------------ ferramenta
    def test_validade_maxima_e_loja_sem_diferenciar_maiusculas(self):
        with self.assertRaisesRegex(ValueError, "máxima"):
            licenca.gerar_licenca(self.SEMENTE, "LOJA-1", licenca.MAX_DIAS + 1, self.HOJE)
        licenca.gerar_licenca(self.SEMENTE, "LOJA-1", licenca.MAX_DIAS, self.HOJE)       # o limite em si vale
        self.ativar(self.codigo(loja="Boate-X"))
        self.ativar(self.codigo(loja="BOATE-X", dias=60))                                  # mesma loja, outra caixa
        self.assertEqual(licenca.estado(self.banco, hoje=self.HOJE, chave_publica=self.publica).situacao, "ok")
        with self.assertRaises(licenca.LicencaInvalida):                                   # outra loja continua recusada
            self.ativar(self.codigo(loja="OUTRA"))

    def test_ferramenta_do_fornecedor_emite_codigo_que_o_pdv_aceita(self):
        from tools import gerar_licenca as ferramenta
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "sub" / "privada.key"
            saida = io.StringIO()
            with contextlib.redirect_stdout(saida):
                ferramenta.novo_par(arquivo)
            publica_hex = saida.getvalue().strip().splitlines()[-1]
            self.assertEqual(len(bytes.fromhex(publica_hex)), 32)
            with self.assertRaises(SystemExit):                  # nunca sobrescreve a chave existente
                ferramenta.novo_par(arquivo)
            with mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", publica_hex):
                saida = io.StringIO()
                with contextlib.redirect_stdout(saida):
                    ferramenta.emitir(arquivo, "LOJA-9", 30)
                codigo = saida.getvalue().strip().splitlines()[-1]
                lic = licenca.ler_licenca(codigo)
                self.assertEqual(lic["loja"], "LOJA-9")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(ferramenta.main(["ver", codigo]), 0)
            with self.assertRaises(SystemExit):                  # chave privada que não bate com a pública embutida
                with contextlib.redirect_stdout(io.StringIO()):
                    ferramenta.emitir(arquivo, "LOJA-9", 30)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ferramenta.main(["ver", "lixo"]), 1)
            with mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", publica_hex):          # --permanente: 100 anos
                saida = io.StringIO()
                with contextlib.redirect_stdout(saida):
                    self.assertEqual(ferramenta.main(["emitir", "--loja", "LOJA-9", "--permanente", "--arquivo", str(arquivo)]), 0)
                lic = licenca.ler_licenca(saida.getvalue().strip().splitlines()[-1])
                self.assertGreater((lic["expira_em"] - lic["emitida_em"]).days, 36000)


class TesteTurnoComLicenca(BaseTeste):
    """TurnoController: com a licença bloqueada não abre turno novo (fechar continua liberado)."""
    SEMENTE = bytes(range(32))

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", ed25519.chave_publica(self.SEMENTE).hex())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.adm = self.operador_adm()
        self.turnos = TurnoController(self.banco)

    def ativar(self, dias):
        hoje = date(2026, 10, 3)                                     # o relógio do teste marca 03/10/2026 21:00
        licenca.ativar(self.banco, licenca.gerar_licenca(self.SEMENTE, "LOJA-1", dias, hoje), hoje=hoje)

    def test_sem_exigencia_abre_normalmente(self):
        self.turnos.abrir(self.adm, 1, 0)
        self.assertEqual(self.banco.cfg("licenca_ultimo_uso"), "")

    def test_exigida_sem_licenca_recusa_abrir(self):
        self.banco.cfg_set("licenca_exigir", "S")
        with self.assertRaisesRegex(ErroNegocio, "Nenhuma licença.*abrir um turno"):
            self.turnos.abrir(self.adm, 1, 0)
        self.assertIsNone(self.turnos.atual())

    def test_licenca_em_dia_ou_em_carencia_abre_e_registra_o_uso(self):
        self.banco.cfg_set("licenca_exigir", "S")
        self.ativar(10)
        self.turnos.abrir(self.adm, 1, 0)
        self.turnos.fechar(self.turnos.atual()["id"], self.adm, 0)
        self.avancar(days=13)                                         # venceu em 13/10; 16/10 ainda está na carência
        self.turnos.abrir(self.adm, 2, 0)
        self.assertEqual(self.banco.cfg("licenca_ultimo_uso"), "2026-10-06")

    def test_vencida_alem_da_carencia_nao_abre_turno_mas_deixa_fechar_o_aberto(self):
        self.banco.cfg_set("licenca_exigir", "S")
        self.ativar(10)
        turno = self.turnos.abrir(self.adm, 1, 0)
        self.avancar(days=20)                                         # 23/10: licença venceu em 13/10 e a carência acabou
        self.assertTrue(licenca.estado(self.banco).bloqueia)
        self.turnos.fechar(turno, self.adm, 0)                       # fechar o turno aberto continua liberado
        with self.assertRaisesRegex(ErroNegocio, "Renove a licença"):
            self.turnos.abrir(self.adm, 2, 0)


if __name__ == "__main__":
    unittest.main()
