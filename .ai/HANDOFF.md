# Handoff — 08/11/2026

## Pedido online (Will Adega 1.10.0, esquema 44)

A boate não recebe pedido. Na nuvem a loja precisa estar marcada `willadega`
(`edicao` vazia conta como WillPDV). Na subida, `marcar_lojas_adega` marca quem
já tem licença `willadega` na ponte ou já estava com o pedido ligado. As outras
lojas Adega se marcam na central do fornecedor.

O caixa:

- Não casa o pedido #1 com o #10 (`ja_importado` exige o número inteiro).
- Não aceita se faltar produto, preço gelado ou saldo (reserva o estoque na hora;
  a baixa oficial continua no fechamento, sem descontar duas vezes). O balcão segue
  podendo vender sem saldo.
- Grava a forma (`forma_online`) e já deixa ela escolhida no pagamento.
- Imprime o pedido de entrega ao aceitar.
- Avisa o cliente: confirmado, saiu, entregue, cancelado. A página retoma ao reabrir.
- O botão e o apito ficam no menu principal, não só na janela do caixa.
- Telefone casa o número inteiro (o 55 do Brasil pode faltar). Endereço até 160 caracteres.
- Gelada, quantidade fracionada e casco devolvido entram no cardápio quando o produto tem isso.
- Bairro fora do cadastro avisa que a taxa é a padrão.
- Número do pedido tem índice único `(chave_loja, numero)` e tenta de novo se colidir.

Código: `backend/pedido_online.py`, `src/controllers/pedido_online_controller.py`,
`src/sync/pedidos_online.py`, `src/ui_qt/pedidos_online.py`, `backend/cardapio_web/`
(`sw.js` cardapio-v3). Guia: `docs/CARDAPIO.md`.

## Pendências

- A atualização automática do caixa continua sem os segredos
  `PDV_ATUALIZACAO_CHAVE`, `PDV_ATUALIZACAO_BASE`, `PDV_NUVEM_URL` e `PDV_API_TOKEN`.
  Sem eles o instalador sobe na Release privada e o manifesto não é assinado.
- Loja Adega que não tem licença na ponte nem pedido já ligado precisa do programa
  `willadega` na central, senão o cardápio fica só consulta.
