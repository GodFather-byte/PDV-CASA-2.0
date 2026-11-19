"""Confere se uma janela Qt já exibida tem algo cortado: texto maior que o botão ou o rótulo, campo para fora da
janela, campos sobrepostos, cabeçalho de tabela cortado, abas que não cabem e rolagem de lado.

É o que o olho procura numa tela "cortada", medido. Usado pelos testes (`tests/test_qt_telas_cabem.py`) e por
`tools.capturar_telas --conferir`, que abre todas as telas numa resolução e lista o que achou:

    QT_QPA_PLATFORM=offscreen python -m tools.capturar_telas build/telas --largura 1024 --altura 728 --conferir

`problemas(janela)` devolve uma lista de frases (vazia = nada cortado). A janela precisa estar visível e com os
eventos processados. Rolagem para baixo não é problema; rolagem de lado é.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox, QCheckBox, QComboBox, QHeaderView,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QTabBar, QTabWidget, QTableView,
    QGroupBox, QStyle, QStyleOptionButton, QTextEdit, QToolButton, QWidget,
)

FOLGA = 2


def _rolagem_acima(w: QWidget, janela: QWidget):
    """As áreas de rolagem entre o widget e a janela."""
    areas, pai = [], w.parentWidget()
    while pai is not None and pai is not janela:
        if isinstance(pai, QAbstractScrollArea):
            areas.append(pai)
        pai = pai.parentWidget()
    return areas


def _trecho(texto: str, limite: int = 46) -> str:
    texto = " ".join(str(texto).replace("&", "").split())
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


def _texto_cortado(w: QWidget) -> str | None:
    if isinstance(w, QLabel):
        if not w.text() or w.pixmap() is not None and not w.pixmap().isNull():
            return None
        if hasattr(w, "texto_exibido"):
            exibido = w.texto_exibido()
            if "…" in exibido:
                return f"rótulo abreviado com reticências ({w.width()}px): “{_trecho(w.text())}”"
            return None
        margem = w.contentsMargins()
        if w.wordWrap():
            precisa = w.heightForWidth(w.width())
            if precisa > w.height() + FOLGA:
                return f"rótulo cortado na altura ({w.height()} de {precisa}px): “{_trecho(w.text())}”"
            # palavra sozinha maior que a largura não quebra: corta de lado
            if w.minimumSizeHint().width() > w.width() + FOLGA and w.textFormat() != Qt.TextFormat.RichText:
                maior = max((w.fontMetrics().horizontalAdvance(p) for p in w.text().split()), default=0)
                if maior + margem.left() + margem.right() > w.width() + FOLGA:
                    return f"rótulo cortado na largura ({w.width()}px): “{_trecho(w.text())}”"
            return None
        precisa = w.sizeHint().width()
        if precisa > w.width() + FOLGA:
            return f"rótulo cortado na largura ({w.width()} de {precisa}px): “{_trecho(w.text())}”"
        if w.sizeHint().height() > w.height() + FOLGA + 2:
            return f"rótulo cortado na altura ({w.height()} de {w.sizeHint().height()}px): “{_trecho(w.text())}”"
        return None
    if isinstance(w, (QPushButton, QToolButton)):
        if not w.text():
            return None
        linhas = w.text().replace("&", "").split("\n")
        largura = max(w.fontMetrics().size(Qt.TextFlag.TextSingleLine, l).width() for l in linhas)
        if not w.icon().isNull():
            largura += w.iconSize().width() + 4
        util = w.width() - 4
        if isinstance(w, QPushButton):
            opcao = QStyleOptionButton()
            w.initStyleOption(opcao)
            miolo = w.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, opcao, w)
            if miolo.isValid() and miolo.width() > 0:
                util = miolo.width()
            if w.menu() is not None:
                util -= 14                                 # a setinha do menu
        if largura > util + 3:                             # até 3 pontos somem na folga do próprio botão
            return f"botão com texto cortado ({util}px úteis para {largura}px de texto): “{_trecho(w.text())}”"
        altura = w.fontMetrics().height() * len(linhas)
        if altura > w.height() + FOLGA:
            return f"botão baixo demais ({w.height()} para {altura}px): “{_trecho(w.text())}”"
        return None
    if isinstance(w, (QCheckBox, QRadioButton)):
        if w.text() and w.sizeHint().width() > w.width() + FOLGA:
            return f"opção com texto cortado ({w.width()} de {w.sizeHint().width()}px): “{_trecho(w.text())}”"
        return None
    if isinstance(w, QComboBox):
        texto = w.currentText()
        if texto and not w.isEditable():
            largura = w.fontMetrics().horizontalAdvance(texto) + 34          # seta e bordas
            if largura > w.width() + FOLGA:
                return f"lista com o item cortado ({w.width()} para {largura}px): “{_trecho(texto)}”"
        return None
    return None


FOLHAS = (QLabel, QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QAbstractItemView)


def _fora_da_area(w: QWidget, janela: QWidget) -> str | None:
    """Parte do widget que fica para fora de algum ancestral e que rolagem nenhuma alcança."""
    if not isinstance(w, FOLHAS) or w.width() <= 0 or w.height() <= 0:
        return None
    r = QRect(w.mapTo(janela, QPoint(0, 0)), w.size())
    falta_l = falta_a = 0
    pai = w.parentWidget()
    while pai is not None:
        pr = QRect(pai.mapTo(janela, QPoint(0, 0)), pai.size()) if pai is not janela else janela.rect()
        exc_l = max(0, pr.left() - r.left()) + max(0, r.right() - pr.right())
        exc_a = max(0, pr.top() - r.top()) + max(0, r.bottom() - pr.bottom())
        area = pai.parentWidget()
        if isinstance(area, QAbstractScrollArea) and area.viewport() is pai:
            if area.verticalScrollBar().maximum() > 0:
                exc_a = 0                                  # dá para rolar até lá
            if area.horizontalScrollBar().maximum() > 0:
                exc_l = 0                                  # a rolagem de lado é anotada à parte
        falta_l, falta_a = max(falta_l, exc_l), max(falta_a, exc_a)
        r = r.intersected(pr)
        if r.isEmpty() or pai is janela:
            break
        pai = pai.parentWidget()
    partes = ([f"{falta_l}px na largura"] if falta_l > FOLGA else []) + ([f"{falta_a}px na altura"] if falta_a > FOLGA else [])
    if not partes:
        return None
    rotulo = getattr(w, "text", lambda: "")() if not isinstance(w, QAbstractItemView) else ""
    if isinstance(w, QLineEdit):
        rotulo = w.placeholderText() or w.objectName()
    return f"{type(w).__name__} para fora da janela em {' e '.join(partes)}: “{_trecho(rotulo or w.objectName())}”"


def _tabela(t: QTableView) -> list[str]:
    achados = []
    cab: QHeaderView = t.horizontalHeader()
    modelo = t.model()
    if modelo is None or cab.isHidden():
        return achados
    cortados = []
    for i in range(cab.count()):
        if cab.isSectionHidden(i):
            continue
        titulo = str(modelo.headerData(i, Qt.Orientation.Horizontal) or "")
        precisa = max(cab.fontMetrics().horizontalAdvance(linha) for linha in titulo.split("\n")) + 12
        if titulo and precisa > cab.sectionSize(i) + FOLGA:
            cortados.append(f"{' '.join(titulo.split())} ({cab.sectionSize(i)}/{precisa})")
    if cortados:
        achados.append("cabeçalho de tabela cortado: " + ", ".join(cortados[:6]))
    falta = cab.length() - t.viewport().width()
    if falta > FOLGA and t.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
        achados.append(f"tabela com rolagem de lado (faltam {falta}px; {cab.count() - cab.hiddenSectionCount()} colunas, "
                       f"{cab.length()}px em {t.viewport().width()}px)")
    return achados


def problemas(janela: QWidget) -> list[str]:
    """O que está cortado na janela como ela aparece agora (a aba e a seção que estão à vista)."""
    achados: list[str] = []
    for w in janela.findChildren(QWidget):
        if not w.isVisibleTo(janela) or w.window() is not janela:
            continue
        if isinstance(w.parentWidget(), (QTabBar, QComboBox, QAbstractSpinBox)) or isinstance(w, QTabBar):
            continue
        if w.objectName().startswith("qt_"):
            continue
        dentro_de_lista = any(isinstance(a, QAbstractItemView) for a in _rolagem_acima(w, janela))
        if not dentro_de_lista:
            for achado in (_texto_cortado(w), _fora_da_area(w, janela)):
                if achado:
                    achados.append(achado)
        if isinstance(w, QGroupBox) and w.title():
            precisa = w.fontMetrics().horizontalAdvance(w.title().replace("&", "")) + 24
            if precisa > w.width() + FOLGA:
                achados.append(f"título de grupo cortado ({w.width()} de {precisa}px): “{_trecho(w.title())}”")
        if isinstance(w, FOLHAS) and not dentro_de_lista and w.parentWidget() is not None:
            for irmao in w.parentWidget().children():
                if irmao is w or not isinstance(irmao, FOLHAS) or not irmao.isVisibleTo(janela) or id(irmao) < id(w):
                    continue
                corte = w.geometry().intersected(irmao.geometry())
                if corte.width() > 4 and corte.height() > 4:
                    achados.append(f"campos sobrepostos ({corte.width()}x{corte.height()}px): "
                                   f"“{_trecho(getattr(w, 'text', lambda: '')() or type(w).__name__, 28)}” e "
                                   f"“{_trecho(getattr(irmao, 'text', lambda: '')() or type(irmao).__name__, 28)}”")
        if isinstance(w, QTableView):
            achados += _tabela(w)
        elif isinstance(w, QScrollArea) and w.horizontalScrollBar().maximum() > 0 \
                and w.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
            achados.append(f"área com rolagem de lado (faltam {w.horizontalScrollBar().maximum()}px)")
        elif isinstance(w, QTabWidget):
            barra = w.tabBar()
            total = sum(barra.tabRect(i).width() for i in range(barra.count()))
            if total > barra.width() + FOLGA and barra.count() > 1:
                achados.append(f"abas não cabem na largura ({total}px em {barra.width()}px, {barra.count()} abas)")
    vistos, unicos = set(), []
    for a in achados:
        if a not in vistos:
            vistos.add(a)
            unicos.append(a)
    return unicos


def por_estado(janela: QWidget, nome: str) -> dict[str, list[str]]:
    """`problemas` da janela e de cada aba (QTabWidget) e seção (QToolBox) dela: {"nome [aba X]": [achados]}.
    Só entram os estados com algum achado. Devolve as abas ao lugar."""
    from PySide6.QtWidgets import QApplication, QToolBox

    def medir(estado: str, resultado: dict) -> None:
        for _ in range(3):
            QApplication.processEvents()
        achados = problemas(janela)
        if achados:
            resultado[estado] = achados

    resultado: dict[str, list[str]] = {}
    medir(nome, resultado)
    for abas in janela.findChildren(QTabWidget):
        if not abas.isVisibleTo(janela):
            continue
        inicial = abas.currentIndex()
        for i in range(abas.count()):
            if i != inicial and abas.isTabEnabled(i) and abas.isTabVisible(i):
                abas.setCurrentIndex(i)
                medir(f"{nome} [aba {abas.tabText(i)}]", resultado)
        abas.setCurrentIndex(inicial)
    for secoes in janela.findChildren(QToolBox):
        if not secoes.isVisibleTo(janela):
            continue
        inicial = secoes.currentIndex()
        for i in range(secoes.count()):
            if i != inicial and secoes.isItemEnabled(i):
                secoes.setCurrentIndex(i)
                medir(f"{nome} [seção {secoes.itemText(i)}]", resultado)
        secoes.setCurrentIndex(inicial)
    return resultado
