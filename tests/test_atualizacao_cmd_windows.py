"""Executa o .cmd real no Windows com processos controlados; não instala o PDV da máquina."""
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from src.atualizacao.cliente import script_aplicar

@unittest.skipUnless(os.name == 'nt', 'Execução real de cmd.exe exige Windows')
class TesteScriptWindows(unittest.TestCase):
    nome = 'WillPDVRetomadaTeste.exe'

    @classmethod
    def setUpClass(cls):
        cls.pasta_compilada = tempfile.TemporaryDirectory()
        pasta = Path(cls.pasta_compilada.name)
        compiladores = list((Path(os.environ['WINDIR']) / 'Microsoft.NET').glob('Framework*/v4.*/csc.exe'))
        if not compiladores:
            raise RuntimeError('Compilador do .NET Framework ausente: não pular a validação do atualizador.')
        fonte = pasta / 'simulador.cs'
        fonte.write_text(r'''
using System;
using System.IO;
using System.Diagnostics;
using System.Threading;
class Simulador {
 static int Main(string[] args) {
  string nome = Path.GetFileNameWithoutExtension(Process.GetCurrentProcess().MainModule.FileName);
  if (nome == "instalador") {
   string comando = Environment.GetEnvironmentVariable("PDV_TESTE_ENCERRAR");
   if (!String.IsNullOrEmpty(comando)) {
    Process p = Process.Start(new ProcessStartInfo("taskkill.exe", comando) { CreateNoWindow=true, UseShellExecute=false });
    p.WaitForExit();
   }
   return Int32.Parse(Environment.GetEnvironmentVariable("PDV_TESTE_CODIGO") ?? "0");
  }
  if (args.Length > 0 && args[0] == "pai") {
   Process.Start(new ProcessStartInfo("cmd.exe", "/d /c \"\"" + args[1] + "\"\"") { CreateNoWindow=true, UseShellExecute=false });
   Thread.Sleep(60000);
   return 0;
  }
  if (args.Length > 0 && args[0] == "--confirmar-atualizacao") {
   if (Environment.GetEnvironmentVariable("PDV_TESTE_LEGADO") != "1")
    File.WriteAllText(args[2], args[1] + "\n");
   return 0;
  }
  return 0;
 }
}
''', encoding='utf-8')
        cls.simulador = pasta / 'simulador.exe'
        subprocess.run([str(compiladores[0]), '/nologo', '/target:exe', '/out:' + str(cls.simulador), str(fonte)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.pasta_compilada.cleanup()

    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory(prefix='pdv retomada ')
        self.raiz = Path(self.pasta.name)
        self.programa = self.raiz / 'programa'
        self.backup = self.raiz / 'anterior'
        self.programa.mkdir(); self.backup.mkdir()
        (self.backup / 'restaurado.txt').write_text('cópia preservada', encoding='utf-8')
        shutil.copyfile(self.simulador, self.programa / self.nome)
        self.instalador = self.raiz / 'instalador.exe'
        shutil.copyfile(self.simulador, self.instalador)
        self.script = self.raiz / 'aplicar.cmd'
        self.script.write_text(script_aplicar(self.instalador, self.programa, self.backup, self.nome, '1.14.2'), encoding='utf-8')
        self.ambiente = dict(os.environ, PDV_TESTE_CODIGO='0', PDV_TESTE_LEGADO='0', PDV_TESTE_ENCERRAR='')

    def tearDown(self):
        subprocess.run(['taskkill', '/F', '/IM', self.nome], capture_output=True)
        self.pasta.cleanup()

    def executar(self):
        return subprocess.run(['cmd.exe', '/d', '/c', str(self.script)], env=self.ambiente, capture_output=True, timeout=20)

    def test_instalacao_confirmada_reinicia(self):
        resultado = self.executar()
        self.assertEqual(resultado.returncode, 0, resultado.stdout)
        self.assertEqual((self.raiz / 'resultado.txt').read_text().strip(), 'instalada')

    def test_instalador_falha_restaura(self):
        self.ambiente['PDV_TESTE_CODIGO'] = '1'
        resultado = self.executar()
        self.assertEqual(resultado.returncode, 1)
        self.assertEqual((self.raiz / 'resultado.txt').read_text().strip(), 'restaurada')
        self.assertTrue((self.programa / 'restaurado.txt').exists())
        self.assertFalse((self.raiz / 'confirmacao.txt').exists())

    def test_executavel_antigo_retornando_zero_nao_confirma(self):
        self.ambiente['PDV_TESTE_LEGADO'] = '1'
        resultado = self.executar()
        self.assertEqual(resultado.returncode, 1)
        self.assertEqual((self.raiz / 'resultado.txt').read_text().strip(), 'restaurada')

    def test_instalador_encerra_pai_sem_matar_os_descendentes(self):
        texto = (Path(__file__).resolve().parents[1] / 'instalador' / 'WillPDV.iss').read_text(encoding='utf-8-sig')
        comando = re.search(r"taskkill\.exe'\), '([^']+)'", texto).group(1)
        self.ambiente['PDV_TESTE_ENCERRAR'] = comando.replace('{#Exe}', self.nome)
        pai = subprocess.Popen([str(self.programa / self.nome), 'pai', str(self.script)], env=self.ambiente)
        try:
            limite = time.monotonic() + 20
            while time.monotonic() < limite and not (self.raiz / 'resultado.txt').exists():
                time.sleep(.1)
            self.assertTrue((self.raiz / 'resultado.txt').exists(), 'O encerramento do pai matou também o instalador/cmd.')
            self.assertEqual((self.raiz / 'resultado.txt').read_text().strip(), 'instalada')
            pai.wait(timeout=5)
        finally:
            if pai.poll() is None:
                pai.kill(); pai.wait()
