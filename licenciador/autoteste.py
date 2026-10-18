"""Autoteste do WillPDV Licenças:  WillLicencas.exe --autoteste [arquivo]

Confere, no próprio executável, o que os testes de código-fonte não pegam: módulo que ficou fora do pacote, assinatura que não
fecha, tela que não abre. Usa uma chave e um histórico TEMPORÁRIOS: não toca na sua chave de verdade nem nas licenças emitidas.
O GitHub Actions roda isto no .exe e no instalador instalado antes de entregar.
"""
from __future__ import annotations

import importlib
import platform
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path

MODULOS = ["licenciador.nucleo", "licenciador.tela", "licenciador.autoteste", "src.core.licenca", "src.core.ed25519",
           "src.core.backup_seguro", "src.core.formatacao", "src.core.erros", "src.ui.tema", "src.ui.icone"]


def _modulos() -> list[str]:
    falhas = []
    for nome in MODULOS:
        try:
            importlib.import_module(nome)
        except Exception as e:  # noqa: BLE001
            falhas.append(f"{nome}: {type(e).__name__}: {e}")
    if falhas:
        raise RuntimeError("módulo(s) que não carregam:\n  " + "\n  ".join(falhas))
    return [f"{len(MODULOS)} módulos carregam"]


def _assinatura(pasta: Path) -> list[str]:
    from licenciador import nucleo
    from src.core import ed25519, licenca
    chave = pasta / "chave.key"
    publica = nucleo.criar_chave(chave)
    semente = nucleo._ler_semente(chave)
    hoje = date(2026, 1, 15)
    linhas = []
    for tipo, qtd in (("mensal", 1), ("mensal", 12), ("permanente", 0), ("teste", 7)):
        expira = nucleo.validade(tipo, qtd, hoje)
        codigo = licenca.gerar_licenca(semente, "LOJA-TESTE", (expira - hoje).days, hoje)
        lic = licenca.ler_licenca(codigo, bytes.fromhex(publica))            # confere com a chave pública, como o PDV faz
        if lic["expira_em"] != expira or lic["loja"] != "LOJA-TESTE":
            raise RuntimeError(f"a licença {tipo} voltou diferente do emitido: {lic}")
    if ed25519.chave_publica(semente).hex() != publica:
        raise RuntimeError("a chave pública não bate com a privada")
    bytes.fromhex(licenca.CHAVE_PUBLICA_HEX)                                 # a chave do PDV embutida é um hexadecimal válido
    linhas.append("assinatura e conferência de licença mensal, permanente e de teste")
    return linhas


def _tela(pasta: Path) -> list[str]:
    import tkinter as tk
    from licenciador.nucleo import Historico
    from licenciador.tela import Janela
    try:
        janela = Janela(pasta / "chave.key", Historico(pasta / "historico.json"))
    except tk.TclError as e:
        raise RuntimeError(f"sem ambiente gráfico (Tk): {e}") from None
    try:
        janela.update()
        if len(janela.abas.tabs()) != 5:
            raise RuntimeError("a janela abriu sem todas as abas")
    finally:
        janela.destroy()
    return ["a janela abre com as 5 abas"]


def _backup(pasta: Path) -> list[str]:
    from licenciador import nucleo
    from licenciador.nucleo import Historico
    from unittest import mock
    from src.core import licenca
    chave = pasta / "chave_backup.key"
    publica = nucleo.criar_chave(chave)
    with mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", publica):       # a chave temporária faz o papel da chave do PDV
        historico = Historico(pasta / "historico_backup.json")
        historico.adicionar(nucleo.emitir("LOJA-TESTE", "mensal", 1, chave, date(2026, 1, 15)))
        nuvem = pasta / "nuvem"
        nuvem.mkdir()
        copia = nucleo.backup_historico(nuvem, historico, date(2026, 1, 15))
        protegido = nucleo.backup_chave_protegido(nuvem, "senha-de-teste-longa", chave)
        if chave.read_text(encoding="ascii").strip() in protegido.read_bytes().decode("latin-1"):
            raise RuntimeError("o backup da chave ficou legível, sem criptografia")
        outra = pasta / "restaurada.key"
        nucleo.restaurar_chave_protegida(protegido, "senha-de-teste-longa", outra)
        if outra.read_text(encoding="ascii") != chave.read_text(encoding="ascii"):
            raise RuntimeError("a chave restaurada não é igual à original")
        novo = Historico(pasta / "historico_restaurado.json")
        if nucleo.restaurar_historico(copia, novo) != 1:
            raise RuntimeError("o histórico restaurado voltou diferente")
    return ["backup do histórico e da chave criptografada (cópia e restauração)"]


def executar(saida: str | None = None) -> int:
    from licenciador.nucleo import VERSAO
    linhas = [f"WillPDV Licenças {VERSAO} — autoteste",
              f"Python {platform.python_version()} ({'executável' if getattr(sys, 'frozen', False) else 'código-fonte'})"]
    ok = True
    with tempfile.TemporaryDirectory(prefix="willlicencas_autoteste_") as pasta:
        etapas = [("módulos", _modulos), ("assinatura", lambda: _assinatura(Path(pasta))), ("backup", lambda: _backup(Path(pasta))),
                  ("tela", lambda: _tela(Path(pasta)))]
        for nome, funcao in etapas:
            try:
                linhas += [f"OK    {nome}: {t}" for t in funcao()]
            except Exception as e:  # noqa: BLE001
                ok = False
                linhas.append(f"FALHA {nome}: {e}")
                linhas += ["      " + l for l in traceback.format_exc().splitlines()[-6:]]
    linhas.append("RESULTADO: " + ("TUDO CERTO" if ok else "COM FALHAS"))
    texto = "\n".join(linhas) + "\n"
    if saida:
        try:
            Path(saida).write_text(texto, encoding="utf-8")
        except OSError:
            pass
    if sys.stdout is not None:                       # o executável "janela" não tem console
        try:
            print(texto, end="")
        except (OSError, UnicodeEncodeError):
            pass
    return 0 if ok else 1
