"""Preços e endereço público do site de vendas. Mude só este arquivo.

Valores em centavos. O anual cobra 10 meses (2 grátis). O WhatsApp padrão abre o
wa.me; a variável PDV_SITE_WHATSAPP, se preenchida, troca o número.
"""

ADEGA_MENSAL_CENT = 14_990       # R$ 149,90
BOATE_MENSAL_CENT = 24_999       # R$ 249,99
INSTALACAO_CENT = 30_000         # R$ 300, uma vez
MESES_GRATIS_NO_ANUAL = 2
DIAS_TESTE = 7

R2_BASE = "https://pub-cc310e7aad10414ca501764d20a48555.r2.dev"
WHATSAPP_PADRAO = "5511915168336"


def meses_cobrados() -> int:
    return 12 - MESES_GRATIS_NO_ANUAL


def anual_cent(mensal_cent: int) -> int:
    return int(mensal_cent) * meses_cobrados()
