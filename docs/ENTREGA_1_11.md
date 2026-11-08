# Entrega 1.11.0 — pedido online do Will Adega

A versão do programa passou de 1.10.0 para 1.11.0 (`src/versao.py`). O instalador
usa esse número (`build_pdv.py` e o reserva do Inno em `WillPDV.iss` e `WillAdega.iss`).

O WillPDV (boate) continua sem pedido online. No Will Adega:

- O caixa não confunde o pedido #1 com o #10.
- A nuvem só aceita loja marcada `willadega`. Edição vazia é WillPDV.
- O cliente acompanha confirmado, saiu para entrega, entregue e cancelado, também ao reabrir o cardápio.
- A forma escolhida no celular já vem marcada no pagamento, e o pedido de entrega imprime ao aceitar.
- Produto fora de venda não aceita o resto. O pedido reserva estoque e não vende sem saldo.
- O aviso de pedido novo fica no menu principal.
- Gelada, quantidade fracionada e casco entram quando o produto tem isso.

Esquema do caixa: 44. Detalhe em `docs/CARDAPIO.md`.
