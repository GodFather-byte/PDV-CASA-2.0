# Especificação: manuais × implementação

Fontes: **MANUAL ADM LOCAL** (administração do Willyan), **MANUAL CAIXA** (operação de
venda) e o manual da **versão web**. Este documento liga cada seção dos manuais ao código,
registra as decisões tomadas onde o manual não definia a regra e lista o que **não** foi feito.

Convenção: `C` = controlador (regra, em `src/controllers/`), `UI` = tela (em `src/ui/`), `T` = teste.

## 1. Mapa dos manuais

### MANUAL ADM LOCAL

| Seção | Assunto | Implementação |
|------|---------|---------------|
| 1 | Entrada (usuário/senha, ADM/ADM, sem diferenciar maiúsculas, "Senha Incorreta", nível 0 vai ao caixa), menu com 7 botões e painel | C `acesso_controller` · UI `login`, `app` (atalhos M, C, L, R, U, O, S) |
| 2 | Botões de tarefas (Incluir, Excluir, Gravar, Cancelar, Filtrar, Pesquisar, Ordenar, Tela, Imprimir, navegação, Sair) | UI `cadastros_tk` |
| 3.1 a 3.3 | Unidades, grupos, subgrupos (impressora remota) | `entidades.py` · C `cadastro_controller` |
| 3.4 | Produtos: código de 13 dígitos, barras, serviço, decimal, estoque mínimo, dividir em 1 a 55, maior, montagem, promoções, fiscais | `entidades.py` · C `produto_controller` (preço vigente, busca) |
| 3.5 | Composição (ficha técnica) e custo | C `produto_controller` · UI `composicao_ui` |
| 3.6 a 3.9 | Cargos, operadores (senha até 10), fornecedores, clientes (+ "Gerar arquivos") | `entidades.py` · UI `cadastros_tk` |
| 3.10 | Tipos de pagamento (ordem, caixa, emite vale, troco, saldo inicial, TEF) | `entidades.py` |
| 3.11 e 3.12 | Plano de contas e sub planos (modelo já carregado) | `entidades.py` · `sementes.py` |
| 5.1 | Lançamento de contas | C `contas_controller` · UI `lancamentos_ui` |
| 5.2 | Estoque: compra, entrada, saída, descarte, contagem | C `estoque_controller` · UI `lancamentos_ui` |
| 6.01 e 6.02 | Venda no período (cupom a cupom, totalização na fita ou A4) e por grupo | C `relatorio_vendas` · UI `relatorios_ui` |
| 6.03 a 6.06 | Entradas/saídas do caixa, fechamentos, comandas, garçons | C `relatorio_vendas` |
| 6.07 | C.M.V. | C `relatorio_vendas.cmv` |
| 6.08 a 6.11 | Clientes inativos e comissões (produto, venda, cliente) | C `relatorio_gestao`, `relatorio_vendas` |
| 6.12 a 6.14 | Resultado financeiro, extrato de contas, movimento de estoque | C `relatorio_gestao` |
| "6.11" | Estoque atual (verde/amarelo/vermelho, filtros por data e valor, formulários de contagem e pedidos) | C `relatorio_gestao.estoque_atual` · UI `JanelaEstoqueAtual` |
| 7.01 a 7.03 | Limpeza do movimento, programa de comunicação, backup | C `utilitario_controller` · UI `utilitarios_ui` |
| 8.01 | Níveis de acesso 0 a 4 por módulo | C `acesso_controller` · UI `config_ui` |
| 8.02 a 8.04 | Loja, configurações, máquinas | C `config_controller` · UI `config_ui` |
| 9 | Saída (volta à tela de entrada) | UI `app.sair` |

### MANUAL CAIXA

