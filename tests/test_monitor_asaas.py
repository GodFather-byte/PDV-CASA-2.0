"""Monitor do Asaas (tools/monitor_asaas.py) e arquivos de implantação do worker agendado."""
import unittest
from pathlib import Path

from tools import monitor_asaas

RAIZ = Path(__file__).resolve().parent.parent


def estado(alertas=(), batida="2026-10-17 10:00:00", agora="2026-10-17 10:10:00"):
    return {"alertas": list(alertas), "worker_batida_em": batida, "consultado_em": agora}


class AvaliarEstadoTest(unittest.TestCase):
    def test_tudo_em_ordem(self):
        self.assertEqual(monitor_asaas.avaliar(estado()), [])

    def test_batida_um_pouco_atrasada_nao_alerta(self):
        # O servidor alerta com 5 min; o cron do GitHub atrasa, então toleramos até 30 min.
        atual = estado(["worker_sem_batida"], batida="2026-10-17 10:00:00", agora="2026-10-17 10:20:00")
        self.assertEqual(monitor_asaas.avaliar(atual), [])

    def test_worker_parado_alerta(self):
        atual = estado(["worker_sem_batida"], batida="2026-10-17 08:00:00", agora="2026-10-17 10:00:00")
        self.assertEqual(monitor_asaas.avaliar(atual), ["worker_sem_batida"])

    def test_worker_que_nunca_rodou_alerta(self):
        atual = estado(["worker_sem_batida"], batida=None)
        self.assertEqual(monitor_asaas.avaliar(atual), ["worker_nunca_rodou"])

    def test_outros_alertas_do_servidor_sempre_passam(self):
        atual = estado(["tarefas_com_erro", "fila_atrasada", "conciliacao_atrasada"])
        self.assertEqual(monitor_asaas.avaliar(atual),
                         ["tarefas_com_erro", "fila_atrasada", "conciliacao_atrasada"])

    def test_data_ilegivel_nao_esconde_problema(self):
        self.assertEqual(monitor_asaas.avaliar(estado(batida="ontem")), ["worker_sem_batida"])


class ImplantacaoTest(unittest.TestCase):
    def ler(self, caminho):
        return (RAIZ / caminho).read_text(encoding="utf-8")

    def test_render_declara_plano_pago_e_variaveis_asaas(self):
        texto = self.ler("render.yaml")
        self.assertIn("plan: starter", texto)
        self.assertNotIn("plan: free", texto)
        for chave in ("ASAAS_AMBIENTE", "ASAAS_API_KEY", "ASAAS_WEBHOOK_TOKEN", "TZ"):
            self.assertIn(f"key: {chave}", texto)

    def test_ambiente_do_asaas_so_no_painel_para_o_blueprint_nao_desfazer_a_virada(self):
        texto = self.ler("render.yaml")
        bloco = texto.split("key: ASAAS_AMBIENTE", 1)[1].split("- key:", 1)[0]
        self.assertIn("sync: false", bloco)
        self.assertNotIn("value:", bloco)

    def test_chaves_do_asaas_nao_ficam_no_arquivo(self):
        texto = self.ler("render.yaml")
        bloco = texto.split("key: ASAAS_API_KEY", 1)[1].split("- key:", 1)[0]
        self.assertIn("sync: false", bloco)
        self.assertNotIn("value:", bloco)

    def test_worker_agendado_usa_lote_unico_e_segredos(self):
        texto = self.ler(".github/workflows/worker-asaas.yml")
        self.assertIn("python -m backend.worker_asaas --uma-vez", texto)
        self.assertIn("secrets.PDV_NUVEM_DB_URL", texto)
        self.assertIn("secrets.ASAAS_API_KEY", texto)
        self.assertIn("TZ: America/Sao_Paulo", texto)
        self.assertIn("cancel-in-progress: false", texto)

    def test_monitor_agendado_usa_token_administrativo(self):
        texto = self.ler(".github/workflows/monitor-asaas.yml")
        self.assertIn("python -m tools.monitor_asaas", texto)
        self.assertIn("secrets.PDV_API_TOKEN", texto)


if __name__ == "__main__":
    unittest.main()
