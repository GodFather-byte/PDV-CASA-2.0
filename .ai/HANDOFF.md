# Handoff de 24/11/2026: "Atualizar o caixa agora" na central (branch `atualizar-caixa-agora`)

- **Intervalo:** o caixa consulta versão nova de hora em hora (`src/atualizacao/cliente.py` `INTERVALO_HORAS = 1`).
  Para isso não acordar o Neon, `/v1/atualizacao/ultima` usa `ultima_em_cache` (30 min) e `publicar` limpa o cache.
- **Botão na central** (Suporte e caixas): `POST /v1/fornecedor/lojas/{chave}/atualizar-agora` grava o pedido em
  `memoria_nuvem.pedir_atualizacao` (6 h, número = segundos do relógio, para não se repetir depois de reiniciar).
  O pedido sai em `GET /v1/sync/pedido` no campo `atualizar`.
- **Caixa:** `Sincronizador._anotar_pedido_atualizacao` guarda o pedido pendente e `_atualizar_se_pedido` chama
  `rodada(..., imediata=True)`. Assim instala com o turno aberto e passa por cima do "adiar", mas venda aberta ainda
  segura. O PDV aberto também ouve o pedido (`ServicoAtualizacao` chama `atender_central`) quando a sincronização
  completa não roda nele.
- Testes em `tests/test_atualizar_caixa_agora.py`. Documentação em `docs/ATUALIZACAO.md`.

## Antes: site público no domínio willpdv.com.br

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
