"""Impressora térmica não fiscal (ESC/POS) e abertura de gaveta pelo conector RJ-11 da impressora.

Gera os bytes ESC/POS (compatível com Epson TM, Bematech MP, Elgin i9, Tanca e a maioria das
térmicas de 58mm/80mm) e envia por um de quatro transportes:

  * rede     — socket TCP (padrão porta 9100). Só biblioteca padrão; funciona sem instalar nada.
  * serial   — porta COM (requer `pyserial`; instale com `pip install pyserial`). O endereço é a porta,
               com a velocidade opcional depois de dois-pontos: `COM3` (9600 bps) ou `COM3:19200`.
  * spooler  — impressora instalada no Windows, pelo nome que o Windows mostra, em modo RAW. Usa o spooler do
               próprio Windows (ctypes): não precisa instalar nada. `impressoras_so` lista as instaladas.
  * arquivo  — grava os bytes num arquivo ou caminho de dispositivo (ex.: \\\\.\\COM3 ou um
               compartilhamento \\\\PC\\IMPRESSORA). Serve para testes e casos avançados.

Não há emissão fiscal: isto é uma impressora comum de cupom. Acentos saem corretos selecionando
a página de código da impressora (padrão CP850, que cobre o português) e codificando o texto nela.
"""
from __future__ import annotations

import ctypes
import socket
import sys
from ctypes import wintypes
from dataclasses import dataclass

from src.core.erros import ErroNegocio
from src.hardware import impressoras_so

# -------------------------------------------------------------- comandos ESC/POS
ESC = b"\x1b"
GS = b"\x1d"
INICIALIZAR = ESC + b"@"               # ESC @  — reinicia a impressora
NEGRITO_ON = ESC + b"E\x01"
NEGRITO_OFF = ESC + b"E\x00"
ALINHAR_ESQ = ESC + b"a\x00"
ALINHAR_CENTRO = ESC + b"a\x01"
ALINHAR_DIR = ESC + b"a\x02"
TAMANHO_NORMAL = GS + b"!\x00"          # GS ! 0
TAMANHO_ALTO = GS + b"!\x01"            # dobro da altura (mantém a largura/colunas)
TAMANHO_GRANDE = GS + b"!\x11"          # dobro de largura e altura

# Página de código: nome do codec Python -> número da tabela ESC/POS (ESC t n).
CODEPAGES = {"cp850": 2, "cp860": 3, "cp1252": 16, "cp437": 0, "ascii": 0, "utf-8": None}


def _selecionar_codepage(codepage: str) -> bytes:
    n = CODEPAGES.get(codepage.lower())
    return b"" if n is None else ESC + b"t" + bytes([n])


def _codificar(texto: str, codepage: str) -> bytes:
    codec = "cp850" if codepage.lower() not in CODEPAGES else codepage.lower()
    if codec == "utf-8":
        codec = "cp850"  # a maioria das térmicas não entende UTF-8; CP850 cobre o português
    return texto.encode(codec, errors="replace")


def pulso_gaveta(pino: int = 0) -> bytes:
    """Pulso que abre a gaveta de dinheiro ligada à impressora (ESC p m t1 t2).
    `pino` 0 = conector 2 (mais comum), 1 = conector 5."""
    m = 1 if int(pino) == 1 else 0
    return ESC + b"p" + bytes([m, 0x19, 0xFA])   # liga 50ms, desliga 500ms


def cortar_papel(parcial: bool = True, avanco: int = 4) -> bytes:
    """Avança `avanco` linhas e corta o papel (parcial deixa um ponto preso; total corta inteiro)."""
    return ESC + b"d" + bytes([max(0, min(avanco, 255))]) + GS + b"V" + (b"\x01" if parcial else b"\x00")


# --------------------------------------------------------------- montagem do ticket
def _estilo_prefixo(linha: str, prefixos) -> bool:
    cru = linha.lstrip()
    return any(cru.startswith(p) for p in prefixos)


