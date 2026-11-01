# HANDOFF

## Painel do dono (celular)

- A PWA continua em `/painel/` (`backend/painel_web/`), com a mesma senha e sessão. O celular atualiza sozinho a cada 30 s.
- **Hoje:** faturamento, vendas, ticket médio (já vinham das vendas fechadas) e, agora, gráfico dos últimos 30 dias
  (vendas já guardadas) e dos últimos 12 meses. O gráfico mensal completo sai do retrato do caixa, porque a nuvem
  apaga a venda depois de cerca de 120 dias. PDV antigo: o gráfico usa só o que a nuvem ainda tem e avisa.
- **Produtos:** ranking por quantidade e faturamento em hoje / 7 dias / 30 dias (`GET /v1/painel/produtos`).
  Estoque baixo usa o `estoque_minimo` de cada produto (já subia no retrato); o alerta também aparece em Hoje.
- **Abertas:** comandas abertas (número, quanto deve, hora) e a marca de comissão lançada — a mesma regra do
  porteiro e do cartão rosa (`comissoes_garotas` pendente no número da comanda). Comissão por garota no período
  (pendente e paga). Mesa fica de fora.
- **Caixa:** além do turno aberto, fechamento (contado, esperado, sobra/falta) e sangrias de cada dia.
- Isso que não era venda fechada entra no retrato (`src/sync/painel_envio.py`). **O PC do caixa precisa ser
  atualizado** para comandas, comissões, fechamento, sangrias e os 12 meses. Vendas, ticket e estoque baixo
  seguem com o PDV que já sincroniza. Guia: `docs/PAINEL_DONO.md`.

## Cobrança da licença (Mercado Pago)

- Sem Asaas. Mensalidade por loja (valor, dia, e-mail, WhatsApp, dados do boleto). A varredura no processo gera
  boleto e Pix 5 dias antes do vencimento (até 20 dias depois, se o Render dormiu).
- E-mail: Brevo (`BREVO_API_KEY` + `EMAIL_FROM`) no Render grátis; SMTP só se não houver chave. WhatsApp:
  `WHATSAPP_API_*` ou link `wa.me`.
- `POST /v1/admin/cobrancas/teste-email` manda o aviso só para o `destino`, nunca para o e-mail da loja.
- Webhook `POST /v1/webhooks/mercadopago` (`MP_WEBHOOK_SECRET`), relê o pagamento e, se `approved` no valor,
  estende a licença um mês a partir do vencimento. Guia: `docs/COBRANCA_LICENCAS_MERCADOPAGO.md`.

## Porteiro

- `/porteiro` no caixa e `/porteiro/?loja=CHAVE` na nuvem. Lista as comandas abertas e deixa de fora a da garota
  (comissão pendente). Consultar número continua. Guia: `docs/PORTEIRO.md`.

## Estado

- PDV **1.9.0**, esquema **30**. Interface do PDV só Qt (PySide6). O gerador de licenças continua em Tkinter.
- Dinheiro em centavos. Duas edições: WillPDV e E&A Superações (`src/core/edicao.py`). Cupom não fiscal.
- O histórico fino de tela (caixa, fechamento, comanda da garota) está no git; não repetir aqui.

## Pendências para produção

- Homologar o Qt no balcão antes do Setup novo. Atualizar o PDV da loja para o painel passar a mostrar comandas,
  comissões, fechamento, sangrias e os 12 meses.
- Cobrança Mercado Pago só funciona com `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET` no Render, e o e-mail com
  `BREVO_API_KEY` e `EMAIL_FROM`.
- Devolução não atende pré-pago nem rodízio. Bruto, CMV e comissões históricos não são estornados por devolução.
