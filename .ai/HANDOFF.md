# HANDOFF

## Trabalho concluído

- Importação de NF-e XML modelo 55 para Bar/Adega, com prévia, associação por EAN/código, sugestão por nome, SKU automático, estoque/custo e histórico por item.
- Preço de venda segue manual; produtos novos aceitam preço manual opcional e preço zero é bloqueado no lançamento e no fechamento.
- Margem mínima configurável, relatórios por categoria e lista de produtos mais vendidos.

## Validação

- Passaram 118 testes de importação, caixa e relatórios.
- Passaram 66 testes de migração/esquema e Adega; `compileall` passou.
- Testes visuais Tk/Qt não executaram: o ambiente não tem `tkinter` nem `PySide6`.

## Pendências

- Confirmar os fluxos visuais Tk/Qt em ambiente com as dependências gráficas disponíveis.
