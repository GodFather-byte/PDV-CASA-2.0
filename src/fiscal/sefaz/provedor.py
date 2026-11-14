"""Provedor "emissão própria": a mesma interface do Focus (`emitir`, `consultar`, `cancelar` -> `Resposta`), mas
falando direto com a SEFAZ-SP. Assim o `FiscalController` e a fila não mudam.

Numeração: cada ambiente tem a sua sequência (`nfce_proximo_numero_<ambiente>`) na série `nfce_serie`. O número e a
chave são gravados na nota antes do envio; se a resposta se perder, o próximo passo consulta a chave na SEFAZ antes de
reenviar (nunca gasta dois números com a mesma venda, nunca autoriza duas vezes).

XMLs: a nota assinada e, depois de autorizada, o nfeProc (nota + protocolo) ficam em `nfce/<ambiente>/` ao lado do
banco. A loja é obrigada a guardar o nfeProc por 5 anos.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

from src.core import formatacao as fmt
from src.fiscal.focus import Resposta
from src.fiscal.nfce import ErroFiscal
from src.fiscal.sefaz import chave as chave_mod
from src.fiscal.sefaz import cliente as cliente_mod
from src.fiscal.sefaz import qrcode, xml_nfce
from src.fiscal.sefaz.assinatura import Certificado, ErroCertificado, assinar

NAO_CONSTA = {"217"}                          # NF-e não consta na base da SEFAZ: pode enviar
DUPLICIDADE = {"204", "539"}                  # já autorizada com essa chave/número: consultar
CRT = {"simples_nacional": "1", "mei": "4", "lucro_presumido": "3", "lucro_real": "3"}


class EmissaoPropria:
    def __init__(self, banco, ambiente: str, cliente=None, certificado: Certificado | None = None, pasta=None):
        if ambiente not in ("homologacao", "producao"):
            raise ValueError("Ambiente da NFC-e inválido.")
        self.banco, self.ambiente = banco, ambiente
        self._cliente, self._certificado = cliente, certificado
        base = Path(pasta) if pasta else Path(getattr(banco, "caminho", ".")).resolve().parent / "nfce"
        self.pasta = base / ambiente

    # ------------------------------------------------------------ configuração
    def certificado(self) -> Certificado:
        if self._certificado is None:
            caminho = (self.banco.cfg("nfce_certificado_arquivo") or "").strip()
            if not caminho or not Path(caminho).is_file():
                raise ErroCertificado("Certificado A1 não encontrado (Configurações > Integrações > NFC-e).")
            self._certificado = Certificado.do_arquivo(caminho, self.banco.cfg("nfce_certificado_senha") or "")
        if self._certificado.vencido():
            raise ErroCertificado(f"O certificado digital venceu em {self._certificado.validade:%d/%m/%Y}. "
                                  "Renove para voltar a emitir.")
        return self._certificado

    def cliente(self):
        if self._cliente is None:
            self._cliente = cliente_mod.ClienteSefaz(self.certificado(), self.ambiente)
        return self._cliente

    def emitente(self) -> xml_nfce.Emitente:
        loja = self.banco.um("SELECT * FROM loja WHERE id = 1")
        loja = dict(loja) if loja else {}
        cfg = lambda chave: (self.banco.cfg(chave) or "").strip()
        return xml_nfce.Emitente(
            cnpj=loja.get("cnpj") or "", razao_social=loja.get("razao_social") or loja.get("nome_fantasia") or "",
            nome_fantasia=loja.get("nome_fantasia") or "", ie=loja.get("ie") or "",
            crt=CRT.get(cfg("nfce_regime_tributario"), ""), logradouro=loja.get("endereco") or "",
            numero=cfg("nfce_endereco_numero") or "S/N", complemento=loja.get("complemento") or "",
            bairro=loja.get("bairro") or "", cod_municipio=cfg("nfce_cod_municipio"), municipio=loja.get("cidade") or "",
            uf=(loja.get("uf") or "").upper(), cep=loja.get("cep") or "", fone=loja.get("telefone") or "")

    def responsavel(self) -> xml_nfce.ResponsavelTecnico | None:
        cfg = lambda chave: (self.banco.cfg(chave) or "").strip()
        if len("".join(c for c in cfg("nfce_resp_cnpj") if c.isdigit())) != 14:
            return None
        return xml_nfce.ResponsavelTecnico(cfg("nfce_resp_cnpj"), cfg("nfce_resp_contato") or "SUPORTE",
                                           cfg("nfce_resp_email") or "suporte@willpdv.com.br", cfg("nfce_resp_fone"))

    def _proximo_numero(self) -> int:
        chave = f"nfce_proximo_numero_{self.ambiente}"
        with self.banco.transacao():
            numero = max(1, self.banco.cfg_int(chave, 1))
            self.banco.cfg_set(chave, str(numero + 1))
        return numero

    # ------------------------------------------------------------ arquivos
    def _arquivo(self, chave: str, tipo: str) -> Path:
        self.pasta.mkdir(parents=True, exist_ok=True)
        return self.pasta / f"{chave}-{tipo}.xml"

    def _concluir(self, chave: str, numero, serie, ret) -> Resposta:
        dados = {"numero": numero, "serie": serie, "chave_nfe": chave, "status_sefaz": ret.cstat,
                 "qrcode_url": qrcode.url_online(chave, self.ambiente), "url_consulta_nf": qrcode.url_chave(self.ambiente)}
        assinada = self._arquivo(chave, "assinada")
        if ret.xml_protocolo and assinada.exists():
            proc = self._arquivo(chave, "nfe")
            proc.write_bytes(cliente_mod.nfe_proc(etree.parse(str(assinada)).getroot(), ret.xml_protocolo))
            dados["caminho_xml_nota_fiscal"] = str(proc)
        return Resposta("autorizada", f"{ret.cstat} - {ret.motivo}".strip(" -"), 200, dados)

    # ------------------------------------------------------------ interface do provedor
    def emitir(self, ref: str, dados: dict) -> Resposta:
        nota = self.banco.um("SELECT * FROM nfce_notas WHERE ref = ?", (ref,))
        if nota is None:
            return Resposta("erro", "Nota não encontrada na fila.")
        try:
            cliente = self.cliente()
            if nota["chave"]:                               # já foi enviada: a SEFAZ tem essa nota?
                ret = cliente.consultar(nota["chave"])
                if ret.situacao == "autorizada":
                    return self._concluir(nota["chave"], nota["numero"], nota["serie"], ret)
                if ret.situacao is None:
                    return Resposta(None, ret.motivo)
            serie = int(nota["serie"] or self.banco.cfg_int("nfce_serie", 1))
            numero = int(nota["numero"] or self._proximo_numero())
            cnf = nota["chave"][35:43] if nota["chave"] else chave_mod.codigo_numerico(numero)
            from src.versao import VERSAO
            nfe, chave = xml_nfce.montar(dados, self.emitente(), xml_nfce.Numeracao(serie, numero, cnf),
                                         self.ambiente, resp_tec=self.responsavel(), ver_proc=f"WillPDV {VERSAO}")
            assinar(nfe, nfe.find(f"{{{xml_nfce.NS}}}infNFe"), self.certificado())
        except (ErroFiscal, ErroCertificado) as erro:
            return Resposta("erro", str(erro))
        self._arquivo(chave, "assinada").write_bytes(xml_nfce.texto(nfe))
        self.banco.executar("UPDATE nfce_notas SET numero = ?, serie = ?, chave = ? WHERE id = ?",
                            (str(numero), str(serie), chave, nota["id"]))
        ret = cliente.autorizar(nfe)
        if ret.situacao == "rejeitada" and ret.cstat in DUPLICIDADE:
            consulta = cliente.consultar(chave)
            if consulta.situacao == "autorizada":
                return self._concluir(chave, numero, serie, consulta)
        if ret.situacao == "autorizada":
            return self._concluir(chave, numero, serie, ret)
        if ret.situacao is None:
            return Resposta(None, ret.motivo)
        return Resposta("rejeitada", f"{ret.cstat} - {ret.motivo}", 200,
                        {"numero": numero, "serie": serie, "chave_nfe": chave, "status_sefaz": ret.cstat})

    def consultar(self, ref: str) -> Resposta:
        nota = self.banco.um("SELECT * FROM nfce_notas WHERE ref = ?", (ref,))
        if nota is None or not nota["chave"]:
            return Resposta(None, "Nota ainda sem chave: será enviada.")
        try:
            ret = self.cliente().consultar(nota["chave"])
        except ErroCertificado as erro:
            return Resposta("erro", str(erro))
        if ret.situacao == "autorizada":
            return self._concluir(nota["chave"], nota["numero"], nota["serie"], ret)
        if ret.situacao == "cancelada":
            return Resposta("cancelada", ret.motivo, 200, {"status_sefaz": ret.cstat})
        if ret.situacao is None or ret.cstat in NAO_CONSTA:
            return Resposta(None, ret.motivo or "Nota não encontrada na SEFAZ.")
        return Resposta("rejeitada", f"{ret.cstat} - {ret.motivo}", 200, {"status_sefaz": ret.cstat})

    def cancelar(self, ref: str, justificativa: str) -> Resposta:
        nota = self.banco.um("SELECT * FROM nfce_notas WHERE ref = ?", (ref,))
        if nota is None or not nota["chave"]:
            return Resposta(None, "Nota sem chave de acesso.")
        protocolo = self._protocolo(nota["chave"])
        if not protocolo:
            return Resposta(None, "Protocolo de autorização não encontrado no XML guardado.")
        try:
            ret = self.cliente().cancelar(nota["chave"], self.emitente().cnpj, protocolo, justificativa, fmt.agora_dt()
                                          .astimezone())
        except (ErroCertificado, ErroFiscal) as erro:
            return Resposta(None, str(erro))
        if ret.situacao == "cancelada":
            if ret.xml_protocolo:
                self._arquivo(nota["chave"], "cancelamento").write_bytes(ret.xml_protocolo)
            return Resposta("cancelada", f"{ret.cstat} - {ret.motivo}", 200, {"status_sefaz": ret.cstat})
        return Resposta(None if ret.situacao is None else "erro", f"{ret.cstat} - {ret.motivo}".strip(" -"))

    def _protocolo(self, chave: str) -> str:
        proc = self._arquivo(chave, "nfe")
        if not proc.exists():
            return ""
        return (etree.parse(str(proc)).getroot().findtext(f".//{{{xml_nfce.NS}}}nProt") or "").strip()