| Assunto | Implementação |
|---------|---------------|
| Abertura do turno (nº do turno, fundo de caixa, "Confirma Valor Inicial?") | C `turno_controller.abrir` · UI `caixa_dialogos.abrir_turno` |
| Lançar item: código, quantidade, Enter; lista por nome; Consultar; observação (tecla O) | UI `caixa_ui` · C `caixa_controller.adicionar_item` |
| Cancelar item e venda inteira; senha de supervisor | UI `caixa_ui.menu_cancelar` · C `acesso_controller.validar_supervisor` |
| Pagamento (F12): formas, múltiplos pagamentos, desconto % e valor, serviço editável, troco, contra-vale | UI `caixa_pagamento` · C `caixa_controller.liquidar/fechar` |
| Comissão das garotas (código 50), na tela do caixa; via da garota; pagamento com recibo, cadastro e relatório | C `comissao_controller`, `relatorio_comissoes`, `impressao_controller.via_comissao` · UI `comissao_ui`, `caixa_ui`, `painel_mesas` |
| Mesas e comandas (F4, `123` e `M5`), transferir inteira (F10), várias (T) e parte dos itens, pré-conta (F8), tempo de inatividade | C `caixa_controller`, `core/posicao` · UI `caixa_ui` |
| Repique (F9), sangria (F7), gaveta (F11), balança (F2), leitor óptico (F3) | UI `caixa_ui` · `hardware/dispositivos.py` (interfaces) |
| Caderneta (F5): escolher/incluir/consultar cliente, débito, crédito, excedente vira crédito | C `caderneta_controller`, `caixa_controller` · UI `clientes_ui` |
| Entrega (F6): taxa por bairro, troco para quanto, entregador (E), pendentes | C `entrega_controller` · UI `clientes_ui`, `caixa_ui` |
| Troca de turno: valor declarado antes do esperado, sobra/falta verde ou vermelho, imprimir e gerar arquivo; conferência (posições abertas, cancelamentos, transferências); fechamento impresso sozinho com sobra/falta, sangrias e assinaturas | C `turno_controller`, `conferencia_turno`, `impressao_controller.fechamento` · UI `caixa_dialogos` (`trocar_turno`, `imprimir_fechamento`, `PainelFechamento`) |
| Consulta de comanda na saída e alerta de sangria (acréscimos nossos, de boate) | C `caixa_controller.situacao_posicao`, `turno_controller.dinheiro_esperado` · UI `caixa_ui` |
| Leitura X e Redução Z | **Gerenciais, não fiscais** (ver seção 3) |

### Manual da versão web

Aproveitado no PDV local: estoque Inicial, Pedido (vira Compra ao confirmar a entrega) e Descarte de
acabados; contas mensais; transferência entre contas; relatórios Informativo, Horas, Cancelados,
Custo médio, Clientes e Financeiro; campos de produto `compõe`, `composto`, `manual`, `automático`.
O sistema web em si (cadastros e relatórios no navegador) é outra aplicação e fica em `backend/`.

## 2. Decisões onde o manual era ambíguo

Estas regras foram escolhidas por quem implementou; confirme com o dono da loja.

- **Valor esperado do turno** = valor inicial + recebimentos das formas que ficam na gaveta (dinheiro, cheque, ticket;
  já líquidos de troco) + entradas − sangrias. Cartão e Pix NÃO entram: são conferidos na maquininha, e o relatório
  mostra o total "fora da gaveta". Cada forma de pagamento tem a marca "Fica na gaveta" (`tipos_pagamento.na_gaveta`;
  cartão, Pix, transferência e TEF saem de fábrica). Repique e contra-vale emitido são informativos e não entram.
  (O exemplo do manual não incluía as sangrias no esperado; aqui elas reduzem o esperado porque o dinheiro saiu.)
- **Dia operacional:** a noite da boate atravessa a meia-noite, então o "vendas do dia" da tela principal, os relatórios
  de vendas por período (o período, o informativo por dia e as vendas por hora, na ordem da noite) e o painel da nuvem
  contam das 6h às 6h do dia seguinte (`virada_dia_hora` no PDV, `PDV_NUVEM_VIRADA_HORA` na nuvem; 0 volta ao dia do
  calendário). Os filtros de horário, os relatórios financeiros e os de estoque continuam pelo calendário.
- **Licença e relógio voltado:** a data de referência da licença é a maior entre hoje, a última data vista
  (`licenca_ultimo_uso`) e o movimento mais recente (venda encerrada ou turno aberto). Apagar ou editar a linha da data vista
  não reabre o prazo; seria preciso adulterar o histórico de vendas. Uma licença offline em código Python não é inviolável:
  isso só fecha o contorno fácil.
- **Cada pagamento conta no turno em que o dinheiro entrou** (`pagamentos_venda.turno_id`, esquema v9), não no turno em que a
  conta fecha: o adiantamento de uma comanda fica no turno que o recebeu (e já entra no esperado enquanto a comanda está
  aberta, porque o dinheiro está na gaveta), e o troco sai dos pagamentos do turno que fecha a conta. Turno fechado não muda
  depois: o pagamento dele não pode ser removido, e cancelar uma conta com adiantamento de turno anterior registra a
  devolução como saída do turno atual (só a parte que fica na gaveta; Pix e cartão são estornados fora do caixa).
  Juntar mesas ou comandas leva junto os pagamentos, o repique e o desconto da origem (somado ao do destino, em valor).
