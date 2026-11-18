"""Backup do caixa na nuvem: envio do backup local, lista, recuperação da loja inteira e limites da nuvem."""
import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.controllers.utilitario_controller import UtilitarioController
from src.database import protecao
from src.database.conexao import BancoDados
from src.sync import backup_nuvem
from tests.test_nuvem import TestClient, nuvem, preparar_lojas, TOKENS

try:
    from backend import backup_nuvem as nuvem_backup
except (ImportError, RuntimeError):
    nuvem_backup = None


class _Http:
    """O TestClient não aceita `timeout`."""

    def __init__(self, http):
        self.http, self.chamadas = http, []

    def post(self, url, data=None, headers=None, timeout=None):
        self.chamadas.append(("POST", url))
        return self.http.post(url, content=data, headers=headers)

    def get(self, url, headers=None, timeout=None):
        self.chamadas.append(("GET", url))
        return self.http.get(url, headers=headers)


@unittest.skipIf(TestClient is None or nuvem_backup is None, "Dependências da nuvem ausentes")
class BaseBackup(unittest.TestCase):
    def setUp(self):
        preparar_lojas()
        with nuvem.SessionLocal() as db:
            db.query(nuvem_backup.BackupNuvem).delete()
            db.commit()
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.raiz = Path(self.pasta.name)
        self.banco = BancoDados(str(self.raiz / "loja.db"))
        self.addCleanup(self.banco.fechar)
        self.banco.cfg_set("pasta_backup", str(self.raiz / "backups"))
        self.loja = sorted(TOKENS)[0]
        self.banco.cfg_set("api_url", "http://testserver/v1/sincronizar")
        self.banco.cfg_set("api_token", TOKENS[self.loja])
        self.client = TestClient(nuvem.app)
        self.addCleanup(self.client.close)
        self.http = _Http(self.client)
        self.util = UtilitarioController(self.banco)


