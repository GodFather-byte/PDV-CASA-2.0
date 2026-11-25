"""Produto novo no leitor: uma tela só com o nome, a categoria, o preço de venda, o gelado, o preço de custo e a
quantidade em estoque. O nome já vem da internet, quando achado."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout)

from src.core import formatacao as fmt

FONTES = {"internet": "Nome achado na internet. Confira.",
          "": "Nome não achado na internet: digite o nome."}


class DialogoProdutoNovo(QDialog):
    """`ler_dinheiro` vem do caixa (mesmas proteções do pagamento). `categorias` = [(id, rótulo, nome do subgrupo)]."""

    def __init__(self, pai, cbarra: str, sugestao: dict, categorias: list[tuple], ler_dinheiro,
                 com_gelada: bool = True, com_custo: bool = True, categoria_padrao: int | None = None):
        super().__init__(pai)
        self.ler_dinheiro = ler_dinheiro
        self.resultado: dict | None = None
        self.setWindowTitle("Produto novo")
        self.setMinimumWidth(480)
        geral = QVBoxLayout(self)
        titulo = QLabel(f"Código de barras {cbarra}")
        titulo.setObjectName("subtitulo")
        geral.addWidget(titulo)
        self.lbl_fonte = QLabel(FONTES.get(sugestao.get("fonte", ""), FONTES[""]))
        self.lbl_fonte.setWordWrap(True)
        geral.addWidget(self.lbl_fonte)
        form = QFormLayout()
        self.ent_nome = QLineEdit(sugestao.get("nome") or "")
        self.ent_nome.setMaxLength(120)
        form.addRow("Nome:", self.ent_nome)
        self.cmb_categoria = QComboBox()
        escolher = None
        sugerida = (sugestao.get("categoria") or "").strip().upper()
        for i, (ident, rotulo, nome) in enumerate(categorias):
            self.cmb_categoria.addItem(rotulo, ident)
            if sugerida and (nome or "").strip().upper() == sugerida:
                escolher = i
            elif escolher is None and ident == categoria_padrao:
                escolher = i
        if escolher is not None:
            self.cmb_categoria.setCurrentIndex(escolher)
        form.addRow("Categoria:", self.cmb_categoria)
        self.ent_preco = self._valor("Preço de venda")
        form.addRow("Preço de venda (R$):", self.ent_preco)
        self.ent_gelada = self._valor("vazio = só natural") if com_gelada else None
        if self.ent_gelada is not None:
            form.addRow("Preço gelada (R$):", self.ent_gelada)
        self.ent_custo = self._valor("quanto você pagou (opcional)") if com_custo else None
        if self.ent_custo is not None:
            form.addRow("Preço de custo (R$):", self.ent_custo)
        self.ent_qtd = QLineEdit()
        self.ent_qtd.setPlaceholderText("vazio = não controla estoque")
        self.ent_qtd.setAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Quantidade em estoque:", self.ent_qtd)
        geral.addLayout(form)
        self.lbl_erro = QLabel("")
        self.lbl_erro.setObjectName("erro")
        self.lbl_erro.setWordWrap(True)
        geral.addWidget(self.lbl_erro)
        botoes = QDialogButtonBox()
        self.btn_ok = botoes.addButton("Cadastrar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_ok.setObjectName("primario")
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.confirmar)
        botoes.rejected.connect(self.reject)
        geral.addWidget(botoes)
        campos = [self.ent_nome, self.ent_preco, self.ent_gelada, self.ent_custo, self.ent_qtd]
        campos = [c for c in campos if c is not None]
        for atual, proximo in zip(campos, campos[1:]):         # Enter passa para o próximo campo; no último, cadastra
            atual.returnPressed.connect(proximo.setFocus)
        campos[-1].returnPressed.connect(self.confirmar)
        (self.ent_preco if self.ent_nome.text() else self.ent_nome).setFocus()

    @staticmethod
    def _valor(dica: str) -> QLineEdit:
        campo = QLineEdit()
        campo.setPlaceholderText(dica)
        campo.setAlignment(Qt.AlignmentFlag.AlignRight)
        return campo

    def _dinheiro(self, campo: QLineEdit | None, rotulo: str, obrigatorio: bool = False) -> int:
        if campo is None or (not campo.text().strip() and not obrigatorio):
            return 0
        try:
            return self.ler_dinheiro(campo.text(), permitir_zero=not obrigatorio)
        except ValueError as erro:
            campo.setFocus()
            campo.selectAll()
            raise ValueError(f"{rotulo}: {erro}") from None

    def confirmar(self) -> None:
        try:
            nome = self.ent_nome.text().strip()
            if not nome:
                self.ent_nome.setFocus()
                raise ValueError("Digite o nome do produto.")
            preco = self._dinheiro(self.ent_preco, "Preço de venda", obrigatorio=True)
            gelada = self._dinheiro(self.ent_gelada, "Preço gelada")
            custo = self._dinheiro(self.ent_custo, "Preço de custo")
            qtd = None
            if self.ent_qtd.text().strip():
                try:
                    qtd = fmt.para_qtd(self.ent_qtd.text())
                except ValueError as erro:
                    self.ent_qtd.setFocus()
                    raise ValueError(f"Quantidade: {erro}") from None
        except ValueError as erro:
            self.lbl_erro.setText(str(erro))
            return
        aviso = custo and custo >= preco
        if aviso and self.lbl_erro.text() != AVISO_CUSTO:
            self.lbl_erro.setText(AVISO_CUSTO)                 # avisa uma vez; o segundo Cadastrar confirma
            return
        self.resultado = {"nome": nome, "subgrupo_id": self.cmb_categoria.currentData(), "preco_cent": preco,
                          "preco_gelada_cent": gelada, "custo_cent": custo, "estoque": qtd}
        self.accept()


AVISO_CUSTO = "O custo ficou igual ou maior que o preço de venda. Confira; para cadastrar assim, clique em Cadastrar de novo."
