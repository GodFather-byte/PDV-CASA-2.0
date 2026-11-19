"""Sinal do Qt não se liga direto a método de objeto comum (que não é QObject). O porquê está em `src/ui_qt/sinais.py`.

O defeito só aparece no executável (código compilado pelo Nuitka), onde nenhum teste de unidade roda. Por isso a
defesa aqui é ler o código: a varredura abaixo acha `sinal.connect(obj.metodo)`, `QPushButton(..., clicked=obj.metodo)`,
`QShortcut(tecla, pai, obj.metodo)` e `menu.addAction(texto, obj.metodo)` em que `obj` não é QObject.
"""
import ast
import ctypes
import gc
import importlib
import unittest
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from src.ui_qt import sinais

RAIZ = Path(__file__).resolve().parent.parent

# `outro.metodo` (não é `self.metodo`) cujo nome também existe em classe comum de `src/`: a varredura não sabe o tipo de
# `outro`, então cada caso conferido à mão entra aqui com o motivo. Vazio é o melhor estado.
CONFERIDOS: dict[tuple[str, str], str] = {}


def _pontuado(no) -> str | None:
    """`a.b.c` como texto; None se a expressão não é só nomes e pontos."""
    partes = []
    while isinstance(no, ast.Attribute):
        partes.append(no.attr)
        no = no.value
    if not isinstance(no, ast.Name):
        return None
    return ".".join([no.id, *reversed(partes)])


