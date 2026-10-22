# Retornáveis por cliente

Disponível para todos os perfis de negócio, mediante a permissão **Lançamentos de
estoque (`lanc_estoque`)** e um operador ativo. As janelas Tk e Qt revalidam ambos
ao abrir, consultar e registrar, mesmo quando a sessão ainda contém o nível antigo.

Este recurso é **controle de posse**, não venda nem movimentação de estoque,
financeiro ou contabilidade. Não cobra, não registra caução e não altera caderneta.
Pode controlar qualquer produto cadastrado: caixas, baldes, equipamentos e
outros retornáveis, não apenas cascos.

1. Selecione o cliente e o produto.
2. Escolha **Empréstimo / saída** (aumenta a quantidade em posse do cliente) ou
   **Devolução / retorno** (diminui a quantidade).
3. Informe uma quantidade positiva, com até quatro casas decimais, e o motivo.
4. Registre e consulte os saldos por produto e o histórico do cliente.

A devolução não pode ultrapassar o saldo daquele cliente e produto. Só clientes
e produtos existentes e ativos podem receber novos registros. Clientes inativos
continuam disponíveis para consulta. Produtos inativos ou excluídos não perdem
seu histórico; é necessário um cadastro ativo para registrar novos movimentos.
O histórico preserva data/hora local ISO, operador, motivo, quantidade e saldo
após o movimento, sem opção de editar ou apagar.

O saldo inicial é zero: vínculos com cascos, trocas, vendas e estoques anteriores
**não comprovam empréstimos e não são convertidos em dívida**. Uma posse
preexistente só entra por um lançamento explícito, com motivo e operador.

## Integração técnica

- `RetornaveisController(banco, operador_id)`:
  - `exigir_acesso()` reconsulta operador e permissão.
  - `registrar(cliente_id, produto_id, tipo, quantidade, motivo) -> int`,
    tipos `emprestimo` e `devolucao`; retorna o identificador do movimento.
  - `saldo(cliente_id, produto_id)`, `saldos(cliente_id)` e
    `historico(cliente_id, produto_id=None)` consultam os registros explícitos.
- Tk: `src.ui.retornaveis_ui.abrir(master, ctx)` retorna a janela.
- Qt: `src.ui_qt.retornaveis.JanelaRetornaveis(ctx, parent=None)`.
- Ambas as janelas oferecem `exigir_acesso()` e `atualizar()`. Ao reaproveitar
  uma janela já aberta, o menu deve chamar `exigir_acesso()` antes de exibi-la.
- Migração 26: `retornaveis_movimentos`, índice cliente/produto e proteção contra
  edição/exclusão. As gravações e os eventos de auditoria são uma única transação.
  O motivo livre fica no histórico, mas não nos retratos da auditoria.

Validação direcionada:

```console
python -m unittest tests.test_retornaveis tests.test_retornaveis_tk tests.test_retornaveis_qt
```
