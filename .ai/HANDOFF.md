# HANDOFF

## Último trabalho

Melhorias operacionais no estoque da Adega:

- Busca do painel aceita nome com/sem acentos, código interno completo/sem zeros e código de barras, preservando filtros de situação, grupo, ativos e recorte Adega.
- Movimentos rápidos e lançamentos completos validam a quantidade antes de converter fardos em unidades. Entradas inválidas geram `ErroNegocio`, sem alterar saldo ou histórico.
- Conversão arredonda somente o resultado da multiplicação, preservando frações válidas (0,1 fardo de 12 = 1,2 unidades) sem erros de representação de float.
- Quatro testes de regressão em `tests/test_estoque.py`; guia atualizado em `docs/ESTOQUE.md`. Sem migração ou dependência nova.
- Mantidas as regras anteriores: saldo conferido no fechamento, ajustes manuais restritos ao gerente, perdas tipadas auditadas e preços de atacado separados por temperatura.

## Validação

- `python -m unittest tests.test_estoque tests.test_adega_regras tests.test_caixa tests.test_regras_caixa tests.test_esquema_v23 tests.test_auditoria_estruturada tests.test_importacao_produtos`: **221 testes, OK**.
- `python -m compileall -q src tests` e `git diff --check`: **OK**.
- Verificação manual dos controladores com SQLite em memória: buscas por nome/EAN/código, entrada fracionada e recusa sem efeitos colaterais, **OK**.
- Suíte completa: **1.097 testes, 50 erros, 201 ignorados**. Dependências gráficas ausentes (`tkinter`, `PySide6`/metadados) causam erros de importação e referências de UI; um erro adicional em `tests.test_telegram.TesteAvisosEmTempoReal.test_avisa_quando_produto_acaba_e_so_na_hora_que_cruza` ocorre também com o controlador original, por venda sem saldo.

## Pendências

- Homologar no painel Tk/Qt: buscar bebida por EAN e nome sem acentos, combinar filtros e lançar frações de fardo.
- Executar a suíte completa em ambiente com dependências gráficas e tratar separadamente o teste preexistente do Telegram.
- Confirmar a revisão/CI do PR antes de instalar.
