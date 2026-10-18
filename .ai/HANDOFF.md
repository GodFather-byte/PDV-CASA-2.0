# HANDOFF

## Último trabalho
- Pedido do titular (Tk, a interface em uso; o piloto Qt não foi alterado, ver Pendências):
  - **Fechar a conta da garota sem comissão**: F12 na comanda vazia abre o acerto (só shows, ou fechar sem valor)
    para garota cadastrada e ativa; inativa ou fora do cadastro pergunta antes ("Acertar a garota"); Não mantém o
    aviso "Lance ao menos um item". Sem comissão, os shows aparecem mesmo com `comissao_pede_shows = N`. Fechar sem
    comissão e sem shows pede confirmação e grava acerto de R$ 0,00 (`ComissaoController.pagar(..., permitir_zerado=True)`;
    sem a flag continua recusado, então clique repetido não duplica). Código: `src/ui/caixa_ui.py`
    (`_acerto_sem_comissao`), `src/ui/comissao_ui.py` (`dialogo_pagar`, `pagar_garota`).
  - **Recibo da garota** (`ImpressaoController.recibo_comissao`): sem as linhas "lançamento N" (só quantidade e total);
    recibo e comprovante de saída da garota saem com linhas importantes em dobro de altura (tipos `recibo_garota` e
    `saida_garota` em `_ESTILOS`; a sangria comum, tipo `comprovante`, não mudou).
  - **Painel de comandas** (`src/ui/painel_mesas.py`): cartões 204x146 -> 184x126; o Balcão virou uma faixa fina na
    largura toda acima da grade (`_celula`, `_vertical`; setas passam pela faixa; busca que esconde o balcão tira a faixa).
- Testes: `tests.test_comissao_na_tela`, `test_acerto_garota_shows`, `test_tela_caixa_cartoes` e `test_ui` ajustados/novos.
  Nota: o robô de testes (`tests/ui_robo.py`) não suporta clicar, dentro do callback, num botão que abre outro diálogo; use
  `w.after(30, lambda: clicar(...))`.
- Antes disso (em `main`): WillPDV Licenças 1.1.0 (aviso de vencimentos, aba Backup/Google Drive) e a força-tarefa Qt
  opt-in (ver `docs/INTERFACE_QT.md`). Cobrança segue **manual**; nuvem/worker adiados (trabalho guardado na branch
  `claude/quirky-rubin-pgs2el`, commit `cb10681`).

## Pendências
- Qt (`src/ui_qt/`, opt-in) ainda tem a regra antiga do acerto da garota (`_acerto_so_de_shows`, `comissao.py`) e o
  recibo/comprovante com o tipo antigo (letra normal); o texto do recibo já vem sem os lançamentos. Alinhar com o Tk se o Qt
  for substituir o Tk. O painel Qt do balcão/comandas também não foi redimensionado.
- Titular: conferir na prática o tamanho dos cartões (184x126) e da faixa (`ALTURA_FAIXA = 52`), e a letra do recibo na
  impressora real; ajustar as constantes se precisar.
- Titular: instalar o Google Drive para computador, escolher a pasta na aba Backup do WillPDV Licenças e anotar a senha da chave.
- Ideia aberta (pede OK do titular, regra de licença): renovar a partir do vencimento atual para o cliente não perder dias.
- Homologar em cópia do banco, com periféricos reais: comissão/acerto/saída, gaveta, teclado/escala. Backup do PDV:
  escolher pasta e senha no caixa e ensaiar recuperação em outra máquina.
- Asaas (quando houver nuvem): homologar sandbox/credenciais/webhook e hospedar API e `python -m backend.worker_asaas`
  sob supervisão; validar custos antes de contratar.
- Painel web e múltiplos caixas seguem fora de escopo.