def texto_para_escpos(texto: str, *, codepage: str = "cp850", cortar: bool = True,
                      abrir_gaveta: bool = False, pino_gaveta: int = 0,
                      negrito_linhas: int = 0, negrito_prefixos=(), grande_prefixos=(),
                      logotipo: bytes | None = None) -> bytes:
    """Converte um texto já formatado (colunas fixas) em bytes ESC/POS.

    A ênfase é por linha, sem mexer no layout em colunas: `negrito_linhas` deixa as N primeiras
    linhas não vazias em negrito e centralizadas (cabeçalho da loja); `grande_prefixos` imprime em
    dobro de altura as linhas que começam com um dos prefixos (ex.: 'TOTAL'); `negrito_prefixos`
    apenas negrita. Como só a altura dobra, as colunas continuam alinhadas.
    """
    out = bytearray()
    out += INICIALIZAR
    out += _selecionar_codepage(codepage)
    if logotipo:
        out += logotipo            # já vem centralizado e termina com o alinhamento à esquerda
    destacadas = 0
    for linha in texto.split("\n"):
        tem_texto = bool(linha.strip())
        grande = tem_texto and _estilo_prefixo(linha, grande_prefixos)
        negrito = tem_texto and (_estilo_prefixo(linha, negrito_prefixos)
                                 or (destacadas < negrito_linhas))
        if tem_texto and destacadas < negrito_linhas:
            destacadas += 1
        if grande:
            out += ALINHAR_CENTRO + NEGRITO_ON + TAMANHO_ALTO
        elif negrito:
            out += ALINHAR_CENTRO + NEGRITO_ON
        out += _codificar(linha, codepage) + b"\n"
        if grande or negrito:
            out += TAMANHO_NORMAL + NEGRITO_OFF + ALINHAR_ESQ
    if abrir_gaveta:
        out += pulso_gaveta(pino_gaveta)
    if cortar:
        out += cortar_papel()
    else:
        out += ESC + b"d\x02"
    return bytes(out)


# ----------------------------------------------------------------- transportes
class ErroImpressao(ErroNegocio):
    """Falha ao enviar para a impressora (offline, sem driver, endereço errado).

    É um ErroNegocio para a interface mostrar a mensagem direto ao operador."""


def _parse_host_porta(endereco: str, porta_padrao: int = 9100) -> tuple[str, int]:
    endereco = (endereco or "").strip()
    if not endereco:
        raise ErroImpressao("Endereço da impressora de rede vazio (ex.: 192.168.0.50:9100).")
    if ":" in endereco:
        host, _, p = endereco.rpartition(":")
        try:
            return host, int(p)
        except ValueError:
            raise ErroImpressao(f"Porta inválida em '{endereco}'.") from None
    return endereco, porta_padrao


def enviar_rede(endereco: str, dados: bytes, timeout: float = 6.0) -> None:
    host, porta = _parse_host_porta(endereco)
    try:
        with socket.create_connection((host, porta), timeout=timeout) as s:
            s.sendall(dados)
    except OSError as e:
        raise ErroImpressao(f"Não foi possível falar com a impressora em {host}:{porta} ({e}).") from e


def _parse_serial(endereco: str, baud_padrao: int = 9600) -> tuple[str, int]:
    """'COM3' -> ('COM3', 9600); 'COM3:115200' -> ('COM3', 115200). O 'COM3:' do Windows antigo também vale."""
    endereco = (endereco or "").strip()
    porta, dois_pontos, velocidade = endereco.rpartition(":")
    if not dois_pontos:
        return endereco, baud_padrao
    velocidade = velocidade.strip()
    if not velocidade:
        return porta.strip(), baud_padrao
    if velocidade.isdigit() and int(velocidade) > 0:
        return porta.strip(), int(velocidade)
    raise ErroImpressao(f"Velocidade inválida em '{endereco}' (use, por exemplo, COM3:19200).")


def enviar_serial(porta: str, dados: bytes, baud: int = 9600, timeout: float = 5.0) -> None:
    """`porta` é o nome da porta, com a velocidade opcional depois de dois-pontos (COM3 ou COM3:19200)."""
    try:
        import serial  # type: ignore
    except ImportError:
        raise ErroImpressao("Impressora serial precisa da biblioteca 'pyserial' (pip install pyserial).") from None
    porta, baud = _parse_serial(porta, baud)
    if not porta:
        raise ErroImpressao("Informe a porta serial da impressora (ex.: COM1 ou COM1:19200).")
    try:
        com = serial.Serial(porta, baudrate=baud, timeout=timeout, write_timeout=timeout)
    except Exception as e:  # serial.SerialException e afins
        raise ErroImpressao(f"Não foi possível abrir a porta serial {porta} ({e}).") from e
    try:
        com.write(dados)
        com.flush()
    finally:
        com.close()


