"""Certificado A1 (.pfx) da loja e a assinatura XML (XMLDSig) que a SEFAZ exige.

Padrão da NF-e: assinatura "enveloped" sobre o elemento com `Id` (infNFe, infEvento, infInut), canonicalização C14N 1.0
(sem comentários), resumo SHA-1 e assinatura RSA-SHA1, com o certificado em `KeyInfo/X509Data/X509Certificate`.

O arquivo e a senha do certificado ficam só no caixa. Nada aqui grava o certificado em disco: a conexão com a SEFAZ
usa arquivos temporários que são apagados logo depois (`arquivos_pem`).
"""
from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

DS = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
RSA_SHA1 = "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
SHA1 = "http://www.w3.org/2000/09/xmldsig#sha1"


class ErroCertificado(ValueError):
    """Certificado ilegível, senha errada, vencido ou sem chave RSA."""


@dataclass
class Certificado:
    chave: rsa.RSAPrivateKey
    cert: x509.Certificate

    @classmethod
    def do_pfx(cls, conteudo: bytes, senha: str) -> "Certificado":
        try:
            chave, cert, _ = pkcs12.load_key_and_certificates(conteudo, (senha or "").encode("utf-8"))
        except (ValueError, TypeError) as erro:
            raise ErroCertificado("Não foi possível abrir o certificado: confira o arquivo e a senha.") from erro
        if chave is None or cert is None or not isinstance(chave, rsa.RSAPrivateKey):
            raise ErroCertificado("O arquivo não traz certificado com chave RSA (precisa ser A1 .pfx).")
        return cls(chave, cert)

    @classmethod
    def do_arquivo(cls, caminho, senha: str) -> "Certificado":
        with open(caminho, "rb") as arquivo:
            return cls.do_pfx(arquivo.read(), senha)

    @property
    def validade(self) -> datetime:
        return self.cert.not_valid_after_utc

    @property
    def titular(self) -> str:
        nomes = self.cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return nomes[0].value if nomes else ""

    def vencido(self, agora: datetime | None = None) -> bool:
        return (agora or datetime.now(timezone.utc)) > self.validade

    def base64_der(self) -> str:
        return base64.b64encode(self.cert.public_bytes(serialization.Encoding.DER)).decode("ascii")

    def assinar_bytes(self, dados: bytes) -> bytes:
        return self.chave.sign(dados, padding.PKCS1v15(), hashes.SHA1())

    @contextmanager
    def arquivos_pem(self):
        """(certificado, chave) em PEM, em arquivos temporários só do usuário, apagados ao sair (para o HTTPS)."""
        pasta = tempfile.mkdtemp(prefix="nfce_")
        caminho_cert, caminho_chave = os.path.join(pasta, "c.pem"), os.path.join(pasta, "k.pem")
        try:
            for caminho, conteudo in (
                    (caminho_cert, self.cert.public_bytes(serialization.Encoding.PEM)),
                    (caminho_chave, self.chave.private_bytes(serialization.Encoding.PEM,
                                                             serialization.PrivateFormat.TraditionalOpenSSL,
                                                             serialization.NoEncryption()))):
                descritor = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descritor, "wb") as arquivo:
                    arquivo.write(conteudo)
            yield caminho_cert, caminho_chave
        finally:
            for caminho in (caminho_cert, caminho_chave):
                try:
                    os.remove(caminho)
                except OSError:
                    pass
            try:
                os.rmdir(pasta)
            except OSError:
                pass


def _c14n(no) -> bytes:
    return etree.tostring(no, method="c14n", exclusive=False, with_comments=False)


def _ds(pai, nome: str, texto: str | None = None, **atributos):
    no = etree.SubElement(pai, f"{{{DS}}}{nome}", **atributos)
    if texto is not None:
        no.text = texto
    return no


def assinar(raiz, alvo, certificado: Certificado):
    """Assina `alvo` (elemento com Id) e põe a <Signature> como último filho de `raiz`. Devolve a <Signature>."""
    ident = alvo.get("Id")
    if not ident:
        raise ValueError("O elemento a assinar precisa de Id.")
    # O resumo é do alvo canonicalizado sem a assinatura (transformação enveloped): calculado antes de inserir.
    digest = base64.b64encode(hashlib.sha1(_c14n(alvo)).digest()).decode("ascii")
    assinatura = etree.SubElement(raiz, f"{{{DS}}}Signature", nsmap={None: DS})
    info = _ds(assinatura, "SignedInfo")
    _ds(info, "CanonicalizationMethod", Algorithm=C14N)
    _ds(info, "SignatureMethod", Algorithm=RSA_SHA1)
    ref = _ds(info, "Reference", URI="#" + ident)
    transforms = _ds(ref, "Transforms")
    _ds(transforms, "Transform", Algorithm=ENVELOPED)
    _ds(transforms, "Transform", Algorithm=C14N)
    _ds(ref, "DigestMethod", Algorithm=SHA1)
    _ds(ref, "DigestValue", digest)
    valor = base64.b64encode(certificado.assinar_bytes(_c14n(info))).decode("ascii")
    _ds(assinatura, "SignatureValue", valor)
    _ds(_ds(_ds(assinatura, "KeyInfo"), "X509Data"), "X509Certificate", certificado.base64_der())
    return assinatura


def verificar(raiz, alvo) -> bool:
    """Confere resumo e assinatura com o certificado embutido (o que a SEFAZ faz primeiro)."""
    assinatura = raiz.find(f"{{{DS}}}Signature")
    if assinatura is None:
        return False
    info = assinatura.find(f"{{{DS}}}SignedInfo")
    digest = info.findtext(f".//{{{DS}}}DigestValue")
    if base64.b64encode(hashlib.sha1(_c14n(alvo)).digest()).decode("ascii") != digest:
        return False
    der = base64.b64decode(assinatura.findtext(f".//{{{DS}}}X509Certificate"))
    publica = x509.load_der_x509_certificate(der).public_key()
    try:
        publica.verify(base64.b64decode(assinatura.findtext(f"{{{DS}}}SignatureValue")), _c14n(info),
                       padding.PKCS1v15(), hashes.SHA1())
    except Exception:
        return False
    return True
