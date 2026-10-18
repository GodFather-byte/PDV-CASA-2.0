# HANDOFF

## Último trabalho
- **Rodízio por pessoa** (quarto e último módulo planejado do ecossistema de operação, depois de
  Cozinha/Bar, Split de conta e Venda por peso — todos em `main`). Decisões fechadas com o
  titular (AskUserQuestion): (1) só os produtos de subgrupo marcado "incluso no rodízio" entram
  no preço fixo — bebida e extras continuam cobrados por item, normalmente; (2) é **opt-in por
  mesa/comanda**, não geral — o módulo liga a funcionalidade, cada mesa decide se é rodízio (a
  casa pode ter mesa à la carte e mesa rodízio ao mesmo tempo).
  - Esquema v20: `subgrupos.rodizio_incluso` (flag, igual padrão de `impressora_remota`),
    `vendas.rodizio` (opt-in da mesa) e `vendas.rodizio_total_cent` (**persistido**, mesmo
    motivo de `desconto_cent`/`servico_cent` já serem: preço mudar no mês seguinte não pode
    alterar o total de uma venda já fechada).
  - `CaixaController.calcular()` (o ponto mais arriscado da fatia, usado por **toda** venda):
    quando `rodizio=0` (padrão, toda venda hoje) o resultado é bit-a-bit igual a antes — testado
    explicitamente (`TesteRodizio.test_calcular_sem_rodizio_e_identico_a_hoje`). Com `rodizio=1`:
    subtotal = itens NÃO inclusos + (pessoas × `valor_rodizio_pessoa`); serviço incide sobre os
    dois; consumação mínima (`complemento_consumacao`) não se aplica a mesa em rodízio.
    `itens()` ganhou a coluna `s.rodizio_incluso` (join com `subgrupos`) para `calcular()` saber
    o que filtrar — item mantém o preço normal do cardápio gravado (não zera nada: preserva CMV
    e histórico), a diferença é só no total.
  - `CaixaController.ativar_rodizio(venda_id, pessoas)` / `desativar_rodizio(venda_id)`: exige
    `usar_rodizio` ligado e modalidade mesa; `pessoas >= 1`.
  - Ação "Rodízio" na barra de tarefas do caixa (`caixa_ui.py`, ao lado de Delivery/Caderneta,
    mesmo padrão `desligados` de módulo); pergunta quantas pessoas (0 desliga o rodízio daquela
    mesa). `_detalhe_total` (tela) e `_totais` (cupom/pré-conta, `impressao_controller.py`)
    ganharam a linha "Rodízio: N pessoa(s)".
  - Sem entrada em `MODULOS_OPCIONAIS`: não há item de menu novo (reaproveita o Cadastro de
    Subgrupos existente + um botão na barra do caixa).
  - Testes: `tests/test_esquema_v20.py`, `TesteRodizio` em `tests/test_caixa.py` (7 casos,
    incluindo o de regressão do `calcular()` sem rodízio e o do total congelado após fechar),
    caso em `TesteFluxosCaixa` (`test_ui.py`) ponta a ponta com a barra de tarefas, casos em
    `TesteModulosNaTela` (`test_modulos.py`) e em `TesteImpressao` (`test_gestao.py`, linha do
    cupom).
  - **Qt (`src/ui_qt/caixa.py`) não recebeu nada disto** — mesmo padrão já registrado para os
    três módulos anteriores.
  - De passagem, corrigido um teste antigo (`test_esquema_v19.py`) que comparava
    `VERSAO_ESQUEMA` com um número fixo (`19`) — quebrava a cada nova migração. Removido dos
    dois arquivos de migração (v19 e v20); só `PRAGMA user_version` é conferido.

## Pendências
- Os quatro módulos de operação planejados com o titular estão feitos. Possíveis evoluções,
  nenhuma pedida ainda:
  - **Split por item consumido**: cada pessoa paga o que pediu, não uma fração igual — exige
    marcar os itens de cada pessoa (mudança de esquema).
  - **Rodízio com preço por faixa** (adulto/criança, dia da semana): hoje é um valor único global
    (`valor_rodizio_pessoa`); se precisar, decidir o desenho com o titular antes de mudar o
    esquema (não é só trocar um número — `vendas.pessoas` teria que virar mais de um campo).
  - **Venda por peso com etiqueta de balança** (código de barras com peso/preço embutido, para
    casa com estação de pesagem separada do caixa — padaria/açougue/mercado maiores): hoje o
    caixa só pesa na hora (F2 ou automático no produto "Balança"); não há leitura de código de
    barras de peso variável (prefixo 2, formato EAN de peso embutido). Maior esforço; só vale a
    pena se o titular tiver esse tipo de equipamento/operação.
- **Homologar a balança com equipamento real** (Toledo ou Filizola, porta serial): o protocolo em
  `Balanca.ler_peso` (`src/hardware/dispositivos.py`) nunca foi testado fora do código.
- **Qt dos módulos de operação**: alinhar `src/ui_qt/caixa.py` com o Tk — roteamento de impressão
  por setor (Cozinha/Bar), "Dividir conta" (Split), acionamento automático da balança e "Rodízio"
  não foram portados. Mesma observação de sempre sobre o acerto da garota no Qt (ver linha
  abaixo).
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
