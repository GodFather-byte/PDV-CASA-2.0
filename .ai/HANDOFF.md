# Handoff de 23/11/2026

Branch `cursor/site-checkout-mercadopago-0c21`, a partir da main com o site comercial e os termos.

## Checkout do site

- `POST /v1/pagamentos/checkout` cria uma preferência do Checkout Pro (`POST /checkout/preferences`). O preço sai do id do plano em `backend/site_checkout.py` (os mesmos centavos de `site_precos.py`). O corpo pode mandar valor: ele é ignorado.
- Planos: Adega 90,00 / 900,00; Restaurante 149,99 / 1.499,90; Variedades 159,99 / 1.599,90; Boate 249,99 / 2.499,90. Um item só. Instalação não entra na cobrança.
- Pix e cartão (boleto e caixa eletrônico ficam de fora). Mensal em 1 vez; anual em até 10 vezes no cartão.
- O formulário pede nome, e-mail, WhatsApp e nome da loja antes de ir ao `init_point` (token `TEST-` usa o `sandbox_init_point`).
- Retornos: `/site/obrigado`, `/site/pagamento-pendente`, `/site/pagamento-falhou`, com `auto_return=approved`.
- Webhook `/v1/pagamentos/webhook` busca o pagamento na API. Com `MP_WEBHOOK_SECRET`, exige `x-signature`. A notificação repetida não duplica (`site_pagamentos`) nem reescreve um pedido já aprovado com um pagamento pior.
- Pedidos em `site_pedidos` / `site_pagamentos` (mesmo banco da nuvem). Não emite licença.
- Sem `MP_ACCESS_TOKEN`, os botões Assinar agora / Comprar abrem o WhatsApp e a rota responde 503. O teste grátis e o botão Assinar (WhatsApp) continuam.
- Variáveis: `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`, `PUBLIC_BASE_URL` (opcional). Documentadas no README e no `render.yaml`.

## Conferência

`tests.test_site_checkout`, `tests.test_site`, `tests.test_site_teste` e `tests.test_cobrancas_mercadopago`. `node --check` em `backend/site_web/checkout.js`.

## Operação pendente da base

Colar `MP_ACCESS_TOKEN` (e, se for validar a assinatura, `MP_WEBHOOK_SECRET`) no Render. Sem o token o site publicado segue no WhatsApp. O checkout não liga a licença da loja: o pedido fica gravado para o acompanhamento.
