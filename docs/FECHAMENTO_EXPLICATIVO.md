# Fechamento explicativo por forma

O fechamento compara o valor **esperado** com o **informado**, em centavos,
separadamente por forma de pagamento. Diferenças não se compensam entre cartão,
Pix ou dinheiro: qualquer diferença exige justificativa textual. Depois da
justificativa o operador ativo pode concluir, sem precisar modificar os valores
para fazer o caixa bater. Não foi criada permissão nova: o caixa permanece
disponível aos perfis atuais, inclusive nível zero.

## Fluxo do caixa Qt (a partir da 1.9.1)

O caixa **não pede mais o valor de cada forma**. "Trocar turno" mostra a conferência da maquininha (totais e cada
lançamento de cartão e Pix, com o botão "Confere com a maquininha"), pede só o valor da gaveta e, se houver diferença
nela, o motivo. Cartão e Pix entram como informados iguais ao lançado no sistema, porque o operador acabou de
conferi-los. Com cheque ou ticket físico no turno só a gaveta é declarada (as outras formas ficam "não informadas").
O diálogo por forma (`coletar`) continua disponível abaixo, mas o caixa não o usa.

## Integração Qt

Diálogos especializados disponíveis:

- Qt: `src.ui_qt.fechamento.coletar(ctx, turno_id, valor_final_cent, parent=None)`.

Ambos retornam `None` no cancelamento, ou
`{"informados_por_forma": {id: centavos}, "justificativa": texto}`.
O chamador entrega esse dicionário como keywords para `TurnoController.fechar`.
Nenhum diálogo grava auditoria, altera turno ou chama fechamento. Erros na
abertura (operador ausente/inativo ou turno fechado) são `ErroNegocio` para o
chamador tratar. As entradas começam vazias, inclusive formas sem movimento.
“Conferir” só revela o esperado depois de declarar todos os valores.
“Usar declaração” revalida operador, turno e composição; se algo mudou desde
a prévia, mostra a nova comparação e exige revisão antes de devolver a coleta.

O controlador não abre diálogo nem fecha automaticamente na prévia:

1. `formas_conferencia(turno_id, operador_id)` retorna
   `[{tipo_id, tipo, na_gaveta, dinheiro}]`, sem revelar valores esperados.
2. Colete os valores reais de **todas** as formas retornadas. Use IDs inteiros
   como chaves de `informados_por_forma`, e inteiros em centavos como valores.
   A soma das formas físicas deve ser igual a `valor_final_cent` (gaveta).
   Cancelar a coleta não chama `fechar`.
3. `conferencia_fechamento(turno_id, operador_id, valor_final_cent, *,
   informados_por_forma=mapa)` retorna `linhas`, `gaveta`, `composicao`,
   `por_forma_informada` e `tem_diferenca`. Cada linha traz `tipo_id`, `tipo`,
   `na_gaveta`, `dinheiro`, `esperado_cent`, `informado_cent`, `diferenca_cent`.
   Diferença positiva é sobra; negativa é falta. Prévia não grava.
4. Apresente o resultado, preserve a declaração e peça justificativa obrigatória
   se `tem_diferenca`. A decisão de cancelar mantém o turno aberto.
5. `fechar(turno_id, operador_id, valor_final_cent, *,
   informados_por_forma=mapa, justificativa=texto)` revalida tudo em transação.
   O retorno inclui `conferencia_fechamento` com a justificativa normalizada.
   Diferença sem motivo gera `ErroNegocio` explícito e não grava fechamento.

Os três parâmetros posicionais antigos continuam válidos. Sem o mapa, só há
declaração da gaveta; cada forma fica **não informada**, nunca artificialmente
conferida. Uma diferença na gaveta continua exigindo justificativa.

## Contabilidade preservada

- O esperado usa o resumo existente, por turno do recebimento, não por turno da
  conclusão da venda. Adiantamento conferido anteriormente não entra de novo.
- Os recebimentos já descontam troco. O acréscimo de cartão já está no
  recebimento; não se soma outra vez à gaveta.
- Fundo e suprimentos menos sangrias pertencem à forma física Dinheiro.
  Cheques/tickets físicos, quando existentes, têm contagens próprias; cartão e
  Pix não compõem a gaveta. A forma Dinheiro é reconhecida pelo nome ou, se
  renomeada, pela forma física que permite troco na ordem do cadastro.
- O resultado legado (`resultado`, `resultado_cent`) continua sendo o resultado
  da gaveta, não a soma de diferenças não físicas.
- `resumo["devolucoes"]` usa `DevolucoesController.resumo_turno`. Reembolsos em
  dinheiro já são saídas nos movimentos: não se descontam novamente.
  A prévia inclui `estornos_informados` (devoluções externas declaradas).
  Eles aparecem separados por forma na fita, sem alterar o esperado bruto
  cartão/Pix nem afirmar que houve comprovação de estorno bancário.
- O evento estruturado `auditoria_eventos`, entidade `turnos`, ação
  `fechamento_conferido`, contém `depois.resumo`: snapshot do resumo, valores
  declarados, diferenças e motivo. Evento, turno e log são atômicos.
  Consultas posteriores de turnos novos fechados usam esse snapshot; não mudam
  depois que uma mesa adiantada fecha em outro turno ou um cadastro é renomeado.
  Turnos históricos sem esse evento não recebem motivo fictício; os valores
  esperado/final/resultado gravados no próprio turno são preservados.
- A conferência textual e a fita existente exibem esperado/informado/diferença
  por forma e a justificativa gravada.

## Validação focada

`python -m unittest tests.test_fechamento_explicativo tests.test_fechamento_telas`

Usa apenas bancos de teste. Não é autorização para fechar turno de produção.