- **Pedidos do dono (boate, 2026-10-04):**
  - **Sem desconto** por padrão (`usar_desconto` = N): os campos somem do fechamento da conta e a linha zerada sai da fita.
  - **Cadastro da casa** no primeiro acesso de quem pode mexer na loja; o nome sai em todos os comprovantes.
  - **Código 1002** (`codigo_saida`): digitado na comanda sem consumo, libera a posição e imprime o comprovante de saída
    (casa, comanda, data, hora, turno, quem liberou); com consumo ou pagamento, recusa. As saídas entram no fechamento.
  - **Comissão em pontos** (`comissao_em_pontos`, `comissao_valor_ponto`): 0,1 = R$ 5,00, 0,2 = R$ 10,00...
  - **Pagar comissão não tira do caixa** por padrão (`comissao_paga_do_caixa` = N): fica registrada, sem sangria.
  - **Fechamento completo:** além do dinheiro, vendas por tipo (balcão, comandas, mesas), todos os produtos vendidos,
    posições abertas, cancelamentos, transferências, saídas sem consumo, comissões, sangrias e assinaturas.
- **Cupom emitido não muda:** a observação de um item só pode ser alterada com a venda aberta, e a numeração dos cupons
  nunca volta atrás, nem depois da limpeza do movimento (o último número fica em `config.ultimo_cupom_emitido`).
- **Serviço** (10% configurável) só em mesa e comanda (cada uma com sua chave: `cobra_servico_mesa` e
  `cobra_servico_comanda`), calculado sobre os itens marcados "cobrar serviço", antes
  do desconto. O desconto incide só nos produtos. O operador pode digitar outro valor de serviço, até zero.
- **Comanda = mesa com numeração própria.** É uma venda de modalidade `mesa` com `vendas.comanda = 1` (esquema v4):
  assim herda serviço, pré-conta, transferência e fechamento sem duplicar regras, e a mesa 2 e a comanda 2 coexistem
  (índice único `(comanda, posicao)` entre as abertas). Notação pedida pelo dono (boate: quase tudo é comanda): o
  **número sem letra é a comanda** (`123`) e a mesa leva `M` (`M5`); `C123` também vale. A configuração `posicao_padrao`
  (`comanda`, o padrão, ou `mesa`) escolhe o que o número sem letra significa, e a tela, as listas e os relatórios mostram a
  posição na mesma notação em que se digita (os registros internos, como as transferências do `log_eventos`, guardam sempre
  `5` e `C2`). No campo do código o número sem letra é produto; só `C123` e `M5` trocam de posição. O 0 é o balcão. O limite
  é `num_comandas` (padrão 10000, esquema v6; 0 desliga). A nuvem recebe a comanda como `mesa` (sem campo novo no contrato);
  se o dono quiser separar no painel, acrescentar `comanda` ao lote é compatível com a API atual.
- **Esc e o painel de ícones** (manual do Caixa, "Abrir e lançar itens em mesas"): Esc leva ao "marcar comanda", com o
  painel de ícones das posições abertas e o campo da posição habilitado; um segundo Esc volta ao balcão, e os dados das
  mesas abertas permanecem gravados. Os ícones seguem o manual (mesa consumindo, conta enviada com bandeja, relógio na
  parada) e foram desenhados do zero; o balcão é o primeiro ícone e cada um mostra o total (acréscimos nossos). O manual
  mostra o painel só depois do Esc; aqui ele fica sempre no rodapé (`painel_mesas_fixo = S`) e `N` volta ao do manual.
- **Conferência do turno** (fechamento e Leitura X): posições abertas (só as com consumo; vale o momento do fechamento, não
  só o turno), cupons cancelados (pelo `turno_id`) e itens cancelados e transferências (pela janela de tempo do turno, lidos
  do `log_eventos`: eventos `item_cancelado` e `transferencia`, sem tabela nova). Um item cancelado aparece no local atual
  da posição (se ela foi transferida depois, o nome novo). Só avisa: não bloqueia a troca de turno com posições abertas.
