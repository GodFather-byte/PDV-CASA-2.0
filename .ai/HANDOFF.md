# Handoff: site público no domínio willpdv.com.br

O código passa a publicar o site em https://willpdv.com.br. Não houve merge nem deploy.
O serviço no Render continua em https://willpdv-nuvem-6sp0.onrender.com para os caixas,
o painel, o cardápio, o porteiro, a central, a retaguarda e o health check.

## O que este PR muda

- Canonical, og:url, og:image, JSON-LD, sitemap.xml e robots.txt usam https://willpdv.com.br.
- O checkout (`POST /v1/pagamentos/checkout`) manda `back_urls` e `notification_url` para
  esse domínio. `RENDER_EXTERNAL_URL` não entra mais nessa escolha.
- GET e HEAD de página pública no host `*.onrender.com` respondem 301 para o domínio,
  preservando a query. `/v1`, webhooks, painel e `/health` não redirecionam.

## O que o dono faz

No Render, no serviço da nuvem, defina:

`PUBLIC_BASE_URL` = `https://willpdv.com.br`

Sem barra no fim. Se essa variável já estiver com o endereço `*.onrender.com`, troque:
valor preenchido ganha do padrão do código. Não altere `RENDER_EXTERNAL_URL`.

Depois do deploy (este PR não publica):

- Google Search Console: propriedade https://willpdv.com.br e o sitemap
  https://willpdv.com.br/sitemap.xml.
- Mercado Pago: pedido novo já avisa `https://willpdv.com.br/v1/pagamentos/webhook`.
  O webhook das mensalidades (`/v1/webhooks/mercadopago`) continua no host onrender.
  Não troque esse.

A loja EA-SUPERACOES2 não foi mexida. Se o caixa ainda não recebeu a correção de custo,
instale a versão e, em Alterações enviadas, use Enviar de novo nos comandos recusados.

## Testes

`tests/test_site.py`, `tests/test_site_checkout.py` e `tests/test_site_teste.py`,
mais a fumaça do caixa.

## Fora

Sem mudança de preço, texto de venda, dado de produção, merge ou deploy.