class _DocInfo1(ctypes.Structure):
    _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]


# O que fazer, em palavras de quem toca a casa, para os erros do spooler que mais aparecem com impressora de cupom (USB).
DICAS_WINDOWS = {
    5: "O Windows negou o acesso: feche outros programas que usam a impressora ou rode o WillPDV como administrador.",
    1722: "O serviço 'Spooler de Impressão' do Windows está parado: abra Serviços (services.msc), inicie 'Spooler de Impressão' e tente de novo.",
    1801: "O nome da impressora no PDV não é o que o Windows mostra: use 'Assistente de impressora' para escolher da lista.",
    1796: "A porta da impressora não existe mais: reinstale o driver da impressora (cabo USB conectado e impressora ligada).",
    1804: "O driver dessa impressora não aceita impressão direta (RAW). Instale o driver do fabricante (Elgin i9) ou use o driver 'Generic / Text Only'.",
    1805: "O Windows não consegue falar com a impressora: confira o cabo USB e se ela está ligada.",
    1906: "A impressora está desconectada: confira o cabo USB e se ela está ligada.",
    6: "A impressora foi desconectada durante o envio: confira o cabo USB.",
    21: "A impressora não está pronta: ligue-a, feche a tampa e confira o cabo USB.",
    1789: "O Windows perdeu a conexão com a impressora: reinicie o computador e a impressora.",
}


def _erro_windows() -> str:
    # get_last_error e FormatError só existem no Windows; fora dele (testes que simulam o spooler) não há código.
    codigo = getattr(ctypes, "get_last_error", lambda: 0)()
    if not codigo:
        return "erro desconhecido"
    dica = DICAS_WINDOWS.get(codigo)
    return f"{ctypes.FormatError(codigo).strip()} [erro {codigo}]" + (f". {dica}" if dica else "")


def enviar_spooler(nome: str, dados: bytes, documento: str = "PDV Cupom") -> None:
    """Envia os bytes, em modo RAW, a uma impressora instalada no Windows (o nome que o Windows mostra).

    Usa o spooler do próprio Windows pela biblioteca padrão (ctypes): não precisa de pywin32. Se a impressora
    estiver desligada, o Windows guarda o trabalho e imprime quando ela voltar. Sem `nome`, usa a padrão do Windows."""
    if sys.platform != "win32":
        raise ErroImpressao("A impressão pelo spooler só existe no Windows.")
    nome = (nome or "").strip() or (impressoras_so.impressora_padrao() or "")
    if not nome:
        raise ErroImpressao("Nenhuma impressora do Windows definida (Configurações > Máquinas).")
    try:
        spool = impressoras_so.winspool()
    except OSError as e:
        raise ErroImpressao(f"Não foi possível usar o spooler do Windows ({e}).") from e
    handle = ctypes.c_void_p()
    if not spool.OpenPrinterW(nome, ctypes.byref(handle), None):
        raise ErroImpressao(f"Impressora '{nome}' não encontrada no Windows ({_erro_windows()}).")
    try:
        doc = _DocInfo1(documento, None, "RAW")
        if not spool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
            raise ErroImpressao(f"O Windows não aceitou o documento para '{nome}' ({_erro_windows()}).")
        try:
            if not spool.StartPagePrinter(handle):
                raise ErroImpressao(f"O Windows não abriu a página em '{nome}' ({_erro_windows()}).")
            try:
                escrito = wintypes.DWORD(0)
                if not spool.WritePrinter(handle, bytes(dados), len(dados), ctypes.byref(escrito)) or escrito.value != len(dados):
                    raise ErroImpressao(f"Falha ao enviar os dados para '{nome}' ({_erro_windows()}).")
            finally:
                spool.EndPagePrinter(handle)
        finally:
            spool.EndDocPrinter(handle)
    finally:
        spool.ClosePrinter(handle)


def enviar_arquivo(caminho: str, dados: bytes) -> None:
    if not (caminho or "").strip():
        raise ErroImpressao("Informe o arquivo ou dispositivo de saída (ex.: \\\\.\\COM3).")
    try:
        with open(caminho, "ab") as f:
            f.write(dados)
    except OSError as e:
        raise ErroImpressao(f"Não foi possível escrever em '{caminho}' ({e}).") from e


