"""Regras do CI que protegem o código e o PC do dono: o runner próprio só roda com o repositório privado e os
instaladores podem ir para um repositório público separado sem quebrar o link das lojas."""
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def runs_on(nome):
    """Cada `runs-on:` do workflow (sem PyYAML, que não está nas dependências fixadas do CI)."""
    return [linha.split("runs-on:", 1)[1].strip() for linha in (RAIZ / nome).read_text(encoding="utf-8").splitlines()
            if linha.strip().startswith("runs-on:")]


class TestCiProtecao(unittest.TestCase):
    def test_runner_proprio_so_com_repositorio_privado(self):
        proprios = [alvo for alvo in runs_on("testes.yml") if "RUNNER_WINDOWS" in alvo]
        self.assertEqual(len(proprios), 3)                    # tutorial, publicação e a suíte no Windows
        for alvo in proprios:
            self.assertIn("github.event.repository.private &&", alvo)
            self.assertIn("'windows-latest'", alvo)           # sem a variável, continua no GitHub

    def test_instalador_que_cria_usuario_no_windows_nunca_roda_no_pc_do_dono(self):
        for arquivo in ("build-windows.yml", "will-restaurante.yml"):
            for alvo in runs_on(arquivo):
                self.assertNotIn("self-hosted", alvo, arquivo)
                self.assertNotIn("RUNNER_WINDOWS", alvo, arquivo)

    def test_downloads_vao_para_o_repositorio_publico_quando_configurado(self):
        for arquivo in ("build-windows.yml", "publicar-pacote.yml", "will-restaurante.yml"):
            texto = (RAIZ / arquivo).read_text(encoding="utf-8")
            self.assertIn("vars.DOWNLOADS_REPO || github.repository", texto, arquivo)
            self.assertIn("secrets.DOWNLOADS_TOKEN || github.token", texto, arquivo)
            self.assertNotIn('--repo "$GITHUB_REPOSITORY" --target', texto, arquivo)

    def test_versao_para_as_lojas_so_sai_quando_o_dono_manda(self):
        for arquivo in ("build-windows.yml", "will-restaurante.yml"):
            texto = (RAIZ / arquivo).read_text(encoding="utf-8")
            gatilhos = texto.split("\non:", 1)[1].split("\npermissions:", 1)[0]
            self.assertIn("workflow_dispatch", gatilhos, arquivo)
            self.assertNotIn("push:", gatilhos, arquivo)


if __name__ == "__main__":
    unittest.main()
