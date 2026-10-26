# HANDOFF

## Estado

- PDV **1.9.0**, esquema **30**. **A interface do PDV é só Qt (PySide6).** O Tk do PDV foi removido
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
- **Comanda sem nada lançado fecha (casas com garotas):** qualquer comanda (não mesa) vazia pode ser fechada: o botão
  Fechar venda fica habilitado, e F12/Enter/Receber não travam mais no aviso "Lance ao menos um item". Qualquer número vale
  como garota (o cadastro é opcional). Com shows ligados e garota cadastrada ativa abre o acerto dos shows (como sempre)
  e, desistindo, pergunta se é para só fechar; senão pede confirmação (sem cadastro a pergunta lembra o código 1002 para
  cliente sem consumo). Mesa vazia e casa sem o módulo das garotas continuam pedindo item
  (`JanelaCaixa._fechar_comanda_da_garota_vazia`). **Correção (o que ainda travava no balcão):** com shows ligados (padrão)
  e garota cadastrada, a janela do acerto (`DialogoAcerto`) recusava Pagar sem shows ("informe os shows"). Agora, como no
  Tk, o primeiro Pagar avisa e o segundo fecha a conta dela sem valor (`zerado` -> `comissoes.pagar(permitir_zerado=True)`,
  recibo de acerto R$ 0,00). E todo acerto feito pelo F12 numa comanda sem consumo (zerado, só shows ou só comissão) fecha a
  comanda junto (`_acertar_e_fechar_comanda` / `_tirar_comanda_vazia`); antes ela ficava aberta e vazia nos cartões.
  Testes em `tests/test_qt_comanda_garota_vazia.py` usam a janela real do acerto (os antigos a trocavam por um valor pronto).
- **Acerto da garota (Qt), repaginado:** a janela do acerto (F12 na comanda dela) tem o campo **Nome dela** (vem do cadastro,
  pode digitar ou trocar). O nome vai só para o acerto (`acertos_garotas.nome`, esquema 30), o recibo, a sangria e os shows do
  fechamento; o cadastro não muda (o número da comanda pode ser de outra garota em outra noite). Shows continuam no mesmo
  lugar (o cursor começa neles). O recibo e o comprovante de saída voltaram a sair com o estilo `recibo_garota`/`saida_garota`
  (linhas da garota, título, data, totais e "Conta fechada" em dobro de altura); o Qt mandava como `comprovante` comum.
- **Enter/F12 na comanda vazia da garota abre SEMPRE o acerto:** antes só abria com garota cadastrada, ativa e shows ligados;
  sem cadastro (o comum: o número basta) só perguntava se fechava, sem tela para os shows. Agora `_fechar_comanda_da_garota_vazia`
  chama o acerto direto (shows, nome, vale, Pix ou conta zerada) e, no Esc, pergunta se é só fechar. `pagar_garota` não recusa
  mais garota sem comissão; o botão "Pagar garota" aparece em toda comanda vazia (casa com garotas) e também fecha a comanda.
  Nos testes, `BaseCaixaQt.janela` troca a janela modal do acerto por um "desistiu" que anota em `j.acertos_abertos`.
- **Comanda com comissão fica rosa:** `cores_do_cartao` (painel_mesas.py) pinta de rosa o cartão da comanda com comissão a
  pagar (com ou sem consumo); a pílula continua com a situação. O "Parada" ficou avermelhado para não confundir com o rosa.
- **Código + Enter leva à quantidade (como no Tk):** Enter no código escolhe o produto, mostra nome e preço e leva ao
  campo da quantidade (selecionada); o segundo Enter (ou o botão Lançar) lança. Direto, sem pausa: "6*código", modo
  leitor (F3) e produto de balança (pesa). `JanelaCaixa.lancar_item(pedir_quantidade=True)`. Esc desiste do produto.
- **Forma de pagamento recomeça em Dinheiro** a cada venda: ao fechar a venda e ao trocar de comanda
  (`JanelaCaixa._forma_padrao`); dentro da mesma venda a escolha fica.