- **Comissão das garotas** (pedido do dono, boate; esquema v7): o número da garota é o da comanda dela (comanda 180 = garota
  180) e o código 50 (`codigo_comissao`) lança a comissão **na própria linha de entrada do caixa**, sem janela: "Garota nº" (o
  da comanda que está na tela, editável) e "Valor (R$)"; Enter lança, Esc cancela (`comissao_na_linha`; desligada, o 50 abre a
  janela de antes). É um registro à parte (`comissoes_garotas`), não uma venda:
  fica fora do faturamento, do estoque e da nuvem, e a comanda da garota continua vazia. Situações: pendente, paga e
  cancelada (nada se apaga). Pagar tudo o que está pendente de uma garota (F12 na comanda dela, ou o botão Comissões) registra
  uma sangria no turno (a conferência da gaveta já conta), abre a gaveta e imprime um recibo para assinar; também dá para pagar
  fora do caixa. Cancelar é Delete na linha da comissão (só pendente). **A cada lançamento sai a via da garota** (`via_comissao`:
  o valor desta comissão, as pendentes e o total a receber; `imprimir_via_comissao`): sem impressora fica só no histórico, e
  falha de impressão nunca desfaz o lançamento. As garotas com comissão a pagar viram **ícones no rodapé** (estrela; selo na
  comanda que também tem consumo; `painel_mostra_garotas`), na mesma faixa do balcão. O cadastro de
  garotas (`garotas`) é opcional e serve para mostrar o nome e pedir confirmação de número desconhecido. Ao abrir a comanda
  da garota, a lista mostra as comissões marcadas nela (pendentes de qualquer turno e as pagas neste turno, guardadas por
  `pago_turno_id`, esquema v8), em linhas só de leitura, e a faixa de cima o total a pagar; o Total da comanda segue sendo só o dos itens. O código 50 é
  reservado: nenhum produto pode usá-lo (código, atalho ou barras). **A confirmar com o dono:** se as garotas são pagas no
  fim da noite com dinheiro da gaveta (é o que fizemos) e se a comissão deve abater consumo da própria garota.
- **Fechamento para passar o caixa** (pedido do dono): ao trocar o turno o fechamento é impresso sozinho
  (`imprimir_fechamento_ao_trocar`, `vias_fechamento` de 1 a 3; sem impressora, só o botão do painel). Além dos totais traz o
  resultado em palavras e letra grande (SOBROU / FALTOU / CAIXA CONFERIDO), as sangrias e suprimentos do turno (com os pagamentos
  de comissão), a conferência do turno, o espaço da justificativa (se houve diferença) e as assinaturas do caixa responsável
  (`turnos.fechado_por`) e do gerente. Segue o modelo de passagem de caixa que se vê em sistemas de bar e boate (sobra/falta,
  justificativa e assinatura). A Leitura X é parcial e não leva resultado nem assinatura.
- **Consulta de comanda e alerta de sangria** (pesquisa sobre caixa de boate): a consulta mostra se a comanda ou mesa está paga
  (cupom, valor e hora), aberta a pagar ou sem registro, pela venda mais recente do número (o cartão é reutilizado). O alerta
  (`limite_gaveta`, em R$; 0 desliga) usa `TurnoController.dinheiro_esperado`, a mesma conta do "Valor esperado" do fechamento
  (um teste garante que as duas batem), e só diz que passou do limite, sem mostrar o valor, para não quebrar a conferência cega.
- **Estoque baixa ao fechar a venda**, não ao lançar o item; cancelar o cupom estorna. Estoque negativo é permitido.
- **Promoções** (período, dias da semana, horário) valem em conjunto; havendo mais de uma, vence a de menor
  preço. Faixas que viram a meia-noite funcionam (ex.: 22:00 às 02:00).
- **Meio a meio**: preço pelo maior (ou média proporcional); combo (`composto`) tem preço único. Cada parte
  baixa a fração correspondente do estoque.
- **Caderneta**: limite 0 significa sem limite; saldo negativo é dívida. Excedente do pagamento pode virar
  crédito ou troco.
- **Conta mensal** repete o mesmo valor por N meses (aluguel, internet). Já a compra lançada em contas a pagar
  em N meses DIVIDE o total (os centavos que sobram vão na 1ª parcela).
