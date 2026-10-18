# HANDOFF

## Último trabalho
- **Pré-pago / cartão consumação** (`usar_prepago`, esquema v21), depois do Perfil do estabelecimento (em `main`). Regras
  fechadas com o titular (AskUserQuestion): (1) a sobra do crédito **volta ao cliente** na saída, em dinheiro; (2) sem
  saldo, **bloqueia até recarregar**; (3) vira pré-paga **a comanda que recebe carga** (as outras, e as das garotas,
  seguem normais).
  - Esquema v21: `vendas.prepago` e `pagamentos_venda.recarga` (a recarga é um pagamento adiantado marcado).
  - `CaixaController`: `recarregar` (exige o módulo e mesa/comanda), `saldo_prepago` (crédito, consumo e saldo; o
    complemento da consumação mínima fica fora do consumo e é acertado na saída) e `_conferir_credito`, chamado dentro da
    transação de `adicionar_item`, `transferir_item`, `transferir_mesa` e `transferir_varias` quando o destino é pré-pago
    (o que passa do crédito é desfeito). `_conferir_limite_comanda` não vale para pré-paga. Comanda pré-paga juntada
    numa comum leva o crédito como adiantamento (a comum não trava).
  - Devolução da sobra (`liquidar`/`fechar`): troco das recargas em dinheiro **do turno atual**; o resto da sobra de
    recarga (Pix/cartão, ou dinheiro de turno já fechado) vira `devolucao`, gravada em `fechar` como **saída do caixa**
    no turno atual ("Devolução do crédito pré-pago da comanda N"), para a gaveta e a maquininha baterem sem mexer em
    turno conferido (mesmo princípio de `_devolver_adiantamentos`). Só recarga vira devolução: Pix pago a mais na saída
    continua recusado (a tela de pagamento depende desse erro). Sem recarga, `liquidar` dá exatamente o resultado de
    antes. `vendas.troco_cent` continua só o troco em dinheiro; a devolução é a diferença `pago - total - troco - vale`.
  - `fechar` aceita pré-paga sem consumo (devolve tudo); comanda comum continua exigindo item.
  - Tela: botão "Recarga" (barra, gated por `usar_prepago`), crédito e saldo sob o total, selo "Pré-pago"/"Sem
    crédito", saldo no cartão do painel em vez de "Falta"/"Concluir acerto", "Devolver:" e aviso na tela de pagamento, e
    o "Troco" depois de fechar passou a mostrar tudo o que volta ao cliente. Pré-conta mostra crédito e saldo; cupom, a
    "Devolução do crédito".
  - Testes: `tests/test_prepago.py` (22 casos: recarga, trava do crédito, transferências, devolução em dinheiro/Pix/turno
    anterior, impressão, painel e tela), `tests/test_esquema_v21.py`, casos em `tests/test_modulos.py` (botão Recarga).
  - **Qt não recebeu o pré-pago** (botão Recarga, saldo, "Devolver:"); o controlador já vale para o Qt (trava e
    devolução), mas a tela de pagamento Qt mostra só o troco.

## Pendências
- **Risco a confirmar com o titular**: a sobra de recarga feita por **cartão de crédito** volta em dinheiro (foi o que
  ele escolheu). Isso permite "saque" no cartão (carrega R$ 500 no crédito, consome R$ 10, leva R$ 490 em dinheiro).
  Se ele quiser, limitar a devolução em dinheiro ao que entrou em dinheiro/Pix e mandar o resto para estorno na
  maquininha.
- Possíveis evoluções do pré-pago: comprovante impresso da recarga; pulseira RFID com número próprio (mapear o código
  da pulseira para uma comanda); relatório de recargas e devoluções do turno.
- Outras evoluções do ecossistema, nenhuma pedida ainda: **split por item consumido** (cada pessoa paga o que pediu;
  mudança de esquema); **rodízio com preço por faixa** (adulto/criança; `vendas.pessoas` viraria mais de um campo);
  **etiqueta de balança no leitor** (EAN de peso/preço embutido); **consumação mínima por tipo de entrada** e cobrança
  da comanda sem consumo (anotados em `docs/ESPECIFICACAO.md` seção 3).
- **Valores de cada perfil** (`PERFIS` em `perfil_controller.py`) foram decididos por mim; titular pode querer ajustar.
- **Homologar a balança com equipamento real** (Toledo ou Filizola, porta serial): `Balanca.ler_peso`
  (`src/hardware/dispositivos.py`) nunca foi testado fora do código.
- **Qt dos módulos de operação**: alinhar `src/ui_qt/caixa.py` com o Tk: impressão por setor (Cozinha/Bar), "Dividir
  conta", balança automática, "Rodízio", perfil do estabelecimento, corte das garotas (botão Comissões e aba do painel)
  e agora o pré-pago.
- Qt (`src/ui_qt/`, opt-in) ainda tem a regra antiga do acerto da garota (`_acerto_so_de_shows`, `comissao.py`) e o
  recibo/comprovante com o tipo antigo (letra normal); o texto do recibo já vem sem os lançamentos. Alinhar com o Tk se o
  Qt for substituir o Tk. O painel Qt do balcão/comandas também não foi redimensionado.
- Titular: conferir na prática o tamanho dos cartões (184x126) e da faixa (`ALTURA_FAIXA = 52`), e a letra do recibo na
  impressora real; ajustar as constantes se precisar.
- Titular: instalar o Google Drive para computador, escolher a pasta na aba Backup do WillPDV Licenças e anotar a senha
  da chave.
- Ideia aberta (pede OK do titular, regra de licença): renovar a partir do vencimento atual para o cliente não perder
  dias.
- Homologar em cópia do banco, com periféricos reais: comissão/acerto/saída, gaveta, teclado/escala. Backup do PDV:
  escolher pasta e senha no caixa e ensaiar recuperação em outra máquina.
- Asaas (quando houver nuvem): homologar sandbox/credenciais/webhook e hospedar API e `python -m backend.worker_asaas` sob
  supervisão; validar custos antes de contratar.
- Painel web e múltiplos caixas seguem fora de escopo.
