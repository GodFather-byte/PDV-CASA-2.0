"""Central em banco temporário, assinatura de teste e rede simulada."""
from __future__ import annotations

import json
import tempfile
import unittest
import threading
import sqlite3
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import urllib.error

from licenciador.central import Central, ClientePonte, ErroCentral
from licenciador.central_bot import TravaCentral, servir
from src.core import ed25519, licenca


class TesteCentral(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name)
        self.semente = bytes(range(32))
        self.chave = self.pasta / "teste.key"
        self.chave.write_text(self.semente.hex(), encoding="ascii")
        self.publica = patch.object(licenca, "CHAVE_PUBLICA_HEX",
                                   ed25519.chave_publica(self.semente).hex())
        self.publica.start()
        self.addCleanup(self.publica.stop)
        self.hoje = patch("src.core.formatacao.hoje", return_value="2026-10-21")
        self.hoje.start()
        self.addCleanup(self.hoje.stop)
        self.agora = patch("src.core.formatacao.agora_dt", return_value=datetime(2026, 10, 21, 12))
        self.agora.start()
        self.addCleanup(self.agora.stop)
        self.agora_texto = patch("src.core.formatacao.agora", return_value="2026-10-21 12:00:00")
        self.agora_texto.start()
        self.addCleanup(self.agora_texto.stop)
        self.chamadas = []
        self.falhar = False
        self.publicados = {}
        self.ponte = ClientePonte("https://exemplo.invalid", "segredo-teste", self.http)
        self.central = Central(self.pasta / "central.db", self.ponte, self.chave)
        self.addCleanup(self.central.fechar)
        self.central.cadastrar("LOJA-1", "Loja Um")
        self.central.administrador(1001)

    def http(self, metodo, rota, dados):
        self.chamadas.append((metodo, rota, dados))
        if self.falhar:
            raise ErroCentral("Falha simulada.")
        if rota == "/v1/central/estado":
            return {"caixas": [], "licencas": list(self.publicados.values()), "solicitacoes": []}
        if rota == "/v1/central/lojas":
            return {"lojas": [{"chave_loja": l["chave"], "nome": l["nome"], "ativa": bool(l["ativa"])}
                             for l in self.central.lojas()]}
        if rota == "/v1/central/licencas":
            self.publicados[dados["id"]] = dados
        if rota == "/v1/central/caixas":
            return {"token": "token-exclusivo-caixa"}
        return {}

    def emitir(self, meses=1):
        pedido = self.central.preparar_emissao(1001, "LOJA-1", meses)
        identificador = self.central.confirmar_emissao(1001, pedido)
        return self.central.db.execute("SELECT * FROM licencas WHERE id=?", (identificador,)).fetchone()

    def test_emite_assinado_localmente_e_renova_a_partir_da_validade(self):
        primeira = self.emitir()
        segunda = self.emitir()
        self.assertEqual(primeira["expira_em"], "2026-11-21")
        self.assertEqual(segunda["expira_em"], "2026-12-21")
        lida = licenca.ler_licenca(segunda["codigo"])
        self.assertEqual(lida["loja"], "LOJA-1")
        self.assertEqual(lida["emitida_em"], date(2026, 10, 21))
        self.assertFalse(segunda["publicada"])

    def test_confirmacao_idempotente_persistida_entre_reinicios(self):
        pedido = self.central.preparar_emissao(1001, "LOJA-1", 2)
        identificador = self.central.confirmar_emissao(1001, pedido)
        outra = Central(self.central.arquivo, arquivo_chave=self.chave)
        try:
            self.assertEqual(outra.confirmar_emissao(1001, pedido), identificador)
            self.assertEqual(outra.db.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 1)
        finally:
            outra.fechar()

    def test_confirmacao_e_exclusiva_do_administrador_e_expira(self):
        pedido = self.central.preparar_emissao(1001, "LOJA-1", 1)
        self.central.administrador(2002)
        with self.assertRaises(ErroCentral):
            self.central.confirmar_emissao(2002, pedido)
        with patch("src.core.formatacao.agora", return_value="2026-10-21 12:06:00"):
            with self.assertRaisesRegex(ErroCentral, "vencida"):
                self.central.confirmar_emissao(1001, pedido)
        self.assertEqual(self.central.db.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 0)

    def test_administrador_removido_nao_emite_e_loja_desativada_tambem_nao(self):
        pedido = self.central.preparar_emissao(1001, "LOJA-1", 1)
        self.central.cadastrar("LOJA-1", "Um", False)
        with self.assertRaisesRegex(ErroCentral, "desativada"):
            self.central.confirmar_emissao(1001, pedido)
        self.central.administrador(1001, remover=True)
        with self.assertRaisesRegex(ErroCentral, "não autorizado"):
            self.central.confirmar_emissao(1001, pedido)

    def test_chave_errada_nao_deixa_licenca_ou_confirmacao_consumida(self):
        self.chave.write_text(bytes(reversed(range(32))).hex(), encoding="ascii")
        pedido = self.central.preparar_emissao(1001, "LOJA-1", 1)
        with self.assertRaises(ErroCentral):
            self.central.confirmar_emissao(1001, pedido)
        self.assertEqual(self.central.db.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 0)
        self.assertFalse(self.central.db.execute("SELECT usada FROM confirmacoes").fetchone()[0])

    def test_importacao_atomica_valida_tudo_antes_e_preserva_original(self):
        codigo = licenca.gerar_licenca(self.semente, "LOJA-1", 30, date(2026, 10, 21))
        origem = self.pasta / "historico.json"
        texto = json.dumps([{"codigo": codigo}, {"codigo": "invalido"}])
        origem.write_text(texto, encoding="utf-8")
        with self.assertRaises(licenca.LicencaInvalida):
            self.central.importar_historico(origem)
        self.assertEqual(origem.read_text(encoding="utf-8"), texto)
        self.assertEqual(self.central.db.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 0)
        origem.write_text(json.dumps([{"codigo": codigo}]), encoding="utf-8")
        self.assertEqual(self.central.importar_historico(origem), 1)
        self.assertEqual(self.central.importar_historico(origem), 0)
        self.central.sincronizar()
        self.assertEqual(self.publicados, {})  # importar não migra a loja automaticamente

    def test_permanente_nao_renova(self):
        codigo = licenca.gerar_licenca(self.semente, "LOJA-1", licenca.MAX_DIAS, date(2026, 10, 21))
        origem = self.pasta / "historico.json"
        origem.write_text(json.dumps([{"codigo": codigo}]), encoding="utf-8")
        self.central.importar_historico(origem)
        with self.assertRaisesRegex(ErroCentral, "permanente"):
            self.emitir()

    def test_publicacao_repetida_apos_falha_nao_emite_de_novo(self):
        item = self.emitir()
        self.falhar = True
        with self.assertRaises(ErroCentral):
            self.central.sincronizar()
        self.falhar = False
        self.central.sincronizar()
        self.central.sincronizar()
        self.assertEqual(list(self.publicados), [item["id"]])
        self.assertEqual(self.central.db.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 1)
        self.assertTrue(self.central.db.execute("SELECT publicada FROM licencas").fetchone()[0])
        self.assertEqual(self.central.config("ultima_sincronizacao"), "2026-10-21 12:00:00")

    def test_aprovar_caixa_nao_guarda_token_em_banco_ou_auditoria(self):
        token = self.central.provisionar("LOJA-1", str(uuid4()))
        self.assertEqual(token, "token-exclusivo-caixa")
        self.assertNotIn(token, "\n".join(self.central.db.iterdump()))
        with self.assertRaises(ErroCentral):
            self.central.provisionar("LOJA-1", "nome-do-pc")

    def test_backup_restauravel_em_novo_caminho(self):
        item = self.emitir()
        backup = self.pasta / "backup.db"
        self.central.backup(backup)
        destino = self.pasta / "recuperada.db"
        Central.restaurar(backup, destino)
        recuperada = Central(destino)
        try:
            self.assertTrue(recuperada.autorizado(1001))
            self.assertEqual(recuperada.db.execute("SELECT id FROM licencas").fetchone()[0], item["id"])
        finally:
            recuperada.fechar()
        with self.assertRaises(ErroCentral):
            Central.restaurar(backup, destino)
        with self.assertRaises(ErroCentral):
            self.central.backup(backup)

    def test_restauracao_reconcilia_emissao_publicada_sem_duplicar(self):
        pedido = self.central.preparar_emissao(1001, "LOJA-1", 1)
        backup = self.pasta / "anterior.db"
        self.central.backup(backup)
        identificador = self.central.confirmar_emissao(1001, pedido)
        self.central.sincronizar()
        destino = self.pasta / "recuperada.db"
        Central.restaurar(backup, destino)
        recuperada = Central(destino, self.ponte, self.chave)
        try:
            with self.assertRaisesRegex(ErroCentral, "Sincronize"):
                recuperada.confirmar_emissao(1001, pedido)
            recuperada.sincronizar()
            self.assertEqual(recuperada.confirmar_emissao(1001, pedido), identificador)
            self.assertEqual(recuperada.db.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 1)
        finally:
            recuperada.fechar()

    def test_trava_impede_dois_servicos(self):
        primeira = TravaCentral(self.central.arquivo)
        segunda = TravaCentral(self.central.arquivo)
        primeira.adquirir()
        try:
            with self.assertRaises(ErroCentral):
                segunda.adquirir()
        finally:
            primeira.liberar()
        segunda.adquirir()
        segunda.liberar()

    def test_url_exige_https_sem_credenciais(self):
        for url in ("http://site.example", "https://usuario:senha@site.example", "https://site.example?a=1", ""):
            with self.subTest(url=url), self.assertRaises(ErroCentral):
                ClientePonte(url, "segredo")
        ClientePonte("http://127.0.0.1:8000", "teste")

    def test_erro_http_da_ponte_nao_expoe_token_ou_corpo(self):
        cliente = ClientePonte("https://exemplo.invalid", "segredo-nunca-expor")
        erro = urllib.error.HTTPError("https://exemplo.invalid", 401, "segredo-nunca-expor", {}, None)
        self.addCleanup(erro.close)
        with patch("urllib.request.OpenerDirector.open", side_effect=erro):
            with self.assertRaises(ErroCentral) as falha:
                cliente.chamar("GET", "/v1/central/estado")
        self.assertIn("401", str(falha.exception))
        self.assertNotIn("segredo-nunca-expor", str(falha.exception))

    def test_preserva_grafia_da_chave_original_em_todo_o_fluxo(self):
        self.central.cadastrar("Boate-Centro", "Centro")
        pedido = self.central.preparar_emissao(1001, "boate-centro", 1)
        identificador = self.central.confirmar_emissao(1001, pedido)
        codigo = self.central.db.execute("SELECT codigo FROM licencas WHERE id=?", (identificador,)).fetchone()[0]
        self.assertEqual(licenca.ler_licenca(codigo)["loja"], "Boate-Centro")
        self.central.provisionar("BOATE-CENTRO", str(uuid4()))
        aprovada = next(d for _, r, d in self.chamadas if r == "/v1/central/caixas")
        self.assertEqual(aprovada["chave_loja"], "Boate-Centro")

    def test_servico_do_telegram_foi_desligado(self):
        with self.assertRaisesRegex(ErroCentral, "Telegram da central foi desligado"):
            servir(self.central, "bot-teste")

    def test_recusa_outro_banco_sem_modificar_suas_tabelas(self):
        outro = self.pasta / "outro.db"
        db = sqlite3.connect(outro)
        try:
            db.execute("CREATE TABLE movimento(id INTEGER)")
            db.commit()
            with self.assertRaisesRegex(ErroCentral, "outro banco"):
                Central(outro)
            tabelas = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertEqual(tabelas, ["movimento"])
        finally:
            db.close()

    def test_publicar_historico_exige_autorizacao_e_nao_emite_ou_estende(self):
        codigo = licenca.gerar_licenca(self.semente, "LOJA-1", 30, date(2026, 10, 21))
        origem = self.pasta / "historico.json"
        origem.write_text(json.dumps([{"codigo": codigo}]), encoding="utf-8")
        self.central.importar_historico(origem)
        self.central.sincronizar()
        self.assertFalse(self.publicados)
        identificador = self.central.autorizar_publicacao("LOJA-1")
        self.central.sincronizar()
        self.assertEqual(self.publicados[identificador]["codigo"], codigo)
        self.assertEqual(self.central.db.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 1)

    def test_estado_da_ponte_continua_gravado_sem_o_bot(self):
        self.emitir()
        self.central._guardar_estado({"caixas": [], "licencas": [], "solicitacoes": [
            {"id": str(uuid4()), "chave_loja": "LOJA-1", "situacao": "pendente"}]})
        self.assertTrue(self.central.arquivo.exists())
