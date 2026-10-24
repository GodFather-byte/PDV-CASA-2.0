# HANDOFF

## Estado

- PDV **1.9.0**, esquema **29**. **A interface do PDV é só Qt (PySide6).** O Tk do PDV foi removido
  (`src/ui/` apagado; o histórico está no git). `python -m src.app` abre o Qt; `--qt`/`--tk` não existem.
- **Gerador de licenças (`licenciador/`) continua em Tkinter**, por decisão do dono. Ele guarda seus próprios
  `tema.py`, `icone.py` e `paleta.py`. É a única parte do repositório que ainda precisa de tkinter
  (o CI instala `python3-tk` e usa xvfb só por causa dele).
- Peças que viviam em `src/ui/`: `Contexto` em `src/controllers/contexto.py`, leitura de valor do pagamento em
  `src/core/valor_pagamento.py`, `entregar_via` em `comissao_controller.py`.
- `--autoteste` confere módulos, bibliotecas (Qt/SQLite/SSL), telas Qt e backup criptografado;
  `--autoteste-qt` é alias (o CI do build usa). Instalador sem atalho "Qt (prévia)"; janelas com o ícone do WillPDV.
- Devoluções/trocas, fechamento explicativo, homologação isolada, backup verificável, diagnóstico de hardware e
  Telegram agendado (23h): ver `docs/MELHORIAS_1_9.md`, `docs/DEVOLUCOES.md`, `docs/FECHAMENTO_EXPLICATIVO.md`.

## Painel de cartões da boate (restaurado no Qt)

- Ao remover o Tk, o caixa Qt perdeu os cartões coloridos de mesas/comandas (ficou só uma lista). Foram
  portados de `src/ui/painel_mesas.py` (git: commit `7e26f04`): modelo em `src/controllers/mesas_modelo.py`
  e painel em `src/ui_qt/painel_mesas.py` (cartões, faixa do balcão, pílulas de situação, selo da garota,
  busca, abas, setas/Enter/T/dígitos). Painel escuro no modo escuro e claro no claro. A boate já é o perfil de
  fábrica (`PerfilController.PADRAO`). Colunas por largura da janela (1/2/3).
- **Visual noturno da boate:** o caixa Qt era meio claro/meio escuro (rótulos quase invisíveis). Agora usa
  `ESTILO_NOITE` (azul-marinho, destaques neon) no modo escuro e o estilo claro no modo claro
  (`JanelaCaixa._aplicar_estilo`). O menu principal ganhou a faixa "noite ao vivo" (posições abertas, aguardando
  acerto, em aberto na casa, comissões a pagar) para casas com mesas (`JanelaPrincipal._atualizar_noite`).
- **Claro/escuro escolhido pelo cliente:** botão "Mudar para o modo claro/escuro" no topo do menu
  (`JanelaPrincipal.alternar_tema`); grava `tema_visual`, aplica no programa todo e refaz o caixa aberto na hora.
  A mesma opção continua em Configurações > Aparência.
- **Esc/F4 no caixa (como no Tk):** Esc desfaz o que está digitado (comissão, código, quantidade); sem nada
  pendente volta ao "marcar comanda" (cartões recarregados e campo da posição selecionado); no campo da posição
  volta ao balcão e a mesa continua aberta; nos cartões volta ao campo da posição (`JanelaCaixa.esc_caixa`).
- **Fechamento de caixa no modelo clássico (Qt):** "Trocar turno" volta a seguir o fluxo do Tk: conferir a
  maquininha (forma/qtd/valor, sem o dinheiro esperado) -> valor da gaveta -> confirmação com os avisos (mesas
  abertas, comissão a pagar) -> conferência por forma -> fecha, backup, impressão das vias -> resumo
  `PainelFechamento` (SOBRA/FALTA/CAIXA CONFERIDO, Imprimir, Gera Arquivo Texto, Conferência do turno). A página
  de fechamento do Qt foi removida (`PAGINA_FECHAMENTO` não existe mais).
- **Trocar de comanda pelas setas:** com o código vazio, ← → (ou ◀ ▶, PgUp/PgDn) vão à comanda anterior/seguinte
  da lista dos cartões (respeita aba e busca); Esc volta a "marcar comanda". `JanelaCaixa.navegar_comanda`.
