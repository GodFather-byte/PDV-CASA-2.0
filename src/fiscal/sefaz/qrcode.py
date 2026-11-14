"""QR Code da NFC-e, versão 3 (NT 2025.001), e o endereço de consulta por chave (urlChave) da SEFAZ-SP.

Emissão normal (on-line): `URL?p=chave|3|tpAmb`, sem CSC. Contingência (off-line) leva também dia da emissão, valor,
destinatário e uma assinatura RSA-SHA1 em Base64 feita com o certificado do emitente (etapa da contingência).
"""
from __future__ import annotations

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
