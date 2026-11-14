"""Emissão própria da NFC-e direto na SEFAZ-SP, sem provedor no meio (custo zero por nota).

O caixa monta o XML 4.00 (`xml_nfce`), assina com o certificado A1 da loja (`assinatura`), gera o QR Code
versão 3 (`qrcode`) e envia ao web service da SEFAZ (`cliente`). O certificado nunca sai do caixa.

Referências: MOC 7.0 da NF-e/NFC-e, NT 2025.001 (QR Code v3) e NT 2025.002 (IBS/CBS, ainda opcional para o
Simples Nacional). Os schemas oficiais usados nos testes ficam em `tests/dados/xsd_nfe`.
"""