- **Enter fecha a conta (como no Tk):** com o código vazio, Enter vai ao pagamento (`JanelaCaixa.ir_para_pagamento`):
  forma (setas, número 1-9 ou inicial; Enter confirma) -> valor (já sugerido) -> Enter lança -> Enter fecha. Conta
  já paga: Enter fecha direto. Pagamento parcial volta à lista de formas. Esc volta um passo (valor -> forma -> itens).
- **Fechar o turno sem digitar forma por forma:** `ir_para_fechamento` não usa mais `ui_qt/fechamento.coletar`
  (continua no código, sem uso no caixa). Fluxo: tela "Conferir maquininha" (totais de débito/crédito/Pix e cada
  lançamento, `TurnoController.maquininha_lancamentos`; botão "Confere com a maquininha") -> só o valor da gaveta ->
  confirmação -> se a gaveta tiver diferença, pede o motivo -> fecha. Cartão/Pix entram como informados = lançados
  (o operador confirmou na tela da maquininha); com cheque/ticket físico no turno só a gaveta é declarada. O resumo
  final ganhou o quadro "Conferir na maquininha" (qtd e valor por forma e total).
- **Modo claro mais confortável:** fundo cinza-azulado (#e8ecf1), cartões off-white (#f5f7fa), texto grafite
  (#1e2a3c), bordas suaves e cartões das mesas em tons pastel mais calmos (`tema.py`, `caixa.py`, `painel_mesas.py`).
- **Comanda da garota sem nada lançado fecha:** F12/Enter na comanda de uma garota cadastrada, sem consumo nem comissão
  marcada, não trava mais no aviso "Lance ao menos um item". Com shows ligados e garota ativa abre o acerto dos shows
  (como sempre) e, se desistir dele, pergunta se é para só fechar; senão pede confirmação e libera a comanda
  (`JanelaCaixa._fechar_comanda_da_garota_vazia`). Comanda de cliente vazia continua pedindo item (a saída é o 1002).
- **Código + Enter leva à quantidade (como no Tk):** Enter no código escolhe o produto, mostra nome e preço e leva ao
  campo da quantidade (selecionada); o segundo Enter (ou o botão Lançar) lança. Direto, sem pausa: "6*código", modo
  leitor (F3) e produto de balança (pesa). `JanelaCaixa.lancar_item(pedir_quantidade=True)`. Esc desiste do produto.
- **Forma de pagamento recomeça em Dinheiro** a cada venda: ao fechar a venda e ao trocar de comanda
  (`JanelaCaixa._forma_padrao`); dentro da mesma venda a escolha fica.
- Não portado ainda: a opção `painel_mesas_fixo` (o Qt sempre mostra o painel).

## Testes

- Os testes de telas Tk foram removidos por script (classes/métodos que citavam tkinter, `src.ui`, `ui_robo`).
  Regras que só eram testadas em tela Tk foram repostas em `tests/test_regras_recuperadas.py` (vias do
  fechamento 1-3, nome da casa obrigatório, alerta de gaveta no Qt).
- **Ainda sem teste equivalente confirmado** (ver `git show 4e6e6d2 -- tests/`): falha de impressão não duplicar
  devolução; ticket de saída 1002 disparado no pagamento; comissão com garota inativa/sem turno; primeiro
  acesso/perfil; exclusão em massa só com a palavra de confirmação; aviso de giro de caixa sem venda.
- CI verde no PR #16 (Linux e Windows, Python 3.10 e 3.12).

## Pendências para produção

- **Homologar o Qt no balcão** (teclado, impressora, falta de papel, gaveta, balança, leitor) antes do novo
  Setup: não existe mais interface de reserva.
- **Gerar o Setup/ZIP 1.9** e validar numa cópia do banco. Outra pasta de instalação não isola
  `%LOCALAPPDATA%\WILL-PDV`: use `PDV_DB` apontando à cópia, uma instância por banco.
- Devolução não atende pré-pago nem rodízio; externo é declaração, não estorno bancário; sem crédito de troca.
- Bruto, CMV e comissões históricos não são estornados por devolução (relatórios deixam isso explícito).
- Impressão física não tem garantia exactly-once; estado `incerto` exige conferência humana.
- Bot Telegram precisa estar ativo, com token e dono pareado. Central/licenças pedem ensaio real; preservar a
  ponte Render/Neon. Cobrança Asaas, iFood e NFC-e SP não estão ativas. Substituir credenciais expostas antes.
