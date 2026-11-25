"""Apps de computador (apps/): o de Mac abre o painel do dono e o de Windows a central do fornecedor, os dois com o
que o dono espera de um programa (login salvo, downloads, links de fora no navegador, sem internet, autoteste)."""
import plistlib
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MAC = RAIZ / "apps" / "mac-painel"
WIN = RAIZ / "apps" / "windows-central"


class TesteAppsDesktop(unittest.TestCase):
    def test_mac_abre_o_painel_com_o_essencial(self):
        fonte = (MAC / "main.swift").read_text(encoding="utf-8")
        self.assertIn('"https://willpdv.com.br/painel/"', fonte)
        for trecho in ("websiteDataStore = .default()", "setFrameAutosaveName", "WKDownloadDelegate", "runOpenPanelWith",
                       "runJavaScriptConfirmPanelWithMessage", "NSWorkspace.shared.open", "Sem conexão", "--autoteste",
                       '"Editar"', "#selector(imprimir)"):
            self.assertIn(trecho, fonte)
        with open(MAC / "Info.plist", "rb") as arquivo:
            info = plistlib.load(arquivo)
        self.assertEqual((info["CFBundleExecutable"], info["CFBundleIdentifier"]), ("WillPainel", "br.com.willpdv.painel"))
        montar = (MAC / "montar.sh").read_text(encoding="utf-8")
        for trecho in ("arm64", "x86_64", "lipo -create", "codesign --force --deep --sign -", "hdiutil create",
                       "backend/painel_web/icones/icone-512.png"):
            self.assertIn(trecho, montar)
        self.assertTrue((RAIZ / "backend/painel_web/icones/icone-512.png").exists())

    def test_windows_abre_a_central_com_o_essencial(self):
        fonte = (WIN / "Program.cs").read_text(encoding="utf-8")
        self.assertIn('"https://willpdv.com.br/central/"', fonte)
        for trecho in ("new Mutex(", "CoreWebView2Environment.CreateAsync", "DownloadStarting", "NewWindowRequested",
                       "WebView2RuntimeNotFoundException", "Keys.F5", "Keys.F11", "Sem conexão", "--autoteste",
                       "GuardarJanela"):
            self.assertIn(trecho, fonte)
        projeto = (WIN / "CentralWB.csproj").read_text(encoding="utf-8")
        self.assertIn("<TargetFramework>net48</TargetFramework>", projeto)
        self.assertIn("Microsoft.Web.WebView2", projeto)
        self.assertTrue((WIN / "CentralWB.ico").exists())
        iss = (WIN / "central.iss").read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", iss)

    def test_workflow_monta_testa_e_publica_so_pela_main(self):
        fluxo = (RAIZ / ".github/workflows/apps-desktop.yml").read_text(encoding="utf-8")
        for trecho in ("runs-on: macos-latest", "runs-on: windows-latest", "--autoteste", "/VERYSILENT",
                       "github.ref == 'refs/heads/main'", "app-mac-painel", "app-windows-central"):
            self.assertIn(trecho, fluxo)
        painel = (RAIZ / "backend/painel_web/index.html").read_text(encoding="utf-8")
        self.assertIn("releases/download/app-mac-painel/WillPainel.dmg", painel)


if __name__ == "__main__":
    unittest.main()
