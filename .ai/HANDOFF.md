# Handoff — 08/11/2026


## Cadastro pelo código de barras com nome e foto (pedido do usuário)

- `foto_produto_controller.buscar_produto(cbarra)` (Open Food Facts, `URL_DADOS`): nome em maiúsculas com a quantidade
  (até 50) e a foto preparada (só de `*.openfoodfacts.org`). O cadastro rápido do caixa (`JanelaCaixa._cadastro_rapido`,
  código desconhecido no leitor) traz o nome preenchido e grava a foto; sem internet ou fora da base, segue digitando.
  No formulário de produtos, botão "Buscar nome e foto pelo código de barras" (`FormularioCadastro.preencher_pela_internet`).
  `BaseCaixaQt` troca a busca por "sem internet" nos testes.

## Site de vendas (mesma API, `/` e `/site`)

Página estática em português, no processo do Render. Preços só em
`backend/site_precos.py` (centavos): Adega R$ 149,90/mês, boate/bar R$ 249,99/mês,
instalação R$ 300 uma vez, anual = 10 meses (2 grátis), teste 7 dias.

Assinar abre o WhatsApp. O número padrão é `5511915168336`. `PDV_SITE_WHATSAPP`
troca o número (com ou sem o 55). Valor vazio ou inválido volta ao padrão.

Instaladores: `https://pub-cc310e7aad10414ca501764d20a48555.r2.dev/{willpdv|willadega}/{versão}/…Setup-….exe`,
com a versão de `src/versao.py` (1.11.0).

Não há arquivo estático montado na raiz. `/v1`, `/porteiro`, `/cardapio`, `/painel`
e `/central` seguem as rotas de antes.

## Pendências

- A atualização automática do caixa continua sem os segredos
  `PDV_ATUALIZACAO_CHAVE`, `PDV_ATUALIZACAO_BASE`, `PDV_NUVEM_URL` e `PDV_API_TOKEN`.
- Loja Adega sem licença na ponte e sem pedido já ligado precisa do programa
  `willadega` na central.
- Checkout do Mercado Pago no botão Assinar ainda não existe: hoje só o WhatsApp.
