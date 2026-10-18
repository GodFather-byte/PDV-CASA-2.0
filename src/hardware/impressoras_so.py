"""Impressoras e portas que o computador enxerga, para o operador escolher em vez de digitar o nome.

Só biblioteca padrão (ctypes e winreg): funciona no executável sem instalar pywin32 nem pyserial.
Fora do Windows as listas vêm vazias. Nada aqui imprime: só lê o que o sistema operacional informa.

  * `listar_impressoras()`  impressoras instaladas no Windows (USB, rede com driver, compartilhadas), com a porta,
                            o driver e a situação (pronta, offline, sem papel...). As que parecem térmicas vêm primeiro.
  * `listar_portas_seriais()` portas COM presentes (adaptador USB-serial incluso).
"""
from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass

_WINDOWS = sys.platform == "win32"

# EnumPrinters: o que listar
PRINTER_ENUM_LOCAL = 0x00000002
PRINTER_ENUM_CONNECTIONS = 0x00000004
# PRINTER_INFO_2.Attributes
ATTR_NETWORK = 0x00000010
ATTR_WORK_OFFLINE = 0x00000400
# PRINTER_INFO_2.Status
ST_PAUSED = 0x00000001
ST_ERROR = 0x00000002
ST_PAPER_JAM = 0x00000008
ST_PAPER_OUT = 0x00000010
ST_PAPER_PROBLEM = 0x00000040
ST_OFFLINE = 0x00000080
ST_BUSY = 0x00000200
ST_PRINTING = 0x00000400
ST_NOT_AVAILABLE = 0x00001000
ST_USER_INTERVENTION = 0x00100000
ST_DOOR_OPEN = 0x00400000

ERRO_BUFFER_PEQUENO = 122

# Térmicas de cupom que o comércio brasileiro mais usa (marca, modelo ou o jeito que o driver se apresenta).
_TERMICA = re.compile(
    r"epson\s*tm|tm-?[tmhul]\d|bematech|mp-?(4200|2500|100|20)|elgin|\bi[79]\b|daruma|dr-?\d{3}|tanca|tp-?\d{3}|"
    r"diebold|procomp|sweda|control\s*id|pos-?\s?(58|80)|pos\s*printer|thermal|t[eé]rmica|receipt|cupom|"
    r"n[aã]o\s*fiscal|esc\s*/?\s*pos|star\s*tsp|\btsp\d|citizen|gertec|jetway|knup|datecs|rongta|xprinter|"
    r"goojprt|generic\s*/?\s*text|somente\s*texto|text\s*only", re.I)
# Impressoras de mentira (PDF, fax, OneNote...): aparecem, mas por último, e não servem para cupom.
_VIRTUAL = re.compile(r"pdf|xps|onenote|fax|document\s*writer|print\s*to|imprimir\s*em|snagit|anydesk|teamviewer|virtual", re.I)
_PORTAS_VIRTUAIS = {"PORTPROMPT:", "FILE:", "NUL:", "XPSPORT:", "SHRFAX:", "NULL:"}


@dataclass(frozen=True)
class ImpressoraWindows:
    nome: str
    porta: str = ""
    driver: str = ""
    padrao: bool = False
    situacao: str = "Pronta"
    pronta: bool = True              # False: offline, sem papel, tampa aberta, com erro...
    virtual: bool = False            # PDF, XPS, fax: não serve para cupom
    termica_provavel: bool = False   # pelo nome/driver (palpite, serve para ordenar a lista)
    de_rede: bool = False            # compartilhada por outro computador
    trabalhos: int = 0               # documentos esperando na fila do Windows (se não zera, algo está preso)
    offline: bool = False            # marcada como "usar impressora offline" ou desconectada
    pausada: bool = False

    @property
    def rotulo(self) -> str:
        return self.nome + ("  (padrão do Windows)" if self.padrao else "")


@dataclass(frozen=True)
class PortaSerial:
    porta: str                       # "COM3"
    descricao: str = ""              # "USB Serial Port", quando o sistema informa


