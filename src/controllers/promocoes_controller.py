"""Gestão e simulação das regras existentes, sem venda ou movimento de estoque."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math

from src.controllers.config_controller import modulos_desligados
from src.controllers.entidades import ENTIDADES
from src.controllers.produto_controller import ProdutoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao, ErroValidacao


CAMPOS = tuple(c for c in ENTIDADES["produtos"].campos if c.secao == "Promoções" or c.nome in {
    "preco_cent", "preco_gelada_cent", "atacado_qtd", "preco_atacado_cent",
    "atacado_gelada_qtd", "preco_atacado_gelada_cent"})
AVISO = ("SEM ACÚMULO: menor preço unitário elegível, sem somar descontos. "
         "Uma faixa por temperatura. Promoções de período/dia/horário valem para natural; "
         "gelada usa seu preço próprio e sua faixa. Valores dos campos de preço em R$. "
         "Simulação não grava venda nem estoque.")
REGRAS = (
    ("Período", "promo_preco_cent", "promo_de", "promo_ate"),
    ("Dias (1=Dom … 7=Sáb)", "sem_preco_cent", "sem_inicial", "sem_final"),
    ("Horário", "hora_preco_cent", "hora_ini", "hora_fim"),
)


class PromocoesController:
    def __init__(self, ctx):
        self.ctx = ctx

    def exigir_acesso(self):
        ctx = self.ctx
        operador_id = ctx.operador_id
        atual = ctx.banco.um("SELECT ativo FROM operadores WHERE id = ?", (operador_id,))
        if atual is None or not atual["ativo"]:
            raise ErroPermissao("Operador ausente ou inativo. Encerre a sessão.")
        ctx.operador = ctx.acesso.operador(operador_id)
        if "cad_produtos" in modulos_desligados(ctx.banco) or not ctx.pode("cad_produtos"):
            raise ErroPermissao("Seu acesso não permite gerir promoções de produtos.")

    def listar(self, texto=""):
        self.exigir_acesso()
        return self.ctx.cadastros.listar("produtos", texto=texto, apenas_ativos=True)

    def obter(self, produto_id):
        self.exigir_acesso()
        produto = self.ctx.cadastros.obter("produtos", produto_id)
        if produto is None:
            raise ErroNegocio("Produto não encontrado.")
        return produto

    @staticmethod
    def _permitidos(valores):
        extras = set(valores) - {c.nome for c in CAMPOS}
        if extras:
            raise ErroValidacao("A gestão permite alterar somente preços, promoções e faixas.")
        return dict(valores)

    def salvar(self, produto_id, valores):
        with self.ctx.banco.transacao():
            self.exigir_acesso()
            self.obter(produto_id)
            return self.ctx.cadastros.salvar("produtos", self._permitidos(valores), produto_id)

    def simular(self, produto_id, quantidade="1", temperatura="natural", quando=None, valores=None):
        produto = self.obter(produto_id)
        if valores is not None:
            ent = ENTIDADES["produtos"]
            dados = self.ctx.cadastros.converter(ent, self._permitidos(valores), inserindo=False)
            # Os campos permitidos não incluem identificadores; o hook não libera códigos.
            produto.update(ent.antes_salvar(self.ctx.banco, dados, produto_id))
        try:
            texto = str(quantidade).strip()
            if "," in texto:
                texto = texto.replace(".", "").replace(",", ".")
            qtd = Decimal(texto)
            if (not qtd.is_finite() or not math.isfinite(float(qtd)) or qtd <= 0
                    or qtd != qtd.quantize(Decimal("0.0001"))):
                raise ValueError
            if not produto["aceita_decimal"] and qtd != qtd.to_integral_value():
                raise ValueError
        except (InvalidOperation, ValueError, OverflowError):
            raise ErroValidacao("Quantidade positiva, finita, com até 4 casas; respeite a unidade do produto.") from None
        if temperatura not in ("natural", "gelada"):
            raise ErroValidacao("Temperatura deve ser natural ou gelada.")
        if temperatura == "gelada" and not produto["preco_gelada_cent"]:
            raise ErroValidacao("Produto sem preço gelada cadastrado.")
        if quando is None:
            instante = fmt.agora_dt()
        elif isinstance(quando, datetime):
            instante = quando
        else:
            try:
                instante = datetime.strptime(quando, "%Y-%m-%d %H:%M:%S")
                if instante.strftime("%Y-%m-%d %H:%M:%S") != quando:
                    raise ValueError
            except (TypeError, ValueError):
                raise ErroValidacao("Simulação: use data/hora local YYYY-MM-DD HH:MM:SS.") from None
        regras = []
        for nome, preco, inicio, fim in REGRAS:
            isolado = dict(produto)
            for _, outro, _, _ in REGRAS:
                if outro != preco:
                    isolado[outro] = 0
            regra = ProdutoController.regra_preco_vigente(isolado, instante)
            regras.append({"nome": nome, "inicio": produto[inicio], "fim": produto[fim],
                           "preco_cent": produto[preco],
                           "elegivel": temperatura == "natural" and regra["tipo"] == "promocao"})
        gelada = temperatura == "gelada"
        origem = ({"tipo": "gelada", "preco_cent": produto["preco_gelada_cent"]} if gelada
                  else ProdutoController.regra_preco_vigente(produto, instante))
        base = produto["preco_gelada_cent" if gelada else "preco_cent"]
        minimo = produto["atacado_gelada_qtd" if gelada else "atacado_qtd"]
        faixa = produto["preco_atacado_gelada_cent" if gelada else "preco_atacado_cent"]
        atingida = minimo > 0 and faixa > 0 and float(qtd) >= minimo
        final = ProdutoController.preco_por_quantidade_adega(produto, origem["preco_cent"], float(qtd), temperatura)
        return {"produto_id": produto_id, "quantidade": float(qtd), "temperatura": temperatura,
                "quando": instante.strftime("%Y-%m-%d %H:%M:%S"), "base_cent": base,
                "promocao_cent": origem["preco_cent"] if origem["tipo"] == "promocao" else None,
                "origem": origem, "regras": regras, "minimo_qtd": minimo, "faixa_cent": faixa,
                "faixa_atingida": atingida, "final_cent": final,
                "total_cent": fmt.mult_cent(final, float(qtd))}

    @staticmethod
    def descrever(resultado):
        r = resultado
        linhas = [f"{r['quando']} | {r['temperatura']} | quantidade {r['quantidade']:g}",
                  f"Base: {r['base_cent']} cent | promoção elegível: {r['promocao_cent'] if r['promocao_cent'] is not None else 'nenhuma'}",
                  f"Faixa: mínimo {r['minimo_qtd']:g}; preço {r['faixa_cent']} cent; "
                  f"{'atingida' if r['faixa_atingida'] else 'não atingida'}",
                  f"FINAL UNITÁRIO: {r['final_cent']} cent | total simulado: {r['total_cent']} cent"]
        for regra in r["regras"]:
            linhas.append(f"{regra['nome']}: {regra['inicio'] or '—'} → {regra['fim'] or '—'} | "
                          f"{regra['preco_cent']} cent | {'elegível' if regra['elegivel'] else 'não elegível'}")
        linhas.append("Sem acúmulo. Intervalos inclusivos; dias/horas podem virar a semana/meia-noite.\n"
                      "Retratos históricos preservados; balcão mantém a reprecificação existente do CaixaController.")
        return "\n".join(linhas)
