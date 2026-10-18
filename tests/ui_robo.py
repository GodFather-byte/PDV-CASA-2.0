"""Robo de teste de interface: reage a janelas modais enquanto o codigo principal espera nelas.

Qualquer janela que fique aberta por mais de `paciencia` segundos sem regra e fechada e registrada
como TRAVADO, para o teste falhar em vez de ficar pendurado."""
import time
import tkinter as tk


def todas(raiz):
    saida = []
    def varre(w):
        for f in w.winfo_children():
            if isinstance(f, tk.Toplevel):
                saida.append(f)
            varre(f)
    varre(raiz)
    return saida


def botoes(w):
    from tkinter import ttk
    achados = []
    for f in w.winfo_children():
        if isinstance(f, ttk.Button):
            achados.append(f)
        achados += botoes(f)
    return achados


def clicar(w, prefixo):
    """Aciona o botao cujo texto comeca com `prefixo` (ex.: 'Sim', 'OK', 'Gravar')."""
    for b in botoes(w):
        if str(b.cget("text")).startswith(prefixo):
            b.invoke()
            return True
    raise AssertionError(f"botao {prefixo!r} nao encontrado em {w.title()!r}: {[str(b.cget('text')) for b in botoes(w)]}")


def entradas(w):
    from tkinter import ttk
    achados = []
    for f in w.winfo_children():
        if isinstance(f, ttk.Entry):
            achados.append(f)
        achados += entradas(f)
    return achados


class Robo:
    def __init__(self, raiz, paciencia=4.0):
        self.raiz, self.regras, self.log = raiz, [], []
        self.paciencia, self.vistas = paciencia, {}
        self._id = self.raiz.after(40, self._tick)

    def parar(self):
        try:
            self.raiz.after_cancel(self._id)
        except Exception:
            pass

    def quando(self, classe, acao, vezes=1):
        self.regras.append([classe, acao, vezes])

    def _tick(self):
        try:
            for w in todas(self.raiz):
                tratada = False
                for r in self.regras:
                    if r[2] > 0 and type(w).__name__ == r[0] and w.winfo_exists():
                        r[2] -= 1
                        self.log.append(r[0])
                        r[1](w)
                        tratada = True
                        break
                if not tratada and w.winfo_exists() and type(w).__name__ in ("Dialogo", "Visualizador"):
                    desde = self.vistas.setdefault(str(w), time.time())
                    if time.time() - desde > self.paciencia:
                        self.log.append(f"TRAVADO: {type(w).__name__} {w.title()!r}")
                        w.destroy()
        except tk.TclError as e:
            self.log.append(f"TclError: {e}")
        self._id = self.raiz.after(40, self._tick)
