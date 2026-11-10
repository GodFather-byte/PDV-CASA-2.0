"""Vários caixas na mesma loja: o caixa principal guarda o banco e atende os outros pela rede local.

O banco SQLite continua num arquivo só, no computador do caixa principal. Cada caixa adicional abre, no lugar do
arquivo, uma ligação com o principal (`pdv://endereço:porta`) e manda por ela os mesmos comandos SQL que mandaria ao
arquivo. No principal, cada ligação tem a sua própria conexão SQLite, numa thread própria: transação, trava de escrita e
SAVEPOINT valem como se o caixa adicional estivesse no mesmo computador. Assim o estoque, o fiado, os preços e a
numeração dos cupons são um só, e as regras de negócio não mudam.

O que é de cada caixa: o número do terminal (turno, gaveta e impressora próprios; ver `BancoRemoto.cfg`).

Segurança: só entra quem tem o código de ligação gerado no principal. As duas pontas derivam dele as chaves da conversa,
que vai cifrada e autenticada (ChaCha20-Poly1305); um código errado não passa da apresentação. Nunca copie o arquivo do
banco para uma pasta compartilhada: o SQLite corrompe o arquivo quando aberto por dois computadores.

Limite assumido: se o principal desligar ou a rede cair, o caixa adicional para de vender até a ligação voltar. A
operação que estava no meio é desfeita no principal; nada fica gravado pela metade.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
import socket
import sqlite3
import struct
import threading
import time
from pathlib import Path
from uuid import uuid4

from src.core.erros import ErroNegocio
from src.database import esquema
from src.database.conexao import RAIZ, BancoDados

log = logging.getLogger("pdv.rede")

PREFIXO = "pdv://"
PORTA_PADRAO = 47811
PROTOCOLO = 1
ARQUIVO_LIGACAO = "caixa_adicional.json"
PREFIXO_CODIGO = "WILLCAIXA1-"
_MAGICA = b"WPDVREDE"
_MAX_QUADRO = 256 * 1024 * 1024
MAX_LIGACOES = 48
TEMPO_LIGAR = 4.0            # segundos para achar o principal
TEMPO_RESPOSTA = 25.0        # maior que a espera de 15 s do SQLite por uma trava de escrita
TEMPO_TRANSACAO = 60.0       # caixa adicional calado no meio de uma transação: o principal desfaz e solta a trava

_ERROS_SQLITE = {c.__name__: c for c in (
    sqlite3.Error, sqlite3.DatabaseError, sqlite3.IntegrityError, sqlite3.OperationalError, sqlite3.ProgrammingError,
    sqlite3.InterfaceError, sqlite3.DataError, sqlite3.InternalError, sqlite3.NotSupportedError)}
_DESFAZ = re.compile(r"\s*(ROLLBACK|RELEASE)\b", re.IGNORECASE)
_CONFIRMA = re.compile(r"\s*(COMMIT|END)\b", re.IGNORECASE)


class ErroLigacao(sqlite3.OperationalError):
    """Sem conversa com o caixa principal. É um erro do SQLite para as telas tratarem como falha de banco."""


# ----------------------------------------------------------------- mensagens
def _para_json(valor):
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(valor)).decode("ascii")}
    return valor


def _do_json(objeto: dict):
    if len(objeto) == 1 and "$b" in objeto:
        return base64.b64decode(objeto["$b"])
    return objeto


def _empacotar(mensagem: dict) -> bytes:
    return json.dumps(mensagem, separators=(",", ":"), default=_para_json).encode("ascii")


def _desempacotar(dados: bytes) -> dict:
    return json.loads(dados.decode("utf-8"), object_hook=_do_json)


def _parametros(params):
    if isinstance(params, dict):
        return {k: _para_json(v) for k, v in params.items()}
    return [_para_json(v) for v in (params or ())]


def _ler_exato(sock: socket.socket, n: int) -> bytes:
    partes, falta = [], n
    while falta:
        pedaco = sock.recv(min(falta, 1 << 20))
        if not pedaco:
            raise ConnectionError("a outra ponta fechou a ligação")
        partes.append(pedaco)
        falta -= len(pedaco)
    return b"".join(partes)


class _Canal:
    """Conversa cifrada sobre um socket já ligado: cada mensagem é um quadro (tamanho + texto cifrado)."""

    def __init__(self, sock: socket.socket, chave_envio: bytes, chave_chegada: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        self.sock = sock
        self._envio = ChaCha20Poly1305(chave_envio)
        self._chegada = ChaCha20Poly1305(chave_chegada)
        self._n_envio = 0
        self._n_chegada = 0

    def enviar(self, mensagem: dict) -> None:
        cifrado = self._envio.encrypt(self._n_envio.to_bytes(12, "big"), _empacotar(mensagem), None)
        self._n_envio += 1
        self.sock.sendall(struct.pack(">I", len(cifrado)) + cifrado)

    def receber(self, limite: int = _MAX_QUADRO) -> dict:
        (tamanho,) = struct.unpack(">I", _ler_exato(self.sock, 4))
        if not 16 <= tamanho <= limite:
            raise ConnectionError("quadro de tamanho inválido")
        from cryptography.exceptions import InvalidTag
        try:
            claro = self._chegada.decrypt(self._n_chegada.to_bytes(12, "big"), _ler_exato(self.sock, tamanho), None)
        except InvalidTag:
            raise ConnectionError("mensagem não confere com o código de ligação") from None
        self._n_chegada += 1
        return _desempacotar(claro)

    def fechar(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _chaves(segredo: bytes, sal: bytes) -> tuple[bytes, bytes]:
    """(chave do adicional para o principal, chave do principal para o adicional)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    material = HKDF(algorithm=hashes.SHA256(), length=64, salt=sal, info=b"willpdv-rede-caixas-v1").derive(segredo)
    return material[:32], material[32:]


