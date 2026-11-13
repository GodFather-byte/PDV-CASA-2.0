"""Vídeos de tutorial gerados com as telas de verdade do PDV (só legenda + música de fundo).

    python -m tools.videos_tutoriais produto operador --saida videos/

O programa abre num banco de demonstração (pasta temporária), executa o cadastro passo a passo, fotografa as telas e
monta o MP4 (1280x720, 30 fps) com destaque no campo da vez, cursor, legendas grandes e uma música de fundo gerada
aqui mesmo (sem direitos autorais). Quando a tela muda numa versão nova, basta gerar de novo.
Precisa de PySide6, Pillow, numpy e ffmpeg.
"""
from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
LARGURA, ALTURA, FPS = 1280, 720, 30
FAIXA = 118                      # altura da faixa da legenda
DESTAQUE = (245, 197, 24)        # amarelo do destaque
VERDE = (61, 220, 151)
FONTES = Path("/usr/share/fonts/opentype/inter")


def fonte(peso: str, tamanho: int) -> ImageFont.FreeTypeFont:
    for caminho in (FONTES / f"Inter-{peso}.otf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if caminho.exists():
            return ImageFont.truetype(str(caminho), tamanho)
    return ImageFont.load_default()


# ------------------------------------------------------------------ desenho
def quebrar(texto: str, fnt, largura: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = (atual + " " + palavra).strip()
        if fnt.getlength(teste) <= largura:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    return linhas + ([atual] if atual else [])


def legenda(img: Image.Image, texto: str, passo: str = "") -> None:
    base = img.convert("RGBA")
    camada = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    d.rectangle((0, ALTURA - FAIXA, LARGURA, ALTURA), fill=(8, 12, 20, 238))
    d.rectangle((0, ALTURA - FAIXA, LARGURA, ALTURA - FAIXA + 4), fill=VERDE + (255,))
    fnt = fonte("SemiBold", 34)
    linhas = quebrar(texto, fnt, LARGURA - 120)[:2]
    alto = 44 * len(linhas)
    y = ALTURA - FAIXA + (FAIXA - alto) // 2 + 4
    if passo:
        d.text((24, ALTURA - FAIXA + 10), passo, font=fonte("Bold", 17), fill=VERDE + (255,))
    for linha in linhas:
        d.text(((LARGURA - fnt.getlength(linha)) / 2, y), linha, font=fnt, fill=(255, 255, 255, 255))
        y += 44
    img.paste(Image.alpha_composite(base, camada).convert("RGB"))


def destacar(img: Image.Image, caixa, escurecer: bool = True) -> None:
    x0, y0, x1, y1 = caixa
    x0, y0, x1, y1 = x0 - 6, y0 - 6, x1 + 6, y1 + 6
    base = img.convert("RGBA")
    if escurecer:
        sombra = Image.new("RGBA", base.size, (0, 0, 0, 120))
        ImageDraw.Draw(sombra).rounded_rectangle((x0, y0, x1, y1), 10, fill=(0, 0, 0, 0))
        base = Image.alpha_composite(base, sombra)
    brilho = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(brilho).rounded_rectangle((x0, y0, x1, y1), 10, outline=DESTAQUE + (170,), width=12)
    base = Image.alpha_composite(base, brilho.filter(ImageFilter.GaussianBlur(6)))
    ImageDraw.Draw(base).rounded_rectangle((x0, y0, x1, y1), 10, outline=DESTAQUE + (255,), width=4)
    img.paste(base.convert("RGB"))


def cursor(img: Image.Image, x: int, y: int, clique: bool = False) -> None:
    d = ImageDraw.Draw(img)
    if clique:
        for r, a in ((26, 2), (16, 3)):
            d.ellipse((x - r, y - r, x + r, y + r), outline=DESTAQUE, width=a)
    seta = [(0, 0), (0, 28), (7, 21), (12, 33), (17, 31), (12, 19), (21, 19)]
    d.polygon([(x + px, y + py) for px, py in seta], fill=(255, 255, 255), outline=(10, 10, 10))


def cartao(titulo: str, subtitulo: str) -> Image.Image:
    img = Image.new("RGB", (LARGURA, ALTURA), (14, 20, 32))
    d = ImageDraw.Draw(img)
    for i in range(ALTURA):                                  # degradê suave
        t = i / ALTURA
        d.line((0, i, LARGURA, i), fill=(int(14 + 6 * t), int(20 + 30 * t), int(32 + 14 * t)))
    logo = RAIZ / "instalador" / "willpdv-logo.png"
    if logo.exists():
        marca = Image.open(logo).convert("RGBA").resize((150, 150))
        img.paste(marca, ((LARGURA - 150) // 2, 150), marca)
    f1, f2 = fonte("Bold", 54), fonte("Medium", 28)
    for texto, fnt, y, cor in ((titulo, f1, 340, (255, 255, 255)), (subtitulo, f2, 420, VERDE)):
        for linha in quebrar(texto, fnt, LARGURA - 160):
            d.text(((LARGURA - fnt.getlength(linha)) / 2, y), linha, font=fnt, fill=cor)
            y += 64
    return img


# ------------------------------------------------------------------ captura das telas reais
class Estudio:
    def __init__(self, pasta: Path, edicao: str = "willpdv"):
        os.environ["PDV_EDICAO"] = edicao
        sys.path.insert(0, str(RAIZ))
        from PySide6.QtWidgets import QApplication
        self.qapp = QApplication.instance() or QApplication([])
        from src.database.conexao import BancoDados
        from src.ui_qt import tema
        from src.ui_qt.app import App, JanelaPrincipal
        from src.core import edicao as ed
        self.dados = Path(tempfile.mkdtemp())
        self.banco = BancoDados(str(self.dados / "demo.db"))
        ed.preparar(self.banco)
        self.app = App(self.banco, self.qapp)
        tema.aplicar(self.qapp, "escuro")
        self.app.ctx.operador = self.app.ctx.acesso.autenticar("ADM", "ADM")
        self.ctx = self.app.ctx
        self.principal = JanelaPrincipal(self.app)
        self.principal._fechamento_autorizado = True
        self.principal.resize(LARGURA, ALTURA)
        self.principal.show()
        self.pasta = pasta
        self.quadros: list[tuple[Path, float]] = []
        self.passo_atual, self.total = 0, 0
        self.atualizar()

    def atualizar(self):
        for _ in range(3):
            self.qapp.processEvents()

    # -- composição de uma foto
    def foto(self, janela, formulario=None) -> tuple[Image.Image, tuple[int, int]]:
        self.atualizar()
        self.escala = 1.0
        fundo = self._para_pil(janela.grab()).resize((LARGURA, ALTURA))
        if formulario is None:
            return fundo, (0, 0)
        escuro = Image.blend(fundo, Image.new("RGB", fundo.size, (0, 0, 0)), 0.55)
        form = self._para_pil(formulario.grab())
        cabe = ALTURA - FAIXA - 16                      # janela alta demais (resumo do fechamento): reduz para caber
        self.escala = min(1.0, cabe / form.height, (LARGURA - 16) / form.width)
        if self.escala < 1:
            form = form.resize((int(form.width * self.escala), int(form.height * self.escala)), Image.LANCZOS)
        x, y = (LARGURA - form.width) // 2, max(8, (ALTURA - FAIXA - form.height) // 2)
        sombra = Image.new("RGBA", (form.width + 40, form.height + 40), (0, 0, 0, 0))
        ImageDraw.Draw(sombra).rectangle((20, 20, form.width + 20, form.height + 20), fill=(0, 0, 0, 160))
        escuro.paste(sombra.filter(ImageFilter.GaussianBlur(12)), (x - 20, y - 14), sombra.filter(ImageFilter.GaussianBlur(12)))
        escuro.paste(form, (x, y))
        ImageDraw.Draw(escuro).rectangle((x - 1, y - 1, x + form.width, y + form.height), outline=(70, 90, 120), width=1)
        return escuro, (x, y)

    @staticmethod
    def _para_pil(pixmap) -> Image.Image:
        from PySide6.QtCore import QBuffer, QIODevice
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buf, "PNG")
        from io import BytesIO
        return Image.open(BytesIO(bytes(buf.data()))).convert("RGB")

    def caixa(self, widget, referencia, deslocamento=(0, 0)):
        """Retângulo do widget na foto (com a redução, se o formulário foi encolhido para caber)."""
        p = widget.mapTo(referencia, widget.rect().topLeft())
        dx, dy = deslocamento
        e = getattr(self, "escala", 1.0)          # vale para a última foto tirada
        return (int(p.x() * e) + dx, int(p.y() * e) + dy, int((p.x() + widget.width()) * e) + dx,
                int((p.y() + widget.height()) * e) + dy)

    # -- gravação
    def gravar(self, img: Image.Image, segundos: float):
        caminho = self.pasta / f"q{len(self.quadros):04d}.jpg"
        img.save(caminho, quality=92)
        self.quadros.append((caminho, segundos))

    @staticmethod
    def mostrar(widget):
        """Rola as áreas de rolagem até o campo aparecer (campo de baixo do formulário)."""
        from PySide6.QtWidgets import QScrollArea
        pai = widget.parentWidget()
        while pai is not None:
            if isinstance(pai, QScrollArea):
                pai.ensureWidgetVisible(widget, 20, 40)
            pai = pai.parentWidget()

    def cena(self, texto: str, janela, alvo=None, formulario=None, segundos=4.5, clique=False, escurecer=True,
             contar=True, caixa=None):
        if contar:
            self.passo_atual += 1
        if alvo is not None:
            self.mostrar(alvo)
        img, desloc = self.foto(janela, formulario)
        if caixa is not None:
            destacar(img, caixa, escurecer)
        if alvo is not None:
            ref = formulario if formulario is not None else janela
            caixa = self.caixa(alvo, ref, desloc)
            destacar(img, caixa, escurecer)
            if clique:                     # o clique vai no canto direito do alvo, para não cobrir o texto dele
                cx = caixa[2] - max(10, min(22, (caixa[2] - caixa[0]) // 5))
                cy = (caixa[1] + caixa[3]) // 2
                antes = img.copy()
                cursor(antes, cx + 40, cy + 30)
                legenda(antes, texto, self._rotulo() if contar else "")
                self.gravar(antes, segundos * 0.6)
                cursor(img, cx, cy, clique=True)
        legenda(img, texto, self._rotulo() if contar else "")
        self.gravar(img, segundos if not (alvo is not None and clique) else segundos * 0.4)

    def digitar(self, texto_legenda: str, janela, campo, texto: str, formulario=None, segundos=3.5):
        """Escreve no campo letra a letra, como alguém digitando."""
        self.passo_atual += 1
        self.mostrar(campo)
        campo.clear()
        passo = max(1, len(texto) // 14)
        for i in range(passo, len(texto) + passo, passo):
            campo.setText(texto[:i])
            img, desloc = self.foto(janela, formulario)
            destacar(img, self.caixa(campo, formulario or janela, desloc))
            legenda(img, texto_legenda, self._rotulo())
            self.gravar(img, 0.09)
        img, desloc = self.foto(janela, formulario)
        destacar(img, self.caixa(campo, formulario or janela, desloc))
        legenda(img, texto_legenda, self._rotulo())
        self.gravar(img, segundos)

    def titulo(self, titulo, subtitulo, segundos=3.5):
        self.gravar(cartao(titulo, subtitulo), segundos)

    def _rotulo(self):
        return f"PASSO {self.passo_atual} DE {self.total}" if self.total else ""

    # -- vídeo
    def renderizar(self, destino: Path, musica: Path | None):
        lista = self.pasta / "quadros.txt"
        with lista.open("w") as f:
            for caminho, segundos in self.quadros:
                f.write(f"file '{caminho.name}'\nduration {segundos:.3f}\n")
            f.write(f"file '{self.quadros[-1][0].name}'\n")
        total = sum(s for _, s in self.quadros)
        temporario = destino.with_name(destino.stem + ".parcial.mp4")
        comando = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista)]
        if musica:
            comando += ["-i", str(musica)]
        comando += ["-vf", f"fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.6,fade=t=out:st={total - 0.8:.2f}:d=0.8",
                    "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-t", f"{total:.2f}", "-movflags", "+faststart"]
        if musica:
            comando += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "128k",
                        "-af", f"afade=t=in:st=0:d=1.5,afade=t=out:st={total - 2.5:.2f}:d=2.5"]
        subprocess.run(comando + [str(temporario)], check=True, cwd=self.pasta)
        temporario.replace(destino)
        return total

    def fechar(self):
        for janela in list(self.principal.janelas.values()):
            janela.close()
        self.principal.close()
        self.app.finalizar()
        self.banco.fechar()
        shutil.rmtree(self.dados, ignore_errors=True)


# ------------------------------------------------------------------ música de fundo (gerada, sem direitos autorais)
def musica(destino: Path, segundos: float, taxa: int = 44100) -> Path:
    import numpy as np
    bpm, compasso = 84, 4
    batida = 60 / bpm
    acordes = [(60, 64, 67, 71), (57, 60, 64, 67), (53, 57, 60, 64), (55, 59, 62, 65)]   # Cmaj7 Am7 Fmaj7 G7
    total = int(segundos * taxa)
    som = np.zeros(total)
    hz = lambda nota: 440 * 2 ** ((nota - 69) / 12)
    t_compasso = batida * compasso
    n = 0
    while n * t_compasso < segundos:
        acorde = acordes[n % len(acordes)]
        ini = int(n * t_compasso * taxa)
        dur = int(t_compasso * taxa)
        t = np.arange(dur) / taxa
        env = np.minimum(1, t / 0.6) * np.minimum(1, (t_compasso - t) / 0.6)
        pad = sum(np.sin(2 * np.pi * hz(nt) * t) + 0.3 * np.sin(4 * np.pi * hz(nt) * t) for nt in acorde) * env * 0.05
        baixo = np.sin(2 * np.pi * hz(acorde[0] - 24) * t) * env * 0.12
        fim = min(total, ini + dur)
        som[ini:fim] += (pad + baixo)[: fim - ini]
        for i in range(8):                                    # arpejo leve, colcheias
            nota = acorde[(0, 1, 2, 3, 2, 1, 2, 3)[i]] + 12
            p0 = ini + int(i * batida / 2 * taxa)
            pd = int(batida * 1.5 * taxa)
            tt = np.arange(pd) / taxa
            pluck = np.sin(2 * np.pi * hz(nota) * tt) * np.exp(-tt * 5) * 0.07
            p1 = min(total, p0 + pd)
            if p0 < total:
                som[p0:p1] += pluck[: p1 - p0]
        n += 1
    som = np.tanh(som * 1.2) * 0.5
    dados = (som * 32767).astype(np.int16)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(dados.tobytes())
    return destino


# ------------------------------------------------------------------ roteiros
def _abrir_grupo(est: Estudio, nome: str):
    p = est.principal
    for i in range(p.menu_grupos.count()):
        if p.menu_grupos.itemText(i) == nome:
            p.menu_grupos.setCurrentIndex(i)
    est.atualizar()


def _botao_grupo(est: Estudio, nome: str):
    """O cabeçalho do grupo no menu da esquerda (para destacar antes de abrir)."""
    from PySide6.QtWidgets import QAbstractButton, QWidget
    caixa = est.principal.menu_grupos
    for filho in caixa.findChildren(QAbstractButton):
        if filho.text().strip() == nome and filho.isVisible():
            return filho
    return caixa


def roteiro_produto(est: Estudio):
    est.total = 10
    est.titulo("Como cadastrar um produto", "WillPDV · passo a passo")
    p = est.principal
    est.cena("No menu da esquerda, toque em \"Produtos e estoque\".", p, _botao_grupo(est, "Produtos e estoque"),
             clique=True)
    _abrir_grupo(est, "Produtos e estoque")
    est.cena("Depois toque em \"Produtos\".", p, p.botoes["produtos"], clique=True)
    lista = p.abrir_cadastro("produtos")
    lista.resize(LARGURA, ALTURA)
    lista.showNormal()
    est.cena("Esta é a lista dos seus produtos. Para criar um novo, clique em \"Novo\".", lista,
             _por_nome(lista, "tutorial_novo"), clique=True)
    from src.ui_qt.cadastros import FormularioCadastro
    form = FormularioCadastro(est.ctx, "produtos", parent=lista)
    form.resize(900, 580)
    form.show()
    est.digitar("Escreva o nome do produto. Exemplo: CERVEJA LATA 350ML.", lista, form.campos["nome"],
                "CERVEJA LATA 350ML", form)
    sub = form.campos["subgrupo_id"]
    est.cena("Escolha o subgrupo: é a \"prateleira\" onde o produto fica.", lista, sub, form, clique=True)
    sub.setCurrentIndex(1)
    form.campos["unidade_id"].setCurrentIndex(form.campos["unidade_id"].findText("UN", flags=_contem()))
    est.cena("Escolha como o produto é vendido: por unidade, por quilo, por litro...", lista, form.campos["unidade_id"], form)
    est.digitar("Digite o preço de venda. Exemplo: 7,50.", lista, form.campos["preco_cent"], "7,50", form)
    est.digitar("O preço de custo é opcional: com ele, o sistema mostra o seu lucro.", lista,
                form.campos["custo_medio_cent"], "4,20", form)
    est.digitar("Se o produto tiver código de barras, passe o leitor neste campo.", lista, form.campos["cbarra"],
                "7891234567895", form)
    salvar = _por_nome(form, "tutorial_salvar")
    est.cena("Confira tudo e clique em \"Salvar\".", lista, salvar, form, clique=True)
    form.salvar()
    est.atualizar()
    lista.atualizar()
    est.atualizar()
    est.cena("Pronto! O produto já aparece na lista e no caixa.", lista, caixa=_linha(est, lista), contar=False,
             segundos=4.5)
    est.titulo("Produto cadastrado!", "Repita para cada produto da sua loja", 3)


def roteiro_operador(est: Estudio):
    est.total = 7
    est.titulo("Como cadastrar quem usa o sistema", "WillPDV · passo a passo")
    p = est.principal
    est.cena("Cada pessoa tem o seu nome e a sua senha. Assim você sabe quem fez cada venda.", p, None, contar=False,
             segundos=4)
    est.cena("No menu da esquerda, toque em \"Cadastros\".", p, _botao_grupo(est, "Cadastros"), clique=True)
    _abrir_grupo(est, "Cadastros")
    est.cena("Depois toque em \"Operadores\".", p, p.botoes["operadores"], clique=True)
    lista = p.abrir_cadastro("operadores")
    lista.resize(LARGURA, ALTURA)
    lista.showNormal()
    est.cena("Clique em \"Novo\".", lista, _por_nome(lista, "tutorial_novo"), clique=True)
    from src.ui_qt.cadastros import FormularioCadastro
    form = FormularioCadastro(est.ctx, "operadores", parent=lista)
    form.resize(900, 580)
    form.show()
    est.digitar("Escreva o nome da pessoa. Exemplo: MARIA.", lista, form.campos["nome"], "MARIA", form)
    est.digitar("Crie uma senha de até 10 letras ou números. Só ela deve saber.", lista, form.campos["senha"],
                "1234", form)
    nivel = form.campos["nivel"]
    est.cena("Escolha o nível: 0 é só o caixa (vender e receber). 4 é o dono, que abre tudo.", lista, nivel, form,
             segundos=5.5)
    est.cena("Clique em \"Salvar\".", lista, _por_nome(form, "tutorial_salvar"), form, clique=True)
    form.salvar()
    lista.atualizar()
    est.atualizar()
    linha = next((i for i in range(lista.grade.rowCount())
                  if any((lista.grade.item(i, c) and lista.grade.item(i, c).text() == "MARIA")
                         for c in range(lista.grade.columnCount()))), 0)
    est.cena("Pronto! Agora a Maria entra no sistema com o nome e a senha dela.", lista, caixa=_linha(est, lista, linha),
             contar=False, segundos=4.5)
    est.titulo("Pessoa cadastrada!", "Cada um com a sua senha", 3)


# ------------------------------------------------------------------ caixa: venda e fechamento
PRODUTOS_DEMO = (("1", "CERVEJA LATA 350ML", "7,50"), ("2", "REFRIGERANTE LATA", "6,00"), ("3", "AGUA MINERAL 500ML", "3,00"))


class DialogosFilmados:
    """Troca as perguntas do caixa (Dialogos) por versões que aparecem no vídeo: cada pergunta é mostrada, fotografada com a
    legenda da vez e respondida pelo roteiro. `falas` traz, na ordem em que as perguntas vão aparecer, o que dizer em cada uma."""

    def __init__(self, est: Estudio, janela, falas: list):
        self.est, self.janela, self.falas = est, janela, list(falas)

    def _fala(self, tipo: str):
        if not self.falas:
            raise RuntimeError(f"O roteiro não previa a pergunta '{tipo}'.")
        return self.falas.pop(0)

    def _botao(self, dlg, texto: str):
        from PySide6.QtWidgets import QPushButton
        return next(b for b in dlg.findChildren(QPushButton) if b.text().replace("&", "") == texto)

    def _mostrar(self, dlg):
        dlg.show()
        dlg.adjustSize()
        self.est.atualizar()

    def confirmar(self, titulo, texto, padrao_sim=True):
        from PySide6.QtWidgets import QMessageBox
        fala = self._fala("confirmar")
        caixa = QMessageBox(QMessageBox.Question, titulo, texto, QMessageBox.NoButton, self.janela)
        sim = caixa.addButton("Sim", QMessageBox.YesRole)
        caixa.addButton("Não", QMessageBox.NoRole)
        caixa.setDefaultButton(sim)
        self._mostrar(caixa)
        self.est.cena(fala, self.janela, sim, caixa, clique=True)
        caixa.close()
        return True

    def maquininha(self, maq, lancamentos=None):
        from src.ui_qt.fechamento_turno import DialogoMaquininha
        fala = self._fala("maquininha")
        dlg = DialogoMaquininha(maq, lancamentos, self.janela)
        self._mostrar(dlg)
        self.est.cena(fala, self.janela, dlg.tabela, dlg, segundos=5.5, escurecer=False)
        self.est.cena("Se bater, clique em \"Confere com a maquininha\".", self.janela, dlg.btn_continuar, dlg, clique=True)
        dlg.close()
        return True

    def pedir_texto(self, titulo, rotulo, senha=False, padrao=""):
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        legenda_digitar, resposta, legenda_ok = self._fala("pedir_texto")
        dlg = QInputDialog(self.janela)
        dlg.setWindowTitle(titulo)
        dlg.setLabelText(rotulo)
        dlg.setOkButtonText("OK")
        dlg.setCancelButtonText("Cancelar")
        dlg.setTextValue(padrao)
        self._mostrar(dlg)
        dlg.resize(max(dlg.width(), 520), dlg.height())
        self.est.digitar(legenda_digitar, self.janela, dlg.findChild(QLineEdit), resposta, dlg)
        if legenda_ok:
            self.est.cena(legenda_ok, self.janela, self._botao(dlg, "OK"), dlg, clique=True)
        dlg.close()
        return resposta

    def painel_fechamento(self, ctx, res, vias, **ganchos):
        from src.ui_qt.fechamento_turno import PainelFechamento
        fala_resultado, fala_imprimir = self._fala("painel_fechamento")
        painel = PainelFechamento(ctx, res, vias, parent=self.janela, **ganchos)
        self._mostrar(painel)
        self.est.cena(fala_resultado, self.janela, painel.faixa, painel, segundos=5.5)
        self.est.cena(fala_imprimir, self.janela, painel.btn_imprimir, painel, clique=True, segundos=5)
        painel.close()

    def aviso(self, titulo, texto):
        raise RuntimeError(f"Aviso inesperado no roteiro: {titulo}: {texto}")

    erro = aviso


class _Calado:
    """Responde às perguntas sem filmar (para preparar o caixa antes da gravação)."""

    def confirmar(self, *a, **k):
        return True

    def aviso(self, titulo, texto):
        raise RuntimeError(f"{titulo}: {texto}")

    erro = aviso


def _abrir_caixa(est: Estudio):
    """Caixa de balcão com três produtos de exemplo, sem impressora, do tamanho do vídeo."""
    from src.controllers.cadastro_controller import CadastroController
    b = est.banco
    for chave, valor in (("caixa_tela_cheia", "N"), ("usar_mesas", "N"), ("usar_garotas", "N"), ("imprimir_cupom", "N"),
                         ("imprimir_fechamento_ao_trocar", "N")):
        b.cfg_set(chave, valor)
    cadastros = CadastroController(b)
    subgrupo = b.valor("SELECT id FROM subgrupos ORDER BY id LIMIT 1")
    unidade = b.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'") or b.valor("SELECT id FROM unidades LIMIT 1")
    for codigo, nome, preco in PRODUTOS_DEMO:
        cadastros.salvar("produtos", {"codigo": codigo, "nome": nome, "subgrupo_id": subgrupo, "unidade_id": unidade,
                                      "preco_cent": preco, "controla_estoque": "N"})
    est.principal.atualizar()
    caixa = est.principal.abrir_caixa()
    caixa.resize(LARGURA, ALTURA)
    caixa.showNormal()
    caixa.dialogos = _Calado()
    est.atualizar()
    return caixa


def _vender(caixa, itens, forma: int, valor: str):
    """Venda feita fora da câmera (para o vídeo do fechamento ter movimento)."""
    for codigo, qtd in itens:
        caixa.ent_codigo.setText(codigo)
        caixa.lancar_item(pedir_quantidade=True)
        caixa.ent_qtd.setText(qtd)
        caixa.lancar_item()
    caixa.ir_para_pagamento()
    caixa.cmb_forma.setCurrentIndex(forma)
    caixa._forma_escolhida()
    caixa.ent_valor.setText(valor)
    caixa.receber()
    caixa.fechar_venda()


def roteiro_venda(est: Estudio):
    est.total = 11
    est.titulo("Como fazer uma venda no caixa", "WillPDV · passo a passo")
    p = est.principal
    caixa = _abrir_caixa(est)
    caixa.hide()
    _abrir_grupo(est, "Operação")
    est.cena("No menu da esquerda, em \"Operação\", toque em \"Abrir caixa\".", p, p.botoes["caixa"], clique=True)
    caixa.showNormal()
    caixa.dialogos = DialogosFilmados(est, caixa, ["Confira o valor e clique em \"Sim\"."])
    est.cena("No começo do dia, o caixa pede para abrir o turno.", caixa, caixa.ent_fundo.parentWidget(), contar=False,
             segundos=4)
    est.digitar("Conte o dinheiro que ficou na gaveta (o troco) e digite aqui. Exemplo: 100,00.", caixa, caixa.ent_fundo,
                "100,00")
    est.cena("Clique em \"Abrir turno\".", caixa, caixa.btn_abrir_turno, clique=True)
    caixa.abrir_turno()
    est.atualizar()
    est.digitar("Digite o código do produto (ou passe o leitor) e tecle Enter.", caixa, caixa.ent_codigo, "1")
    caixa.lancar_item(pedir_quantidade=True)
    est.digitar("Digite a quantidade e tecle Enter. Exemplo: 2 cervejas.", caixa, caixa.ent_qtd, "2")
    caixa.lancar_item()
    est.atualizar()
    est.digitar("Próximo produto: código e Enter. Para 1 unidade, é só teclar Enter de novo.", caixa, caixa.ent_codigo,
                "3")
    caixa.lancar_item(pedir_quantidade=True)
    caixa.lancar_item()
    est.atualizar()
    est.cena("Os itens aparecem aqui, com o total da venda em cima.", caixa, caixa.tabela, segundos=4.5, escurecer=False)
    est.cena("Terminou de passar? Tecle Enter com o campo do código vazio para ir ao pagamento.", caixa,
             caixa.ent_codigo, segundos=5)
    caixa.ir_para_pagamento()
    est.atualizar()
    est.cena("Escolha a forma de pagamento: setas, o número ou a inicial (D = Dinheiro, P = Pix). Enter confirma.", caixa,
             caixa.cmb_forma, segundos=5.5)
    caixa._forma_escolhida()
    est.digitar("Digite quanto o cliente entregou e tecle Enter. Exemplo: 20,00.", caixa, caixa.ent_valor, "20,00")
    caixa.receber()
    est.atualizar()
    est.cena("O troco aparece aqui: R$ 2,00.", caixa, caixa.lbl_troco.parentWidget(), segundos=4.5)
    est.cena("Tecle Enter mais uma vez (ou F12) para fechar a venda.", caixa, caixa.btn_fechar_venda, clique=True)
    caixa.fechar_venda()
    est.atualizar()
    est.cena("Pronto! Venda fechada e o caixa já está livre para o próximo cliente.", caixa, caixa.ent_codigo,
             contar=False, segundos=4.5, escurecer=False)
    est.titulo("Venda feita!", "Código, Enter · Pagamento, Enter · Enter fecha", 3.5)


def roteiro_fechamento(est: Estudio):
    est.total = 8
    est.titulo("Como fechar o caixa", "WillPDV · troca de turno, passo a passo")
    caixa = _abrir_caixa(est)
    caixa.ent_fundo.setText("100,00")
    caixa.abrir_turno()
    _vender(caixa, [("1", "2"), ("3", "1")], 0, "20,00")         # dinheiro: R$ 18,00
    _vender(caixa, [("2", "2")], 1, "12,00")                     # cartão de débito: R$ 12,00
    est.atualizar()
    est.cena("No fim do expediente, o caixa é fechado pelo botão \"Trocar turno\".", caixa, None, contar=False,
             segundos=4)
    est.cena("Sem venda aberta na tela, clique em \"Trocar turno\".", caixa, caixa.btn_trocar_turno, clique=True)
    caixa.dialogos = DialogosFilmados(est, caixa, [
        "Primeiro, confira o cartão e o Pix com o relatório da maquininha.",
        ("Conte o dinheiro da gaveta (junto com o troco do começo) e digite o total. Exemplo: 118,00.", "118,00",
         "Clique em \"OK\"."),
        "Confira o valor e clique em \"Sim\". Depois disso o turno é encerrado.",
        ("Pronto! O resumo mostra se sobrou ou faltou dinheiro. Se não bater, o sistema pede o motivo.",
         "Clique em \"Imprimir Fechamento\" e guarde a folha assinada."),
    ])
    caixa.ir_para_fechamento()
    est.atualizar()
    est.cena("O caixa volta para a abertura: o próximo turno começa aqui.", caixa, caixa.ent_fundo.parentWidget(),
             contar=False, segundos=4.5)
    est.titulo("Caixa fechado!", "Confira a maquininha · Conte a gaveta · Imprima o resumo", 3.5)


def _linha(est: Estudio, lista, linha: int = 0):
    """Caixa (na foto) da linha da tabela, para destacar o registro recém-salvo."""
    grade = lista.grade
    modelo = grade.model()
    primeira = grade.visualRect(modelo.index(linha, 0))
    ultima = grade.visualRect(modelo.index(linha, modelo.columnCount() - 1))
    topo = grade.viewport().mapTo(lista, primeira.topLeft())
    return (max(4, topo.x() - 30), topo.y(), min(LARGURA - 4, topo.x() + ultima.right()), topo.y() + primeira.height())


def _por_nome(janela, nome):
    from PySide6.QtWidgets import QWidget
    return janela.findChild(QWidget, nome)


def _contem():
    from PySide6.QtCore import Qt
    return Qt.MatchFlag.MatchContains


ROTEIROS = {"produto": ("cadastrar-produto", roteiro_produto), "operador": ("cadastrar-operador", roteiro_operador),
            "venda": ("vender-no-caixa", roteiro_venda), "fechamento": ("fechar-o-caixa", roteiro_fechamento)}


def gerar(chave: str, saida: Path, so_quadros: bool = False) -> Path:
    nome, roteiro = ROTEIROS[chave]
    pasta = Path(tempfile.mkdtemp(prefix=f"video-{chave}-"))
    est = Estudio(pasta)
    try:
        roteiro(est)
    finally:
        est.fechar()
    saida.mkdir(parents=True, exist_ok=True)
    if so_quadros:
        return pasta
    total = sum(s for _, s in est.quadros)
    trilha = musica(pasta / "musica.wav", total + 1)
    destino = saida / f"willpdv-{nome}.mp4"
    est.renderizar(destino, trilha)
    shutil.rmtree(pasta, ignore_errors=True)
    return destino


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("videos", nargs="*", default=list(ROTEIROS), choices=list(ROTEIROS))
    ap.add_argument("--saida", default="videos")
    ap.add_argument("--so-quadros", action="store_true", help="só gera as fotos (para conferir), sem o MP4")
    args = ap.parse_args(argv)
    for chave in args.videos:
        print(gerar(chave, Path(args.saida), args.so_quadros))


if __name__ == "__main__":
    main()
