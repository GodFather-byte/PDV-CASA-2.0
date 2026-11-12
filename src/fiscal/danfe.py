"""Cupom fiscal impresso (DANFE NFC-e) na térmica, com o QR Code da consulta.

Segue o leiaute resumido do DANFE NFC-e: emitente, itens, total, pagamentos, consulta pela chave, consumidor,
número, série, data e QR Code. Em homologação sai a faixa "SEM VALOR FISCAL". Largura: a da fita do caixa.
"""
from __future__ import annotations

from src.core import formatacao as fmt
from src.hardware import impressora_termica as term

FORMAS = {"01": "Dinheiro", "02": "Cheque", "03": "Cartão de crédito", "04": "Cartão de débito", "05": "Crédito loja",
          "10": "Vale alimentação", "11": "Vale refeição", "12": "Vale presente", "13": "Vale combustível",
          "15": "Boleto", "16": "Depósito", "17": "PIX", "18": "Transferência", "20": "PIX", "99": "Outros"}


def qrcode(conteudo: str, modulo: int = 5) -> bytes:
    """QR Code nativo ESC/POS (GS ( k), modelo 2, correção M, centralizado."""
    dados = conteudo.encode("ascii", "ignore")
    tamanho = len(dados) + 3
    return (term.ESC + b"a\x01"
            + term.GS + b"(k\x04\x00\x31\x41\x32\x00"
            + term.GS + b"(k\x03\x00\x31\x43" + bytes([max(1, min(modulo, 16))])
            + term.GS + b"(k\x03\x00\x31\x45\x31"
            + term.GS + b"(k" + bytes([tamanho % 256, tamanho // 256]) + b"\x31\x50\x30" + dados
            + term.GS + b"(k\x03\x00\x31\x51\x30"
            + b"\n" + term.ESC + b"a\x00")


def _colunas(banco) -> int:
    try:
        from src.controllers.config_controller import ConfigController
        return int(ConfigController(banco).maquina().get("colunas_fita") or 48)
    except Exception:
        return 48


def _linha(esquerda: str, direita: str, largura: int) -> str:
    espaco = max(largura - len(esquerda) - len(direita), 1)
    return (esquerda + " " * espaco + direita)[:max(largura, len(direita) + 1)]


def _centro(texto: str, largura: int) -> list[str]:
    linhas, atual = [], ""
    palavras = []
    for palavra in str(texto).split():          # endereço de consulta é maior que a fita: quebra no meio
        palavras += [palavra[i:i + largura] for i in range(0, len(palavra), largura)]
    for palavra in palavras:
        if atual and len(atual) + 1 + len(palavra) > largura:
            linhas.append(atual.center(largura).rstrip())
            atual = palavra
        else:
            atual = f"{atual} {palavra}".strip()
    if atual:
        linhas.append(atual.center(largura).rstrip())
    return linhas


def chave_formatada(chave: str) -> str:
    digitos = "".join(c for c in str(chave or "") if c.isdigit())
    return " ".join(digitos[i:i + 4] for i in range(0, len(digitos), 4))


def texto(banco, nota: dict, largura: int | None = None) -> tuple[str, str]:
    """(antes do QR Code, depois do QR Code)."""
    from src.fiscal import nfce
    largura = largura or _colunas(banco)
    loja = banco.um("SELECT * FROM loja WHERE id = 1")
    venda = banco.um("SELECT * FROM vendas WHERE id = ?", (nota["venda_id"],))
    itens = banco.todos(
        """SELECT i.quantidade, i.total_cent, p.codigo, p.nome, COALESCE(u.abreviatura, 'UN') AS unidade
             FROM itens_venda i JOIN produtos p ON p.id = i.produto_id LEFT JOIN unidades u ON u.id = p.unidade_id
            WHERE i.venda_id = ? AND i.cancelado = 0 AND i.total_cent > 0 ORDER BY i.id""", (nota["venda_id"],))
    traco = "-" * largura
    a: list[str] = []
    a += _centro(loja["razao_social"] or loja["nome_fantasia"] or "", largura)
    a += _centro(f"CNPJ {loja['cnpj'] or ''}  IE {loja['ie'] or ''}", largura)
    endereco = ", ".join(x for x in (loja["endereco"], loja["bairro"], loja["cidade"], loja["uf"]) if x)
    a += _centro(endereco, largura)
    a.append(traco)
    a += _centro("DANFE NFC-e - Documento Auxiliar da Nota Fiscal de Consumidor Eletrônica", largura)
    if nota["ambiente"] == "homologacao":
        a += _centro("EMITIDA EM AMBIENTE DE HOMOLOGAÇÃO - SEM VALOR FISCAL", largura)
    a.append(traco)
    a.append(_linha("Item  Descrição", "Total", largura))
    for n, item in enumerate(itens, start=1):
        a.append(f"{n:03d} {item['codigo']} {item['nome']}"[:largura])
        qtd = f"{float(item['quantidade']):.3f}".rstrip("0").rstrip(".")
        unit = fmt.fmt_num(fmt.dividir_cent(int(item["total_cent"]), item["quantidade"])) if item["quantidade"] else ""
        a.append(_linha(f"    {qtd} {item['unidade']} x {unit}", fmt.fmt_num(item["total_cent"]), largura))
    a.append(traco)
    a.append(_linha("Qtde. total de itens", str(len(itens)), largura))
    subtotal = sum(int(i["total_cent"]) for i in itens)
    a.append(_linha("Valor total R$", fmt.fmt_num(subtotal), largura))
    if int(venda["desconto_cent"] or 0):
        a.append(_linha("Descontos R$", fmt.fmt_num(int(venda["desconto_cent"])), largura))
    outras = int(venda["servico_cent"] or 0) + int(venda["acrescimo_cent"] or 0)
    if outras:
        a.append(_linha("Acréscimos R$", fmt.fmt_num(outras), largura))
    a.append(_linha("VALOR A PAGAR R$", fmt.fmt_num(int(venda["total_cent"])), largura))
    a.append(_linha("FORMA PAGAMENTO", "VALOR PAGO R$", largura))
    troco = 0
    for p in banco.todos("""SELECT p.valor_cent, p.troco_cent, t.tipo, t.forma_fiscal FROM pagamentos_venda p
                              JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id
                             WHERE p.venda_id = ? AND p.recarga = 0 ORDER BY p.id""", (nota["venda_id"],)):
        forma = FORMAS.get(nfce.forma_fiscal(p["tipo"], p["forma_fiscal"]), "Outros")
        a.append(_linha(forma, fmt.fmt_num(int(p["valor_cent"])), largura))
        troco += int(p["troco_cent"] or 0)
    if troco:
        a.append(_linha("Troco R$", fmt.fmt_num(troco), largura))
    a.append(traco)
    a += _centro("Consulte pela Chave de Acesso em", largura)
    a += _centro(nota.get("url_consulta") or "https://www.nfce.fazenda.sp.gov.br/consulta", largura)
    a += _centro(chave_formatada(nota.get("chave")), largura)
    a.append(traco)
    cpf = nota.get("cpf") or ""
    a += _centro(f"CONSUMIDOR CPF: {cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11
                 else "CONSUMIDOR NÃO IDENTIFICADO", largura)
    a += _centro(f"NFC-e nº {nota.get('numero') or '-'}  Série {nota.get('serie') or '-'}  "
                 f"{fmt.fmt_datahora(nota.get('autorizada_em'))}",
                 largura)
    a += _centro("Consulta via leitor de QR Code", largura)
    depois = [""]
    if nota["ambiente"] == "homologacao":
        depois += _centro("SEM VALOR FISCAL", largura)
    return "\n".join(a), "\n".join(depois)


def escpos(banco, nota: dict) -> bytes:
    antes, depois = texto(banco, nota)
    corpo = term.texto_para_escpos(antes, cortar=False, negrito_linhas=1)
    if nota.get("qrcode_url"):
        corpo += qrcode(nota["qrcode_url"])
    corpo += term.texto_para_escpos(depois, cortar=True)
    return corpo