# ------------------------------------------------------------- código de ligação
def nova_chave() -> str:
    return secrets.token_hex(32)


def enderecos_locais() -> list[str]:
    """Endereço deste computador na rede da loja e o nome dele (o nome ainda vale se o roteador trocar o IP)."""
    achados: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))          # não envia nada: só descobre a placa de saída
            achados.append(s.getsockname()[0])
    except OSError:
        pass
    nome = socket.gethostname()
    if not achados:
        try:
            achados.append(socket.gethostbyname(nome))
        except OSError:
            pass
    if nome and nome not in achados:
        achados.append(nome)
    return [h for h in achados if h and not h.startswith("127.")] or ["127.0.0.1"]


def gerar_codigo(hosts: list[str], porta: int, chave: str) -> str:
    corpo = json.dumps({"h": list(hosts), "p": int(porta), "k": chave}, separators=(",", ":")).encode("utf-8")
    return PREFIXO_CODIGO + base64.urlsafe_b64encode(corpo).decode("ascii").rstrip("=")


def ler_codigo(texto: str) -> dict:
    """{'hosts': [...], 'porta': n, 'chave': hex}. Código torto vira ErroNegocio com texto para o operador."""
    limpo = "".join((texto or "").split())
    if not limpo.upper().startswith(PREFIXO_CODIGO):
        raise ErroNegocio("Este não é um código de ligação de caixa. Copie o código em Caixas da loja, no caixa principal.")
    corpo = limpo[len(PREFIXO_CODIGO):]
    try:
        dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)).decode("utf-8"))
        hosts = [str(h).strip() for h in dados["h"] if str(h).strip()]
        porta = int(dados["p"])
        chave = str(dados["k"])
        bytes.fromhex(chave)
    except (ValueError, KeyError, TypeError):
        raise ErroNegocio("O código de ligação está incompleto. Copie de novo no caixa principal.") from None
    if not hosts or not 1 <= porta <= 65535 or len(chave) != 64:
        raise ErroNegocio("O código de ligação está incompleto. Copie de novo no caixa principal.")
    return {"hosts": hosts, "porta": porta, "chave": chave}


# --------------------------------------------------- ligação guardada neste computador
_REGISTRO: dict[str, dict] = {}          # ligações declaradas em memória (testes e ferramentas)


def url(host: str, porta: int) -> str:
    return f"{PREFIXO}{host}:{int(porta)}"


def eh_remoto(caminho) -> bool:
    return str(caminho or "").startswith(PREFIXO)


