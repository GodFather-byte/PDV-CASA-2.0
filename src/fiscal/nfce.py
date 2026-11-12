"""Monta a NFC-e de uma venda fechada no formato do provedor (campos do Focus NFe).

Tudo em centavos até o fim; só a saída vira texto em reais ("12.50"). O desconto e o acréscimo da venda (taxa de
serviço, acréscimo) são rateados entre os itens proporcionalmente ao valor de cada um, e a sobra do arredondamento
vai para os maiores itens: a soma dos itens bate exatamente com o total da nota. Os pagamentos vão pelo valor
líquido (pago menos troco), de modo que a soma dos pagamentos é o total da nota.

Os dados fiscais vêm do produto; o que estiver vazio usa o padrão da loja (Configurações > Integrações), que o
contador confirma. Produto sem NCM impede a emissão: a nota fica com o motivo para o gerente corrigir o cadastro.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

DESCRICAO_HOMOLOGACAO = "NOTA FISCAL EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"

# Nome do tipo de pagamento -> código da forma de pagamento na NFC-e (tPag), quando o cadastro não diz.
_FORMAS_PELO_NOME = (
    ("dinheiro", "01"), ("especie", "01"), ("cheque", "02"),
    ("credito loja", "05"), ("caderneta", "05"), ("fiado", "05"), ("crediario", "05"),
    ("credito", "03"), ("debito", "04"),
    ("alimentacao", "10"), ("refeicao", "11"), ("presente", "12"), ("combustivel", "13"),
    ("boleto", "15"), ("deposito", "16"), ("pix", "17"), ("transferencia", "18"),
)


class ErroFiscal(ErroNegocio):
    """A venda não pode virar NFC-e como está (cadastro fiscal incompleto, pagamento que não fecha)."""


def _norm(texto) -> str:
    sem = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem.lower()).strip()


def _so_digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def reais(centavos: int) -> str:
    sinal = "-" if centavos < 0 else ""
    return f"{sinal}{abs(centavos) // 100}.{abs(centavos) % 100:02d}"


def forma_fiscal(tipo: str, forma: str | None = None) -> str:
    """Código tPag: o do cadastro do tipo de pagamento ou, vazio, o que o nome indica (senão 99 = outros)."""
    forma = (forma or "").strip()
    if re.fullmatch(r"\d{2}", forma):
        return forma
    nome = _norm(tipo)
    for trecho, codigo in _FORMAS_PELO_NOME:
        if trecho in nome:
            return codigo
    return "99"


def ratear(total: int, pesos: list[int]) -> list[int]:
    """Divide `total` centavos proporcionalmente aos pesos; a sobra vai para os maiores pesos. Soma exata."""
    if total == 0 or not pesos:
        return [0] * len(pesos)
    soma = sum(pesos)
    if soma <= 0:
        raise ErroFiscal("Não há itens com valor para distribuir o desconto ou o acréscimo.")
    partes = [total * p // soma for p in pesos]
    sobra = total - sum(partes)
    for i in sorted(range(len(pesos)), key=lambda i: (-pesos[i], i))[:abs(sobra)]:
        partes[i] += 1 if sobra > 0 else -1
    return partes


def cpf_valido(cpf: str) -> bool:
    d = _so_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if int(d[n]) != (soma * 10 % 11) % 10:
            return False
    return True


def _texto_qtd(qtd: float) -> str:
    texto = f"{qtd:.4f}".rstrip("0").rstrip(".")
    return texto or "0"


def montar(banco, venda_id: int, ambiente: str, cpf: str | None = None, agora: datetime | None = None) -> dict:
    """Dados da NFC-e da venda, prontos para o provedor. Lança ErroFiscal com o que falta corrigir."""
    venda = banco.um("SELECT * FROM vendas WHERE id = ?", (venda_id,))
    if venda is None:
        raise ErroFiscal("Venda não encontrada.")
    if venda["status"] != "fechada":
        raise ErroFiscal("Só venda fechada vira NFC-e.")
    loja = banco.um("SELECT * FROM loja WHERE id = 1")
    cnpj = _so_digitos(loja["cnpj"] if loja else "")
    if len(cnpj) != 14:
        raise ErroFiscal("CNPJ da loja não informado (Configurações > Dados da loja).")
    itens = banco.todos(
        """SELECT i.quantidade, i.total_cent, p.id AS produto_id, p.codigo, p.nome, p.ncm, p.cfop, p.cest,
                  p.origem_mercadoria, p.situacao_tributaria, p.ibscbs_cst, p.ibscbs_class,
                  COALESCE(u.abreviatura, 'UN') AS unidade
             FROM itens_venda i JOIN produtos p ON p.id = i.produto_id
             LEFT JOIN unidades u ON u.id = p.unidade_id
            WHERE i.venda_id = ? AND i.cancelado = 0 AND i.total_cent > 0 ORDER BY i.id""", (venda_id,))
    if not itens:
        raise ErroFiscal("A venda não tem itens com valor.")
    sem_ncm = [i["nome"] for i in itens if len(_so_digitos(i["ncm"])) != 8]
    if sem_ncm:
        raise ErroFiscal("Produto sem NCM válido (8 números) no cadastro fiscal: " + ", ".join(sem_ncm[:3])
                         + ("…" if len(sem_ncm) > 3 else "") + ".")
    cfg = lambda chave, padrao="": (banco.cfg(chave) or padrao).strip()
    brutos = [int(i["total_cent"]) for i in itens]
    descontos = ratear(int(venda["desconto_cent"] or 0), brutos)
    acrescimo = int(venda["servico_cent"] or 0) + int(venda["acrescimo_cent"] or 0)
    outras = ratear(acrescimo, brutos)
    total = sum(brutos) - sum(descontos) + sum(outras)
    if total != int(venda["total_cent"]):
        raise ErroFiscal(f"O total da venda ({reais(int(venda['total_cent']))}) não bate com os itens "
                         f"({reais(total)}). Confira descontos e taxas desta venda.")
    enviar_ibscbs = banco.cfg_bool("nfce_ibscbs_enviar", False)
    saida_itens = []
    for n, (item, bruto, desc, outra) in enumerate(zip(itens, brutos, descontos, outras), start=1):
        qtd = float(item["quantidade"])
        if qtd <= 0:
            raise ErroFiscal(f"Quantidade inválida em {item['nome']}.")
        unitario = f"{bruto / 100 / qtd:.10f}".rstrip("0").rstrip(".")
        descricao = DESCRICAO_HOMOLOGACAO if ambiente == "homologacao" and n == 1 else str(item["nome"])[:120]
        linha = {
            "numero_item": n, "codigo_produto": str(item["codigo"])[:60], "descricao": descricao,
            "cfop": _so_digitos(item["cfop"]) or cfg("nfce_cfop_padrao", "5102"),
            "codigo_ncm": _so_digitos(item["ncm"]),
            "unidade_comercial": str(item["unidade"])[:6], "quantidade_comercial": _texto_qtd(qtd),
            "valor_unitario_comercial": unitario,
            "unidade_tributavel": str(item["unidade"])[:6], "quantidade_tributavel": _texto_qtd(qtd),
            "valor_unitario_tributavel": unitario,
            "valor_bruto": reais(bruto),
            "icms_origem": (item["origem_mercadoria"] or "0").strip()[:1] or "0",
            "icms_situacao_tributaria": (item["situacao_tributaria"] or "").strip() or cfg("nfce_icms_padrao", "102"),
            "pis_situacao_tributaria": cfg("nfce_pis_cofins_padrao", "49"),
            "cofins_situacao_tributaria": cfg("nfce_pis_cofins_padrao", "49"),
        }
        if desc:
            linha["valor_desconto"] = reais(desc)
        if outra:
            linha["valor_outras_despesas"] = reais(outra)
        if _so_digitos(item["cest"]):
            linha["cest"] = _so_digitos(item["cest"])
        if enviar_ibscbs:
            linha["ibs_cbs_situacao_tributaria"] = (item["ibscbs_cst"] or "").strip() or cfg("nfce_ibscbs_cst_padrao", "000")
            linha["ibs_cbs_classificacao_tributaria"] = ((item["ibscbs_class"] or "").strip()
                                                         or cfg("nfce_ibscbs_class_padrao", "000001"))
        saida_itens.append(linha)
    formas = _pagamentos(banco, venda, total)
    momento = (agora or fmt.agora_dt()).astimezone()
    dados = {
        "cnpj_emitente": cnpj, "data_emissao": momento.isoformat(timespec="seconds"),
        "natureza_operacao": "VENDA AO CONSUMIDOR", "presenca_comprador": "1", "modalidade_frete": "9",
        "local_destino": "1", "items": saida_itens, "formas_pagamento": formas,
    }
    cpf = _so_digitos(cpf)
    if cpf:
        if not cpf_valido(cpf):
            raise ErroFiscal("CPF do consumidor inválido.")
        dados["cpf_destinatario"] = cpf
    return dados


def _pagamentos(banco, venda, total: int) -> list[dict]:
    linhas = banco.todos(
        """SELECT p.valor_cent, p.troco_cent, t.tipo, t.forma_fiscal FROM pagamentos_venda p
             JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id
            WHERE p.venda_id = ? AND p.recarga = 0 ORDER BY p.id""", (venda["id"],))
    por_forma: dict[str, int] = {}
    for p in linhas:
        liquido = int(p["valor_cent"]) - int(p["troco_cent"] or 0)
        if liquido:
            codigo = forma_fiscal(p["tipo"], p["forma_fiscal"])
            por_forma[codigo] = por_forma.get(codigo, 0) + liquido
    if venda["modalidade"] == "caderneta" and not por_forma:
        por_forma["05"] = total                                   # fiado: crédito da loja
    pago = sum(por_forma.values())
    if pago != total:
        raise ErroFiscal(f"Os pagamentos ({reais(pago)}) não fecham com o total da nota ({reais(total)}).")
    return [{"forma_pagamento": codigo, "valor_pagamento": reais(valor)} for codigo, valor in por_forma.items()
            if valor > 0]