# ------------------------------------------------------------ fachada configurável
@dataclass
class ImpressoraTermica:
    conexao: str = "rede"          # rede | serial | spooler | arquivo | nenhuma
    endereco: str = ""
    codepage: str = "cp850"
    colunas: int = 48
    cortar: bool = True
    tem_gaveta: bool = False
    pino_gaveta: int = 0

    @classmethod
    def da_maquina(cls, m: dict) -> "ImpressoraTermica":
        return cls(
            conexao=m.get("impressora_termica_conexao") or "rede",
            endereco=m.get("impressora_termica_endereco") or "",
            codepage=m.get("impressora_termica_codepage") or "cp850",
            colunas=int(m.get("colunas_fita") or 48),
            cortar=bool(m.get("impressora_termica_cortar", 1)),
            tem_gaveta=bool(m.get("impressora_termica_gaveta", 0)),
            pino_gaveta=int(m.get("impressora_termica_pino") or 0),
        )

    @property
    def configurada(self) -> bool:
        return self.conexao not in ("", "nenhuma")

    def enviar_bytes(self, dados: bytes) -> None:
        if not self.configurada:
            raise ErroImpressao("Nenhuma impressora térmica configurada (Configurações > Máquinas).")
        despacho = {"rede": lambda: enviar_rede(self.endereco, dados),
                    "serial": lambda: enviar_serial(self.endereco, dados),
                    "spooler": lambda: enviar_spooler(self.endereco, dados),
                    "arquivo": lambda: enviar_arquivo(self.endereco, dados)}
        fn = despacho.get(self.conexao)
        if fn is None:
            raise ErroImpressao(f"Conexão de impressora desconhecida: {self.conexao}.")
        fn()

    def montar(self, texto: str, *, cortar: bool | None = None, abrir_gaveta: bool = False, copias: int = 1,
               logotipo: bytes | None = None, **estilo) -> bytes:
        """Gera os bytes ESC/POS sem enviar (é o que vai para a fila de impressão).

        `copias` repete o cupom inteiro, com corte entre as vias; a gaveta só abre na primeira."""
        corte = self.cortar if cortar is None else cortar
        base = dict(codepage=self.codepage, cortar=corte, pino_gaveta=self.pino_gaveta, logotipo=logotipo, **estilo)
        primeira = texto_para_escpos(texto, abrir_gaveta=abrir_gaveta and self.tem_gaveta, **base)
        copias = max(1, min(int(copias or 1), 5))
        if copias == 1:
            return primeira
        return primeira + texto_para_escpos(texto, abrir_gaveta=False, **base) * (copias - 1)

    def imprimir(self, texto: str, *, cortar: bool | None = None, abrir_gaveta: bool = False, copias: int = 1,
                 logotipo: bytes | None = None, **estilo) -> None:
        self.enviar_bytes(self.montar(texto, cortar=cortar, abrir_gaveta=abrir_gaveta, copias=copias,
                                      logotipo=logotipo, **estilo))

    def abrir_gaveta(self) -> None:
        if not self.tem_gaveta:
            raise ErroImpressao("A gaveta não está marcada como ligada à impressora térmica (Configurações > Máquinas).")
        self.enviar_bytes(INICIALIZAR + pulso_gaveta(self.pino_gaveta))

    def ticket_teste(self, nome_loja: str = "PDV") -> str:
        return "\n".join([
            nome_loja.upper().center(self.colunas), "=" * self.colunas,
            "PAGINA DE TESTE".center(self.colunas),
            "Impressora termica ESC/POS".center(self.colunas), "-" * self.colunas,
            "Acentuacao: acao, pao, cafe, R$ 1.234,56",
            f"Colunas configuradas: {self.colunas}",
            f"Conexao: {self.conexao}  {self.endereco}",
            f"Pagina de codigo: {self.codepage}",
            "0123456789 ABCDEFGHIJ abcdefghij",
            "-" * self.colunas, "TOTAL: R$ 0,00", "=" * self.colunas,
            "Se este texto saiu alinhado e com", "acentos corretos, esta tudo certo.",
        ])

    def teste(self, nome_loja: str = "PDV") -> None:
        self.imprimir(self.ticket_teste(nome_loja), grande_prefixos=("TOTAL",), negrito_linhas=1)