class TesteBackupNuvem(BaseBackup):
    def test_sem_backup_local_nao_envia(self):
        self.assertFalse(backup_nuvem.ha_pendente(self.banco))
        self.assertFalse(backup_nuvem.enviar(self.banco, self.http))
        self.assertEqual(self.http.chamadas, [])

    def test_envia_uma_vez_e_respeita_o_intervalo(self):
        self.util.backup()
        self.assertTrue(backup_nuvem.enviar(self.banco, self.http))
        self.assertFalse(backup_nuvem.ha_pendente(self.banco))           # mesmo arquivo
        with mock.patch("src.core.formatacao.agora", return_value="2026-11-18 23:59:59"):
            self.util.backup()                                           # outro nome de arquivo
        self.assertFalse(backup_nuvem.ha_pendente(self.banco))           # arquivo novo, mas dentro de 3 h
        self.banco.cfg_set(backup_nuvem.CHAVE_ULTIMO, "2000-01-01 00:00:00")
        self.assertTrue(backup_nuvem.ha_pendente(self.banco))
        lista = backup_nuvem.listar(self.banco, self.http)
        self.assertEqual(len(lista), 1)
        self.assertGreater(lista[0]["tamanho_banco"], 0)
        self.assertIn("Backup na nuvem: último enviado", backup_nuvem.situacao(self.banco)[1])

    def test_recupera_a_loja_mantendo_token_e_licenca_desta_instalacao(self):
        self.banco.cfg_set("marcador", "loja-antiga")
        self.banco.cfg_set("licenca_token", "licenca-antiga")
        self.util.backup()
        backup_nuvem.enviar(self.banco, self.http)
        # PC novo: banco vazio, ligado à nuvem com o código de instalação novo (outra licença)
        novo = BancoDados(str(self.raiz / "novo.db"))
        self.addCleanup(novo.fechar)
        novo.cfg_set("pasta_backup", str(self.raiz / "backups-novo"))
        novo.cfg_set("api_url", "http://testserver/v1/sincronizar")
        novo.cfg_set("api_token", TOKENS[self.loja])
        novo.cfg_set("licenca_token", "licenca-nova")
        backup_id = backup_nuvem.listar(novo, self.http)[0]["id"]
        backup_nuvem.restaurar(novo, backup_id, None, self.http)
        marca = Path(str(novo.caminho) + "." + protecao.PENDENTE)
        self.assertTrue(marca.exists())
        recuperado = Path(marca.read_text(encoding="utf-8").strip())
        restaurado = BancoDados(str(recuperado))
        self.addCleanup(restaurado.fechar)
        self.assertEqual(restaurado.cfg("marcador"), "loja-antiga")             # dados da loja voltam
        self.assertEqual(restaurado.cfg("licenca_token"), "licenca-nova")       # instalação atual fica
        self.assertEqual(restaurado.cfg("api_token"), TOKENS[self.loja])

    def test_outra_loja_nao_ve_nem_baixa(self):
        self.util.backup()
        backup_nuvem.enviar(self.banco, self.http)
        outra = sorted(TOKENS)[1]
        cab = {"Authorization": f"Bearer {TOKENS[outra]}"}
        self.assertEqual(self.client.get("/v1/backup/lista", headers=cab).json()["backups"], [])
        with nuvem.SessionLocal() as db:
            bid = db.query(nuvem_backup.BackupNuvem.id).first()[0]
        self.assertEqual(self.client.get(f"/v1/backup/{bid}", headers=cab).status_code, 404)

    def test_nuvem_recusa_arquivo_que_nao_e_banco_ou_corrompido(self):
        cab = {"Authorization": f"Bearer {TOKENS[self.loja]}", "X-Backup-Feito-Em": "2026-11-18 10:00:00"}
        lixo = gzip.compress(b"nao sou sqlite" * 10)
        r = self.client.post("/v1/backup", content=lixo,
                             headers={**cab, "X-Backup-Sha256": hashlib.sha256(lixo).hexdigest()})
        self.assertEqual(r.status_code, 422)
        bom = gzip.compress(b"SQLite format 3\x00" + b"x" * 100)
        r = self.client.post("/v1/backup", content=bom, headers={**cab, "X-Backup-Sha256": "0" * 64})
        self.assertEqual(r.status_code, 422)

    def test_retencao_por_dia_mes_e_limite(self):
        cab = {"Authorization": f"Bearer {TOKENS[self.loja]}"}
        def mandar(quando, extra=b""):
            dados = gzip.compress(b"SQLite format 3\x00" + quando.encode() + extra)
            r = self.client.post("/v1/backup", content=dados, headers={
                **cab, "X-Backup-Feito-Em": quando, "X-Backup-Sha256": hashlib.sha256(dados).hexdigest()})
            self.assertEqual(r.status_code, 200, r.text)
        for dia in range(1, 21):                                       # 20 dias de novembro, 2 por dia
            mandar(f"2026-11-{dia:02d} 10:00:00")
            mandar(f"2026-11-{dia:02d} 22:00:00")
        mandar("2026-10-15 22:00:00")
        mandar("2026-09-15 22:00:00")
        lista = self.client.get("/v1/backup/lista", headers=cab).json()["backups"]
        dias = [b["feito_em"] for b in lista]
        self.assertEqual(dias[:7], [f"2026-11-{d:02d} 22:00:00" for d in range(20, 13, -1)])
        self.assertIn("2026-10-15 22:00:00", dias)
        self.assertIn("2026-09-15 22:00:00", dias)
        self.assertLessEqual(len(dias), 7 + 4)
        with mock.patch.object(nuvem_backup, "LIMITE_LOJA_BYTES", 1):         # limite: o mais novo nunca sai
            mandar("2026-11-21 10:00:00")
        dias = [b["feito_em"] for b in self.client.get("/v1/backup/lista", headers=cab).json()["backups"]]
        self.assertEqual(dias, ["2026-11-21 10:00:00"])

    def test_caixa_adicional_nao_envia(self):
        self.util.backup()
        with mock.patch.object(type(self.banco), "remoto", True, create=True):
            self.assertFalse(backup_nuvem.ha_pendente(self.banco))


class TesteCentralBackup(BaseBackup):
    def test_central_lista_e_baixa_com_auditoria(self):
        from backend import central_fornecedor as central
        with central._trava:
            central._tentativas.clear()
        self.util.backup()
        backup_nuvem.enviar(self.banco, self.http)
        c = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(c.close)
        self.assertEqual(c.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"},
                                headers={"X-Central-Login": "1"}).status_code, 200)
        lista = c.get(f"/v1/fornecedor/lojas/{self.loja}/backups").json()["backups"]
        self.assertEqual(len(lista), 1)
        r = c.get(f"/v1/fornecedor/lojas/{self.loja}/backups/{lista[0]['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(gzip.decompress(r.content).startswith(b"SQLite format 3"))
        with nuvem.SessionLocal() as db:
            self.assertTrue(db.query(central.AuditoriaFornecedor).filter_by(acao="baixar_backup_nuvem").count())


class TesteTelaBackupNuvem(BaseBackup):
    def test_tela_lista_e_recupera(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from src.controllers.contexto import Contexto
        from src.ui_qt.backup_nuvem import JanelaBackupNuvem
        self.util.backup()
        backup_nuvem.enviar(self.banco, self.http)
        ctx = Contexto(self.banco)
        janela = JanelaBackupNuvem(ctx, http=self.http, perguntar=lambda _t: True)
        self.addCleanup(janela.deleteLater)
        self.assertEqual(janela.tabela.rowCount(), 1)
        self.assertTrue(janela.recuperar())
        self.assertIn("Feche e abra", janela.mensagem.text())
        self.assertTrue(Path(str(self.banco.caminho) + "." + protecao.PENDENTE).exists())
        app.processEvents()