- **Cupom** é numerado ao fechar ou cancelar. Só dá para cancelar cupom do turno ainda aberto.
- **Impressão térmica** (`hardware/impressora_termica.py`, `controllers/fila_impressao_controller.py`): todo documento
  vai para uma **fila** (`fila_impressao`, esquema v5) e uma thread com conexão própria o envia, então impressora
  fora do ar não trava o caixa. A ordem é preservada por destino (caixa, cozinha/bar); tentativas após 5, 10, 20,
  40 e 60 s e depois a cada minuto, até 60, quando o item vira `erro` e espera o operador (nada pendente é apagado
  sozinho; impresso e cancelado somem após 7 dias). A gaveta abre pelo pulso da impressora quando alguma forma
  usada tem `na_gaveta`, quando há troco e na sangria. As vias são o maior `tipos_pagamento.vias` (1 a 3). O
  manual pede logotipo BMP de 180x121 em 256 cores; aceitamos BMP sem compressão (1, 4, 8, 24 ou 32 bits) e
  reduzimos o que passar da largura do papel. Tudo é não fiscal. As impressoras do computador são listadas pela API do
  Windows (`hardware/impressoras_so.py`, ctypes) e o envio RAW pelo spooler usa a mesma API: o `pywin32` deixou de ser
  necessário. As portas COM vêm do registro do Windows (e do `pyserial`, só para a descrição).
- **Limpeza do movimento** apaga até o dia anterior à data informada, faz backup antes, recusa apagar vendas não
  enviadas à nuvem quando a sincronização está configurada e preserva o saldo da caderneta.
- **Módulos de acesso**: o manual cita 31 módulos sem listá-los; foram definidos 40 (ver `sementes.ACESSOS`),
  todos com nível configurável de 1 a 4.
- **Senhas** são guardadas com PBKDF2 e comparadas sem diferenciar maiúsculas, como pede o manual.
- **Busca por nome** (produtos, clientes, contas, cadastros) ignora acento e caixa: "cafe" acha "Café" (função SQL `norm()`).
- **Quantidade por item** tem teto (configuração `qtd_maxima_item`, padrão 99.999; 0 desliga), para um código de
  barras digitado no campo Quantidade não virar uma venda de bilhões. `nan` e `inf` são recusados.
- **Transferir parte de um item** divide total e comissão sem perder nem criar centavo.
- **Licença mensal** (Ed25519, offline): aviso 7 dias antes, carência de 5 dias, nunca bloqueia com o turno aberto;
  só é exigida no executável ou com `licenca_exigir = S`. Detalhes em `src/core/licenca.py` e no README.

## 3. O que NÃO está implementado

| Item | Situação |
|------|----------|
| Impressora fiscal (ECF), NFC-e, SAT | Não emite documento fiscal. Cupom é "NÃO FISCAL". Leitura X e Redução Z são relatórios gerenciais. Campos fiscais do produto (NCM, alíquotas) são guardados mas não usados. |
| TEF (cartões) | Campos do cadastro existem; não há integração. |
| Balança Toledo/Filizola | Há a interface; a leitura automática não foi implementada (depende do equipamento). O caixa pede o peso digitado. |
| Gaveta | Abre pelo pulso da impressora térmica (ESC p) e a abertura manual é registrada. Sem impressora térmica configurada o caixa só registra. Não testada em gaveta real. |
| Impressora térmica em equipamento real | Testada só com impressora TCP simulada e arquivo. Faltam modelos reais: página de código, corte, pino da gaveta e velocidade serial variam. |
| Rede com vários caixas no mesmo banco | O banco SQLite é local a cada terminal. |
| Nuvem | Só licença e atualizações (FastAPI); vendas e painel foram retirados de propósito (cada boate guarda as suas). Falta validar em loja e HTTPS. Licença liberada automaticamente no pagamento online: não existe (hoje é `lojas assinatura`). |
| Tabela de preços por empresa (multi-loja) | Uma única tabela de preços. |
| E-mail da loja, foto do subgrupo | Os campos são guardados; não são usados. (O logotipo da loja é impresso no cupom térmico quando a opção está ligada.) |
| Colunas "Turno 1 a 3" e "Figura" do tipo de pagamento | O manual não explica o uso; omitidas. |
| Acesso "Transportadoras" da versão web | Citado sem descrição; omitido. |
| Campos de nota fiscal de compra (BC ICMS, chave de acesso...) | Fora de escopo (dependem de consultor fiscal, segundo o próprio manual). |
| Controles de boate pesquisados e ainda não feitos | **Consumação mínima** já existe por comanda (valor único, faixa de números); falta o mínimo por tipo de entrada e a cobrança da comanda sem nenhum consumo. **Pré-pago/pulseira** (crédito carregado na entrada e debitado no consumo). **Taxa de comanda perdida** e **consumação na entrada** já funcionam cadastrando um produto e lançando-o na comanda. |
