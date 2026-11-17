"""QR Code da NFC-e, versão 3 (NT 2025.001), e o endereço de consulta por chave (urlChave) da SEFAZ-SP.

Emissão normal (on-line): `URL?p=chave|3|tpAmb`, sem CSC. Contingência (off-line) leva também dia da emissão, valor,
destinatário e uma assinatura RSA-SHA1 em Base64 feita com o certificado do emitente (etapa da contingência).
"""
from __future__ import annotations

import base64
import re

# URLs publicadas pela SEFAZ-SP (portal.fazenda.sp.gov.br/servicos/nfce/Paginas/WebServices.aspx)
URL_QRCODE = {
    "producao": "https://www.nfce.fazenda.sp.gov.br/qrcode",
    "homologacao": "https://www.homologacao.nfce.fazenda.sp.gov.br/qrcode",
}
URL_CHAVE = {
    "producao": "https://www.nfce.fazenda.sp.gov.br/NFCeConsultaPublica",
    "homologacao": "https://www.homologacao.nfce.fazenda.sp.gov.br/NFCeConsultaPublica",
}
TP_AMB = {"producao": "1", "homologacao": "2"}


def url_online(chave: str, ambiente: str) -> str:
    return f"{URL_QRCODE[ambiente]}?p={chave}|3|{TP_AMB[ambiente]}"


def url_chave(ambiente: str) -> str:
    return URL_CHAVE[ambiente]


def url_offline(chave: str, ambiente: str, dia: int, vnf: str, cpf_cnpj: str, assinar_bytes) -> str:
    """QR Code v3 em contingência off-line (Manual do DANFE NFC-e 6.00, 4.4.2):
    `p=chave|3|tpAmb|dia|vNF|tp_idDest|idDest|assinatura`. A assinatura é RSA-SHA1 em Base64 dos sete primeiros
    parâmetros com os separadores, feita com o certificado que assina a nota. Sem destinatário, tp_idDest e idDest
    ficam vazios (1 = CNPJ, 2 = CPF)."""
    doc = re.sub(r"\D", "", cpf_cnpj or "")
    tipo = "1" if len(doc) == 14 else "2" if len(doc) == 11 else ""
    if not tipo:
        doc = ""
    base = f"{chave}|3|{TP_AMB[ambiente]}|{int(dia):02d}|{vnf}|{tipo}|{doc}"
    assinatura = base64.b64encode(assinar_bytes(base.encode("ascii"))).decode("ascii")
    return f"{URL_QRCODE[ambiente]}?p={base}|{assinatura}"
