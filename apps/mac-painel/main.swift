// Will Painel para Mac: o painel do dono (willpdv.com.br/painel/) numa janela própria.
//
// O conteúdo vem da nuvem, então o app se atualiza sozinho quando o painel muda. Aqui fica só o que um navegador
// daria: login guardado, janela lembrada, menus com atalhos do Mac, imprimir, baixar relatórios, enviar planilha ou
// foto, links de fora no navegador padrão e uma página para quando a internet cair.
//
// Montado por apps/mac-painel/montar.sh no GitHub (macOS). `--autoteste` abre o painel e sai com 0 se carregou.
import Cocoa
import WebKit

let ENDERECO = URL(string: ProcessInfo.processInfo.environment["WILL_PAINEL_URL"] ?? "https://willpdv.com.br/painel/")!
let NOME_APP = "Will Painel"
let AUTOTESTE = CommandLine.arguments.contains("--autoteste")

final class Controlador: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
    var janela: NSWindow!
    var web: WKWebView!
    var ultimoEndereco: URL = ENDERECO
    var downloads: [AnyObject] = []
    var destinos: [ObjectIdentifier: URL] = [:]

    func applicationDidFinishLaunching(_ aviso: Notification) {
        montarMenu()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()                   // login e preferências ficam salvos entre aberturas
        config.preferences.javaScriptCanOpenWindowsAutomatically = true
        config.applicationNameForUserAgent = "Version/17.0 Safari/605.1.15 WillPainelMac/1.0"
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        web.allowsMagnification = true

        janela = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 800),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        janela.title = NOME_APP
        janela.minSize = NSSize(width: 420, height: 560)
        janela.center()
        janela.setFrameAutosaveName("JanelaPrincipal")         // tamanho e posição lembrados
        janela.contentView = web
        janela.delegate = self
        janela.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        web.load(URLRequest(url: ENDERECO))

        if AUTOTESTE {
            DispatchQueue.main.asyncAfter(deadline: .now() + 45) {
                FileHandle.standardError.write("Autoteste: o painel não carregou em 45 s.\n".data(using: .utf8)!)
                exit(1)
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { janela.makeKeyAndOrderFront(nil) }   // clique no Dock traz a janela de volta
        return true
    }

    // MARK: menus (sem o menu Editar, copiar e colar não funcionam nos campos)
    func montarMenu() {
        let principal = NSMenu()
        func submenu(_ titulo: String, _ itens: [NSMenuItem]) {
            let item = NSMenuItem(title: titulo, action: nil, keyEquivalent: "")
            let menu = NSMenu(title: titulo)
            itens.forEach { menu.addItem($0) }
            item.submenu = menu
            principal.addItem(item)
        }
        func item(_ titulo: String, _ acao: Selector?, _ tecla: String = "", _ mods: NSEvent.ModifierFlags = [.command]) -> NSMenuItem {
            let i = NSMenuItem(title: titulo, action: acao, keyEquivalent: tecla)
            i.keyEquivalentModifierMask = mods
            return i
        }
        submenu(NOME_APP, [
            item("Sobre o \(NOME_APP)", #selector(NSApplication.orderFrontStandardAboutPanel(_:))),
            .separator(),
            item("Ocultar \(NOME_APP)", #selector(NSApplication.hide(_:)), "h"),
            item("Ocultar os outros", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("Mostrar todos", #selector(NSApplication.unhideAllApplications(_:))),
            .separator(),
            item("Sair do \(NOME_APP)", #selector(NSApplication.terminate(_:)), "q"),
        ])
        submenu("Arquivo", [
            item("Início do painel", #selector(irAoInicio), "i", [.command, .shift]),
            item("Abrir no navegador", #selector(abrirNoNavegador)),
            .separator(),
            item("Imprimir…", #selector(imprimir), "p"),
            .separator(),
            item("Fechar janela", #selector(NSWindow.performClose(_:)), "w"),
        ])
        submenu("Editar", [
            item("Desfazer", Selector(("undo:")), "z"),
            item("Refazer", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Recortar", #selector(NSText.cut(_:)), "x"),
            item("Copiar", #selector(NSText.copy(_:)), "c"),
            item("Colar", #selector(NSText.paste(_:)), "v"),
            item("Selecionar tudo", #selector(NSText.selectAll(_:)), "a"),
        ])
        submenu("Visualizar", [
            item("Recarregar", #selector(recarregar), "r"),
            item("Voltar", #selector(voltar), "["),
            item("Avançar", #selector(avancar), "]"),
            .separator(),
            item("Aumentar", #selector(aumentar), "+"),
            item("Diminuir", #selector(diminuir), "-"),
            item("Tamanho real", #selector(tamanhoReal), "0"),
            .separator(),
            item("Tela cheia", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
        ])
        let janelaMenu = NSMenu(title: "Janela")
        janelaMenu.addItem(item("Minimizar", #selector(NSWindow.performMiniaturize(_:)), "m"))
        janelaMenu.addItem(item("Zoom", #selector(NSWindow.performZoom(_:))))
        janelaMenu.addItem(item("Mostrar painel", #selector(mostrarJanela), "1"))
        let itemJanela = NSMenuItem(title: "Janela", action: nil, keyEquivalent: "")
        itemJanela.submenu = janelaMenu
        principal.addItem(itemJanela)
        NSApp.mainMenu = principal
        NSApp.windowsMenu = janelaMenu
    }

    @objc func irAoInicio() { web.load(URLRequest(url: ENDERECO)) }
    @objc func abrirNoNavegador() { NSWorkspace.shared.open(web.url ?? ENDERECO) }
    @objc func recarregar() {
        if web.url == nil || web.url?.absoluteString == "about:blank" { web.load(URLRequest(url: ultimoEndereco)) }
        else { web.reload() }
    }
    @objc func voltar() { web.goBack() }
    @objc func avancar() { web.goForward() }
    @objc func aumentar() { web.pageZoom = min(web.pageZoom + 0.1, 3) }
    @objc func diminuir() { web.pageZoom = max(web.pageZoom - 0.1, 0.5) }
    @objc func tamanhoReal() { web.pageZoom = 1 }
    @objc func mostrarJanela() { janela.makeKeyAndOrderFront(nil) }
    @objc func imprimir() {
        if #available(macOS 11.0, *) {
            let operacao = web.printOperation(with: NSPrintInfo.shared)
            operacao.view?.frame = web.bounds
            operacao.runModal(for: janela, delegate: nil, didRun: nil, contextInfo: nil)
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)                                    // fechar esconde; o app continua no Dock
        return false
    }

    // MARK: navegação: o painel fica aqui; o resto abre no navegador padrão
    func mesmoSite(_ url: URL?) -> Bool {
        guard let url = url else { return true }
        if ["about", "blob", "data"].contains(url.scheme ?? "") { return true }
        return url.host == ENDERECO.host
    }

    func webView(_ webView: WKWebView, decidePolicyFor acao: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if #available(macOS 11.3, *), acao.shouldPerformDownload {
            decisionHandler(.download)
            return
        }
        if acao.targetFrame?.isMainFrame != false, !mesmoSite(acao.request.url), let url = acao.request.url,
           ["http", "https", "mailto", "tel"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor resposta: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if #available(macOS 11.3, *), !resposta.canShowMIMEType {
            decisionHandler(.download)
            return
        }
        decisionHandler(.allow)
    }

    // Links com target=_blank e window.open: do painel, na mesma janela; de fora, no navegador.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for acao: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = acao.request.url {
            if mesmoSite(url) { webView.load(acao.request) } else { NSWorkspace.shared.open(url) }
        }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url, url.scheme?.hasPrefix("http") == true { ultimoEndereco = url }
        if let titulo = webView.title, !titulo.isEmpty { janela.title = titulo }
        if AUTOTESTE, webView.url?.host == ENDERECO.host {
            print("Autoteste: painel carregado (\(webView.title ?? "")).")
            exit(0)
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError erro: Error) {
        semInternet(erro)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError erro: Error) {
        if (erro as NSError).code != NSURLErrorCancelled { semInternet(erro) }
    }

    func semInternet(_ erro: Error) {
        let codigo = (erro as NSError).code
        if codigo == NSURLErrorCancelled || codigo == 102 { return }      // 102: virou download
        let html = """
        <html lang="pt-BR"><head><meta charset="utf-8"><style>
        body{font:16px -apple-system,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;
        margin:0;background:#0f1f1b;color:#e8f2ef}div{text-align:center;max-width:420px}
        button{font:inherit;padding:.7rem 1.4rem;border:0;border-radius:10px;background:#1f9d74;color:#fff;cursor:pointer}
        </style></head><body><div><h1>Sem conexão</h1>
        <p>Não consegui abrir o painel. Confira a internet do Mac e tente de novo.</p>
        <button onclick="location.href='\(ultimoEndereco.absoluteString)'">Tentar de novo</button></div></body></html>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    // MARK: alertas do painel (alert, confirm, prompt) e escolha de arquivo
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage mensagem: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alerta = NSAlert()
        alerta.messageText = mensagem
        alerta.addButton(withTitle: "OK")
        alerta.beginSheetModal(for: janela) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage mensagem: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alerta = NSAlert()
        alerta.messageText = mensagem
        alerta.addButton(withTitle: "OK")
        alerta.addButton(withTitle: "Cancelar")
        alerta.beginSheetModal(for: janela) { resposta in completionHandler(resposta == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt pergunta: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let alerta = NSAlert()
        alerta.messageText = pergunta
        let campo = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
        campo.stringValue = defaultText ?? ""
        alerta.accessoryView = campo
        alerta.addButton(withTitle: "OK")
        alerta.addButton(withTitle: "Cancelar")
        alerta.beginSheetModal(for: janela) { resposta in
            completionHandler(resposta == .alertFirstButtonReturn ? campo.stringValue : nil)
        }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parametros: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let painel = NSOpenPanel()
        painel.allowsMultipleSelection = parametros.allowsMultipleSelection
        painel.canChooseDirectories = false
        painel.beginSheetModal(for: janela) { resposta in completionHandler(resposta == .OK ? painel.urls : nil) }
    }

    func applicationDidBecomeActive(_ aviso: Notification) {
        if janela != nil, !janela.isVisible { janela.makeKeyAndOrderFront(nil) }
    }
}

// MARK: downloads (relatórios em PDF, planilhas): vão para Downloads e aparecem no Finder
@available(macOS 11.3, *)
extension Controlador: WKDownloadDelegate {
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
        downloads.append(download)
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
        downloads.append(download)
    }

    func download(_ download: WKDownload, decideDestinationUsing resposta: URLResponse, suggestedFilename nome: String,
                  completionHandler: @escaping (URL?) -> Void) {
        let pasta = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first!
        var destino = pasta.appendingPathComponent(nome.isEmpty ? "arquivo" : nome)
        let base = destino.deletingPathExtension().lastPathComponent
        let ext = destino.pathExtension
        var n = 1
        while FileManager.default.fileExists(atPath: destino.path) {
            n += 1
            destino = pasta.appendingPathComponent(ext.isEmpty ? "\(base) (\(n))" : "\(base) (\(n)).\(ext)")
        }
        destinos[ObjectIdentifier(download)] = destino
        completionHandler(destino)
    }

    func downloadDidFinish(_ download: WKDownload) {
        if let url = destinos.removeValue(forKey: ObjectIdentifier(download)) {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        }
        downloads.removeAll { $0 === download }
    }

    func download(_ download: WKDownload, didFailWithError erro: Error, resumeData: Data?) {
        destinos.removeValue(forKey: ObjectIdentifier(download))
        downloads.removeAll { $0 === download }
        let alerta = NSAlert()
        alerta.messageText = "O arquivo não foi baixado."
        alerta.informativeText = erro.localizedDescription
        alerta.runModal()
    }
}

let app = NSApplication.shared
let controlador = Controlador()
app.delegate = controlador
app.setActivationPolicy(.regular)
app.run()
