# Custo e lucro

O preço de custo do produto é o **custo médio** (`produtos.custo_medio_cent`). O último preço
de uma nota continua em `Últ. preço (custo)`. O lucro da venda usa o custo **congelado**
no fechamento (`itens_venda_custos`), o mesmo número que já existia.

Dinheiro é sempre centavo inteiro.

## Quem vê

Custo no cadastro, lucro da nota e os relatórios novos só aparecem para o nível 4
(gerente/dono), módulo `rel_custo`. O operador de caixa não vê esses campos nem esses
relatórios. Quem já lançava estoque (nível 2) continua digitando a quantidade e o
custo da nota, como antes.

## Nota de compra

Ao lançar uma compra, o estoque sobe e o custo médio é recalculado:

média nova = (média atual × saldo + custo da entrada) ÷ (saldo + quantidade).

Saldo zero: a média vira o custo dessa entrada. Cada mudança fica em `custo_historico`.

Na nota, o previsto é quantidade × preço de venda de hoje, menos o custo da nota.
O realizado reparte as vendas do produto, da mais antiga para a mais nova, entre as
notas ainda não cobertas. O lucro realizado usa o custo **daquela nota**, não a média
de hoje. O que ainda não vendeu fica só no previsto.

## Relatórios

No menu Relatórios, para o gerente: lucro do período (venda, desconto, custo, lucro
e margem), ranking do mais lucrativo ao menos lucrativo, alerta de venda abaixo do
custo ou sem custo, curva ABC, giro e valor do estoque a custo e a preço de venda,
lucro por dia, semana ou mês, lucro por forma de pagamento, compras por fornecedor,
perdas, quebras e cascos. O filtro aceita período, categoria, produto e fornecedor,
conforme o relatório. Dá para exportar CSV (abre no Excel) e PDF.

## Painel do dono

O custo que sobe é o valor congelado da linha (`custo_linha_cent`). O celular mostra
a venda dos itens, o CMV e a margem do período. Caixas antigos, sem esse campo,
continuam com o custo unitário que já enviavam.
