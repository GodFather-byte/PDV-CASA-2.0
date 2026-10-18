# HANDOFF

## Último trabalho
- **Split de conta** (segundo módulo do ecossistema de operação, depois de Cozinha/Bar):
  divisão guiada do pagamento por pessoa, direto na tela de pagamento do caixa. Decisão com
  o titular: fluxo guiado (pergunta em quantas partes, calcula o rateio e vai guiando parte
  por parte), não calculadora solta nem divisão por item consumido (isso exigiria mudança de
  esquema — ver Pendências). **Sem mudança de esquema**: lançar vários pagamentos (formas e
  valores diferentes) na mesma venda já funcionava (`adicionar_pagamento`/`liquidar`); faltava
  só a conta de dividir.
  - `CaixaController.dividir_restante(venda_id, partes)` (`src/controllers/caixa_controller.py`,
    perto de `liquidar`): divide `liquidar()['falta']` (não o total bruto — se já tem pagamento
    lançado, divide só o que falta) em N partes iguais, em centavos, sem perder nem sobrar
    (`LIMITE_PARTES_DIVISAO = 30`, erro de digitação acima disso).
  - `src/ui/caixa_pagamento.py` (`JanelaPagamento`): botão "Dividir conta" (some na caderneta/
    crédito), estado `_divisao`/`_parte_atual`. Pergunta as partes (`tema.pedir_numero`), sugere
    o valor de cada parte em `_sugerir_valor` (guarda no topo: durante a divisão, a parte manda,
    não a falta inteira), avança em `_lancar_valor` a cada pagamento lançado, sai do modo guiado
    se um pagamento é removido no meio (`_remover_pagamento`) — simples e previsível, sem tentar
    "voltar" para a parte certa. O operador ainda digita no mesmo campo de valor de sempre, então
    pode mudar o valor de uma parte específica (ex.: uma pessoa paga mais) sem nenhum código
    extra. `fechar_venda`/`CaixaController.fechar` não mudaram: a divisão só lança pagamentos
    normais, o fechamento já sabia liquidar vários.
  - Testes: `tests/test_caixa.py` (`TesteDividirConta`, regra pura) e `tests/test_ui.py`
    (`TesteFluxosCaixa`, fluxo completo com o robô — 3 casos: divide e fecha, cancela ao remover
    no meio, divide só o que falta depois de um pagamento parcial).
  - Nota de robô (reafirma a do HANDOFF anterior): clicar em "Dividir conta" **dentro** do
    callback de `JanelaPagamento` trava o Dialogo da pergunta de partes — precisa de
    `j.after(30, lambda: clicar(...))` para rodar fora do `_tick` atual. E nunca `assert` dentro
    do callback do Tk: uma exceção lá só é impressa (não reprova o teste) — grave num dict e
    confira depois do `sem_travar()`.
  - **Qt (`src/ui_qt/caixa.py`) NÃO recebeu "Dividir conta"** — mesmo padrão já registrado para
    Cozinha/Bar: o piloto Qt segue sem os módulos de operação novos.

## Pendências
- **Qt dos módulos de operação**: alinhar `src/ui_qt/caixa.py` com o Tk — nem o roteamento de
  impressão por setor (Cozinha/Bar) nem "Dividir conta" (Split) foram portados. Mesma observação
  de sempre sobre o acerto da garota no Qt (ver linha abaixo).
- **Próximos módulos de operação** (mesma convenção documentada em `config_controller.py` e
  `docs/ESPECIFICACAO.md`, cada um como fatia independente, não implementados ainda):
  - **Rodízio por pessoa**: cobrança fixa por pessoa no fechamento da conta (não em
    `itens_venda`); `usar_rodizio` + valor configurável; decidir como interage com
    desconto/serviço em `CaixaController.fechar`.
  - **Venda por peso**: `produtos.balanca` já existe; falta o fluxo de pesagem no caixa ligado à
    balança (`src/hardware/dispositivos.py`) atrás de `usar_venda_peso`.
  - **Split por item consumido** (evolução do split atual, só se o titular quiser depois): cada
    pessoa paga o que pediu, não uma fração igual — exige marcar os itens de cada pessoa
    (mudança de esquema, provavelmente uma tag/grupo em `itens_venda`); por ora o split cobre só
    divisão em partes (iguais ou ajustadas à mão), que já atende o caso comum.
- Qt (`src/ui_qt/`, opt-in) ainda tem a regra antiga do acerto da garota (`_acerto_so_de_shows`,
  `comissao.py`) e o recibo/comprovante com o tipo antigo (letra normal); o texto do recibo já
  vem sem os lançamentos. Alinhar com o Tk se o Qt for substituir o Tk. O painel Qt do
  balcão/comandas também não foi redimensionado.
- Titular: conferir na prática o tamanho dos cartões (184x126) e da faixa (`ALTURA_FAIXA = 52`),
  e a letra do recibo na impressora real; ajustar as constantes se precisar.
- Titular: instalar o Google Drive para computador, escolher a pasta na aba Backup do WillPDV
  Licenças e anotar a senha da chave.
- Ideia aberta (pede OK do titular, regra de licença): renovar a partir do vencimento atual para
  o cliente não perder dias.
- Homologar em cópia do banco, com periféricos reais: comissão/acerto/saída, gaveta,
  teclado/escala. Backup do PDV: escolher pasta e senha no caixa e ensaiar recuperação em outra
  máquina.
- Asaas (quando houver nuvem): homologar sandbox/credenciais/webhook e hospedar API e
  `python -m backend.worker_asaas` sob supervisão; validar custos antes de contratar.
- Painel web e múltiplos caixas seguem fora de escopo.