class Codigo:
    """Lê os módulos sem importar o PDV: classes, bases, métodos e de onde vem cada nome importado."""

    def __init__(self, fontes: dict[str, str]):
        self.arvores = {modulo: ast.parse(texto) for modulo, texto in fontes.items()}
        self.imports = {modulo: self._imports(modulo, arvore) for modulo, arvore in self.arvores.items()}
        self.classes = {(modulo, no.name): no for modulo, arvore in self.arvores.items()
                        for no in ast.walk(arvore) if isinstance(no, ast.ClassDef)}
        self._qobject: dict[tuple[str, str], bool] = {}
        self.de_objeto_comum = {metodo for (modulo, nome) in self.classes if not self.classe_qobject(modulo, nome)
                                for metodo in self.metodos(modulo, nome)}

    @classmethod
    def de_src(cls):
        fontes = {}
        for arquivo in sorted((RAIZ / "src").rglob("*.py")):
            partes = arquivo.relative_to(RAIZ).with_suffix("").parts
            fontes[".".join(partes[:-1] if partes[-1] == "__init__" else partes)] = arquivo.read_text(encoding="utf-8")
        return cls(fontes)

    @staticmethod
    def _imports(modulo: str, arvore) -> dict[str, str]:
        nomes = {}
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                for alias in no.names:
                    nomes[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
            elif isinstance(no, ast.ImportFrom):
                base = no.module or ""
                if no.level:                                    # import relativo: sobe a partir do pacote do módulo
                    pacote = modulo.split(".")[:-no.level]
                    base = ".".join([*pacote, base] if base else pacote)
                for alias in no.names:
                    nomes[alias.asname or alias.name] = f"{base}.{alias.name}"
        return nomes

    def _base_qobject(self, modulo: str, base, visitados) -> bool:
        caminho = _pontuado(base)
        if caminho is None:
            return False
        primeiro, _, resto = caminho.partition(".")
        if not resto and (modulo, primeiro) in self.classes:
            return self.classe_qobject(modulo, primeiro, visitados)
        origem = self.imports[modulo].get(primeiro)
        if origem is None:
            return False
        completo = f"{origem}.{resto}" if resto else origem
        if completo.startswith("PySide6."):
            objeto = self._do_pyside(completo)
            return isinstance(objeto, type) and issubclass(objeto, QObject)
        dono, _, nome = completo.rpartition(".")
        return (dono, nome) in self.classes and self.classe_qobject(dono, nome, visitados)

    @staticmethod
    def _do_pyside(caminho: str):
        partes = caminho.split(".")
        for corte in range(len(partes), 1, -1):
            try:
                objeto = importlib.import_module(".".join(partes[:corte]))
            except ImportError:
                continue
            for nome in partes[corte:]:
                objeto = getattr(objeto, nome, None)
            return objeto
        return None

    def classe_qobject(self, modulo: str, nome: str, visitados=()) -> bool:
        chave = (modulo, nome)
        if chave in visitados:
            return False
        if chave not in self._qobject:
            self._qobject[chave] = any(self._base_qobject(modulo, base, (*visitados, chave))
                                       for base in self.classes[chave].bases)
        return self._qobject[chave]

    def metodos(self, modulo: str, nome: str, visitados=()) -> set[str]:
        chave = (modulo, nome)
        if chave in visitados or chave not in self.classes:
            return set()
        classe = self.classes[chave]
        achados = {no.name for no in classe.body if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for base in classe.bases:
            caminho = _pontuado(base)
            if caminho is None:
                continue
            if (modulo, caminho) in self.classes:
                achados |= self.metodos(modulo, caminho, (*visitados, chave))
                continue
            dono, _, nome_base = self.imports[modulo].get(caminho.split(".")[0], "").rpartition(".")
            achados |= self.metodos(dono, nome_base, (*visitados, chave))
        return achados

    def violacoes(self) -> list[str]:
        achadas = []
        for modulo, arvore in self.arvores.items():
            visita = _Visita(self, modulo)
            visita.visit(arvore)
            achadas += visita.achadas
        return [f"{modulo}:{linha}: {trecho}" for modulo, linha, trecho in sorted(achadas)]


class _Visita(ast.NodeVisitor):
    def __init__(self, codigo: Codigo, modulo: str):
        self.codigo, self.modulo = codigo, modulo
        self.classes: list[str] = []
        self.locais: list[dict[str, list]] = [{}]       # por função: nome -> expressões que ele pode valer
        self.achadas: list[tuple[str, int, str]] = []

    # ------------------------------------------------------------ contexto
    def visit_ClassDef(self, no):
        self.classes.append(no.name)
        self.generic_visit(no)
        self.classes.pop()

    def visit_FunctionDef(self, no):
        self.locais.append({})
        self.generic_visit(no)
        self.locais.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, no):
        return                                          # dentro de lambda a chamada é feita na hora: nada é ligado

    def visit_Assign(self, no):
        if len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
            self.locais[-1].setdefault(no.targets[0].id, []).append(no.value)
        self.generic_visit(no)

    def visit_For(self, no):
        # for texto, acao in (("Salvar", self.salvar), ...): botao.clicked.connect(acao)
        nomes = [n.id for n in ast.walk(no.target) if isinstance(n, ast.Name)]
        valores = [n for n in self._sem_lambda(no.iter) if isinstance(n, (ast.Attribute, ast.Call))]
        for nome in nomes:
            self.locais[-1].setdefault(nome, []).extend(valores)
        self.generic_visit(no)

    @staticmethod
    def _sem_lambda(no):
        pilha = [no]
        while pilha:
            atual = pilha.pop()
            if isinstance(atual, ast.Lambda):
                continue
            yield atual
            if isinstance(atual, ast.Attribute):
                continue                                # `a.b.c` vale como um alvo só, não também `a.b`
            pilha.extend(ast.iter_child_nodes(atual))

    # ------------------------------------------------------------- ligações
    def visit_Call(self, no):
        for alvo in self._alvos(no):
            self._conferir(alvo, no.lineno)
        self.generic_visit(no)

    @staticmethod
    def _alvos(no: ast.Call) -> list:
        funcao = no.func
        nome = funcao.attr if isinstance(funcao, ast.Attribute) else getattr(funcao, "id", "")
        alvos = []
        if nome == "connect":
            alvos += no.args[:1]
        elif nome in ("QShortcut", "addAction", "QAction"):
            alvos += no.args[1:]
        if nome == "connect" or (nome[:1] == "Q" and nome[1:2].isupper()):
            alvos += [chave.value for chave in no.keywords if chave.arg]
        return alvos

    def _conferir(self, alvo, linha: int, vistos=()):
        if isinstance(alvo, ast.IfExp):
            self._conferir(alvo.body, linha, vistos)
            self._conferir(alvo.orelse, linha, vistos)
        elif isinstance(alvo, ast.Name) and alvo.id not in vistos:
            for valor in self.locais[-1].get(alvo.id, ()):
                self._conferir(valor, linha, (*vistos, alvo.id))
        elif isinstance(alvo, ast.Call):
            if getattr(alvo.func, "id", "") == "getattr" and alvo.args and getattr(alvo.args[0], "id", "") == "self" \
                    and self.classes and not self.codigo.classe_qobject(self.modulo, self.classes[-1]):
                self._anotar(alvo, linha)
        elif isinstance(alvo, ast.Attribute):
            de_self = isinstance(alvo.value, ast.Name) and alvo.value.id == "self" and self.classes
            if de_self:
                classe = self.classes[-1]
                if not self.codigo.classe_qobject(self.modulo, classe) \
                        and alvo.attr in self.codigo.metodos(self.modulo, classe):
                    self._anotar(alvo, linha)
            elif alvo.attr in self.codigo.de_objeto_comum \
                    and (self.modulo, ast.unparse(alvo)) not in CONFERIDOS:
                self._anotar(alvo, linha)

    def _anotar(self, alvo, linha: int):
        self.achadas.append((self.modulo, linha, ast.unparse(alvo)))


class TesteVarredura(unittest.TestCase):
    """A regra: o que se entrega ao Qt é método de QObject, lambda, função solta ou `sinais.ligar_metodo`."""

    def test_src_nao_liga_sinal_direto_a_metodo_de_objeto_comum(self):
        achadas = Codigo.de_src().violacoes()
        self.assertEqual(achadas, [], "Sinal do Qt ligado direto a método de objeto que não é QObject (no executável "
                                      "isso destrói a função: use src.ui_qt.sinais.ligar_metodo ou um lambda):\n"
                                      + "\n".join(achadas))

    def test_os_conferidos_a_mao_ainda_existem(self):
        codigo = Codigo.de_src()
        for (modulo, expressao), motivo in CONFERIDOS.items():
            self.assertTrue(motivo.strip(), f"{modulo}: {expressao} sem motivo")
            self.assertIn(expressao, ast.unparse(codigo.arvores[modulo]), f"{modulo} não tem mais {expressao}")

    BASE = ("from PySide6.QtCore import QObject\n"
            "from PySide6.QtGui import QKeySequence, QShortcut\n"
            "from PySide6.QtWidgets import QDialog, QMenu, QPushButton\n")

    def violacoes(self, corpo: str, outros: dict[str, str] | None = None) -> list[str]:
        return Codigo({"src.exemplo": self.BASE + corpo, **(outros or {})}).violacoes()

    def test_acha_metodo_da_propria_classe_comum(self):
        achadas = self.violacoes("class Servico:\n"
                                 "    def ligar(self, botao):\n"
                                 "        botao.clicked.connect(self.rodar)\n"
                                 "    def rodar(self):\n"
                                 "        pass\n")
        self.assertEqual(achadas, ["src.exemplo:6: self.rodar"])

    def test_acha_metodo_herdado_e_as_outras_formas_de_ligar(self):
        achadas = self.violacoes("class Base:\n"
                                 "    def rodar(self):\n"
                                 "        pass\n"
                                 "class Servico(Base):\n"
                                 "    def ligar(self, janela, menu, nome):\n"
                                 "        QPushButton('x', janela, clicked=self.rodar)\n"
                                 "        QShortcut(QKeySequence('F2'), janela, self.rodar)\n"
                                 "        menu.addAction('x', self.rodar)\n"
                                 "        janela.finished.connect(getattr(self, nome))\n")
        self.assertEqual([a.split(": ")[1] for a in achadas],
                         ["self.rodar", "self.rodar", "self.rodar", "getattr(self, nome)"])

    def test_acha_por_variavel_e_por_lista_de_botoes(self):
        achadas = self.violacoes("class Servico:\n"
                                 "    def ligar(self, janela):\n"
                                 "        acao = self.rodar\n"
                                 "        janela.finished.connect(acao)\n"
                                 "        for texto, comando in (('Rodar', self.rodar), ('Parar', lambda: self.parar())):\n"
                                 "            QPushButton(texto).clicked.connect(comando)\n"
                                 "    def rodar(self):\n"
                                 "        pass\n"
                                 "    def parar(self):\n"
                                 "        pass\n")
        self.assertEqual(achadas, ["src.exemplo:7: self.rodar", "src.exemplo:9: self.rodar"])

    def test_acha_metodo_de_outro_objeto_comum(self):
        achadas = self.violacoes("class Trava:\n"
                                 "    def liberar(self):\n"
                                 "        pass\n"
                                 "def main(aplicacao, trava):\n"
                                 "    aplicacao.aboutToQuit.connect(trava.liberar)\n")
        self.assertEqual(achadas, ["src.exemplo:8: trava.liberar"])

    def test_aceita_qobject_lambda_funcao_solta_e_ligar_metodo(self):
        achadas = self.violacoes(
            "import sqlite3\n"
            "from src.outro import JanelaBase\n"
            "from src.ui_qt import sinais\n"
            "class Janela(QDialog):\n"
            "    def __init__(self, dialogo):\n"
            "        super().__init__()\n"
            "        botao = QPushButton('x', clicked=self.salvar)\n"
            "        botao.clicked.connect(self.salvar)\n"
            "        botao.clicked.connect(self.reject)\n"
            "        botao.clicked.connect(dialogo.accept)\n"
            "        QShortcut(QKeySequence('F2'), self, self.salvar)\n"
            "        for texto, acao in (('Salvar', self.salvar),):\n"
            "            QPushButton(texto).clicked.connect(acao)\n"
            "    def salvar(self):\n"
            "        pass\n"
            "class Filha(JanelaBase):\n"
            "    def __init__(self):\n"
            "        self.botao.clicked.connect(self.salvar)\n"
            "    def salvar(self):\n"
            "        pass\n"
            "class Vigia(QObject):\n"
            "    def __init__(self, temporizador):\n"
            "        temporizador.timeout.connect(self.conferir)\n"
            "    def conferir(self):\n"
            "        pass\n"
            "class Servico:\n"
            "    def __init__(self, caminho, janela):\n"
            "        self.caminho = caminho\n"
            "        self.conexao = sqlite3.connect(self.caminho)\n"
            "        janela.finished.connect(lambda: self.rodar())\n"
            "        sinais.ligar_metodo(janela.finished, self, 'rodar')\n"
            "        def depois():\n"
            "            self.rodar()\n"
            "        janela.finished.connect(depois)\n"
            "    def rodar(self):\n"
            "        pass\n",
            {"src.outro": "from PySide6.QtWidgets import QWidget\nclass JanelaBase(QWidget):\n    pass\n"})
        self.assertEqual(achadas, [])


class _SinalFalso:
    def __init__(self):
        self.ligadas = []

    def connect(self, funcao):
        self.ligadas.append(funcao)

    def emitir(self, *argumentos):
        for funcao in list(self.ligadas):
            funcao(*argumentos)


class _Alvo:
    def __init__(self):
        self.chamadas = []

    def receber(self, *argumentos):
        self.chamadas.append(argumentos)

    @staticmethod
    def solta():
        return "solta"

    @classmethod
    def da_classe(cls):
        return cls


class TesteLigarMetodo(unittest.TestCase):
    def test_chama_o_metodo_com_os_argumentos_do_sinal(self):
        sinal, alvo = _SinalFalso(), _Alvo()
        ligada = sinais.ligar_metodo(sinal, alvo, "receber")
        sinal.emitir()
        sinal.emitir(3, "x")
        self.assertEqual(alvo.chamadas, [(), (3, "x")])
        self.assertEqual(sinal.ligadas, [ligada])
        self.assertEqual(type(ligada).__name__, "function", "tem de ser função solta, não método")

    def test_nao_segura_o_objeto_vivo_e_se_cala_depois_que_ele_morre(self):
        sinal, alvo = _SinalFalso(), _Alvo()
        sinais.ligar_metodo(sinal, alvo, "receber")
        del alvo
        gc.collect()
        sinal.emitir()                                  # não chama nada nem levanta erro

    def test_liga_e_desliga_em_sinal_do_qt_de_verdade(self):
        QApplication.instance() or QApplication([])
        temporizador, alvo = QTimer(), _Alvo()
        ligada = sinais.ligar_metodo(temporizador.timeout, alvo, "receber")
        temporizador.timeout.emit()
        self.assertEqual(alvo.chamadas, [()])
        temporizador.timeout.disconnect(ligada)
        temporizador.timeout.emit()
        self.assertEqual(alvo.chamadas, [()])
        temporizador.deleteLater()


class TesteContagemDasFuncoes(unittest.TestCase):
    """A conferência que o autoteste do executável faz. Aqui o defeito é imitado soltando a referência à mão."""

    def test_fotografa_as_funcoes_das_classes_do_modulo(self):
        rotulos = [item[0] for item in sinais.fotografar_funcoes(__name__)]
        for nome in ("receber", "solta", "da_classe"):
            self.assertIn(f"{__name__}._Alvo.{nome}", rotulos)
        self.assertNotIn(f"{__name__}.TesteVarredura.BASE", rotulos)

    def test_metodo_em_uso_nao_e_acusado(self):
        foto = sinais.fotografar_funcoes(__name__)
        alvo = _Alvo()
        guardados = [alvo.receber for _ in range(5)]    # quem segura o método soma referência, nunca tira
        self.assertEqual(sinais.funcoes_soltas(foto), [])
        del guardados, alvo
        gc.collect()
        self.assertEqual(sinais.funcoes_soltas(foto), [])

    def test_acusa_a_funcao_que_perdeu_referencia(self):
        foto = sinais.fotografar_funcoes(__name__)

        def mexer(operacao):                            # sem guardar a função em variável: ela entraria na contagem
            for _ in range(2):
                operacao(ctypes.py_object(_Alvo.__dict__["receber"]))

        mexer(ctypes.pythonapi.Py_DecRef)               # o que o PySide faz ao desfazer a ligação do método compilado
        try:
            self.assertEqual(sinais.funcoes_soltas(foto), [f"{__name__}._Alvo.receber (perdeu 2)"])
        finally:
            mexer(ctypes.pythonapi.Py_IncRef)
        self.assertEqual(sinais.funcoes_soltas(foto), [])

    def test_no_codigo_fonte_o_autoteste_nao_fotografa(self):
        from src.ui_qt.app import App, _fotografar_funcoes_do_executavel
        self.assertFalse(sinais.compilado(App.encerrar))
        self.assertEqual(_fotografar_funcoes_do_executavel(), [])


if __name__ == "__main__":
    unittest.main()
