# Handoff — 09/11/2026

## Custo e lucro (1.12.0, esquema 45)

O preço de custo editável é `produtos.custo_medio_cent`. O último preço da nota
continua em `ult_preco_cent`. A compra recalcula a média ponderada e grava
`custo_historico`. O lucro da venda segue o custo congelado em `itens_venda_custos`.

Só o nível 4 vê custo e lucro (`rel_custo`). O painel do dono usa `custo_linha_cent`
quando o caixa novo envia; o custo unitário antigo continua valendo.

Critério da nota: previsto = quantidade × preço de venda de hoje. Realizado = vendas
na ordem, cada nota absorve o que ainda cabia nela, com o custo da própria nota.
Guia: `docs/CUSTO_LUCRO.md`.

## Pendências

- Checkout do site de vendas ainda é só WhatsApp.
- Atualização automática segue sem os segredos `PDV_ATUALIZACAO_*`.
