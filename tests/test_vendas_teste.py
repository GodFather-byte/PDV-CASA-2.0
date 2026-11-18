"""Apagar vendas de teste com a senha de segurança do dono (caixa)."""
from __future__ import annotations

from src.controllers import vendas_teste_controller as vt
from src.controllers.vendas_teste_controller import TurnoFechado, VendasTesteController
from src.core.erros import ErroNegocio, ErroPermissao
from tests.test_caixa import BaseCaixa

SENHA = "segredo123"


class TesteVendasTeste(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.ctl = VendasTesteController(self.banco, self.adm)

    def _venda_fechada(self, qtd=2):
        vid = self.vender((self.skol, qtd))
        self.pagar(vid, "Dinheiro", 800 * qtd)
        self.caixa.fechar(vid)
        return vid

    def _com_senha(self):
        self.ctl.definir_senha(SENHA, SENHA)

    # ---------------------------------------------------------------- senha
    def test_sem_senha_cadastrada_bloqueia(self):
        vid = self._venda_fechada()
        with self.assertRaisesRegex(ErroNegocio, "Crie antes a senha"):
            self.ctl.apagar([vid], "qualquer")
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM vendas WHERE id = ?", (vid,)))

    def test_senha_guardada_so_como_hash_e_fora_da_config(self):
        self._com_senha()
        linha = self.banco.um("SELECT senha_hash FROM seguranca_dono")
        self.assertNotIn(SENHA, linha["senha_hash"])
        self.assertTrue(linha["senha_hash"].startswith("pbkdf2$"))
        self.assertIsNone(self.banco.um("SELECT 1 FROM config WHERE valor LIKE '%pbkdf2$%'"))

    def test_senha_curta_ou_confirmacao_diferente(self):
        with self.assertRaises(ErroNegocio):
            self.ctl.definir_senha("123", "123")
        with self.assertRaises(ErroNegocio):
            self.ctl.definir_senha(SENHA, "outra12345")

    def test_trocar_exige_a_atual(self):
        self._com_senha()
        with self.assertRaises(ErroPermissao):
            self.ctl.definir_senha("nova12345", "nova12345", atual="errada")
        self.ctl.definir_senha("nova12345", "nova12345", atual=SENHA)
        vid = self._venda_fechada()
        self.assertEqual(self.ctl.apagar([vid], "nova12345")["apagadas"], 1)

    def test_so_gerente_mexe(self):
        caixa_id = self.banco.inserir("operadores", {"nome": "ZE", "nivel": 1, "ativo": 1, "senha": "x"})
        with self.assertRaises(ErroPermissao):
            VendasTesteController(self.banco, caixa_id).definir_senha(SENHA, SENHA)

    def test_cinco_erros_bloqueiam_quinze_minutos(self):
        self._com_senha()
        vid = self._venda_fechada()
        for _ in range(4):
            with self.assertRaisesRegex(ErroPermissao, "incorreta"):
                self.ctl.apagar([vid], "errada")
        with self.assertRaisesRegex(ErroPermissao, "bloqueada por 15"):
            self.ctl.apagar([vid], "errada")
        with self.assertRaisesRegex(ErroPermissao, "bloqueada"):
            self.ctl.apagar([vid], SENHA)              # nem a certa passa durante o bloqueio
        self.avancar(minutes=16)
        self.assertEqual(self.ctl.apagar([vid], SENHA)["apagadas"], 1)

    # ---------------------------------------------------------------- apagar
    def test_apaga_venda_devolve_estoque_e_registra(self):
        self._com_senha()
        vid = self._venda_fechada(3)
        uuid = self.banco.valor("SELECT uuid FROM vendas WHERE id = ?", (vid,))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 97)
        r = self.ctl.apagar([vid], SENHA)
        self.assertEqual(r, {"apagadas": 1, "total_cent": 2400})
        self.assertIsNone(self.banco.um("SELECT 1 FROM vendas WHERE id = ?", (vid,)))
        self.assertIsNone(self.banco.um("SELECT 1 FROM itens_venda WHERE venda_id = ?", (vid,)))
        self.assertIsNone(self.banco.um("SELECT 1 FROM pagamentos_venda WHERE venda_id = ?", (vid,)))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 100)
        apagada = self.banco.um("SELECT * FROM vendas_apagadas WHERE uuid = ?", (uuid,))
        self.assertEqual((apagada["total_cent"], apagada["origem"], apagada["operador_id"]), (2400, "caixa", self.adm))
        self.assertIsNotNone(self.banco.um(
            "SELECT 1 FROM auditoria_eventos WHERE entidade = 'venda' AND entidade_id = ? AND acao = 'apagada_como_teste'",
            (uuid,)))
        self.assertEqual(vt.pendentes_envio(self.banco)[0]["uuid"], uuid)

    def test_venda_cancelada_nao_devolve_estoque_duas_vezes(self):
        self._com_senha()
        vid = self._venda_fechada(2)
        self.caixa.cancelar_venda(vid, "teste")
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 100)
        self.ctl.apagar([vid], SENHA)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 100)

    def test_nfce_autorizada_bloqueia(self):
        self._com_senha()
        vid = self._venda_fechada()
        self.banco.executar("INSERT INTO nfce_notas(venda_id, ref, ambiente, situacao, criada_em) "
                            "VALUES (?, 'r1', 'producao', 'autorizada', '2026-10-03 21:00:00')",
                            (vid,))
        with self.assertRaisesRegex(ErroNegocio, "NFC-e"):
            self.ctl.apagar([vid], SENHA)
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM vendas WHERE id = ?", (vid,)))

    def test_venda_aberta_nao_entra(self):
        self._com_senha()
        vid = self.vender((self.skol, 1))
        with self.assertRaisesRegex(ErroNegocio, "aberta"):
            self.ctl.apagar([vid], SENHA)

    def test_tudo_ou_nada(self):
        self._com_senha()
        boa = self._venda_fechada()
        ruim = self.vender((self.agua, 1))
        with self.assertRaises(ErroNegocio):
            self.ctl.apagar([boa, ruim], SENHA)
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM vendas WHERE id = ?", (boa,)))

    def test_turno_fechado_pede_confirmacao(self):
        self._com_senha()
        vid = self._venda_fechada()
        self.turnos.fechar(self.turno, self.adm, 10000 + 1600)
        with self.assertRaises(TurnoFechado):
            self.ctl.apagar([vid], SENHA)
        self.assertEqual(self.ctl.apagar([vid], SENHA, confirmar_turno_fechado=True)["apagadas"], 1)

    def test_candidatas_mostram_bloqueio(self):
        self._com_senha()
        vid = self._venda_fechada()
        lista = self.ctl.candidatas("2026-10-03", "2026-10-03")
        self.assertEqual([(c["id"], c["bloqueio"]) for c in lista], [(vid, None)])

    # ---------------------------------------------------------------- nuvem
    def test_ordem_do_painel_apaga_sem_senha_e_e_idempotente(self):
        vid = self._venda_fechada()
        uuid = self.banco.valor("SELECT uuid FROM vendas WHERE id = ?", (vid,))
        vt.anotar_resposta(self.banco, {"apagar_no_caixa": [uuid, "de-outro-caixa"]}, None)
        self.assertIsNone(self.banco.um("SELECT 1 FROM vendas WHERE id = ?", (vid,)))
        self.assertEqual(self.banco.valor("SELECT origem FROM vendas_apagadas WHERE uuid = ?", (uuid,)), "painel")
        self.assertEqual([p["uuid"] for p in vt.pendentes_envio(self.banco)], [uuid])
        self.assertEqual(VendasTesteController(self.banco).aplicar_da_nuvem([uuid]), {"apagadas": [], "recusadas": []})
        self.assertEqual(vt.recusadas_envio(self.banco), [])

    def test_ordem_do_painel_respeita_nfce_e_avisa(self):
        vid = self._venda_fechada()
        uuid = self.banco.valor("SELECT uuid FROM vendas WHERE id = ?", (vid,))
        self.banco.executar("INSERT INTO nfce_notas(venda_id, ref, ambiente, situacao, criada_em) "
                            "VALUES (?, 'r2', 'producao', 'autorizada', '2026-10-03 21:00:00')", (vid,))
        vt.anotar_resposta(self.banco, {"apagar_no_caixa": [uuid]}, None)
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM vendas WHERE id = ?", (vid,)))
        recusa = vt.recusadas_envio(self.banco)
        self.assertEqual(recusa[0]["uuid"], uuid)
        self.assertIn("NFC-e", recusa[0]["motivo"])
        vt.anotar_resposta(self.banco, {"recusadas_uuids": [uuid]}, None)
        self.assertEqual(vt.recusadas_envio(self.banco), [])

    def test_confirmacao_da_nuvem_tira_da_fila(self):
        self._com_senha()
        vid = self._venda_fechada()
        uuid = self.banco.valor("SELECT uuid FROM vendas WHERE id = ?", (vid,))
        self.ctl.apagar([vid], SENHA)
        h = vt.hash_para_enviar(self.banco)
        self.assertTrue(h)
        vt.anotar_resposta(self.banco, {"apagadas_uuids": [uuid], "seguranca_ok": True}, h)
        self.assertEqual(vt.pendentes_envio(self.banco), [])
        self.assertIsNone(vt.hash_para_enviar(self.banco))
