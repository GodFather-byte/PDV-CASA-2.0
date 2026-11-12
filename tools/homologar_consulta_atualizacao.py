"""Confere no Windows instalado a consulta automática, com banco e nuvem fictícios isolados."""
import argparse
import json
import os
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, urlsplit
from src.database.conexao import BancoDados
from src.versao import VERSAO


def executar(programa):
    consulta = Event()
    consultas = []
    class NuvemFicticia(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == '/v1/atualizacao/ultima':
                consultas.append(parse_qs(url.query))
                corpo = {'disponivel': False, 'pacote': None}
                codigo = 200
                consulta.set()
            else:
                corpo, codigo = {'detail': 'Ambiente fictício'}, 401
            dados = json.dumps(corpo).encode('utf-8')
            self.send_response(codigo)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
        def do_POST(self):
            self.send_response(401)
            self.send_header('Content-Length', '0')
            self.end_headers()
    servidor = ThreadingHTTPServer(('127.0.0.1', 0), NuvemFicticia)
    thread = Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    processo = None
    try:
        with tempfile.TemporaryDirectory(prefix='consulta automática ') as pasta:
            raiz = Path(pasta)
            caminho = raiz / 'loja-ficticia.db'
            perfil = raiz / 'perfil'
            perfil.mkdir()
            banco = BancoDados(str(caminho))
            banco.cfg_set('api_url', f'http://127.0.0.1:{servidor.server_port}')
            banco.cfg_set('api_token', 'token-ficticio')
            banco.cfg_set('sync_quase_tempo_real', 'N')
            banco.fechar()
            ambiente = dict(os.environ, PDV_DB=str(caminho), LOCALAPPDATA=str(perfil), QT_QPA_PLATFORM='offscreen')
            processo = subprocess.Popen([str(Path(programa).resolve())], env=ambiente)
            try:
                if not consulta.wait(60):
                    raise RuntimeError(f'O programa instalado não consultou a atualização automaticamente. Saída={processo.poll()}')
                if consultas[0].get('versao') != [VERSAO]:
                    raise RuntimeError('A consulta veio de outra versão do programa.')
                if processo.poll() is not None:
                    raise RuntimeError('O programa fechou após consultar uma nuvem sem atualização.')
                print(f'OK: programa instalado {VERSAO} consultou automaticamente com sync_quase_tempo_real=N, sem fechar.')
            finally:
                if processo.poll() is None:
                    processo.terminate()
                processo.wait(timeout=15)
    finally:
        if processo is not None and processo.poll() is None:
            processo.kill()
            processo.wait()
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--programa', required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Este teste exige o executável Windows instalado.')
    executar(args.programa)