def arquivo_ligacao() -> Path:
    return Path(RAIZ) / ARQUIVO_LIGACAO


def ligacao_salva() -> dict | None:
    """A ligação deste computador com um caixa principal, ou None quando ele usa o banco próprio."""
    try:
        dados = json.loads(arquivo_ligacao().read_text(encoding="utf-8"))
        hosts = [str(h) for h in dados["hosts"] if str(h).strip()]
        ligacao = {"hosts": hosts, "porta": int(dados["porta"]), "chave": str(dados["chave"]),
                   "terminal": int(dados["terminal"]), "instalacao": str(dados["instalacao"])}
        bytes.fromhex(ligacao["chave"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not hosts or ligacao["terminal"] < 2:
        return None
    return ligacao


def salvar_ligacao(codigo: str, terminal: int, instalacao: str | None = None) -> dict:
    """Faz deste computador um caixa adicional. Vale a partir da próxima abertura do programa."""
    dados = ler_codigo(codigo)
    if type(terminal) is not int or not 2 <= terminal <= 99:
        raise ErroNegocio("O número deste caixa vai de 2 a 99 (o 1 é o caixa principal).")
    anterior = ligacao_salva()
    ligacao = {**dados, "terminal": terminal,
               "instalacao": instalacao or (anterior["instalacao"] if anterior else uuid4().hex)}
    arquivo = arquivo_ligacao()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    provisorio = arquivo.with_suffix(".tmp")
    provisorio.write_text(json.dumps(ligacao, ensure_ascii=False), encoding="utf-8")
    os.replace(provisorio, arquivo)
    return ligacao


def remover_ligacao() -> bool:
    """Volta a usar o banco deste computador. Devolve False se não havia ligação."""
    try:
        arquivo_ligacao().unlink()
        return True
    except FileNotFoundError:
        return False


def caminho_da_ligacao(ligacao: dict) -> str:
    return url(ligacao["hosts"][0], ligacao["porta"])


def registrar_ligacao(caminho: str, chave: str, terminal: int, instalacao: str | None = None,
                      hosts: list[str] | None = None) -> None:
    """Declara uma ligação sem arquivo (testes): `BancoDados(caminho)` passa a abrir o banco do principal."""
    _REGISTRO[caminho] = {"hosts": hosts or [_partes(caminho)[0]], "porta": _partes(caminho)[1], "chave": chave,
                          "terminal": terminal, "instalacao": instalacao or uuid4().hex}


def esquecer_ligacao(caminho: str) -> None:
    _REGISTRO.pop(caminho, None)


def _partes(caminho: str) -> tuple[str, int]:
    resto = str(caminho)[len(PREFIXO):].strip("/")
    host, _, porta = resto.rpartition(":")
    if not host or not porta.isdigit():
        raise ErroLigacao(f"Endereço de caixa principal inválido: {caminho}")
    return host, int(porta)


def _ligacao_de(caminho: str) -> dict:
    if caminho in _REGISTRO:
        return _REGISTRO[caminho]
    salva = ligacao_salva()
    if salva and caminho_da_ligacao(salva) == caminho:
        return salva
    raise ErroLigacao("Este computador não tem o código de ligação com o caixa principal.")


# -------------------------------------------------------------- caixa adicional
class Linha:
    """Linha de resultado com o mesmo uso de `sqlite3.Row`: por posição, por nome, `keys()` e `dict(linha)`."""
    __slots__ = ("_colunas", "_indice", "_valores")

    def __init__(self, colunas: tuple, indice: dict, valores: list):
        self._colunas = colunas
        self._indice = indice
        self._valores = tuple(valores)

    def __getitem__(self, chave):
        if isinstance(chave, str):
            posicao = self._indice.get(chave)
            if posicao is None:
                posicao = self._indice.get(chave.lower())
            if posicao is None:
                raise IndexError(f"No item with that key: {chave}")
            return self._valores[posicao]
        return self._valores[chave]

    def keys(self) -> list:
        return list(self._colunas)

    def __iter__(self):
        return iter(self._valores)

    def __len__(self) -> int:
        return len(self._valores)

    def __eq__(self, outra) -> bool:
        if isinstance(outra, Linha):
            return self._colunas == outra._colunas and self._valores == outra._valores
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._colunas, self._valores))

    def __repr__(self) -> str:
        return f"Linha({dict(zip(self._colunas, self._valores))!r})"


