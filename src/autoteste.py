"""Autoteste do programa instalado:  WillPDV.exe --autoteste [arquivo] [--rede]

Serve para conferir, no próprio executável (PyInstaller) e no instalador, o que os testes de código-fonte não pegam: módulo
que ficou de fora do pacote, biblioteca que não veio junto (Qt, SQLite, SSL) ou tela que não abre. O GitHub Actions roda isto
depois de gerar o executável e depois de instalar o instalador; em qualquer PC também dá para rodar para ver se o programa
está inteiro. Não mexe nos dados do caixa: usa um banco temporário.

Escreve o resultado em `arquivo` (o executável é "janela", sem console) e devolve 0 se tudo deu certo, 1 se algo falhou.
`--rede` também confere a conexão HTTPS com o Telegram (usa um token falso: basta o Telegram responder "não autorizado").
"""
from __future__ import annotations

import importlib
import platform
import sys
import tempfile
import traceback
from pathlib import Path

# Todos os módulos do programa. O PyInstaller só leva o que enxerga por `import`; importar tudo aqui, no executável, mostra
# se algo ficou para trás. Um teste confere que esta lista acompanha os arquivos de `src/` (módulo novo precisa entrar aqui).
# `src.app` fica de fora de propósito: no executável ele é o próprio script de entrada (`__main__`), não um módulo importável.
MODULOS = [
    "src.autoteste", "src.autoteste_qt", "src.versao",
    "src.controllers.auditoria_controller",
    "src.controllers.acesso_controller", "src.controllers.cadastro_controller", "src.controllers.caderneta_controller",
    "src.controllers.caixa_controller", "src.controllers.comissao_controller", "src.controllers.conferencia_turno",
    "src.controllers.config_controller", "src.controllers.contas_controller", "src.controllers.entidades",
    "src.controllers.entrega_controller", "src.controllers.estoque_controller", "src.controllers.fila_impressao_controller",
    "src.controllers.importacao_produtos", "src.controllers.impressao_assistente", "src.controllers.impressao_controller", "src.controllers.notificacoes", "src.controllers.perfil_controller", "src.controllers.preparo_controller", "src.controllers.quartos_controller",
    "src.controllers.produto_controller",
    "src.controllers.relatorio_comissoes", "src.controllers.relatorio_controller", "src.controllers.relatorio_gestao",
    "src.controllers.relatorio_vendas", "src.controllers.telegram_controller", "src.controllers.telegram_textos",
    "src.controllers.turno_controller", "src.controllers.utilitario_controller",
    "src.core.ed25519", "src.core.erros", "src.core.formatacao", "src.core.instancia", "src.core.licenca",
    "src.core.posicao", "src.core.registro", "src.core.relatorio", "src.core.seguranca", "src.core.backup_seguro",
    "src.core.identidade_visual",
    "src.database.conexao", "src.database.esquema", "src.database.protecao", "src.database.sementes",
    "src.hardware.campainha", "src.hardware.dispositivos", "src.hardware.imagem_escpos", "src.hardware.impressora_termica",
    "src.hardware.impressoras_so",
    "src.sync.atualizacoes", "src.sync.licenca_nuvem", "src.sync.painel_envio", "src.sync.sincronizador", "src.sync.telegram_api",
    "src.sync.ponte",
    "src.controllers.integracoes_controller",
    "src.controllers.alertas_controller", "src.controllers.etiqueta_controller",
    "src.controllers.promocoes_controller", "src.controllers.retornaveis_controller", "src.controllers.diagnostico_controller",
    "src.controllers.devolucoes_controller", "src.homologacao", "src.controllers.contexto", "src.core.valor_pagamento",
    "src.ui_qt.app", "src.ui_qt.tema", "src.ui_qt.login", "src.ui_qt.cadastros", "src.ui_qt.caixa", "src.ui_qt.auditoria",
    "src.ui_qt.comissao", "src.ui_qt.assistente_impressora", "src.ui_qt.composicao",
    "src.ui_qt.configuracoes", "src.ui_qt.estoque", "src.ui_qt.fila_impressao",
    "src.ui_qt.importar_produtos", "src.ui_qt.relatorio_vendas", "src.ui_qt.relatorios",
    "src.ui_qt.restaurar_backup", "src.ui_qt.contas",
    "src.ui_qt.maquinas", "src.ui_qt.acessos", "src.ui_qt.telegram", "src.ui_qt.utilitarios",
    "src.ui_qt.atualizacoes", "src.ui_qt.visualizador", "src.ui_qt.estoque_lancamentos",
    "src.ui_qt.alertas", "src.ui_qt.etiquetas", "src.ui_qt.promocoes", "src.ui_qt.retornaveis",
    "src.ui_qt.cozinha", "src.ui_qt.quartos", "src.ui_qt.diagnostico",
    "src.ui_qt.devolucoes", "src.ui_qt.fechamento", "src.ui_qt.painel_mesas", "src.ui_qt.relogio", "src.core.edicao", "src.controllers.mesas_modelo", "src.ui_qt.fechamento_turno",
    "src.porteiro.consulta", "src.porteiro.servidor", "src.porteiro.servico", "src.porteiro.nuvem_envio", "src.ui_qt.porteiro",
]


