// Central WB para Windows: a central do fornecedor (willpdv.com.br/central/) numa janela própria.
//
// O conteúdo vem da nuvem, então o app se atualiza sozinho quando a central muda. Aqui fica só o que um navegador
// daria: login guardado, uma janela só (abrir de novo traz a mesma), tamanho e posição lembrados, F5, F11, Ctrl+P,
// zoom, downloads (ZIP de XMLs, planilhas) na pasta Downloads, links de fora no navegador padrão e uma página para
// quando a internet cair. `--autoteste` abre a central e sai com 0 se carregou.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace CentralWB
{
    internal static class Program
    {
        internal const string NomeApp = "Central WB";
        internal static readonly Uri Endereco = new Uri(
            Environment.GetEnvironmentVariable("CENTRAL_WB_URL") ?? "https://willpdv.com.br/central/");
        internal static readonly string Pasta = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WB Sistemas", "Central WB");
        internal static bool Autoteste;

        [STAThread]
        private static int Main(string[] args)
        {
            Autoteste = Array.IndexOf(args, "--autoteste") >= 0;
            using (var unica = new Mutex(true, "WBSistemas.CentralWB", out bool primeira))
            {
                if (!primeira && !Autoteste)
                {
                    Janela.TrazerAberta();                     // já está aberta: mostra a mesma janela
                    return 0;
                }
                Directory.CreateDirectory(Pasta);
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                var janela = new Janela();
                Application.Run(janela);
                return janela.Resultado;
            }
        }
    }

    internal sealed class Janela : Form
    {
        private const string TituloJanela = "Central WB";
        private readonly WebView2 web = new WebView2 { Dock = DockStyle.Fill };
        private readonly string arquivoJanela = Path.Combine(Program.Pasta, "janela.txt");
        private Uri ultimoEndereco = Program.Endereco;
        internal int Resultado;

        internal Janela()
        {
            Text = TituloJanela;
            MinimumSize = new Size(480, 560);
            KeyPreview = true;
            try { Icon = new Icon(Assembly.GetExecutingAssembly().GetManifestResourceStream("CentralWB.CentralWB.ico")); }
            catch { /* sem ícone embutido: usa o padrão */ }
            Controls.Add(web);
            RestaurarJanela();
            Load += async (s, e) => await Iniciar();
            FormClosing += (s, e) => GuardarJanela();
            KeyDown += Teclas;
        }

        internal static void TrazerAberta()
        {
            foreach (var p in Process.GetProcessesByName(Process.GetCurrentProcess().ProcessName))
            {
                if (p.Id == Process.GetCurrentProcess().Id || p.MainWindowHandle == IntPtr.Zero) continue;
                Nativo.ShowWindow(p.MainWindowHandle, 9);     // SW_RESTORE
                Nativo.SetForegroundWindow(p.MainWindowHandle);
                return;
            }
        }

        private async Task Iniciar()
        {
            try
            {
                var ambiente = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Program.Pasta, "WebView2"));
                await web.EnsureCoreWebView2Async(ambiente);
            }
            catch (WebView2RuntimeNotFoundException)
            {
                var r = MessageBox.Show("Para abrir a central, o Windows precisa do Microsoft Edge WebView2 (gratuito, da " +
                                        "Microsoft). Abrir a página para instalar?", TituloJanela, MessageBoxButtons.YesNo,
                                        MessageBoxIcon.Information);
                if (r == DialogResult.Yes) AbrirFora(new Uri("https://go.microsoft.com/fwlink/p/?LinkId=2124703"));
                Resultado = 2;
                Close();
                return;
            }
            var core = web.CoreWebView2;
            core.Settings.UserAgent = core.Settings.UserAgent + " CentralWB/1.0";
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.AreDevToolsEnabled = false;
            core.DocumentTitleChanged += (s, e) => Text = string.IsNullOrWhiteSpace(core.DocumentTitle)
                ? TituloJanela : core.DocumentTitle;
            core.NewWindowRequested += NovaJanela;
            core.NavigationStarting += Navegando;
            core.NavigationCompleted += Carregou;
            core.DownloadStarting += (s, e) =>
            {
                var pasta = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                e.ResultFilePath = UnicoEm(Path.Combine(pasta, "Downloads"), Path.GetFileName(e.ResultFilePath));
            };
            core.Navigate(Program.Endereco.ToString());
            if (Program.Autoteste)
            {
                var limite = new System.Windows.Forms.Timer { Interval = 60000 };
                limite.Tick += (s, e) => { Console.Error.WriteLine("Autoteste: a central não carregou em 60 s."); Resultado = 1; Close(); };
                limite.Start();
            }
        }

        private static bool MesmoSite(Uri url) =>
            url == null || url.Scheme == "about" || url.Scheme == "data" || url.Scheme == "blob"
            || string.Equals(url.Host, Program.Endereco.Host, StringComparison.OrdinalIgnoreCase);

        private void Navegando(object sender, CoreWebView2NavigationStartingEventArgs e)
        {
            if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var url) && !MesmoSite(url)
                && (url.Scheme == "http" || url.Scheme == "https" || url.Scheme == "mailto" || url.Scheme == "tel"))
            {
                e.Cancel = true;                               // de fora da central: navegador padrão
                AbrirFora(url);
            }
        }

        private void NovaJanela(object sender, CoreWebView2NewWindowRequestedEventArgs e)
        {
            e.Handled = true;
            if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out var url)) return;
            if (MesmoSite(url)) web.CoreWebView2.Navigate(url.ToString()); else AbrirFora(url);
        }

        private void Carregou(object sender, CoreWebView2NavigationCompletedEventArgs e)
        {
            var atual = web.Source;
            if (e.IsSuccess)
            {
                if (atual != null && atual.Scheme.StartsWith("http")) ultimoEndereco = atual;
                if (Program.Autoteste && atual != null && atual.Host == Program.Endereco.Host)
                {
                    Console.WriteLine("Autoteste: central carregada (" + web.CoreWebView2.DocumentTitle + ").");
                    Resultado = 0;
                    Close();
                }
                return;
            }
            if (e.WebErrorStatus == CoreWebView2WebErrorStatus.OperationCanceled) return;
            var volta = ultimoEndereco.ToString().Replace("'", "%27");
            web.CoreWebView2.NavigateToString(
                "<html lang='pt-BR'><head><meta charset='utf-8'><style>body{font:16px 'Segoe UI',sans-serif;display:flex;" +
                "align-items:center;justify-content:center;height:100vh;margin:0;background:#0f1f1b;color:#e8f2ef}" +
                "div{text-align:center;max-width:420px}button{font:inherit;padding:.7rem 1.4rem;border:0;border-radius:10px;" +
                "background:#1f9d74;color:#fff;cursor:pointer}</style></head><body><div><h1>Sem conexão</h1>" +
                "<p>Não consegui abrir a central. Confira a internet e tente de novo (F5).</p>" +
                "<button onclick=\"location.href='" + volta + "'\">Tentar de novo</button></div></body></html>");
        }

        private void Teclas(object sender, KeyEventArgs e)
        {
            if (web.CoreWebView2 == null) return;
            if (e.KeyCode == Keys.F5)
            {
                if (web.Source == null || web.Source.Scheme == "about" || web.Source.Scheme == "data")
                    web.CoreWebView2.Navigate(ultimoEndereco.ToString());
                else web.CoreWebView2.Reload();
                e.Handled = true;
            }
            else if (e.KeyCode == Keys.F11)
            {
                if (FormBorderStyle == FormBorderStyle.None)
                {
                    FormBorderStyle = FormBorderStyle.Sizable;
                    WindowState = FormWindowState.Normal;
                }
                else
                {
                    FormBorderStyle = FormBorderStyle.None;
                    WindowState = FormWindowState.Maximized;
                }
                e.Handled = true;
            }
            else if (e.Alt && e.KeyCode == Keys.Home)
            {
                web.CoreWebView2.Navigate(Program.Endereco.ToString());
                e.Handled = true;
            }
        }

        private static void AbrirFora(Uri url)
        {
            try { Process.Start(new ProcessStartInfo(url.ToString()) { UseShellExecute = true }); }
            catch { /* sem navegador padrão: ignora */ }
        }

        private static string UnicoEm(string pasta, string nome)
        {
            Directory.CreateDirectory(pasta);
            if (string.IsNullOrWhiteSpace(nome)) nome = "arquivo";
            var destino = Path.Combine(pasta, nome);
            var n = 1;
            while (File.Exists(destino))
            {
                n++;
                destino = Path.Combine(pasta, Path.GetFileNameWithoutExtension(nome) + " (" + n + ")" + Path.GetExtension(nome));
            }
            return destino;
        }

        // Tamanho e posição da janela: guardados ao fechar, conferidos contra as telas ligadas ao abrir.
        private void RestaurarJanela()
        {
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(1280, 820);
            try
            {
                var p = File.ReadAllText(arquivoJanela).Split(';');
                var area = new Rectangle(int.Parse(p[0]), int.Parse(p[1]), int.Parse(p[2]), int.Parse(p[3]));
                foreach (var tela in Screen.AllScreens)
                {
                    if (!tela.WorkingArea.IntersectsWith(area)) continue;
                    StartPosition = FormStartPosition.Manual;
                    Bounds = area;
                    if (p.Length > 4 && p[4] == "max") WindowState = FormWindowState.Maximized;
                    break;
                }
            }
            catch { /* primeira vez ou arquivo estranho: centraliza */ }
        }

        private void GuardarJanela()
        {
            try
            {
                var r = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                File.WriteAllText(arquivoJanela, r.X + ";" + r.Y + ";" + r.Width + ";" + r.Height + ";" +
                                                 (WindowState == FormWindowState.Maximized ? "max" : "normal"));
            }
            catch { /* não guardar não atrapalha */ }
        }
    }

    internal static class Nativo
    {
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern bool SetForegroundWindow(IntPtr janela);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern bool ShowWindow(IntPtr janela, int modo);
    }
}