class _Cursor:
    def __init__(self, resposta: dict | None = None):
        resposta = resposta or {}
        colunas = tuple(resposta.get("c") or ())
        indice: dict = {}
        for posicao, nome in enumerate(colunas):
            indice.setdefault(nome, posicao)
            indice.setdefault(nome.lower(), posicao)
        self._linhas = [Linha(colunas, indice, v) for v in resposta.get("l") or ()]
        self._proxima = 0
        self.lastrowid = resposta.get("i")
        self.rowcount = resposta.get("n", -1)
        self.description = tuple((c, None, None, None, None, None, None) for c in colunas) or None

    def fetchone(self):
        if self._proxima >= len(self._linhas):
            return None
        self._proxima += 1
        return self._linhas[self._proxima - 1]

    def fetchall(self) -> list:
        resto = self._linhas[self._proxima:]
        self._proxima = len(self._linhas)
        return resto

    def fetchmany(self, size: int = 1) -> list:
        resto = self._linhas[self._proxima:self._proxima + size]
        self._proxima += len(resto)
        return resto

    def __iter__(self):
        return self

    def __next__(self):
        linha = self.fetchone()
        if linha is None:
            raise StopIteration
        return linha

    def close(self) -> None:
        self._linhas = []


class ConexaoRemota:
    """Faz o papel de `sqlite3.Connection` para o `BancoDados`: `execute`, `in_transaction` e `close`.

    Religa sozinha antes de um comando, nunca no meio de uma transação: se a ligação cai com uma transação aberta, o
    principal já a desfez, e daqui em diante todo comando falha até o `ROLLBACK` que encerra a transação deste lado.
    Sem isso, o resto da operação seria gravado fora da transação, pela metade."""

    def __init__(self, hosts: list[str], porta: int, chave: str, terminal: int, instalacao: str,
                 tempo_resposta: float = TEMPO_RESPOSTA):
        self.hosts = list(hosts)
        self.porta = int(porta)
        self._segredo = bytes.fromhex(chave)
        self.terminal = terminal
        self.instalacao = instalacao
        self.tempo_resposta = tempo_resposta
        self._canal: _Canal | None = None
        self._trava = threading.RLock()
        self._operador = None
        self._fechada = False
        self.in_transaction = False
        self._transacao_perdida = False
        self.principal: dict = {}

    # ------------------------------------------------------------ ligação
    def ligar(self) -> None:
        with self._trava:
            if self._canal is None:
                self._ligar()

    def _ligar(self) -> None:
        if self._fechada:
            raise ErroLigacao("A ligação com o caixa principal foi encerrada.")
        ultimo = None
        for host in self.hosts:
            sock = None
            try:
                sock = socket.create_connection((host, self.porta), timeout=TEMPO_LIGAR)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.settimeout(self.tempo_resposta)
                vez = secrets.token_bytes(16)
                sock.sendall(_MAGICA + bytes([PROTOCOLO]) + vez)
                vez_principal = _ler_exato(sock, 16)
                ida, volta = _chaves(self._segredo, vez + vez_principal)
                canal = _Canal(sock, ida, volta)
                from src.core import edicao
                from src.versao import VERSAO
                canal.enviar({"o": "ola", "esquema": esquema.VERSAO_ESQUEMA, "versao": VERSAO,
                              "edicao": edicao.atual().chave, "terminal": self.terminal,
                              "instalacao": self.instalacao, "nome": socket.gethostname(),
                              "operador": self._operador})
                resposta = canal.receber()
            except (OSError, ConnectionError) as erro:
                if sock is not None:
                    sock.close()
                ultimo = erro
                continue
            if "e" in resposta:
                canal.fechar()
                raise ErroLigacao(resposta["e"][1])
            self._canal = canal
            self.principal = resposta
            return
        if isinstance(ultimo, ConnectionError) and not isinstance(ultimo, ConnectionRefusedError):
            raise ErroLigacao("O caixa principal recusou a ligação. Confira se o código de ligação é o atual "
                              "(Caixas da loja, no caixa principal).")
        raise ErroLigacao("Sem ligação com o caixa principal. Confira se ele está ligado, com o programa aberto, "
                          "e se este computador está na rede da loja.")

    def _cair(self) -> None:
        if self._canal is not None:
            self._canal.fechar()
            self._canal = None
        if self.in_transaction:
            self._transacao_perdida = True
        self.in_transaction = False

    def _chamar(self, mensagem: dict) -> dict:
        with self._trava:
            if self._canal is None:
                self._ligar()
            try:
                self._canal.enviar(mensagem)
                resposta = self._canal.receber()
            except (OSError, ConnectionError):
                self._cair()
                raise ErroLigacao("A ligação com o caixa principal caiu durante a operação. Confira no caixa "
                                  "principal se ela foi gravada antes de repetir.") from None
            self.in_transaction = bool(resposta.get("t"))
            if "e" in resposta:
                tipo, texto = resposta["e"]
                if tipo == "ErroNegocio":
                    raise ErroNegocio(texto)
                if tipo == "ValueError":
                    raise ValueError(texto)
                raise _ERROS_SQLITE.get(tipo, sqlite3.DatabaseError)(texto)
            return resposta

    # --------------------------------------------------------------- uso
    def execute(self, sql: str, params=()) -> _Cursor:
        with self._trava:
            if self._transacao_perdida:
                if _DESFAZ.match(sql):
                    if re.match(r"\s*ROLLBACK\s*;?\s*$", sql, re.IGNORECASE):
                        self._transacao_perdida = False
                    return _Cursor()
                if _CONFIRMA.match(sql):
                    self._transacao_perdida = False
                raise ErroLigacao("A ligação com o caixa principal caiu no meio da operação e ela foi desfeita. "
                                  "Repita quando a ligação voltar.")
            return _Cursor(self._chamar({"o": "sql", "s": sql, "p": _parametros(params)}))

    def definir_operador(self, operador_id) -> None:
        with self._trava:
            self._chamar({"o": "operador", "id": operador_id})
            self._operador = operador_id

    def ping(self) -> dict:
        return self._chamar({"o": "ping"})

    def backup(self, *_args, **_kwargs):
        raise ErroNegocio("A cópia do banco é feita no caixa principal.")

    def close(self) -> None:
        with self._trava:
            self._fechada = True
            if self._canal is not None:
                try:
                    self._canal.enviar({"o": "tchau"})
                except (OSError, ConnectionError):
                    pass
            self._cair()
            self._transacao_perdida = False


