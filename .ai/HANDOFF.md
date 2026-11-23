# Handoff de 23/11/2026

Branch `cursor/site-precos-servicos-seo-e676`, a partir da main `63e3752` (1.14.19).

## Site comercial

- Tabela em `backend/site_precos.py`: Will Adega R$ 90,00; Will Restaurante R$ 149,99; Will Variedades R$ 159,99; WillPDV boate e bar R$ 249,99. O anual continua 10 meses (2 grátis): R$ 900,00, R$ 1.499,90, R$ 1.599,90 e R$ 2.499,90.
- A instalação na loja é grátis. A taxa de R$ 300 saiu da página, do WhatsApp e do JSON-LD.
- Will Variedades não está mais como "Em breve". Não há edição `willvariedades` nem instalador no repositório: o cartão abre o WhatsApp. O teste grátis (`#teste`, `POST /v1/site/teste`) segue só Adega, Restaurante e WillPDV.
- Cada plano mostra o mensal e a linha do ano com o selo "2 meses grátis". O botão Mensal/Anual troca o preço em destaque (sem o script, a linha do ano continua visível).
- Botão flutuante de WhatsApp, no canto, com a mensagem para o Willyan. A seção Serviços lista os 12 itens com preço; o botão de cada um abre o WhatsApp.
- Título, description, Open Graph e JSON-LD (LocalBusiness, SoftwareApplication e Service) citam sistema de caixa (PDV) em Osasco e região, o telefone +55 11 91516-8336 e as cidades da região.

## Conferência

Testes `tests.test_site` e `tests.test_site_teste`. Página local em 1280, 390 e 360 px, sem rolagem horizontal; o anual e os 12 serviços foram clicados no navegador.

## Operação pendente da base

A publicação da nuvem e o restante do backlog operacional continuam os da main (chave da IA no Render, Casa Verde, RustDesk, NFC-e, backups no Neon). Este branch ainda não foi publicado no Render.
