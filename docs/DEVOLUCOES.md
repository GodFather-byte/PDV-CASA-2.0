# Devoluções e trocas de venda fechada

Frente 6. Devolução parcial ou total de uma venda **FECHADA**, ligada ao cupom original. A venda
original e os pagamentos dela nunca são alterados: a devolução é um registro novo e imutável.
**Troca** é uma devolução seguida de uma **venda nova** de balcão, feita pelo fluxo normal do
`CaixaController`.

## Regras

- **Venda aceita:** só venda `fechada`. Venda aberta ou cancelada é recusada.
- **Cancelar depois:** uma venda que já tem devolução não pode mais ser cancelada, para não
  haver segunda via de reembolso.
- **Autorização:** motivo obrigatório (até 300 caracteres). O autorizador precisa do acesso
  `caixa_cancelamento`: o próprio operador, se tiver nível, ou a senha de um supervisor.
- **Turno:** precisa de turno aberto. A devolução pertence ao turno e à data do **reembolso**,
  não aos da venda original.
- **Idempotência:** cada tentativa leva um `uuid` v4. Repetir o mesmo uuid (duplo clique,
  nova tentativa) devolve o registro já gravado com `repetida=True`, sem gravar de novo.
- **Atomicidade:** uma única transação grava o registro, a saída da gaveta (ou o crédito na
  caderneta) e, se escolhido, a volta ao estoque.
- **Impressão:** o comprovante sai depois da gravação. Se a impressão falhar, a devolução não
  é repetida; a tela oferece reimprimir.
- **Saldo por item:** quantidade com até 4 casas, finita e maior que zero, limitada ao saldo
  ainda não devolvido do item.

## Valores (sempre inteiros em centavos)

- **Rateio:** o desconto e a taxa de serviço reais da venda são rateados por item,
  proporcionalmente ao bruto. Os centavos que sobram vão aos primeiros itens, em ordem
  determinística (`ratear`).
- **Parciais:** cada devolução usa o valor acumulado arredondado para baixo. Uma devolução
  parcial nunca passa do proporcional (pode sair alguns centavos menor) e a que completa a
  venda fecha o valor exato.
- **Extras:** acréscimo da forma de pagamento e outros extras explícitos só são devolvidos na
  devolução que completa a venda, e apenas se `reembolsar_extras=True`.
- **Teto:** a soma das devoluções nunca passa do total líquido efetivamente pago (pagamentos menos troco e vale, limitado ao total da venda).
- **Bruto preservado:** o bruto histórico da venda nunca é reescrito.
## Modos de reembolso

| `reembolso_modo` | Efeito | Exige |
|---|---|---|
| `dinheiro_gaveta` | Saída em `movimentos_caixa` no turno atual. Já está na gaveta esperada: não somar de novo. | `tipo_pagamento_id` de forma `na_gaveta` (se omitido, usa a primeira forma de dinheiro). |
| `externo` | Estorno Pix ou cartão feito **fora** do PDV. Nenhuma chamada de rede. | `tipo_pagamento_id` usado na venda, `referencia_externa` (até 120 caracteres) e valor dentro do pago nessa forma. |
| `caderneta` | Lançamento `tipo='credito'` na caderneta, que abate o saldo do cliente. | Só para venda em caderneta. |

A `referencia_externa` é declarada pelo operador e **não prova** que o estorno bancário
aconteceu. Fechamento, relatórios e Telegram devem mostrá-la como "estorno declarado".

## Estoque

- **Volta ao estoque:** opcional, item por item (`retorna_estoque`).
- **Produto com composição:** devolve os insumos, até o que foi de fato baixado pela venda.
- **Movimentos:** são lançados com `tipo = ref_tipo = 'devolucao_venda'` e `ref_id` igual ao
  id da devolução.
- **Relatórios de consumo:** devem manter o bruto vendido e mostrar a devolução em linha
  separada, sem abater em silêncio.

## API (escrita sempre pelo `CaixaController`)

```python
caixa.situacao_devolucao(venda_id) -> dict
caixa.previa_devolucao(venda_id, selecao, reembolsar_extras=True) -> dict      # sem gravar
caixa.devolver(venda_id, selecao, motivo, autorizado_por, reembolso_modo, uuid,
               tipo_pagamento_id=None, referencia_externa=None, troca=False,
               reembolsar_extras=True) -> dict                                 # = obter(id) (+ "repetida": True)
caixa.abrir_troca(devolucao_id) -> int                                         # id da venda nova (idempotente)
```

