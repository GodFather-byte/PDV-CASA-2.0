"""Pedido online no caixa (Will Adega): o botão "🛵 Pedidos online" acende quando chega pedido do cardápio.

A busca na nuvem roda a cada 30 s em segundo plano (o caixa nunca espera a rede). Pedido novo apita e aparece no botão.
Atender: escolher o pedido, ver os itens e Aceitar (vira a entrega do F6, já preenchida, com o preço do caixa) ou Recusar
com o motivo (o cliente vê no cardápio). Se a nuvem não responder ao aceitar, a entrega fica no caixa e a próxima busca
avisa a nuvem de novo (aceitar é idempotente nos dois lados).
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QPushButton

from src.controllers.pedido_online_controller import detalhe, marca, resumo
from src.sync import pedidos_online as rede

INTERVALO_MS = 30_000


class VigiaPedidosOnline(QObject):
    chegou = Signal(list, str)          # pedidos, erro (vazio = ok); emitido da thread da rede

    def __init__(self, ctx, botao: QPushButton, janela=None, intervalo_ms: int = INTERVALO_MS):
        super().__init__(botao)
        self.ctx = ctx
        self.botoes = [botao]
        self.ouvintes = [janela] if janela is not None else []
        self.pedidos: list[dict] = []
        self.vistos: set[int] = set()
        self.erro = ""
        self._buscando = False
        self.chegou.connect(self._receber)
        self.timer = QTimer(self)
        self.timer.setInterval(intervalo_ms)
        self.timer.timeout.connect(self.buscar)
        self._mostrar()
        if self.ligado():
            self.timer.start()
            QTimer.singleShot(1500, self.buscar)

    def registrar(self, botao: QPushButton, janela=None) -> None:
        """O menu principal e a janela do caixa dividem o mesmo vigia, para o apito não sair duas vezes."""
        if botao not in self.botoes:
            self.botoes.append(botao)
        if janela is not None and janela not in self.ouvintes:
            self.ouvintes.append(janela)
        self._mostrar()

    def ligado(self) -> bool:
        try:
            return rede.ligado(self.ctx.banco)
        except Exception:  # noqa: BLE001 - o botão some, o caixa segue
            return False

    def buscar(self, sincrono: bool = False, http=None) -> None:
        if not self.ligado():
            self.pedidos = []
            self._mostrar()
            return
        if self._buscando:
            return
        base, token = rede.acesso(self.ctx.banco)

        def trabalhar():
            try:
                self.chegou.emit(rede.consultar(base, token, http), "")
            except Exception as e:  # noqa: BLE001 - sem rede: tenta de novo na próxima volta
                self.chegou.emit([], str(e))

        self._buscando = True
        if sincrono:
            trabalhar()
        else:
            threading.Thread(target=trabalhar, name="pedidos-online", daemon=True).start()

    def _receber(self, pedidos: list, erro: str) -> None:
        self._buscando = False
        self.erro = erro
        if erro:
            self._mostrar()
            return
        pendentes = []
        for p in pedidos:
            if self.ctx.pedidos_online.ja_importado(p.get("numero"), p.get("id")):
                try:                                    # aceito no caixa, mas a nuvem não soube: avisa de novo
                    rede.aceitar(self.ctx.banco, p["id"])
                    continue
                except RuntimeError:
                    pass
            pendentes.append(p)
        novos = [p for p in pendentes if p["id"] not in self.vistos]
        self.vistos |= {p["id"] for p in pendentes}
        self.pedidos = pendentes
        try:
            rede.empurrar_avisos(self.ctx.banco)
        except Exception:  # noqa: BLE001 - o aviso ao cliente espera a próxima busca
            pass
        self._mostrar()
        if novos:
            QApplication.beep()
            texto = f"🛵 Pedido online novo: {resumo(novos[-1])}. Clique em Pedidos online."
            for janela in self.ouvintes:
                avisar = getattr(janela, "avisar", None)
                if callable(avisar):
                    avisar(texto)

    def _botoes_vivos(self) -> list:
        vivos = []
        for botao in self.botoes:
            try:
                botao.objectName()
            except RuntimeError:
                continue
            vivos.append(botao)
        self.botoes = vivos
        return vivos

    def _mostrar(self) -> None:
        ligado = self.ligado()
        botoes = self._botoes_vivos()
        if not botoes:
            return
        n = len(self.pedidos)
        texto = f"🛵 {n} pedido{'s' if n != 1 else ''} online" if n else "🛵 Pedidos online"
        for botao in botoes:
            botao.setVisible(ligado)
            if not ligado:
                continue
            botao.setText(texto)
            botao.setObjectName("rosa" if n else "neutro")
            botao.style().unpolish(botao)
            botao.style().polish(botao)
            botao.setToolTip(self.erro or "Pedidos feitos no cardápio pelo celular")

    def retirar(self, pedido_id: int) -> None:
        self.pedidos = [p for p in self.pedidos if p["id"] != pedido_id]
        self._mostrar()


def atender(janela, vigia: VigiaPedidosOnline) -> None:
    """Botão do caixa: escolhe o pedido e aceita (vira entrega) ou recusa (com o motivo)."""
    dialogos = janela.dialogos
    if not vigia.pedidos:
        vigia.buscar(sincrono=True)
    if not vigia.pedidos:
        dialogos.aviso("Pedidos online", vigia.erro or "Nenhum pedido novo agora.")
        return
    pid = dialogos.escolher("Pedidos online", "Escolha o pedido:", [(p["id"], resumo(p)) for p in vigia.pedidos])
    pedido = next((p for p in vigia.pedidos if p["id"] == pid), None)
    if pedido is None:
        return
    acao = dialogos.escolher(f"Pedido online #{pedido['numero']}", detalhe(pedido) + "\n\nO que fazer?", [
        ("aceitar", f"Aceitar: lançar na mesa {pedido['mesa']}" if pedido.get("mesa") else "Aceitar: vira entrega no caixa"), ("recusar", "Recusar e avisar o cliente")])
    if acao == "aceitar":
        atual = janela.ctx.caixa.obter(janela.venda_id) if janela.venda_id else None
        if (not pedido.get("mesa") or (atual and atual["modalidade"] == "balcao")) and not janela._exigir_venda_vazia():
            return
        ok, r = janela._executar(janela.ctx.pedidos_online.importar, pedido)
        if not ok:
            return
        try:
            rede.aceitar(janela.ctx.banco, pedido["id"])
            janela.ctx.banco.executar(
                "UPDATE pedidos_mesa_importados SET aviso_ok = 1 WHERE pedido_id = ? AND aviso = 'aceito'",
                (pedido["id"],))
            janela.ctx.banco.executar(
                "UPDATE vendas SET pedido_online_aviso_ok = 1 WHERE id = ? AND pedido_online_aviso = 'aceito'",
                (r["venda_id"],))
        except RuntimeError as e:
            dialogos.aviso("Pedido online", f"{e}\nO pedido já está no caixa; o cliente fica sabendo na próxima busca.")
        vigia.retirar(pedido["id"])
        janela.venda_id = r["venda_id"]
        janela.recarregar()
        if pedido.get("mesa"):
            if r.get("item_ids"):
                janela._enviar_remoto(r["item_ids"])
            janela.avisar(f"{marca(pedido['numero'])} lançado na mesa {pedido['mesa']}.")
            return
        emitido, _ = janela._executar(janela.ctx.entregas.emitir_pedido, r["venda_id"])
        if emitido:
            janela._documento_operacao(
                "Pedido de entrega", lambda: janela.ctx.impressao.pedido_entrega(r["venda_id"]),
                f"entrega_{r['venda_id']}", "entrega")
            janela.venda_id = None
            janela._limpar_entrada()
            janela.recarregar()
        janela.avisar(f"{marca(pedido['numero'])} aceito. O pedido de entrega "
                      f"{'foi impresso' if emitido else 'está na tela: emita com F8'}.")
    elif acao == "recusar":
        motivo = dialogos.pedir_texto("Recusar pedido", "Motivo (o cliente vê no cardápio):", padrao="Produto em falta")
        if not (motivo or "").strip():
            return
        try:
            rede.recusar(janela.ctx.banco, pedido["id"], motivo.strip())
        except RuntimeError as e:
            dialogos.erro("Pedido online", str(e))
            return
        vigia.retirar(pedido["id"])
        janela.avisar(f"{marca(pedido['numero'])} recusado.")
