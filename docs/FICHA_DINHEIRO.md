# Ficha de dinheiro (sangria automática por produto)

## Objetivo

Para a Casa Verde, o produto de **código 31** representa dinheiro entregue ao portador
para pagamento futuro pela comanda. Exemplo: caixa com R$ 200,00; ficha de R$ 10,00
entregue e cobrada na comanda; saldo esperado da gaveta cai imediatamente para R$ 190,00.
Quando a comanda é paga em dinheiro, o recebimento entra normalmente no caixa.

## Habilitação

O recurso nasce **desligado** em todas as lojas. Na loja que utiliza o recurso, entre
como administrador em **Configurações > Parâmetros** e configure:

- **Código do produto que entrega dinheiro como ficha na comanda e faz sangria automática:** `31`.

O produto 31 deve estar cadastrado e habilitado para venda, com preço/quantidade
representando o valor entregue. Deixe o campo vazio nas lojas que não usam ficha.
Não misture a ficha com um produto de estoque físico.

## Operação

1. Abra o turno e selecione uma **comanda** (não balcão nem mesa).
2. Lance o código 31 e a quantidade correspondente ao valor da ficha.
3. O PDV exige autorização de sangria e confirmação explícita de entrega do dinheiro.
4. Produto na comanda e saída `movimentos_caixa` são gravados na **mesma transação SQLite**.
   Se o saldo esperado não cobre a entrega ou há erro, o lançamento é revertido.
5. O programa imprime **FICHA - SAÍDA DE DINHEIRO** com comanda, valor, operador e
   identificação do item. Reimprima pela rotina de documentos caso falhe a impressora;
   **não lance a ficha uma segunda vez** só para imprimir outra via.
6. O fechamento calcula fundo + pagamentos em dinheiro + suprimentos - sangrias.

A movimentação é vinculada ao ID do item no campo `descricao`, com prefixo
`FICHA-ITEM:` e um único movimento por item. O comprovante é não fiscal.

## Cancelamentos e segurança

- Cancelar ficha exige **receber de volta o dinheiro físico**, confirmação na tela
  e estorno registrado como **entrada** na gaveta, na mesma transação do cancelamento.
- O cancelamento parcial da linha de ficha é bloqueado. Para cancelar parte,
  faça acerto supervisionado e registre uma operação adequada.
- Cancelar comanda com fichas ativas exige confirmar devolução da soma do dinheiro.
- Cancelamento de cupom já fechado contendo ficha precisa de procedimento financeiro
  específico; não é realizado automaticamente.
- A transferência de ficha e de comanda com ficha ativa é bloqueada para preservar
  rastreabilidade da saída. A ficha não recebe comissão nem taxa de serviço.
- Nenhuma loja é afetada até configurar o código. Histórico de outras vendas/turnos
  não é recalculado.

## Homologação

Rodar `python -m unittest tests.test_ficha_sangria tests.test_caixa tests.test_ponte_pdv`
e a suíte inteira em Windows/Linux. Com **banco de teste**, registrar uma ficha de
R$ 10,00 num turno com R$ 200,00, confirmar R$ 190,00 esperado e documento,
receber de volta R$ 10,00 e cancelar, conferir R$ 200,00 esperado.
Não testar com dinheiro real nem publicar em produção sem homologação.

## Central do fornecedor

Em **Configurações > Nuvem > Testar conexão agora**, o teste executa uma rodada
autêntica da ponte, sem respeitar o intervalo de retentativas (até 60 minutos).
Ele usa a configuração já salva e pode aplicar uma licença publicada, como a
sincronização automática. Não substitui o token nem o ID do caixa.