- **Caixa mais legível e em tela cheia:** valor recebido (16pt) e troco (22pt) maiores, forma de pagamento em letra
  maior, painel direito com 360px. O caixa abre em tela cheia (config `caixa_tela_cheia`, padrão "S", em Configurações >
  Aparência); Ctrl+F alterna, botões "Tela cheia" e "Fechar caixa" no cabeçalho (`JanelaCaixa.aplicar_tela_cheia`, chamado
  por `abrir_caixa` em `app.py`). Modo claro com contornos mais definidos (quadros, botões, campos e cartões das mesas).
- **Pendente:** seletor de forma em botões grandes (1 Dinheiro, 2 Débito...). Foi feito e retirado: qualquer versão de um
  `QWidget` próprio no lugar do `QComboBox` do caixa fazia o job Linux/Python 3.10 abortar no encerramento do processo
  (`munmap_chunk(): invalid pointer`, na coleta de lixo, depois de todos os testes passarem; Python 3.12 e Windows passavam).
  Retomar depurando num Python 3.10 com Tk+Qt (ver PR #24, commits `f848ae0` a `8315eec`).
- Não portado ainda: a opção `painel_mesas_fixo` (o Qt sempre mostra o painel).

## Edição E&A Superações (PDV só de adega)

- O mesmo código gera duas edições (`src/core/edicao.py`): **WillPDV** (completo, igual a antes) e **E&A Superações**
  (adega). A palavra "edição" foi escolhida porque "produto" no código é item à venda.
- Qual roda: variável `PDV_EDICAO`; no executável, `edicao.txt` ao lado do .exe (fase 3 grava no build); senão WillPDV.
  Do código-fonte: `python -m src.app --edicao ea_superacoes` ou `iniciar_ea_superacoes.bat`.
- A adega: marca, logotipo e ícone próprios (`instalador/ea-superacoes-logo.png` e `.ico`, com a grafia corrigida para
  SUPERAÇÕES), pasta de dados `%LOCALAPPDATA%\EA-SUPERACOES` no executável, perfil Adega aplicado na primeira entrada
  (`edicao.preparar`, chamado em `App.iniciar`; marca `edicao` no config), mesas/garotas/portaria/rodízio/pré-pago sempre
  desligados (voltam a N a cada entrada e `salvar_config` recusa ligar), opções de mesas/garotas/comissão/portaria fora das
  Configurações, sem o botão Cozinha/Bar no menu e sem o botão Comissões no caixa (este some em qualquer casa sem garotas).
- **Fase 3 (feita):** `python build_pdv.py --edicao ea_superacoes` gera `dist/EASuperacoes/EASuperacoes.exe` (com `edicao.txt`,
  ícone e logotipo no pacote) e `instalador/saida/EASuperacoes-Setup-<versão>.exe` (`instalador/EASuperacoes.iss`, `AppId`
  próprio, instala ao lado do WillPDV, imagens `ea-superacoes-assistente*.bmp`). O CI (`build-windows.yml`) tem o job `adega`
  (autoteste no .exe e no instalado, instalação silenciosa, atualização por cima com o programa aberto) e publica na Release
  `ultima-versao-adega`. O autoteste agora mostra a edição e confere se a marca dela veio no pacote.
- **Licença por edição:** o código assinado leva o campo `edicao` (só nas licenças da adega; as do WillPDV continuam
  idênticas). `licenca.ativar`/`estado` recusam licença de outra edição. Emissão: WillPDV Licenças (escolha do programa na aba
  Emitir; coluna Programa nas lojas; conferência mostra o programa) e `python -m tools.gerar_licenca emitir --edicao ea_superacoes`.
  Limites: versões antigas do WillPDV não conhecem o campo e aceitariam uma licença da adega; a **central do Telegram**
  (`licenciador/central.py`) ainda emite só licença do WillPDV, então um caixa E&A com a ponte ligada recusaria a renovação
  automática (emitir pelo WillPDV Licenças até a central saber a edição de cada caixa).
- Conferir no Windows real: o "&" do nome no assistente do Inno (pode aparecer sublinhado) e o ícone no .exe.
- Cupom continua NÃO FISCAL (confirmado pelo dono); NFC-e não está ativa.

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
