# Caixa: cancelamento parcial e divisão da conta (melhorias 1 e 6)

Vale para o caixa Qt (`src/ui_qt/caixa.py`) e para
todos os perfis. Toda regra fica no `CaixaController`; as telas só perguntam e mostram.

## 1. Cancelamento parcial por quantidade

- `cancelar_item(item_id, motivo="", quantidade=None)`: `None` (ou a quantidade inteira) mantém o cancelamento
  antigo. Uma quantidade menor **cinde a linha**: a original fica com o que sobrou e uma nova linha
  `cancelado=1` guarda a parte cancelada (total e comissão proporcionais, partes de composição copiadas, retrato
  de preço preservado). Devolve o id da linha cancelada.
- Motivo é **obrigatório** no parcial; o evento `cancelamento_parcial` vai para `auditoria_eventos` (antes/depois).
- Protegido: a quantidade já paga **por item** não pode ser cancelada; se a conta tem pagamentos **por valor**, o
  cancelamento é recusado (com rollback) quando o total ficaria abaixo do que já foi pago.
- `info_cancelamento(item_id)` → `{quantidade, qtd_paga, qtd_livre, aceita_decimal, pergunta_qtd}`. As telas só
  perguntam a quantidade quando `pergunta_qtd` (mais de uma unidade, quantidade fracionada ou parte já paga); uma
  unidade inteira cancela direto, como antes.
- Tela Qt: "Cancelar item"/modo cancelar pedem quantidade (validada: faixa e fração) e, no
  parcial, motivo obrigatório. O cancelamento total segue o fluxo e a autorização de sempre.

## 6. Divisão da conta

- **Por valor**: `dividir_restante(venda_id, partes)` (já existente) divide `liquidar()["falta"]` em centavos exatos.
  A tela Qt ("Dividir conta") sugere a parte da vez no valor; remover um pagamento zera a divisão.
- **Por item**: `itens_para_divisao`, `previa_pagamento_itens`, `pagar_itens(venda_id, tipo_id, selecao,
  valor_esperado_cent=None)` e `itens_do_pagamento(pagamento_id)`. Cada pagamento grava o vínculo
  pagamento/item/quantidade/valor em `pagamentos_itens`; o que já foi pago não aparece de novo (sem cobrar duas vezes).
  Valor = itens (rateio proporcional; a última fração leva o resto exato) + taxa da forma. Serviço, desconto e
  taxas ficam no restante, para dividir por valor. Recusa caderneta, pré-pago e item incluso no rodízio.
- `remover_pagamento` apaga os vínculos (auditoria `vinculo_itens_liberado`) e libera os itens; `cancelar_venda`
  também apaga. `transferir_item` não move quantidade já paga por item.
- Tela Qt: botão "Pagar itens" na janela de pagamento. Confirma forma e valor.

## Tabela `pagamentos_itens` (migração 27, dono do esquema)

```sql
CREATE TABLE IF NOT EXISTS pagamentos_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pagamento_id INTEGER NOT NULL REFERENCES pagamentos_venda(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES itens_venda(id) ON DELETE CASCADE,
    quantidade REAL NOT NULL CHECK (quantidade > 0),
    valor_cent INTEGER NOT NULL CHECK (valor_cent >= 0),
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pagamentos_itens_item ON pagamentos_itens(item_id);
CREATE INDEX IF NOT EXISTS ix_pagamentos_itens_pagamento ON pagamentos_itens(pagamento_id);
```

Sem backfill. Sem a tabela (banco antigo), `pagar_itens` recusa com mensagem e o resto funciona.

## Caixa Qt: paridade com o Tk

- Rodízio (Ctrl+R) e Recarga pré-pago (Ctrl+Shift+P) em "Operações do caixa", visíveis só com o módulo ligado
  (`usar_rodizio`/`usar_prepago`) e com mesas; usam `ativar_rodizio`/`desativar_rodizio`/`recarregar`.
- Pré-pago: título mostra "Pré-pago"/"Sem crédito", painel mostra crédito e saldo, F12 fecha comanda sem consumo e
  confirma a devolução da sobra (recarga por Pix/cartão).
- Pedido remoto da cozinha/bar vai ao setor do subgrupo (`setor_do_subgrupo`), como no Tk.

## Restrições conhecidas

- Trava dos vínculos (`_conferir_vinculos`, dentro da transação): lançamento, agrupamento, reprecificação do atacado,
  cancelamento, desconto, serviço, rodízio e transferências são RECUSADOS (com rollback) se mudarem preço, quantidade,
  conta ou valor próprio de item já pago por item, ou deixarem a conta abaixo do pago por item. Remover o pagamento
  libera. Leitura nova nunca é agrupada em linha paga; cisão que deixa só a parte paga fica com o valor exato pago.
- `transferir_item` não protege pagamentos por valor (comportamento anterior).
- Lacunas Qt fechadas (só tela, reaproveitando controllers e permissões do Tk; teste `tests/test_qt_caixa_lacunas.py`):
  F3 liga/desliga o leitor óptico (padrão vem de `config.maquina()["leitor_optico"]`; com leitor, produto sem fração
  lança 1 unidade sem perguntar); F7 abre sangria/suprimento; menu de ações ganhou "Nomear comanda" (só com mesas,
  usa `definir_apelido`), "Leitor óptico liga/desliga (F3)", "Leitura X", "Redução Z" e "Fila de impressão"
  (`JanelaFilaImpressao`, uma só janela; sem permissão mostra aviso).
- Não verificado no Qt: ergonomia da barra fixa de botões do Tk e telas de acertos.
