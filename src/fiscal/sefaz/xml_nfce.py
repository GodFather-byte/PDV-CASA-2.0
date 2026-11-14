"""XML da NFC-e (modelo 65, leiaute 4.00) a partir dos dados que `src.fiscal.nfce.montar` já confere.

`montar` entrega os itens com rateio exato de desconto e acréscimo, NCM, CFOP e pagamentos fechando com o total; aqui
isso vira o XML na ordem que o schema oficial exige. Valores em centavos até o fim, para os totais baterem.

Tributação suportada nesta etapa (a dos clientes de hoje):
  Simples Nacional (CRT 1, 2 ou 4) - CSOSN 102, 103, 300 e 400 (ICMSSN102), 500 (ICMSSN500) e 900 (ICMSSN900);
  Regime Normal (CRT 3)            - CST 40, 41 e 50 (ICMS40) e 60 (ICMS60);
  PIS/COFINS                       - CST 04 a 09 (não tributado) e 49 a 99 (outras, sem valor).
O que pede alíquota (CST 00, 01/02 de PIS, CSOSN 101) é recusado com uma mensagem clara até ganhar suporte.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from lxml import etree

from src.fiscal.nfce import ErroFiscal, reais
from src.fiscal.sefaz import chave as chave_mod
from src.fiscal.sefaz import qrcode

NS = "http://www.portalfiscal.inf.br/nfe"
VERSAO = "4.00"
TP_AMB = {"producao": "1", "homologacao": "2"}
CARTAO = {"03", "04"}                       # crédito e débito: grupo `card` (tpIntegra 2 = maquininha não integrada)


@dataclass(frozen=True)
class Emitente:
    cnpj: str
    razao_social: str
    ie: str
    crt: str                                # 1 Simples, 2 Simples excesso, 3 Normal, 4 MEI
    logradouro: str
    numero: str
    bairro: str
    cod_municipio: str                      # IBGE, 7 números
    municipio: str
    uf: str
    cep: str
    nome_fantasia: str = ""
    complemento: str = ""
    fone: str = ""

    def conferir(self) -> None:
        faltando = []
        if len(_digitos(self.cnpj)) != 14:
            faltando.append("CNPJ")
        if not _digitos(self.ie):
            faltando.append("inscrição estadual")
        if self.crt not in {"1", "2", "3", "4"}:
            faltando.append("regime tributário (CRT)")
        if len(_digitos(self.cod_municipio)) != 7:
            faltando.append("código do município (IBGE, 7 números)")
        if len(_digitos(self.cep)) != 8:
            faltando.append("CEP")
        for campo, nome in ((self.razao_social, "razão social"), (self.logradouro, "endereço"), (self.numero,
                            "número do endereço"), (self.bairro, "bairro"), (self.municipio, "cidade")):
            if not (campo or "").strip():
                faltando.append(nome)
        if (self.uf or "").upper() != "SP":
            faltando.append("UF (a emissão própria atende só SP por enquanto)")
        if faltando:
            raise ErroFiscal("Dados da loja incompletos para a NFC-e: " + ", ".join(faltando) + ".")


@dataclass(frozen=True)
class ResponsavelTecnico:
    cnpj: str
    contato: str
    email: str
    fone: str


@dataclass(frozen=True)
class Numeracao:
    serie: int
    numero: int
    cnf: str


def _digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _texto(texto, limite: int) -> str:
    """Texto aceito pelo schema: sem quebras nem espaços nas pontas, sem espaços duplos, cortado no limite."""
    limpo = re.sub(r"\s+", " ", str(texto or "")).strip()
    return limpo[:limite].strip() or "-"


def _cent(valor: str) -> int:
    inteiro, _, frac = str(valor).partition(".")
    sinal = -1 if inteiro.startswith("-") else 1
    return sinal * (abs(int(inteiro or "0")) * 100 + int((frac + "00")[:2]))


def _sub(pai, nome: str, texto=None):
    no = etree.SubElement(pai, f"{{{NS}}}{nome}")
    if texto is not None:
        no.text = str(texto)
    return no


def montar(dados: dict, emit: Emitente, num: Numeracao, ambiente: str, tp_emis: int = 1,
           resp_tec: ResponsavelTecnico | None = None, ver_proc: str = "WillPDV",
           contingencia: tuple[datetime, str] | None = None) -> tuple[etree._Element, str]:
    """Elemento <NFe> sem assinatura (com infNFeSupl) e a chave de acesso."""
    if ambiente not in TP_AMB:
        raise ValueError("Ambiente da NFC-e inválido.")
    emit.conferir()
    emissao = datetime.fromisoformat(dados["data_emissao"])
    chave = chave_mod.montar(chave_mod.UF_SP, emissao, emit.cnpj, num.serie, num.numero, tp_emis, num.cnf)

    nfe = etree.Element(f"{{{NS}}}NFe", nsmap={None: NS})
    inf = _sub(nfe, "infNFe")
    inf.set("versao", VERSAO)
    inf.set("Id", "NFe" + chave)

    ide = _sub(inf, "ide")
    for nome, valor in (("cUF", chave_mod.UF_SP), ("cNF", num.cnf), ("natOp", _texto(dados["natureza_operacao"], 60)),
                        ("mod", "65"), ("serie", int(num.serie)), ("nNF", int(num.numero)),
                        ("dhEmi", emissao.isoformat(timespec="seconds")), ("tpNF", "1"), ("idDest", "1"),
                        ("cMunFG", _digitos(emit.cod_municipio)), ("tpImp", "4"), ("tpEmis", int(tp_emis)),
                        ("cDV", chave[-1]), ("tpAmb", TP_AMB[ambiente]), ("finNFe", "1"), ("indFinal", "1"),
                        ("indPres", "1"), ("procEmi", "0"), ("verProc", _texto(ver_proc, 20))):
        _sub(ide, nome, valor)
    if tp_emis == 9:
        if contingencia is None:
            raise ErroFiscal("NFC-e em contingência sem data e justificativa.")
        quando, justificativa = contingencia
        _sub(ide, "dhCont", quando.isoformat(timespec="seconds"))
        _sub(ide, "xJust", _texto(justificativa, 256))

    e = _sub(inf, "emit")
    _sub(e, "CNPJ", _digitos(emit.cnpj))
    _sub(e, "xNome", _texto(emit.razao_social, 60))
    if (emit.nome_fantasia or "").strip():
        _sub(e, "xFant", _texto(emit.nome_fantasia, 60))
    end = _sub(e, "enderEmit")
    _sub(end, "xLgr", _texto(emit.logradouro, 60))
    _sub(end, "nro", _texto(emit.numero, 60))
    if (emit.complemento or "").strip():
        _sub(end, "xCpl", _texto(emit.complemento, 60))
    _sub(end, "xBairro", _texto(emit.bairro, 60))
    _sub(end, "cMun", _digitos(emit.cod_municipio))
    _sub(end, "xMun", _texto(emit.municipio, 60))
    _sub(end, "UF", emit.uf.upper())
    _sub(end, "CEP", _digitos(emit.cep))
    _sub(end, "cPais", "1058")
    _sub(end, "xPais", "BRASIL")
    if 6 <= len(_digitos(emit.fone)) <= 14:
        _sub(end, "fone", _digitos(emit.fone))
    _sub(e, "IE", _digitos(emit.ie))
    _sub(e, "CRT", emit.crt)

    if dados.get("cpf_destinatario"):
        dest = _sub(inf, "dest")
        _sub(dest, "CPF", _digitos(dados["cpf_destinatario"]))
        if ambiente == "homologacao":
            _sub(dest, "xNome", "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL")
        _sub(dest, "indIEDest", "9")

    total_prod = total_desc = total_outro = 0
    for item in dados["items"]:
        bruto, desc = _cent(item["valor_bruto"]), _cent(item.get("valor_desconto", "0.00"))
        outro = _cent(item.get("valor_outras_despesas", "0.00"))
        total_prod, total_desc, total_outro = total_prod + bruto, total_desc + desc, total_outro + outro
        det = _sub(inf, "det")
        det.set("nItem", str(item["numero_item"]))
        prod = _sub(det, "prod")
        _sub(prod, "cProd", _texto(item["codigo_produto"], 60))
        _sub(prod, "cEAN", "SEM GTIN")
        _sub(prod, "xProd", _texto(item["descricao"], 120))
        _sub(prod, "NCM", _digitos(item["codigo_ncm"]))
        if item.get("cest"):
            _sub(prod, "CEST", _digitos(item["cest"]))
        _sub(prod, "CFOP", _digitos(item["cfop"]))
        _sub(prod, "uCom", _texto(item["unidade_comercial"], 6))
        _sub(prod, "qCom", item["quantidade_comercial"])
        _sub(prod, "vUnCom", item["valor_unitario_comercial"])
        _sub(prod, "vProd", reais(bruto))
        _sub(prod, "cEANTrib", "SEM GTIN")
        _sub(prod, "uTrib", _texto(item["unidade_tributavel"], 6))
        _sub(prod, "qTrib", item["quantidade_tributavel"])
        _sub(prod, "vUnTrib", item["valor_unitario_tributavel"])
        if desc:
            _sub(prod, "vDesc", reais(desc))
        if outro:
            _sub(prod, "vOutro", reais(outro))
        _sub(prod, "indTot", "1")
        imposto = _sub(det, "imposto")
        _icms(_sub(imposto, "ICMS"), item, emit.crt)
        _pis_cofins(_sub(imposto, "PIS"), "PIS", item["pis_situacao_tributaria"], item["descricao"])
        _pis_cofins(_sub(imposto, "COFINS"), "COFINS", item["cofins_situacao_tributaria"], item["descricao"])

    v_nf = total_prod - total_desc + total_outro
    tot = _sub(_sub(inf, "total"), "ICMSTot")
    for nome, valor in (("vBC", 0), ("vICMS", 0), ("vICMSDeson", 0), ("vFCP", 0), ("vBCST", 0), ("vST", 0),
                        ("vFCPST", 0), ("vFCPSTRet", 0), ("vProd", total_prod), ("vFrete", 0), ("vSeg", 0),
                        ("vDesc", total_desc), ("vII", 0), ("vIPI", 0), ("vIPIDevol", 0), ("vPIS", 0), ("vCOFINS", 0),
                        ("vOutro", total_outro), ("vNF", v_nf)):
        _sub(tot, nome, reais(valor))

    _sub(_sub(inf, "transp"), "modFrete", "9")

    pag = _sub(inf, "pag")
    pago = 0
    for forma in dados["formas_pagamento"]:
        det_pag = _sub(pag, "detPag")
        codigo = forma["forma_pagamento"]
        _sub(det_pag, "tPag", codigo)
        if codigo == "99":
            _sub(det_pag, "xPag", "OUTROS")
        _sub(det_pag, "vPag", forma["valor_pagamento"])
        pago += _cent(forma["valor_pagamento"])
        if codigo in CARTAO:
            _sub(_sub(det_pag, "card"), "tpIntegra", "2")
    if pago != v_nf:
        raise ErroFiscal(f"Os pagamentos ({reais(pago)}) não fecham com o total da nota ({reais(v_nf)}).")

    if resp_tec is not None:
        resp = _sub(inf, "infRespTec")
        _sub(resp, "CNPJ", _digitos(resp_tec.cnpj))
        _sub(resp, "xContato", _texto(resp_tec.contato, 60))
        _sub(resp, "email", _texto(resp_tec.email, 60))
        _sub(resp, "fone", _digitos(resp_tec.fone))

    supl = _sub(nfe, "infNFeSupl")
    _sub(supl, "qrCode", qrcode.url_online(chave, ambiente))
    _sub(supl, "urlChave", qrcode.url_chave(ambiente))
    return nfe, chave


def _icms(icms, item: dict, crt: str) -> None:
    codigo = _digitos(item["icms_situacao_tributaria"])
    origem = (item.get("icms_origem") or "0")[:1]
    simples = crt in {"1", "2", "4"}
    if simples and codigo in {"102", "103", "300", "400"}:
        grupo = _sub(icms, "ICMSSN102")
        _sub(grupo, "orig", origem)
        _sub(grupo, "CSOSN", codigo)
    elif simples and codigo == "500":
        grupo = _sub(icms, "ICMSSN500")
        _sub(grupo, "orig", origem)
        _sub(grupo, "CSOSN", "500")
    elif simples and codigo == "900":
        grupo = _sub(icms, "ICMSSN900")
        _sub(grupo, "orig", origem)
        _sub(grupo, "CSOSN", "900")
    elif not simples and codigo in {"40", "41", "50"}:
        grupo = _sub(icms, "ICMS40")
        _sub(grupo, "orig", origem)
        _sub(grupo, "CST", codigo)
    elif not simples and codigo == "60":
        grupo = _sub(icms, "ICMS60")
        _sub(grupo, "orig", origem)
        _sub(grupo, "CST", "60")
    else:
        regime = "Simples Nacional (CSOSN)" if simples else "Regime Normal (CST)"
        raise ErroFiscal(f"Situação do ICMS '{codigo}' de {item['descricao']} ainda não é emitida pelo sistema "
                         f"para o {regime}. Confira o cadastro fiscal com o contador.")


def _pis_cofins(no, tributo: str, cst: str, descricao: str) -> None:
    cst = _digitos(cst).zfill(2)
    if cst in {"04", "05", "06", "07", "08", "09"}:
        _sub(_sub(no, f"{tributo}NT"), "CST", cst)
    elif 49 <= int(cst) <= 99:
        grupo = _sub(no, f"{tributo}Outr")
        _sub(grupo, "CST", cst)
        _sub(grupo, "vBC", "0.00")
        _sub(grupo, f"p{tributo}", "0.00")
        _sub(grupo, f"v{tributo}", "0.00")
    else:
        raise ErroFiscal(f"CST de {tributo} '{cst}' de {descricao} ainda não é emitido pelo sistema "
                         "(precisa de alíquota). Confira o cadastro fiscal com o contador.")


def texto(no) -> bytes:
    """XML sem declaração e sem espaços entre as tags (como a SEFAZ espera)."""
    return etree.tostring(no, encoding="utf-8")