# ------------------------------------------------------------------------- API do Windows (ctypes)
class _PrinterInfo2(ctypes.Structure):
    _fields_ = [("pServerName", wintypes.LPWSTR), ("pPrinterName", wintypes.LPWSTR), ("pShareName", wintypes.LPWSTR),
                ("pPortName", wintypes.LPWSTR), ("pDriverName", wintypes.LPWSTR), ("pComment", wintypes.LPWSTR),
                ("pLocation", wintypes.LPWSTR), ("pDevMode", ctypes.c_void_p), ("pSepFile", wintypes.LPWSTR),
                ("pPrintProcessor", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR), ("pParameters", wintypes.LPWSTR),
                ("pSecurityDescriptor", ctypes.c_void_p), ("Attributes", wintypes.DWORD), ("Priority", wintypes.DWORD),
                ("DefaultPriority", wintypes.DWORD), ("StartTime", wintypes.DWORD), ("UntilTime", wintypes.DWORD),
                ("Status", wintypes.DWORD), ("cJobs", wintypes.DWORD), ("AveragePPM", wintypes.DWORD)]


class _PrinterInfo4(ctypes.Structure):
    _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR), ("Attributes", wintypes.DWORD)]


def winspool():
    """A DLL do spooler do Windows, com os protótipos das funções que o PDV usa (handles de 64 bits sem truncar)."""
    if not _WINDOWS:
        raise OSError("O spooler de impressão só existe no Windows.")
    dll = ctypes.WinDLL("winspool.drv", use_last_error=True)
    dll.EnumPrintersW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    dll.EnumPrintersW.restype = wintypes.BOOL
    dll.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    dll.GetDefaultPrinterW.restype = wintypes.BOOL
    dll.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    dll.OpenPrinterW.restype = wintypes.BOOL
    dll.ClosePrinter.argtypes = [ctypes.c_void_p]
    dll.ClosePrinter.restype = wintypes.BOOL
    dll.StartDocPrinterW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    dll.StartDocPrinterW.restype = wintypes.DWORD
    dll.EndDocPrinter.argtypes = [ctypes.c_void_p]
    dll.EndDocPrinter.restype = wintypes.BOOL
    dll.StartPagePrinter.argtypes = [ctypes.c_void_p]
    dll.StartPagePrinter.restype = wintypes.BOOL
    dll.EndPagePrinter.argtypes = [ctypes.c_void_p]
    dll.EndPagePrinter.restype = wintypes.BOOL
    dll.WritePrinter.argtypes = [ctypes.c_void_p, ctypes.c_char_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    dll.WritePrinter.restype = wintypes.BOOL
    return dll


def _enum(dll, flags: int, nivel: int, estrutura):
    """Chama EnumPrintersW duas vezes (a 1ª pergunta o tamanho) e devolve (buffer, vetor de estruturas)."""
    precisa, retornou = wintypes.DWORD(0), wintypes.DWORD(0)
    dll.EnumPrintersW(flags, None, nivel, None, 0, ctypes.byref(precisa), ctypes.byref(retornou))
    if precisa.value == 0:
        return None, []
    buf = ctypes.create_string_buffer(precisa.value)
    if not dll.EnumPrintersW(flags, None, nivel, buf, precisa.value, ctypes.byref(precisa), ctypes.byref(retornou)):
        erro = getattr(ctypes, "get_last_error", lambda: 0)()      # só existe no Windows
        raise OSError(f"EnumPrinters falhou (erro {erro}).")
    return buf, list((estrutura * retornou.value).from_buffer(buf))


def _enumerar_windows() -> list[dict]:
    """Impressoras locais (com porta, driver e situação) e as conectadas de outros computadores (só o nome)."""
    dll = winspool()
    encontradas: dict[str, dict] = {}
    buf, locais = _enum(dll, PRINTER_ENUM_LOCAL, 2, _PrinterInfo2)
    for p in locais:
        nome = p.pPrinterName or ""
        encontradas[nome.lower()] = {"nome": nome, "porta": p.pPortName or "", "driver": p.pDriverName or "",
                                     "status": int(p.Status), "atributos": int(p.Attributes), "trabalhos": int(p.cJobs)}
    del locais, buf
    try:        # compartilhadas por outro PC: o nível 4 não abre a impressora, então não trava com servidor fora do ar
        buf, conexoes = _enum(dll, PRINTER_ENUM_CONNECTIONS, 4, _PrinterInfo4)
        for p in conexoes:
            nome = p.pPrinterName or ""
            encontradas.setdefault(nome.lower(), {"nome": nome, "porta": "", "driver": "", "status": 0,
                                                  "atributos": int(p.Attributes) | ATTR_NETWORK})
        del conexoes, buf
    except OSError:
        pass
    return list(encontradas.values())


def _padrao_windows() -> str | None:
    dll = winspool()
    tamanho = wintypes.DWORD(0)
    dll.GetDefaultPrinterW(None, ctypes.byref(tamanho))
    if tamanho.value == 0:
        return None
    buf = ctypes.create_unicode_buffer(tamanho.value)
    if not dll.GetDefaultPrinterW(buf, ctypes.byref(tamanho)):
        return None
    return buf.value or None


# ------------------------------------------------------------------------------------- regras
def situacao(status: int, atributos: int = 0) -> tuple[str, bool]:
    """(texto para o operador, pronta?) a partir do que o spooler informa. A situação é uma dica: depende do driver
    informar o estado da impressora, e muitas térmicas só avisam que estão desligadas."""
    if atributos & ATTR_WORK_OFFLINE or status & (ST_OFFLINE | ST_NOT_AVAILABLE):
        return "Offline (desligada, sem cabo ou 'usar offline')", False
    if status & ST_PAPER_OUT:
        return "Sem papel", False
    if status & ST_DOOR_OPEN:
        return "Tampa aberta", False
    if status & (ST_PAPER_JAM | ST_PAPER_PROBLEM):
        return "Problema com o papel", False
    if status & ST_ERROR:
        return "Com erro", False
    if status & ST_PAUSED:
        return "Pausada", False
    if status & ST_USER_INTERVENTION:
        return "Precisa de atenção", False
    if status & (ST_PRINTING | ST_BUSY):
        return "Ocupada", True
    return "Pronta", True


def _virtual(nome: str, driver: str, porta: str) -> bool:
    return porta.strip().upper() in _PORTAS_VIRTUAIS or bool(_VIRTUAL.search(f"{nome} {driver}"))


def _termica(nome: str, driver: str) -> bool:
    return bool(_TERMICA.search(f"{nome} {driver}"))


def _montar(bruta: dict, padrao: str | None) -> ImpressoraWindows | None:
    nome = (bruta.get("nome") or "").strip()
    if not nome:
        return None
    porta, driver = (bruta.get("porta") or "").strip(), (bruta.get("driver") or "").strip()
    status, atributos = int(bruta.get("status") or 0), int(bruta.get("atributos") or 0)
    texto, pronta = situacao(status, atributos)
    virtual = _virtual(nome, driver, porta)
    return ImpressoraWindows(
        nome=nome, porta=porta, driver=driver, padrao=bool(padrao) and nome.lower() == padrao.strip().lower(),
        situacao=texto, pronta=pronta, virtual=virtual, termica_provavel=not virtual and _termica(nome, driver),
        de_rede=bool(atributos & ATTR_NETWORK) or nome.startswith("\\\\"),
        trabalhos=int(bruta.get("trabalhos") or 0), offline=bool(atributos & ATTR_WORK_OFFLINE or status & (ST_OFFLINE | ST_NOT_AVAILABLE)),
        pausada=bool(status & ST_PAUSED))


def listar_impressoras() -> list[ImpressoraWindows]:
    """As impressoras instaladas neste computador. As que parecem térmicas primeiro, as virtuais (PDF, fax) por último."""
    if not _WINDOWS:
        return []
    try:
        brutas, padrao = _enumerar_windows(), _padrao_windows()
    except (OSError, AttributeError):
        return []
    lista = [i for i in (_montar(b, padrao) for b in brutas) if i is not None]
    return sorted(lista, key=lambda i: (i.virtual, not i.termica_provavel, i.nome.lower()))


# SetPrinter: o que dá para mandar à fila do Windows
CONTROLE_PAUSAR, CONTROLE_RETOMAR, CONTROLE_LIMPAR = 1, 2, 3
_ACESSO_ADMINISTRAR = 0x00000004


class _PrinterDefaults(ctypes.Structure):
    _fields_ = [("pDatatype", wintypes.LPWSTR), ("pDevMode", ctypes.c_void_p), ("DesiredAccess", wintypes.DWORD)]


def controlar_fila(nome: str, acao: int) -> None:
    """Retoma (`CONTROLE_RETOMAR`) ou esvazia (`CONTROLE_LIMPAR`) a fila de uma impressora do Windows: é o 'Cancelar todos os
    documentos' e o 'Retomar impressão' do Windows. Levanta OSError com a causa se o Windows recusar (ex.: sem permissão)."""
    dll = winspool()
    dll.SetPrinterW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dll.SetPrinterW.restype = wintypes.BOOL
    dll.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    handle = ctypes.c_void_p()
    padrao = _PrinterDefaults(None, None, _ACESSO_ADMINISTRAR)
    if not dll.OpenPrinterW(nome, ctypes.byref(handle), ctypes.byref(padrao)):
        codigo = ctypes.get_last_error()
        raise OSError(f"O Windows não deixou abrir '{nome}' para administrar a fila ({ctypes.FormatError(codigo).strip()} [erro {codigo}]).")
    try:
        if not dll.SetPrinterW(handle, 0, None, acao):
            codigo = ctypes.get_last_error()
            raise OSError(f"O Windows recusou a ação na fila de '{nome}' ({ctypes.FormatError(codigo).strip()} [erro {codigo}]).")
    finally:
        dll.ClosePrinter(handle)


class _PortInfo1(ctypes.Structure):
    _fields_ = [("pName", wintypes.LPWSTR)]


def listar_portas_usb() -> list[str]:
    """Portas de impressora USB que o Windows criou (USB001, USB002...): existem quando há uma impressora USB LIGADA e reconhecida
    como impressora, mesmo sem driver instalado. Vazio = o Windows não enxerga nada de impressora no cabo USB."""
    if not _WINDOWS:
        return []
    try:
        dll = winspool()
        dll.EnumPortsW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
        dll.EnumPortsW.restype = wintypes.BOOL
        precisa, retornou = wintypes.DWORD(0), wintypes.DWORD(0)
        dll.EnumPortsW(None, 1, None, 0, ctypes.byref(precisa), ctypes.byref(retornou))
        if precisa.value == 0:
            return []
        buf = ctypes.create_string_buffer(precisa.value)
        if not dll.EnumPortsW(None, 1, buf, precisa.value, ctypes.byref(precisa), ctypes.byref(retornou)):
            return []
        portas = [(p.pName or "") for p in (_PortInfo1 * retornou.value).from_buffer(buf)]
    except (OSError, AttributeError):
        return []
    return sorted(p for p in portas if re.fullmatch(r"USB\d+", p.strip(), re.I))


def servico_spooler_rodando() -> bool | None:
    """True/False: o serviço 'Spooler de Impressão' do Windows está rodando? None se não deu para saber (fora do Windows)."""
    if not _WINDOWS:
        return None
    import subprocess
    try:
        saida = subprocess.run(["sc", "query", "spooler"], capture_output=True, text=True, errors="replace", timeout=8,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if saida is None:
        return None
    if "RUNNING" in saida.upper():
        return True
    return False if "STOPPED" in saida.upper() or "PAUSED" in saida.upper() else None


def impressora_padrao() -> str | None:
    """Nome da impressora padrão do Windows (ou None)."""
    if not _WINDOWS:
        return None
    try:
        return _padrao_windows()
    except (OSError, AttributeError):
        return None


# ---------------------------------------------------------------------------------- portas COM
def _portas_do_registro() -> list[str]:
    """Portas COM presentes, como o Windows registra (inclui adaptadores USB-serial conectados)."""
    if not _WINDOWS:
        return []
    import winreg
    portas: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as chave:
            i = 0
            while True:
                try:
                    _, valor, _ = winreg.EnumValue(chave, i)
                except OSError:
                    break
                portas.append(str(valor))
                i += 1
    except OSError:
        pass
    return portas


def _descricoes_pyserial() -> dict[str, str]:
    """Descrição de cada porta, se o pyserial estiver instalado (ele já é necessário para imprimir pela serial)."""
    try:
        from serial.tools import list_ports  # type: ignore
        return {p.device.upper(): (p.description or "") for p in list_ports.comports()}
    except Exception:  # noqa: BLE001 - sem pyserial ou sem permissão: a lista segue sem descrição
        return {}


def listar_portas_seriais() -> list[PortaSerial]:
    portas = {p.strip().upper(): "" for p in _portas_do_registro() if p.strip()}
    if portas:
        for porta, descricao in _descricoes_pyserial().items():
            if porta in portas and descricao and descricao.upper() != porta:
                portas[porta] = descricao
    return [PortaSerial(p, d) for p, d in sorted(portas.items(), key=lambda x: (int(re.sub(r"\D", "", x[0]) or 0), x[0]))]
