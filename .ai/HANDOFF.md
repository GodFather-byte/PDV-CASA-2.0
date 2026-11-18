# Handoff (18/11/2026): delivery Insta-BDelivery mais redondo (branch `delivery-esgotado-ia-insta`)

No ar: 1.14.15 (IA nos caixas: cadastro por foto e nomes da NF-e, ligada por loja na central).

## O que entrou (junto com o PR do repositório GodFather-byte/Insta-BDelivery)
- **Esgotado:** `src/sync/cardapio_envio.coletar` manda `esgotado: true` para produto que controla estoque e está
  zerado (só o sim/não). A nossa nuvem (`backend/cardapio.py`) guarda e mostra; `backend/pedido_online.py` recusa o
  pedido com item esgotado; o cardápio por QR mostra "Esgotado". O Insta deixa indisponível e volta sozinho.
- **Insta pela central** (`backend/insta.py`): no detalhe da loja, "Delivery Insta-BDelivery" guarda endereço e chave
  (`insta_lojas`). O caixa manda `insta_hash` no envio do painel; se for diferente, a resposta traz `insta` e o caixa
  grava (`src/sync/insta_bdelivery.anotar_resposta`). Quando o hash bate, a chave em texto sai da nuvem.
- **IA da vitrine paga:** `GET /v1/parceiro/insta/ia?h=<sha256 da chave>` responde `{liberada}` pelo liga/desliga de
  "IA no caixa". O Insta consulta com `WILLPDV_NUVEM_URL` (Vercel) e cacheia 10 min.
- Insta (outro repo): promoções do PDV no preço, taxa por bairro (do caixa e do painel), bairro vai ao caixa.
- Testes: `test_insta_central`, `TesteEsgotado` em `test_pedido_online`. No Insta: `supabase/tests/promo_zonas_esgotado.sql`.

## Pendências
- Depois do merge dos dois PRs: aplicar a migração do Insta no Supabase e definir `WILLPDV_NUVEM_URL` na Vercel
  (só depois de a nuvem 1.14.16 estar no ar, senão a IA das lojas ligadas fica bloqueada).
- IA: criar a chave da Claude Platform e colar em `ANTHROPIC_API_KEY` no Render; ligar a Casa Verde na central
  (ela precisa da instalação manual da 1.14.15+).
- Backlog: homologação NFC-e DeliciOz; alíquotas IBS/CBS de 2027; mensalidade EA Superações.