def _modulos() -> list[str]:
    falhas = []
    for nome in MODULOS:
        try:
            importlib.import_module(nome)
        except Exception as e:  # noqa: BLE001 - o que importa é listar TODOS os que falharam
            falhas.append(f"{nome}: {type(e).__name__}: {e}")
    if falhas:
        raise RuntimeError(f"{len(falhas)} módulo(s) não carregam:\n  " + "\n  ".join(falhas))
    return [f"{len(MODULOS)} módulos carregam"]


def _bibliotecas() -> list[str]:
    import sqlite3
    import ssl
    import PySide6
    ssl.create_default_context()           # no Windows lê os certificados do sistema: sem isto o Telegram não conecta
    return [f"Python {platform.python_version()} ({'executável' if getattr(sys, 'frozen', False) else 'código-fonte'}), "
            f"SQLite {sqlite3.sqlite_version}, Qt/PySide6 {PySide6.__version__}, {ssl.OPENSSL_VERSION}"]


def _edicao() -> list[str]:
    """Qual edição o programa abre (WillPDV ou E&A Superações) e se a marca dela veio no pacote."""
    from src.core import edicao
    ed = edicao.atual()
    pasta = edicao.pasta_recursos()
    faltando = [nome for nome in (ed.icone, ed.logotipo) if nome and not (pasta / nome).is_file()]
    if faltando:
        raise RuntimeError(f"{ed.nome}: faltam no pacote: {', '.join(faltando)}")
    return [f"{ed.nome} (dados em {ed.pasta_dados}): ícone{' e logotipo' if ed.logotipo else ''} no pacote"]


def _banco_e_telas(pasta: Path) -> list[str]:
    """Abre a interface Qt com banco efêmero (sem tocar nos dados da loja) e confere o backup criptografado."""
    from src.autoteste_qt import _backup_seguro
    from src.ui_qt.app import autoteste
    try:
        textos = autoteste(pasta)
    except ImportError as e:
        raise RuntimeError(f"sem ambiente gráfico (Qt): {e}") from None
    return [*textos, _backup_seguro(pasta)]


def _rede() -> list[str]:
    from src.sync.telegram_api import ClienteTelegram, ErroTelegram
    try:
        ClienteTelegram("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA").quem_sou()
    except ErroTelegram as e:
        if e.codigo is None:
            raise RuntimeError(f"sem conexão HTTPS com o Telegram: {e}") from None
        return [f"HTTPS com o Telegram funciona (respondeu {e.codigo}, como esperado para um token falso)"]
    raise RuntimeError("o Telegram aceitou um token falso?!")


def executar(saida: str | None = None, rede: bool = False) -> int:
    """Roda os testes, escreve o relatório em `saida` (e na tela, se houver console) e devolve 0 (tudo certo) ou 1."""
    from src.core import edicao
    from src.versao import VERSAO
    linhas = [f"{edicao.atual().nome} {VERSAO} — autoteste"]
    etapas = [("módulos", _modulos), ("bibliotecas", _bibliotecas), ("edição", _edicao)]
    ok = True
    with tempfile.TemporaryDirectory(prefix="willpdv_autoteste_") as pasta:
        etapas.append(("telas", lambda: _banco_e_telas(Path(pasta))))
        if rede:
            etapas.append(("rede", _rede))
        for nome, funcao in etapas:
            try:
                linhas += [f"OK    {nome}: {texto}" for texto in funcao()]
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
    if sys.stdout is not None:                  # o executável "janela" não tem console
        try:
            print(texto, end="")
        except (OSError, UnicodeEncodeError):
            pass
    return 0 if ok else 1
