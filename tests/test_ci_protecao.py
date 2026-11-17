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
        proprios = [alvo for alvo in runs_on("testes.yml") if "RUNNER_PC" in alvo]
        self.assertEqual(len(proprios), 3)                    # tutorial, publicação e a suíte no Windows
        for alvo in proprios:
            self.assertIn("github.event.repository.private &&", alvo)
            self.assertIn("'windows-latest'", alvo)           # sem a variável, continua no GitHub

    def test_instalador_que_cria_usuario_no_windows_nunca_roda_no_pc_do_dono(self):
        for arquivo in ("build-windows.yml", "will-restaurante.yml", "will-variedades.yml"):
            for alvo in runs_on(arquivo):
                self.assertNotIn("self-hosted", alvo, arquivo)
                self.assertNotIn("RUNNER_PC", alvo, arquivo)

    def test_downloads_vao_para_o_repositorio_publico_quando_configurado(self):
        for arquivo in ("build-windows.yml", "publicar-pacote.yml", "will-restaurante.yml", "will-variedades.yml"):
            texto = (RAIZ / arquivo).read_text(encoding="utf-8")
            self.assertIn("vars.DOWNLOADS_REPO || github.repository", texto, arquivo)
            self.assertIn("secrets.DOWNLOADS_TOKEN || github.token", texto, arquivo)
            self.assertNotIn('--repo "$GITHUB_REPOSITORY" --target', texto, arquivo)

    def test_versao_para_as_lojas_so_sai_quando_o_dono_manda(self):
        for arquivo in ("build-windows.yml", "will-restaurante.yml", "will-variedades.yml"):
            texto = (RAIZ / arquivo).read_text(encoding="utf-8")
            gatilhos = texto.split("\non:", 1)[1].split("\npermissions:", 1)[0]
            self.assertIn("workflow_dispatch", gatilhos, arquivo)
            self.assertNotIn("push:", gatilhos, arquivo)

    def test_privado_sem_runner_economiza_windows(self):
        texto = (RAIZ / "testes.yml").read_text(encoding="utf-8")
        matriz = texto.split("include:", 1)[1].split("steps:", 1)[0]
        pc, pr, merge, manual, normal = [trecho.split("'", 1)[0] for trecho in matriz.split("'[")[1:]]
        self.assertIn("vars.RUNNER_PC)\n            && '[", matriz)              # com o PC: só o Windows 3.12, lá
        self.assertEqual((pc.count("windows-latest"), pc.count("ubuntu")), (1, 0))
        self.assertIn("!vars.RUNNER_PC && github.event_name == 'pull_request'", matriz)
        self.assertIn("!vars.RUNNER_PC && github.event_name == 'push'", matriz)
        self.assertNotIn("windows", pr)                       # PR no privado sem runner: só Linux
        self.assertEqual(merge.count("windows-latest"), 1)    # depois do merge: uma vez no Windows...
        self.assertNotIn("ubuntu", merge)                     # ...e o Linux não repete o que o PR já rodou
        self.assertEqual(manual.count("windows-latest"), 1)
        self.assertEqual(normal.count("windows-latest"), 2)   # público: as duas versões
        self.assertIn("!(github.event.repository.private && vars.RUNNER_PC && github.event_name == 'push')", texto)

    def test_testes_nao_gastam_minutos_a_toa(self):
        texto = (RAIZ / "testes.yml").read_text(encoding="utf-8")
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", texto)
        self.assertEqual(texto.count('paths-ignore: ["docs/**", ".ai/**", "**/*.md"]'), 2)
        for job in ("tutorial-windows:", "publicacao-windows:", "cobrancas-postgres:"):
            trecho = texto.split("  " + job, 1)[1][:400]
            self.assertIn("github.event_name != 'push'", trecho, job)
            self.assertIn("!(github.event.repository.private && vars.RUNNER_PC)", trecho, job)   # com o PC, a suíte cobre

    def test_link_padrao_do_instalador_nao_depende_do_repositorio_do_codigo(self):
        from backend.central_fornecedor import INSTALADORES
        for link in INSTALADORES.values():
            self.assertIn("/willpdv-downloads/releases/download/", link)

    def test_publicacao_nao_depende_da_cota_de_artifacts(self):
        """Repositório privado tem cota pequena de artifacts: o build entrega o instalador num rascunho do repositório de
        downloads, a publicação busca de lá e apaga no fim. Artifact virou cópia opcional (cota cheia não derruba)."""
        for arquivo in ("build-windows.yml", "will-restaurante.yml", "will-variedades.yml", "publicar-pacote.yml"):
            texto = (RAIZ / arquivo).read_text(encoding="utf-8")
            self.assertNotIn("download-artifact", texto, arquivo)
            self.assertIn("select(.tag_name == env.TAG)", texto, arquivo)
            for bloco in texto.split("uses: actions/upload-artifact@v4")[1:]:
                self.assertTrue(bloco.lstrip().startswith("continue-on-error: true"), arquivo)
        for arquivo, edicoes in (("build-windows.yml", ("willpdv", "willadega")), ("will-restaurante.yml", ("willrestaurante",)),
                                 ("will-variedades.yml", ("willvariedades",))):
            texto = (RAIZ / arquivo).read_text(encoding="utf-8")
            for edicao in edicoes:
                self.assertIn(f"TAG: rascunho-{edicao}-${{{{ github.sha }}}}", texto)
                self.assertIn(f'"rascunho-{edicao}-$GITHUB_SHA"', texto)          # e é apagado no fim
            self.assertIn("--draft", texto)


if __name__ == "__main__":
    unittest.main()
