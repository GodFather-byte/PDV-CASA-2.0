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

No celular, a aba **Relatórios** mostra faturamento, desconto, custo, lucro e margem
de hoje, da semana, do mês ou de um período escolhido. Também mostra o ranking por
lucro, o que foi vendido sem custo ou abaixo do custo, o valor do estoque a custo e
a preço de venda, as notas de compra (lucro previsto e realizado) e o lucro por forma
de pagamento.

O lucro do período é calculado na nuvem com as vendas que o caixa já envia. Estoque e
notas vão no retrato, só com os totais (sem item de nota). O botão Atualizar e o envio
de 15 minutos continuam os mesmos. Caixa antigo, sem custo, aparece como "ainda não
enviou o custo".

## Nota fiscal de compra (XML)

Em Notas de compra, o gerente usa **Importar XML da NF-e**. Aceita o `.xml` que o
fornecedor manda por e-mail e um `.zip` com vários XML. O emitente vira fornecedor.
A chave de acesso impede lançar a mesma nota duas vezes.

Antes de gravar, a tela pede para vincular cada item a um produto (pelo código de
barras, pelo código daquele fornecedor já usado, ou na mão) ou criar um produto novo.
Um fardo de 12 fica com fator 12, e o PDV lembra isso. O custo da unidade soma o
valor do item, o desconto, o frete e o IPI, o ICMS-ST e o FCP-ST. A tela mostra o
custo novo, o custo atual e um preço de venda sugerido com margem de 30%.

Dá para digitar a chave de 44 dígitos só para conferir se é o arquivo certo. O PDV
não baixa a nota na SEFAZ: isso pede certificado digital e fica para uma próxima versão.