class BancoRemoto(BancoDados):
    """O banco do caixa principal, visto de um caixa adicional. Mesma interface do `BancoDados`; esquema, migração e
    sementes são assunto do principal."""

    remoto = True

    def __init__(self, caminho: str | None = None, semear: bool = True):
        from src.database.conexao import caminho_padrao
        self.caminho = str(caminho or caminho_padrao())
        ligacao = _ligacao_de(self.caminho)
        self.terminal = int(ligacao["terminal"])
        self._profundidade = 0
        self._operador_auditoria = None
        self._auditoria_ativa = True
        self.conexao = ConexaoRemota(ligacao["hosts"], ligacao["porta"], ligacao["chave"], self.terminal,
                                     ligacao["instalacao"])
        self.conexao.ligar()

    def cfg(self, chave: str, padrao: str = "") -> str:
        if chave == "terminal":
            return str(self.terminal)        # o número do caixa é deste computador, não da loja
        return super().cfg(chave, padrao)

    def cfg_set(self, chave: str, valor) -> None:
        if chave == "terminal":
            return
        super().cfg_set(chave, valor)

    def definir_operador_auditoria(self, operador_id: int | None) -> None:
        if operador_id is not None and (not isinstance(operador_id, int) or isinstance(operador_id, bool)):
            raise ValueError("Operador da auditoria deve ser um identificador inteiro.")
        self.conexao.definir_operador(operador_id)
        self._operador_auditoria = operador_id

    def copiar_para(self, destino: str) -> None:
        raise ErroNegocio("O backup é feito no caixa principal, onde o banco está guardado.")

    def fechar(self) -> None:
        self.conexao.close()