O formato de `selecao` é uma lista de dicts. A chave de estoque é `retorna_estoque`, não
`retornar_estoque`. Itens com quantidade 0 são ignorados:

```python
[{"item_id": 12, "quantidade": 1.5, "retorna_estoque": True},
 {"item_id": 13, "quantidade": "0,3333"}]          # retorna_estoque padrão False
# atalho aceito: {item_id: quantidade}  (sem estoque)
```

`previa` devolve `{itens:[{item_id, produto_id, nome, quantidade, unid, bruto_cent,
desconto_cent, servico_cent, valor_cent, retorna_estoque}], itens_bruto_cent,
desconto_rateado_cent, servico_rateado_cent, extras_cent, valor_cent, completa}`.

`situacao` devolve:

- Venda e totais: `venda`, `total_cent`, `teto_cent`, `devolvido_cent`, `saldo_cent`,
  `extras_cent`, `extras_devolvidos_cent`, `rodizio_nao_devolvivel_cent`, `completa`, `modos`,
  `devolucoes`.
- `itens`, uma lista de `{item_id, produto_id, codigo, nome, unidade, observacao, quantidade,
  devolvida, saldo, total_cent, desconto_cent, servico_cent, liquido_cent, devolvido_cent,
  sugere_estoque}`.
- `formas`, uma lista de `{tipo_pagamento_id, tipo, na_gaveta, pago_cent,
  estornado_externo_cent}`.

### Consultas (`DevolucoesController(banco, operador_id=None)`)

- `venda_por_cupom(cupom)`, `obter(id)` (a linha mais `itens`), `da_venda(venda_id)`,
  `comprovante(id, largura=40)`.
- `listar(turno_id=None, de=None, ate=None)` filtra pela data do **reembolso**
  (`criado_em`), em ordem `criado_em, id`.
  - `de` e `ate` são texto ISO local e os dois limites entram (inclusive).
  - `ate` só com a data (`YYYY-MM-DD`) vale até `23:59:59` desse dia; com data e hora, é
    comparado como veio.
  - `de` só com a data começa à `00:00:00`.

Cada linha de `listar`, `da_venda` e `obter` traz:

- Todas as colunas de `devolucoes`: `id, uuid, venda_id, venda_uuid, cupom_original, turno_id,
  criado_em, operador_id, autorizado_por, motivo, completa, troca, itens_bruto_cent,
  desconto_rateado_cent, servico_rateado_cent, extras_cent, valor_cent, reembolso_modo,
  tipo_pagamento_id, referencia_externa, movimento_caixa_id, caderneta_id, cliente_id`.
- Mais estes campos: `operador`, `autorizador`, `forma` (nome do tipo de pagamento ou None),
  `na_gaveta`, `venda_fechada_em`, `venda_turno_id`, `venda_total_cent`, `troca_venda_id`.
- `valor_cent = itens_bruto_cent - desconto_rateado_cent + servico_rateado_cent + extras_cent`.
## Contrato por turno: fechamento, relatórios e Telegram

`DevolucoesController(banco).resumo_turno(turno_id)`:

```python
{"turno_id", "quantidade", "valor_cent", "itens_bruto_cent", "desconto_rateado_cent",
 "servico_rateado_cent", "extras_cent", "dinheiro_gaveta_cent", "trocas",
 "por_modo": {"dinheiro_gaveta": {"quantidade", "valor_cent"},
              "externo": {...}, "caderneta": {...}},          # os 3 sempre presentes
 "por_forma": [{"modo", "tipo_pagamento_id", "tipo", "na_gaveta", "quantidade", "valor_cent"}],
 "movimentos_caixa_ids": [...],
 "externos": [{"devolucao_id", "cupom_original", "tipo", "valor_cent", "referencia_externa"}]}
```

- **Gaveta:** só `dinheiro_gaveta_cent` sai da gaveta, e já está em `movimentos_caixa` (saída
  com `movimentos_caixa_ids`). Não descontar de novo.
- **Externo:** não reduz o esperado da maquininha nem do Pix. É um estorno declarado, a
  conferir no extrato.
- **Venda original:** não reescreva o bruto nem as vendas líquidas do dia original. A
  devolução aparece na data e no turno do reembolso, em linha separada.
- **Por período:** use `listar(de=..., ate=...)` e some no relatório.

