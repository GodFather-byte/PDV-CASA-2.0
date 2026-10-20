# HANDOFF

## Último trabalho

Regras de estoque e vendas da Adega:

- Fechamento agrega consumo de produtos e composição dentro de transação SQLite `BEGIN IMMEDIATE`; saldo insuficiente recusa a venda, preserva a venda aberta e registra a tentativa na auditoria.
- Vendas aceitam até quatro casas decimais quando `aceita_decimal` está habilitado; precisão maior é recusada. Produto sem a opção continua aceitando somente inteiro.
- Perdas tipadas (quebra, oxidação e devolução ao fornecedor) registram saldo, operador, data e observação opcional; movimentos e custo têm eventos estruturados de auditoria.
- Ajustes manuais de estoque e custo exigem operador ativo de nível 4 (gerente/administrador); compras normais mantêm seu fluxo.
- Esquema v23 acrescenta operador/observação a movimentos e subtipo de perda aos lançamentos. Documentação operacional em `docs/ESTOQUE.md`.

## Validação

- `python -m unittest tests.test_caixa tests.test_estoque tests.test_esquema_v23 tests.test_auditoria_estruturada tests.test_adega_regras tests.test_regras_caixa tests.test_importacao_produtos`: **217 testes, OK**.
- `python -m compileall -q src tests` e `git diff --check`: **OK**.
- Não foi possível executar os testes de interface neste runner: faltam `tkinter` e `PySide6`.

## Pendências

- Validar visualmente as telas Tk/Qt e o fluxo com operador da loja em ambiente com dependências gráficas.
- Confirmar a revisão/CI do PR antes de instalar.