# --------------------------------------------------------------- caixa principal
def _nega_anexos(acao, *_resto):
    """Um caixa adicional usa o banco da loja, não outros arquivos do computador principal."""
    return sqlite3.SQLITE_DENY if acao in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK


class ServidorBanco:
    """Atende os caixas adicionais no computador do caixa principal. Uma thread e uma conexão SQLite por ligação."""

    def __init__(self, caminho: str, chave: str, porta: int = PORTA_PADRAO, host: str = "0.0.0.0"):
        if caminho == ":memory:" or eh_remoto(caminho):
            raise ErroNegocio("O caixa principal precisa do banco em arquivo neste computador.")
        self.caminho = caminho
        self._segredo = bytes.fromhex(chave)
        self._host = host
        self._porta_pedida = int(porta)
        self._escuta: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._trava = threading.Lock()
        self._ligacoes: dict[int, dict] = {}
        self._seq = 0
        self.ultimo_erro: str | None = None

    # ---------------------------------------------------------- ciclo de vida
    @property
    def porta(self) -> int:
        return self._escuta.getsockname()[1] if self._escuta else self._porta_pedida

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        escuta = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":
                escuta.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            escuta.bind((self._host, self._porta_pedida))
            escuta.listen(16)
            escuta.settimeout(0.5)
        except OSError as erro:
            escuta.close()
            raise ErroNegocio(f"Não foi possível abrir a porta {self._porta_pedida} para os outros caixas: {erro}. "
                              "Escolha outra porta ou feche o programa que a está usando.") from None
        self._escuta = escuta
        self._parar.clear()
        self._thread = threading.Thread(target=self._aceitar, name="rede-caixas", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 5.0) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout)
        if self._escuta is not None:
            self._escuta.close()
            self._escuta = None
        with self._trava:
            ligacoes = list(self._ligacoes.values())
        for ligacao in ligacoes:
            try:
                ligacao["sock"].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for ligacao in ligacoes:
            ligacao["thread"].join(timeout)

    def conectados(self) -> list[dict]:
        """Um registro por caixa adicional com ligação aberta agora."""
        with self._trava:
            vistos: dict[int, dict] = {}
            for ligacao in self._ligacoes.values():
                if ligacao.get("terminal") is None:
                    continue
                atual = vistos.setdefault(ligacao["terminal"], {
                    "terminal": ligacao["terminal"], "nome": ligacao["nome"], "endereco": ligacao["endereco"],
                    "desde": ligacao["desde"], "ligacoes": 0})
                atual["ligacoes"] += 1
                atual["desde"] = min(atual["desde"], ligacao["desde"])
            return sorted(vistos.values(), key=lambda c: c["terminal"])

    # --------------------------------------------------------------- escuta
    def _aceitar(self) -> None:
        while not self._parar.is_set():
            try:
                sock, endereco = self._escuta.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._parar.is_set():
                    return
                time.sleep(0.2)
                continue
            with self._trava:
                if len(self._ligacoes) >= MAX_LIGACOES:
                    sock.close()
                    continue
                self._seq += 1
                numero = self._seq
                thread = threading.Thread(target=self._atender, args=(numero, sock, endereco[0]),
                                          name=f"rede-caixa-{numero}", daemon=True)
                self._ligacoes[numero] = {"sock": sock, "thread": thread, "endereco": endereco[0], "terminal": None,
                                          "nome": "", "desde": time.time()}
            thread.start()

    def _apresentar(self, sock: socket.socket) -> _Canal:
        sock.settimeout(10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        cabecalho = _ler_exato(sock, len(_MAGICA) + 1 + 16)
        if cabecalho[:len(_MAGICA)] != _MAGICA:
            raise ConnectionError("não é um caixa adicional")
        vez = cabecalho[len(_MAGICA) + 1:]
        vez_principal = secrets.token_bytes(16)
        sock.sendall(vez_principal)
        ida, volta = _chaves(self._segredo, vez + vez_principal)
        canal = _Canal(sock, volta, ida)
        canal.protocolo = cabecalho[len(_MAGICA)]
        return canal

    def _conferir(self, banco: BancoDados, ola: dict, protocolo: int) -> str | None:
        """None se o caixa adicional pode entrar; senão, o motivo, em texto para o operador dele."""
        from src.core import edicao
        from src.versao import VERSAO
        if protocolo != PROTOCOLO or ola.get("o") != "ola":
            return "Este caixa e o caixa principal estão em versões diferentes do programa. Atualize os dois."
        if ola.get("versao") != VERSAO or ola.get("esquema") != esquema.VERSAO_ESQUEMA:
            return (f"O caixa principal está na versão {VERSAO} e este caixa na {ola.get('versao')}. "
                    "Deixe os dois na mesma versão antes de ligar.")
        if ola.get("edicao") != edicao.atual().chave:
            return f"O caixa principal é {edicao.atual().nome}. Instale o mesmo programa neste computador."
        terminal, instalacao = ola.get("terminal"), ola.get("instalacao")
        if type(terminal) is not int or not 2 <= terminal <= 99 or not isinstance(instalacao, str) or not instalacao:
            return "O número deste caixa vai de 2 a 99 (o 1 é o caixa principal)."
        if terminal == banco.cfg_int("terminal", 1):
            return f"O caixa {terminal} é o caixa principal. Escolha outro número para este computador."
        with banco.transacao():
            donos = terminais_registrados(banco)
            dono = donos.get(terminal)
            if dono and dono["instalacao"] != instalacao:
                return (f"O caixa {terminal} já é de outro computador ({dono.get('nome') or 'sem nome'}). Escolha outro "
                        f"número, ou libere o caixa {terminal} em Caixas da loja, no caixa principal.")
            donos[terminal] = {"instalacao": instalacao, "nome": str(ola.get("nome") or "")[:60]}
            if donos.get(terminal) != dono:
                banco.cfg_set("rede_caixas_terminais", json.dumps({str(k): v for k, v in donos.items()},
                                                                  ensure_ascii=False))
        return None

    # -------------------------------------------------------------- ligação
    def _atender(self, numero: int, sock: socket.socket, endereco: str) -> None:
        banco = None
        try:
            canal = self._apresentar(sock)
            ola = canal.receber(limite=4096)       # antes de provar que tem o código, só cabe a apresentação
            banco = BancoDados(self.caminho, semear=False)
            banco.conexao.set_authorizer(_nega_anexos)
            motivo = self._conferir(banco, ola, canal.protocolo)
            if motivo:
                canal.enviar({"e": ["ErroLigacao", motivo]})
                return
            if ola.get("operador") is not None:
                try:
                    banco.definir_operador_auditoria(ola["operador"])
                except ValueError:
                    pass
            with self._trava:
                self._ligacoes[numero].update(terminal=ola["terminal"], nome=str(ola.get("nome") or "")[:60])
            from src.versao import VERSAO
            canal.enviar({"ok": 1, "versao": VERSAO, "nome": socket.gethostname(),
                          "terminal": banco.cfg_int("terminal", 1)})
            self._conversar(canal, banco)
        except (OSError, ConnectionError):
            pass                                   # caixa adicional desligou, rede caiu ou código errado
        except Exception as erro:  # noqa: BLE001 - uma ligação com defeito não derruba as outras
            self.ultimo_erro = str(erro)
            log.exception("Falha ao atender o caixa adicional em %s.", endereco)
        finally:
            if banco is not None:
                try:
                    if banco.conexao.in_transaction:
                        banco.conexao.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                banco.fechar()
            try:
                sock.close()
            except OSError:
                pass
            with self._trava:
                self._ligacoes.pop(numero, None)

    def _conversar(self, canal: _Canal, banco: BancoDados) -> None:
        conexao = banco.conexao
        while not self._parar.is_set():
            canal.sock.settimeout(TEMPO_TRANSACAO if conexao.in_transaction else None)
            pedido = canal.receber()
            operacao = pedido.get("o")
            try:
                if operacao == "sql":
                    cursor = conexao.execute(pedido["s"], pedido.get("p") or ())
                    resposta = {"i": cursor.lastrowid, "n": cursor.rowcount}
                    if cursor.description:
                        resposta["c"] = [d[0] for d in cursor.description]
                        resposta["l"] = [list(linha) for linha in cursor.fetchall()]
                elif operacao == "operador":
                    banco.definir_operador_auditoria(pedido.get("id"))
                    resposta = {}
                elif operacao == "ping":
                    resposta = {"ok": 1}
                elif operacao == "tchau":
                    return
                else:
                    resposta = {"e": ["ProgrammingError", "pedido desconhecido"]}
            except sqlite3.Error as erro:
                resposta = {"e": [type(erro).__name__, str(erro)]}
            except ErroNegocio as erro:
                resposta = {"e": ["ErroNegocio", str(erro)]}
            except (ValueError, TypeError, KeyError) as erro:
                resposta = {"e": ["ValueError", str(erro)]}
            resposta["t"] = conexao.in_transaction
            canal.sock.settimeout(TEMPO_RESPOSTA)
            canal.enviar(resposta)


# ------------------------------------------------ configuração no caixa principal
def terminais_registrados(banco) -> dict[int, dict]:
    """{número do caixa: {'instalacao', 'nome'}} dos computadores que já se ligaram como caixa adicional."""
    try:
        bruto = json.loads(banco.cfg("rede_caixas_terminais", "") or "{}")
        return {int(k): {"instalacao": str(v["instalacao"]), "nome": str(v.get("nome") or "")}
                for k, v in bruto.items()}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {}


def liberar_terminal(banco, terminal: int) -> bool:
    """Solta o número de um caixa para outro computador usar (troca de máquina). Não apaga vendas nem turnos."""
    with banco.transacao():
        donos = terminais_registrados(banco)
        if donos.pop(terminal, None) is None:
            return False
        banco.cfg_set("rede_caixas_terminais", json.dumps({str(k): v for k, v in donos.items()}, ensure_ascii=False))
        banco.log("rede_caixa_liberado", f"caixa {terminal}")
    return True


def chave_da_loja(banco, criar: bool = True) -> str:
    chave = banco.cfg("rede_caixas_chave", "")
    try:
        if len(bytes.fromhex(chave)) == 32:
            return chave
    except ValueError:
        pass
    if not criar:
        return ""
    chave = nova_chave()
    banco.cfg_set("rede_caixas_chave", chave)
    return chave


def porta_da_loja(banco) -> int:
    porta = banco.cfg_int("rede_caixas_porta", PORTA_PADRAO)
    return porta if 1024 <= porta <= 65535 else PORTA_PADRAO


def codigo_da_loja(banco) -> str:
    return gerar_codigo(enderecos_locais(), porta_da_loja(banco), chave_da_loja(banco))


def trocar_chave(banco) -> str:
    """Código novo: os caixas adicionais já ligados precisam receber o código de novo."""
    chave = nova_chave()
    banco.cfg_set("rede_caixas_chave", chave)
    banco.log("rede_caixas_codigo_trocado")
    return chave


class ServicoRedeCaixas:
    """Liga o `ServidorBanco` quando a loja marcou "Atender outros caixas". Mesmo contrato dos outros serviços do
    programa (`iniciar`/`parar`), com conexão própria só para ler a configuração."""

    def __init__(self, caminho_banco: str):
        self.caminho = caminho_banco
        self.servidor: ServidorBanco | None = None
        self.ultimo_erro: str | None = None         # porta ocupada, por exemplo: a tela Caixas da loja mostra

    @property
    def ativo(self) -> bool:
        return bool(self.servidor and self.servidor.ativo)

    def iniciar(self) -> None:
        if self.ativo or eh_remoto(self.caminho) or self.caminho == ":memory:":
            return
        banco = BancoDados(self.caminho, semear=False)
        try:
            if not banco.cfg_bool("rede_caixas", False):
                return
            chave, porta = chave_da_loja(banco), porta_da_loja(banco)
        finally:
            banco.fechar()
        servidor = ServidorBanco(self.caminho, chave, porta)
        servidor.iniciar()
        self.servidor = servidor

    def parar(self) -> None:
        servidor, self.servidor = self.servidor, None
        if servidor is not None:
            servidor.parar()

    def reiniciar(self) -> None:
        self.parar()
        self.iniciar()

    def conectados(self) -> list[dict]:
        return self.servidor.conectados() if self.ativo else []
