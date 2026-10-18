"""Assistente de impressora: o caminho curto para o cupom sair na Elgin i9 (ou outra térmica instalada no Windows).

Mostra o que está errado (diagnóstico), deixa escolher a impressora (a Elgin vem marcada), configura o caixa de uma vez e imprime
a página de teste. Se não sair, explica o que conferir e copia o diagnóstico para mandar ao suporte. Regras em
`controllers/impressao_assistente.py`."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from src.controllers import impressao_assistente as assistente
from src.hardware import impressoras_so
from src.ui import tema

COR_NIVEL = {"erro": tema.COR["perigo"], "aviso": tema.COR["aviso"], "ok": tema.COR["ok"]}
# Só caracteres comuns (nada de ✖ ✔ ▲): no Linux o Tk cai (segmentation fault) ao desenhar símbolos que a fonte de emojis
# do sistema também tem, e a queda aparece só no teste seguinte. A cor da linha já diz o nível.
SIMBOLO = {"erro": "ERRO:", "aviso": "ATENÇÃO:", "ok": "OK:"}


class JanelaAssistenteImpressora(tk.Toplevel):
    def __init__(self, master, ctx, ao_configurar=None):
        super().__init__(master)
        self.ctx = ctx
        self.ao_configurar = ao_configurar          # avisa a janela de Máquinas (aberta por trás) para recarregar os campos
        self.impressoras: list[impressoras_so.ImpressoraWindows] = []
        self._id_after = None
        self.title("Assistente de impressora")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("900x640")
        self.minsize(640, 480)
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        barra = ttk.Frame(corpo)
        barra.pack(side="bottom", fill="x", pady=(10, 0))
        intro = ttk.Label(corpo, text="Elgin i9 não imprime? Siga em ordem: 1) deixe a impressora ligada, com papel e o cabo USB conectado;  "
                                      "2) se ela NÃO aparece na lista abaixo, toque em 'Instalar Elgin i9 (driver genérico)';  "
                                      "3) escolha-a na lista e toque em 'Configurar e imprimir teste'.", wraplength=820, font=tema.FONTE_B)
        intro.pack(side="top", fill="x", anchor="w")
        self._textos_que_quebram = [intro]
        corpo.bind("<Configure>", lambda e: self._ajustar_quebra(e.width))
        self.quadro_achados = ttk.LabelFrame(corpo, text="O que o assistente encontrou", padding=8)
        self.quadro_achados.pack(side="top", fill="x", pady=(8, 8))
        self.grade = tema.Grade(corpo, [("nome", "Impressora do Windows", 260, "w"), ("detalhe", "Porta e driver", 330, "w"),
                                        ("situacao", "Situação", 190, "w"), ("fila", "Na fila", 70, "e")], altura=8)
        self.grade.pack(side="top", fill="both", expand=True)
        self.grade.tag("termica", foreground=tema.COR["ok"])
        self.grade.tag("virtual", foreground=tema.COR["virtual"])
        self.grade.tag("problema", foreground=tema.COR["perigo"])
        self.grade.tree.bind("<Double-1>", lambda e: self.configurar_e_testar())
        linha1, linha2 = ttk.Frame(barra), ttk.Frame(barra)
        linha1.pack(fill="x")
        linha2.pack(fill="x", pady=(6, 0))
        ttk.Button(linha1, text="Configurar e imprimir teste", style="Ok.TButton", command=self.configurar_e_testar).pack(side="left")
        ttk.Button(linha1, text="Instalar Elgin i9 (driver genérico)", command=self.instalar).pack(side="left", padx=6)
        ttk.Button(linha1, text="Impressoras do Windows", command=self.abrir_windows).pack(side="left")
        ttk.Button(linha2, text="Destravar fila do Windows", command=self.destravar).pack(side="left")
        ttk.Button(linha2, text="Atualizar (F5)", command=self.atualizar).pack(side="left", padx=6)
        ttk.Button(linha2, text="Copiar diagnóstico", command=self.copiar).pack(side="left")
        ttk.Button(linha2, text="Fechar (Esc)", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F5>", lambda e: self.atualizar())
        self.atualizar()
        # transient ANTES de centralizar: centralizar força o mapeamento da janela, e mapeá-la antes de ligá-la a uma janela-mãe
        # escondida deixava o Tk instável (segmentation fault no teste seguinte, no Linux).
        self.transient(master.winfo_toplevel())
        tema.centralizar(self, master.winfo_toplevel())

    def _ajustar_quebra(self, largura: int) -> None:
        """Os textos quebram de linha na largura da janela (em tela pequena nada fica cortado no lado direito)."""
        for w in self._textos_que_quebram:
            try:
                w.configure(wraplength=max(largura - 40, 300))
            except tk.TclError:
                pass

    def _cancelar_agendamento(self) -> None:
        if self._id_after:
            try:
                self.after_cancel(self._id_after)
            except (tk.TclError, ValueError):
                pass
            self._id_after = None

    def destroy(self) -> None:
        self._cancelar_agendamento()
        super().destroy()

    # ------------------------------------------------------------------ dados
    def atualizar(self) -> None:
        self.impressoras = impressoras_so.listar_impressoras()
        atual = (self.ctx.config.maquina()["impressora_termica_endereco"] or "").strip().lower()
        linhas, ids, tags = [], [], []
        for n, i in enumerate(self.impressoras):
            marca = "virtual" if i.virtual else "termica" if i.termica_provavel else ""
            if (i.offline or i.pausada) and not i.virtual:
                marca = "problema"
            linhas.append([i.nome + ("  (padrão do Windows)" if i.padrao else ""), " · ".join(x for x in (i.porta, i.driver) if x),
                           i.situacao + (" · PAUSADA" if i.pausada else ""), str(i.trabalhos)])
            ids.append(str(n))
            tags.append((marca,) if marca else ())
        self.grade.preencher(linhas, ids, tags)
        escolhida = next((str(n) for n, i in enumerate(self.impressoras) if i.nome.strip().lower() == atual), None)
        if escolhida is None:
            sugerida = assistente.sugerir(self.impressoras)
            escolhida = str(self.impressoras.index(sugerida)) if sugerida else (ids[0] if ids else None)
        self.grade.selecionar(escolhida)
        self._mostrar_achados()

    def _mostrar_achados(self) -> None:
        for w in self.quadro_achados.winfo_children():
            w.destroy()
        self._textos_que_quebram = self._textos_que_quebram[:1]
        for a in assistente.diagnosticar(self.ctx.banco, self.impressoras):
            texto = f"{SIMBOLO[a.nivel]}  {a.texto}" + (f"\n      Como resolver: {a.solucao}" if a.solucao else "")
            rotulo = ttk.Label(self.quadro_achados, text=texto, foreground=COR_NIVEL[a.nivel], wraplength=820, justify="left")
            rotulo.pack(anchor="w", pady=1)
            self._textos_que_quebram.append(rotulo)
        self._ajustar_quebra(self.winfo_width() - 24)

    def _escolhida(self) -> impressoras_so.ImpressoraWindows | None:
        chave = self.grade.selecionado()
        if chave is None:
            tema.aviso(self, "Escolha uma impressora da lista.\nSe a Elgin i9 não aparece, instale o driver dela no Windows, ligue o cabo USB e toque em Atualizar.")
            return None
        return self.impressoras[int(chave)]

    # ------------------------------------------------------------------ ações
    def configurar_e_testar(self) -> None:
        imp = self._escolhida()
        if imp is None:
            return
        if imp.virtual and not tema.confirmar(self, f"'{imp.nome}' é virtual (PDF/fax) e não imprime cupom no papel.\nUsar mesmo assim?",
                                              "Impressora virtual", padrao_sim=False):
            return
        ok, _ = tema.tratar(self, assistente.configurar, self.ctx.banco, imp.nome)
        if not ok:
            return
        if self.ao_configurar:
            self.ao_configurar()
        enviado, _ = tema.tratar(self, self.ctx.impressao.imprimir_teste, self.ctx.impressao.impressora_de("spooler", imp.nome))
        self._cancelar_agendamento()
        self._id_after = self.after(2500, self._depois_do_teste)          # dá tempo de o Windows mostrar fila presa/offline
        if not enviado:
            self._mostrar_achados()
            return
        if tema.confirmar(self, f"Página de teste enviada para '{imp.nome}'.\n\nO papel saiu, com acentos e corte?",
                          "Teste de impressão", sim="Sim, saiu", nao="Não saiu"):
            tema.mensagem(self, "Pronto! O caixa já está imprimindo os cupons nessa impressora.", "Impressora configurada")
        else:
            tema.mensagem(self, "Vamos conferir, nesta ordem:\n\n"
                                "1. A impressora está LIGADA, com papel e a tampa fechada?\n"
                                "2. O cabo USB está bem encaixado? (teste outra porta USB do computador)\n"
                                "3. No Windows (Impressoras e scanners), a Elgin i9 não está como 'Offline' nem 'Pausada'?\n"
                                "4. O driver da Elgin i9 está instalado? Se o nome dela não aparece na lista, instale o driver do site da Elgin.\n\n"
                                "Se continuar sem imprimir, toque em 'Copiar diagnóstico' e mande para o suporte.", "Não saiu o papel?")

    def _depois_do_teste(self) -> None:
        self._id_after = None
        try:
            if self.winfo_exists():
                self.atualizar()
        except tk.TclError:
            pass

    def instalar(self) -> None:
        """Instala a Elgin i9 no Windows com o driver genérico (quando o do fabricante não está instalado)."""
        if not tema.confirmar(self, "Vou instalar a impressora 'Elgin i9' no Windows usando o driver genérico (Generic / Text Only) na porta USB "
                                    "dela.\n\nA Elgin i9 precisa estar LIGADA e com o cabo USB conectado. Se o Windows pedir permissão, aceite.\n\n"
                                    "Continuar?", "Instalar Elgin i9", sim="Instalar", nao="Cancelar"):
            return
        ok, nome = tema.tratar(self, assistente.instalar_generica, "Elgin i9")
        if ok:
            self.ctx.banco.log("impressora_instalada", nome)
            self.atualizar()
            tema.mensagem(self, f"'{nome}' instalada no Windows.\nAgora toque em 'Configurar e imprimir teste'.", "Impressora instalada")

    def abrir_windows(self) -> None:
        """Abre 'Impressoras e scanners' do Windows (para instalar o driver do fabricante ou ver a fila)."""
        try:
            os.startfile("ms-settings:printers")                 # type: ignore[attr-defined]
        except (AttributeError, OSError):
            tema.aviso(self, "Abra, no Windows: Iniciar > Configurações > Dispositivos > Impressoras e scanners.")

    def destravar(self) -> None:
        imp = self._escolhida()
        if imp is None:
            return
        limpar = tema.confirmar(self, f"Retomar a fila de '{imp.nome}' no Windows?\n\nEscolha 'Retomar e apagar' para também CANCELAR os "
                                      "documentos que estão presos lá (cupons antigos não saem mais).", "Destravar fila",
                                sim="Retomar e apagar", nao="Só retomar", padrao_sim=False)
        ok, msg = tema.tratar(self, assistente.destravar_fila, imp.nome, limpar)
        if ok:
            tema.mensagem(self, msg, "Fila do Windows")
            self.atualizar()

    def copiar(self) -> None:
        from src.versao import VERSAO
        texto = assistente.relatorio(self.ctx.banco, self.impressoras, versao=VERSAO)
        self.clipboard_clear()
        self.clipboard_append(texto)
        tema.mensagem(self, "Diagnóstico copiado. Cole (Ctrl+V) numa mensagem para o suporte.", "Copiado")
