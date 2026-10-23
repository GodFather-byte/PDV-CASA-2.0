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
- Não portado ainda: PgUp/PgDn para navegar entre comandas; a opção `painel_mesas_fixo` (o Qt sempre mostra o painel).

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