## Telas

- **Permissão:** módulo `caixa_cancelamento` (constante `MODULO`).
- **Abrir a tela:** `DevolucoesController(banco, operador_id).exigir_acesso()` é público. Exige
  operador ativo, conferido no cadastro, e lança `ErroPermissao`. As duas telas já o chamam ao
  abrir.
- **Gravar:** `operador_autoriza()` diz se o próprio operador autoriza; se não, a tela pede a
  senha de um supervisor (`autorizado_por`).
- **Tk:** `src.ui.devolucoes_ui.abrir(master, ctx)` devolve `JanelaDevolucoes` (Toplevel).
- **Qt:** `src.ui_qt.devolucoes.JanelaDevolucoes(ctx, parent=None)` (QDialog).
- **ctx:** as telas usam `ctx.banco`, `ctx.caixa`, `ctx.operador_id` e `ctx.impressao`.
- **Fluxo da tela:** buscar o cupom, marcar itens e quantidades, escolher estoque, modo, forma,
  referência e motivo, conferir a prévia, confirmar e autorizar, gravar e imprimir. A troca
  abre a venda nova no caixa.

## Onde aparece (integração feita pelo pai)

- **Caixa Tk e Qt:** a tela de devolução abre como modal pelo botão ou menu do caixa
  ("mais opções") e pelo menu Lançamentos.
- **Relatório:** em Relatórios > Caixa > "Devoluções e reembolsos" (`RelatorioController.devolucoes`),
  com uma linha por cupom.
  - O período é `[início, fim)`, contado pela data e pelo turno do **reembolso**.
  - Mostra o motivo, a referência externa e os três modos de reembolso.
- **Movimentos de caixa:** a saída aparece com o rótulo "Reembolso", sem ser deduzida duas vezes.
- **Vendas, grupos, mais vendidos e CMV:** mantêm as quantidades e os valores **BRUTOS** da
  venda original, com nota explícita. Os retornos aparecem só nos movimentos de estoque
  (`devolucao_venda`).
- **Comissões:** de garçom, garotas e vendedor também ficam **BRUTAS**. A devolução **não**
  estorna comissão automaticamente (política que já existia). Qualquer ajuste é manual e
  auditado.
## Limpeza de movimento

`UtilitarioController.limpar_movimento` apaga devoluções antigas junto com a venda original,
na ordem `devolucoes_itens`, `devolucoes_trocas`, `devolucoes`, depois a venda e depois o turno.
As travas de imutabilidade são retiradas e recriadas **dentro** da mesma transação; uma falha
desfaz tudo, inclusive as travas.

Uma venda antiga **fica** quando:

- tem alguma devolução feita a partir da data de corte; ou
- a venda nova da troca fica (aberta ou fechada depois do corte), e vice-versa.

Um turno com devolução não é apagado.

## Limites conhecidos

- **Pré-pago:** venda de cartão pré-pago é recusada, porque o saldo é acertado pela recarga.
- **Rodízio:** a cobrança de rodízio e os itens inclusos não são devolvíveis.
- **Vale:** o vale entra no teto (só o pago de fato pode voltar).
- **Crédito de troca:** não existe forma de pagamento "crédito de troca". A troca é reembolso
  mais venda nova paga normalmente.
- **Caderneta:** uma venda na caderneta só devolve como crédito na caderneta.
- **Externo:** só nas formas usadas na venda e até o valor pago em cada uma.
- **Dinheiro em venda no cartão:** é permitido, e o PDV não confere se há dinheiro suficiente
  na gaveta.
- **Autorização:** é sempre exigida, inclusive para valores pequenos.
- **Vendas antigas:** vendas com totais inconsistentes (soma dos itens diferente do total) são
  recusadas.
- **Correção:** não há "desfazer" de devolução, porque o histórico é imutável. Para corrigir,
  é preciso um lançamento manual auditado.

## Esquema

- **v28:** tabelas `devolucoes`, `devolucoes_itens` e `devolucoes_trocas`.
  - Têm CHECKs de valor e de modo.
  - Gatilhos impedem UPDATE e DELETE.
  - A auditoria registra a inclusão.
- **v29:** `fila_impressao.status` aceita `pendente`, `enviando`, `enviado`, `erro`, `incerto`
  e `cancelado` (`FILA_IMPRESSAO_STATUS`). Bancos antigos passam por uma reconstrução que
  preserva linhas, ids e sequência.