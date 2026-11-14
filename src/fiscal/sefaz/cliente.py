"""Conversa com os web services da SEFAZ-SP (NFC-e 4.00): SOAP 1.2 sobre HTTPS com o certificado da loja.

Status do serviço, autorização síncrona (um lote com uma nota, `indSinc=1`), consulta pela chave e cancelamento
(evento 110111). A resposta vem traduzida em
`Retorno`: `autorizada` (100), `rejeitada` (o resto com motivo), ou `None` quando não deu para saber (rede, SEFAZ fora,
lote não processado) e a nota precisa ser consultada de novo antes de qualquer reenvio.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from lxml import etree

from src.fiscal.sefaz.assinatura import Certificado
from src.fiscal.sefaz.chave import UF_SP
from src.fiscal.sefaz.xml_nfce import NS, TP_AMB, VERSAO

SOAP = "http://www.w3.org/2003/05/soap-envelope"
WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/"

# portal.fazenda.sp.gov.br/servicos/nfce/Paginas/WebServices.aspx
URLS = {
    "producao": "https://nfce.fazenda.sp.gov.br/ws/",
    "homologacao": "https://homologacao.nfce.fazenda.sp.gov.br/ws/",
}
SERVICOS = {
    "status": ("NFeStatusServico4.asmx", "NFeStatusServico4", "nfeStatusServicoNF"),
    "autorizacao": ("NFeAutorizacao4.asmx", "NFeAutorizacao4", "nfeAutorizacaoLote"),
    "consulta": ("NFeConsultaProtocolo4.asmx", "NFeConsultaProtocolo4", "nfeConsultaNF"),
    "evento": ("NFeRecepcaoEvento4.asmx", "NFeRecepcaoEvento4", "nfeRecepcaoEvento"),
}
EVENTO_REGISTRADO = {"135", "155"}           # 155: cancelamento fora do prazo (homologado)
AUTORIZADA = {"100", "150"}                  # 150: autorizada fora do prazo
EM_PROCESSAMENTO = {"103", "105"}            # lote recebido / em processamento: consultar depois


@dataclass
class Retorno:
    situacao: str | None                     # 'autorizada' | 'rejeitada' | 'em_servico' | None (não deu para saber)
    cstat: str = ""
    motivo: str = ""
    protocolo: str = ""
    recebida_em: str = ""
    xml_protocolo: bytes = b""              # <protNFe> como veio, para montar o nfeProc
    http: int = 0


def _no(nome: str, texto=None, ns: str = NS, **atributos):
    no = etree.Element(f"{{{ns}}}{nome}", nsmap={None: ns}, **atributos)
    if texto is not None:
        no.text = str(texto)
    return no


def _sub(pai, nome: str, texto=None):
    no = etree.SubElement(pai, f"{{{NS}}}{nome}")
    if texto is not None:
        no.text = str(texto)
    return no


def envelope(servico: str, corpo) -> bytes:
    _, wsdl, _ = SERVICOS[servico]
    env = etree.Element(f"{{{SOAP}}}Envelope", nsmap={"soap12": SOAP})
    dados = etree.SubElement(etree.SubElement(env, f"{{{SOAP}}}Body"), f"{{{WSDL}{wsdl}}}nfeDadosMsg",
                             nsmap={None: WSDL + wsdl})
    dados.append(corpo)
    return etree.tostring(env, encoding="utf-8", xml_declaration=True)


def corpo_status(ambiente: str):
    cons = _no("consStatServ", versao=VERSAO)
    _sub(cons, "tpAmb", TP_AMB[ambiente])
    _sub(cons, "cUF", UF_SP)
    _sub(cons, "xServ", "STATUS")
    return cons


def corpo_autorizacao(nfe_assinada, id_lote: int | None = None):
    envi = _no("enviNFe", versao=VERSAO)
    _sub(envi, "idLote", str(id_lote or random.randint(1, 10 ** 15 - 1)))
    _sub(envi, "indSinc", "1")
    envi.append(nfe_assinada)
    return envi


def corpo_consulta(chave: str, ambiente: str):
    cons = _no("consSitNFe", versao=VERSAO)
    _sub(cons, "tpAmb", TP_AMB[ambiente])
    _sub(cons, "xServ", "CONSULTAR")
    _sub(cons, "chNFe", chave)
    return cons


def evento_cancelamento(chave: str, cnpj: str, protocolo: str, justificativa: str, ambiente: str, quando,
                        certificado: Certificado, id_lote: int | None = None):
    """<envEvento> com o cancelamento assinado (o Id é ID + tipo do evento + chave + sequência 01)."""
    from src.fiscal.sefaz.assinatura import assinar
    envio = _no("envEvento", versao="1.00")
    _sub(envio, "idLote", str(id_lote or random.randint(1, 10 ** 15 - 1)))
    evento = _sub(envio, "evento")
    evento.set("versao", "1.00")
    inf = _sub(evento, "infEvento")
    inf.set("Id", f"ID110111{chave}01")
    for nome, valor in (("cOrgao", UF_SP), ("tpAmb", TP_AMB[ambiente]), ("CNPJ", cnpj), ("chNFe", chave),
                        ("dhEvento", quando.isoformat(timespec="seconds")), ("tpEvento", "110111"),
                        ("nSeqEvento", "1"), ("verEvento", "1.00")):
        _sub(inf, nome, valor)
    det = _sub(inf, "detEvento")
    det.set("versao", "1.00")
    _sub(det, "descEvento", "Cancelamento")
    _sub(det, "nProt", protocolo)
    _sub(det, "xJust", " ".join(justificativa.split())[:255])
    assinar(evento, inf, certificado)
    return envio


def _achar(raiz, nome: str):
    return raiz.find(f".//{{{NS}}}{nome}")


def _texto(raiz, nome: str) -> str:
    no = _achar(raiz, nome)
    return (no.text or "").strip() if no is not None else ""


def ler_retorno(conteudo: bytes, http: int = 200) -> Retorno:
    """Traduz o XML de resposta (status, autorização ou consulta)."""
    try:
        raiz = etree.fromstring(conteudo)
    except etree.XMLSyntaxError:
        return Retorno(None, motivo=f"Resposta ilegível da SEFAZ (HTTP {http}).", http=http)
    ret_evento = _achar(raiz, "retEvento")
    if ret_evento is not None:
        inf = ret_evento.find(f"{{{NS}}}infEvento")
        cstat = (inf.findtext(f"{{{NS}}}cStat") or "").strip()
        situacao = "cancelada" if cstat in EVENTO_REGISTRADO else "rejeitada"
        return Retorno(situacao, cstat, (inf.findtext(f"{{{NS}}}xMotivo") or "").strip(),
                       (inf.findtext(f"{{{NS}}}nProt") or "").strip(), (inf.findtext(f"{{{NS}}}dhRegEvento") or "").strip(),
                       etree.tostring(ret_evento, encoding="utf-8"), http)
    prot = _achar(raiz, "protNFe")
    if prot is not None:
        inf = prot.find(f"{{{NS}}}infProt")
        cstat = (inf.findtext(f"{{{NS}}}cStat") or "").strip()
        motivo = (inf.findtext(f"{{{NS}}}xMotivo") or "").strip()
        situacao = "autorizada" if cstat in AUTORIZADA else "rejeitada"
        return Retorno(situacao, cstat, motivo, (inf.findtext(f"{{{NS}}}nProt") or "").strip(),
                       (inf.findtext(f"{{{NS}}}dhRecbto") or "").strip(), etree.tostring(prot, encoding="utf-8"), http)
    cstat, motivo = _texto(raiz, "cStat"), _texto(raiz, "xMotivo")
    if cstat == "107":                       # serviço em operação (status)
        return Retorno("em_servico", cstat, motivo, http=http)
    if not cstat or cstat in EM_PROCESSAMENTO or cstat.startswith("1"):
        return Retorno(None, cstat, motivo or f"SEFAZ sem resposta conclusiva (HTTP {http}).", http=http)
    return Retorno("rejeitada", cstat, motivo, http=http)


class ClienteSefaz:
    def __init__(self, certificado: Certificado, ambiente: str, http=None, timeout=(10, 30)):
        if ambiente not in URLS:
            raise ValueError("Ambiente da NFC-e inválido.")
        self.certificado, self.ambiente, self.timeout = certificado, ambiente, timeout
        if http is None:
            import requests as http
        self.http = http

    def _postar(self, servico: str, corpo) -> Retorno:
        arquivo, wsdl, metodo = SERVICOS[servico]
        cabecalho = {"Content-Type": f'application/soap+xml; charset=utf-8; action="{WSDL}{wsdl}/{metodo}"'}
        try:
            with self.certificado.arquivos_pem() as cert:
                r = self.http.post(URLS[self.ambiente] + arquivo, data=envelope(servico, corpo), headers=cabecalho,
                                   cert=cert, timeout=self.timeout)
        except (OSError, ValueError) as erro:
            return Retorno(None, motivo=f"Sem conexão com a SEFAZ ({type(erro).__name__}).")
        codigo = int(getattr(r, "status_code", 0) or 0)
        if codigo >= 500 and not r.content:
            return Retorno(None, motivo=f"SEFAZ indisponível (HTTP {codigo}).", http=codigo)
        return ler_retorno(r.content, codigo)

    def status(self) -> Retorno:
        return self._postar("status", corpo_status(self.ambiente))

    def autorizar(self, nfe_assinada, id_lote: int | None = None) -> Retorno:
        return self._postar("autorizacao", corpo_autorizacao(nfe_assinada, id_lote))

    def consultar(self, chave: str) -> Retorno:
        return self._postar("consulta", corpo_consulta(chave, self.ambiente))

    def cancelar(self, chave: str, cnpj: str, protocolo: str, justificativa: str, quando) -> Retorno:
        return self._postar("evento", evento_cancelamento(chave, cnpj, protocolo, justificativa, self.ambiente, quando,
                                                          self.certificado))


def nfe_proc(nfe_assinada, xml_protocolo: bytes) -> bytes:
    """O XML que a loja guarda por 5 anos: a nota assinada mais o protocolo de autorização."""
    proc = _no("nfeProc", versao=VERSAO)
    proc.append(etree.fromstring(etree.tostring(nfe_assinada)))
    proc.append(etree.fromstring(xml_protocolo))
    return etree.tostring(proc, encoding="utf-8", xml_declaration=True)
