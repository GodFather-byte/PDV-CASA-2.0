"""Fotografa todas as telas do PDV (Qt) com dados de exemplo, para revisão visual.

    QT_QPA_PLATFORM=offscreen python -m tools.capturar_telas [pasta] [--largura 1366 --altura 768] [--claro] [--conferir]

Com `--conferir`, além das fotos lista o que ficou cortado em cada tela (texto maior que o botão, campo para fora da
janela, cabeçalho de tabela cortado, rolagem de lado): ver `tools/conferir_telas.py`. Para um monitor de 1024x768 com a
barra de tarefas, use `--largura 1024 --altura 728`.

Abre o programa num banco em memória (nada é gravado no PC), cadastra alguns produtos, abre o turno, lança uma venda
e então abre cada tela do menu (os métodos `abrir_*` da janela principal) e cada cadastro, salvando um PNG por tela.
Diálogos modais (`exec`) são fotografados e fechados na hora, sem esperar ninguém clicar.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import tempfile  # noqa: E402



def _argumento(nome: str, padrao: int) -> int:
    """O monitor fictício precisa existir antes do Qt: lê --largura e --altura direto da linha de comando."""
    try:
        return int(sys.argv[sys.argv.index(nome) + 1])
    except (ValueError, IndexError):
        return padrao


_LARGURA, _ALTURA = _argumento("--largura", 1366), _argumento("--altura", 768)
_TELA = Path(tempfile.gettempdir()) / f"willpdv_tela_{_LARGURA}x{_ALTURA}.json"
_TELA.write_text('{"screens":[{"name":"tela","x":0,"y":0,"width":%d,"height":%d,"logicalDpi":96,'
                 '"logicalBaseDpi":96,"dpr":1}]}' % (_LARGURA, _ALTURA), encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_TELA}")   # monitor fictício do tamanho pedido

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget  # noqa: E402

PRODUTOS = (("1", "CERVEJA LATA 350ML", 750), ("2", "REFRIGERANTE LATA", 600), ("3", "AGUA MINERAL 500ML", 300),
            ("4", "DOSE WHISKY RED LABEL", 1800), ("5", "PORCAO DE FRITAS", 3200))
# Telas que abrem navegador, serviço de rede ou o próprio caixa já fotografado à parte.
PULAR = {"abrir_caixa", "abrir_whatsapp", "abrir_cadastro", "abrir_backup", "abrir_restaurar_backup"}


class Fotografo:
    def __init__(self, pasta: Path, largura: int, altura: int, conferir: bool = False):
        self.pasta, self.largura, self.altura = pasta, largura, altura
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.feitas: list[str] = []
        self.atual = "tela"
        self.conferir = conferir
        self.cortadas: dict[str, list[str]] = {}       # tela (e aba) -> o que ficou cortado

    def foto(self, janela: QWidget, nome: str | None = None, cheia: bool = False) -> None:
        """`cheia`: a janela ocupa a tela toda (principal e caixa). As outras abrem como no PDV: o tamanho do código
        passa pelo mesmo ajuste da primeira exibição (tema.ajustar_na_primeira_exibicao)."""
        from src.ui_qt import tema
        app = QApplication.instance()
        if cheia:
            janela.resize(self.largura, self.altura)
        janela.show()
        tema.ajustar_na_primeira_exibicao(janela)
        for _ in range(3):
            app.processEvents()
        nome = nome or self.atual
        arquivo = self.pasta / f"{len(self.feitas) + 1:02d}-{nome}.png"
        janela.grab().save(str(arquivo))
        self.feitas.append(arquivo.name)
        if self.conferir:
            from tools import conferir_telas
            self.cortadas.update(conferir_telas.por_estado(janela, nome))


def preparar(app_pdv) -> None:
    from src.controllers.cadastro_controller import CadastroController
    b = app_pdv.banco
    for chave, valor in (("imprimir_cupom", "N"), ("imprimir_fechamento_ao_trocar", "N"), ("caixa_tela_cheia", "N")):
        b.cfg_set(chave, valor)
    cad = CadastroController(b)
    subgrupo = b.valor("SELECT id FROM subgrupos ORDER BY id LIMIT 1")
    unidade = b.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'") or b.valor("SELECT id FROM unidades LIMIT 1")
    for codigo, nome, preco in PRODUTOS:
        cad.salvar("produtos", {"codigo": codigo, "nome": nome, "subgrupo_id": subgrupo, "unidade_id": unidade,
                                "preco_cent": preco, "controla_estoque": "N"})
    app_pdv.ctx.turnos.abrir(app_pdv.ctx.operador_id, 1, 15000)


def executar(pasta: Path, largura: int, altura: int, aparencia: str, conferir: bool = False) -> list[str]:
    """Devolve os arquivos gravados. Com `conferir`, `executar.cortadas` fica com {tela: [o que ficou cortado]}."""
    from src.database.conexao import BancoDados
    from src.ui_qt import tema
    from src.ui_qt.app import App, JanelaPrincipal

    aplicacao = QApplication.instance() or QApplication(sys.argv[:1])
    foto = Fotografo(pasta, largura, altura, conferir)
    executar.cortadas = foto.cortadas

    def exec_fotografado(self, *_args):
        foto.foto(self, f"{foto.atual}-dialogo-{type(self).__name__}")
        self.reject() if isinstance(self, QDialog) else self.close()
        return 0

    QDialog.exec = exec_fotografado
    QMessageBox.exec = exec_fotografado

    from PySide6.QtCore import QTimer

    def fechar_modal():                    # QMessageBox.question & cia. (estáticos) não passam pelo exec do Python
        modal = QApplication.activeModalWidget()
        if modal is not None:
            foto.foto(modal, f"{foto.atual}-modal-{type(modal).__name__}")
            modal.reject() if isinstance(modal, QDialog) else modal.close()

    vigia = QTimer()
    vigia.timeout.connect(fechar_modal)
    vigia.start(200)

    banco = BancoDados(":memory:")
    app_pdv = App(banco, aplicacao)
    tema.aplicar(aplicacao, aparencia)
    app_pdv.ctx.operador = app_pdv.ctx.acesso.autenticar("ADM", "ADM")
    preparar(app_pdv)
    principal = JanelaPrincipal(app_pdv)
    app_pdv.principal = principal
    foto.atual = "principal"
    foto.foto(principal, cheia=True)

    foto.atual = "caixa"
    caixa = principal.abrir_caixa()
    foto.foto(caixa, "caixa-vazio", cheia=True)
    for codigo, qtd in (("1", "2"), ("4", "1"), ("5", "1")):
        caixa.ent_codigo.setText(codigo)
        caixa.ent_qtd.setText(qtd)
        caixa.btn_lancar.click()
    foto.foto(caixa, "caixa-com-itens", cheia=True)
    caixa.close()

    for nome in sorted(n for n in dir(principal) if n.startswith("abrir_") and n not in PULAR):
        foto.atual = nome[len("abrir_"):]
        print("abrindo", nome, flush=True)
        antes = set(QApplication.topLevelWidgets())
        try:
            janela = getattr(principal, nome)()
        except Exception as erro:            # tela que precisa de algo que o banco de exemplo não tem
            print(f"PULEI {nome}: {type(erro).__name__}: {erro}")
            continue
        novas = [w for w in QApplication.topLevelWidgets() if w not in antes and w.isVisible()]
        for w in ([janela] if isinstance(janela, QWidget) else []) + [n for n in novas if n is not janela]:
            foto.foto(w)
            w.close()

    from src.ui_qt.cadastros import FormularioCadastro
    for chave, _rotulo in (("produtos", ""), ("operadores", ""), *JanelaPrincipal.CADASTROS_QT):
        foto.atual = f"cadastro-{chave}"
        janela = principal.abrir_cadastro(chave)
        if janela is not None:
            foto.foto(janela)
            janela.close()
            foto.atual = f"formulario-{chave}"         # o formulário de "Novo": é onde há mais campo para cortar
            formulario = FormularioCadastro(app_pdv.ctx, chave, None, principal)
            foto.foto(formulario)
            formulario.close()
    return foto.feitas


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("pasta", nargs="?", default="build/telas")
    p.add_argument("--largura", type=int, default=1366)
    p.add_argument("--altura", type=int, default=768)
    p.add_argument("--claro", action="store_true")
    p.add_argument("--conferir", action="store_true", help="lista o que ficou cortado em cada tela")
    a = p.parse_args()
    feitas = executar(Path(a.pasta), a.largura, a.altura, "claro" if a.claro else "escuro", a.conferir)
    print(f"{len(feitas)} telas em {a.pasta}")
    if a.conferir:
        for tela, achados in executar.cortadas.items():
            print(f"\n{tela}")
            for achado in achados:
                print(f"  - {achado}")
        print(f"\n{len(executar.cortadas)} tela(s) com algo cortado em {a.largura}x{a.altura}")


if __name__ == "__main__":
    main()
