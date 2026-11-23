"""Preços e endereço público do site de vendas. Mude só este arquivo.

Valores em centavos. O anual cobra 10 meses (2 grátis). A instalação na loja é grátis.
O WhatsApp padrão abre o wa.me; a variável PDV_SITE_WHATSAPP, se preenchida, troca o número.

Serviços: (chave, nome, centavos, prefixo, período). Prefixo vazio é preço fechado;
"a partir de" é o mínimo. Período "mês" entra no cartão; vazio é pagamento único.
"""

ADEGA_MENSAL_CENT = 9_000          # R$ 90,00
RESTAURANTE_MENSAL_CENT = 14_999   # R$ 149,99
VARIEDADES_MENSAL_CENT = 15_999    # R$ 159,99
BOATE_MENSAL_CENT = 24_999         # R$ 249,99
MESES_GRATIS_NO_ANUAL = 2
DIAS_TESTE = 7

URL_PUBLICA = "https://willpdv-nuvem-6sp0.onrender.com"
CIDADES = ("Osasco", "Carapicuíba", "Barueri", "São Paulo", "Cotia", "Itapevi")

# chave, nome, centavos, prefixo, período
SERVICOS = (
    ("software", "Software sob medida", 49_900, "a partir de", ""),
    ("site", "Site profissional", 29_900, "", ""),
    ("bot", "Bot de atendimento com IA", 14_900, "", "mês"),
    ("automacoes", "Automações para empresas", 19_900, "a partir de", ""),
    ("delivery_cadastro", "Cadastro em apps de delivery (iFood, 99Food, Keeta)", 7_900, "", ""),
    ("delivery_gestao", "Gestão de delivery", 15_000, "", "mês"),
    ("atendente", "Atendente de IA no WhatsApp", 9_900, "", "mês"),
    ("social", "Social media com IA", 19_900, "", "mês"),
    ("whatsapp_business", "Configuração de WhatsApp Business", 9_999, "", ""),
    ("logo", "Logo e identidade visual", 14_999, "", ""),
    ("curriculo", "Currículo profissional em PDF", 3_999, "", ""),
    ("loja_digital", "Pacote Loja Digital", 49_900, "", ""),
)

DESCRICAO_SERVICO = {
    "software": "Sistema feito para a rotina da empresa.",
    "site": "Página da empresa para o cliente achar você.",
    "bot": "Atendimento automático com inteligência artificial.",
    "automacoes": "Tarefas repetidas encaminhadas pelo sistema.",
    "delivery_cadastro": "Cadastro da loja no iFood, 99Food e Keeta.",
    "delivery_gestao": "Acompanhamento do delivery da loja.",
    "atendente": "Atendimento pelo WhatsApp com inteligência artificial.",
    "social": "Conteúdo para as redes da empresa.",
    "whatsapp_business": "Deixa o WhatsApp Business pronto para atender.",
    "logo": "Logo e a cara visual da marca.",
    "curriculo": "Currículo pronto em PDF.",
    "loja_digital": "Pacote para a loja começar no digital.",
}

R2_BASE = "https://pub-cc310e7aad10414ca501764d20a48555.r2.dev"
WHATSAPP_PADRAO = "5511915168336"


def meses_cobrados() -> int:
    return 12 - MESES_GRATIS_NO_ANUAL


def anual_cent(mensal_cent: int) -> int:
    return int(mensal_cent) * meses_cobrados()
