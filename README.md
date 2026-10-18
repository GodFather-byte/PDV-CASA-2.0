# WillPDV

**Autor:** Willyan  ·  **Licença:** proprietária, código visível (veja [`LICENSE`](LICENSE))

Sistema de ponto de venda offline-first para bares, casas noturnas e operações de
alimentação. O objetivo é evoluir para um PDV confiável de ponta a ponta: vendas,
mesas e comandas, turnos, pagamentos, estoque, clientes, financeiro, relatórios e
licença mensal e atualizações pela nuvem.

> **Estado do projeto:** em desenvolvimento. O sistema local (cadastros, caixa, mesas,
> caderneta, entrega, estoque, contas, relatórios, utilitários e configurações dos
> manuais Willyan) está implementado em Python + SQLite + Tkinter e coberto
> por testes automatizados de regras e de telas. Ainda **não foi validado em loja**: não há
> emissão fiscal, TEF nem leitura real de balança, e a impressora térmica e a gaveta só foram testadas com
> impressora simulada (ver
> [`docs/ESPECIFICACAO.md`](docs/ESPECIFICACAO.md)), e a nuvem (licença e atualizações) ainda não foi testada em loja.

## Os dois programas deste repositório

O repositório gera **dois programas Windows diferentes**. Não confunda:

| Programa | Para quem | O que faz | Onde baixar | Guia |
| --- | --- | --- | --- | --- |
| **WillPDV** (o PDV) | o **cliente** (a boate, o bar) | caixa, mesas e comandas, estoque, relatórios, impressão | [aba Releases](https://github.com/GodFather-byte/PDV-CASA-/releases/tag/ultima-versao) · [instalador direto](https://github.com/GodFather-byte/PDV-CASA-/releases/download/ultima-versao/WillPDV-Instalador.exe) | [`docs/INSTALAR_E_TESTAR.md`](docs/INSTALAR_E_TESTAR.md) |
| **WillPDV Licenças** (o gerador de licenças) | **só você**, o fornecedor | emite os códigos de licença (mensal, permanente, teste) | [aba Actions](https://github.com/GodFather-byte/PDV-CASA-/actions/workflows/build-windows.yml) > *Artifacts* (não fica na Releases, que é pública) | [seção abaixo](#willpdv-licenças-o-gerador-de-licenças) · [`docs/LICENCIADOR.md`](docs/LICENCIADOR.md) |

> **Procurando o programa que cria as licenças?** Vá direto para
> [WillPDV Licenças: o gerador de licenças](#willpdv-licenças-o-gerador-de-licenças): lá estão onde ele fica no GitHub,
> como baixar, instalar e usar, passo a passo.

## Índice

1. [Os dois programas deste repositório](#os-dois-programas-deste-repositório)
2. [Começar (rodar e testar)](#começar)
3. [O que já existe](#o-que-já-existe)
4. [Mesas e comandas](#mesas-e-comandas) · [Comissão das garotas](#comissão-das-garotas) · [Fechamento do turno](#fechamento-do-turno) · [Controles de caixa de boate](#controles-de-caixa-de-boate)
5. [Impressão térmica](#impressão-térmica) · [Proteção dos dados](#proteção-dos-dados)
6. [Estrutura do repositório](#estrutura-do-repositório) · [Banco local e dados](#banco-local-e-dados)
7. [Licença do software (copyright)](#licença-do-software-copyright)
8. [**WillPDV Licenças: o gerador de licenças**](#willpdv-licenças-o-gerador-de-licenças)
9. [Como a licença funciona no caixa do cliente](#como-a-licença-funciona-no-caixa-do-cliente)
10. [Emitir licenças pela linha de comando](#emitir-licenças-pela-linha-de-comando)
11. [Gerar o executável e o instalador](#gerar-o-executável-e-o-instalador)
12. [Telegram do dono](#telegram-do-dono-acompanhar-a-casa-pelo-celular) · [Nuvem (licença e atualizações)](#nuvem-só-licença-e-atualizações)
13. [Documentação (pasta `docs/`)](#documentação-pasta-docs)

## Começar

Requer Python 3.10 ou superior. Na raiz do repositório:

```powershell
python --version
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Para abrir o sistema (Windows: também há o atalho `iniciar_pdv.bat`):

```powershell
python -m src.app
```

Usuário inicial: **ADM**, senha **ADM** (nível 4). Na primeira entrada o sistema obriga a trocar essa senha (vale para
qualquer operador cuja senha seja igual ao nome); depois crie os operadores em Manutenção de Cadastros > Operadores.
Cinco senhas erradas seguidas bloqueiam aquele usuário (ou a senha de supervisor) por 5 minutos. Operadores de nível 0
entram direto no caixa. O primeiro acesso ao caixa pede o número do turno e o valor do fundo de caixa.

O caixa continua usando SQLite local e a interface Tk completa pode funcionar sem pacotes externos.
Instale `pip install -r requirements.txt` para Qt, backup criptografado e integrações.
O instalador Windows já inclui as dependências.
`python -m src.app --qt` abre a interface Qt em migração; `--tk` abre explicitamente a atual.
Confira os limites antes de operar na [documentação Qt](docs/INTERFACE_QT.md).
Veja também [backup externo criptografado](docs/BACKUP_EXTERNO.md) e
[auditoria estruturada](docs/AUDITORIA.md).

## O que já existe

- **Caixa e vendas:** balcão, mesas e comandas, itens, preços promocionais, descontos,
  serviço, pagamentos, troco/vale e cancelamento.
- **Estoque:** painel com a situação de cada produto (sem estoque / repor / normal), valor parado, busca e filtros
  enquanto digita, entrada/saída/perda/contagem em dois cliques, histórico por produto, pedido e lista de compras
  sugeridos pelo estoque mínimo ([docs/ESTOQUE.md](docs/ESTOQUE.md)); importação de produtos em massa por planilha, com prévia ([docs/IMPORTAR_PRODUTOS.md](docs/IMPORTAR_PRODUTOS.md)); compras e outros lançamentos completos, pedidos,
  contagem, composição de produtos e histórico de movimentos; a venda fechada baixa o estoque e o
  cancelamento estorna os movimentos.
- **Cadastros e operação:** produtos, clientes, operadores, formas de pagamento,
  configurações, turnos, contas, caderneta e entregas.
- **Relatórios e impressão:** relatórios de vendas/gestão e cupom não fiscal com saída em tela, arquivo,
  impressora do Windows ou **impressora térmica ESC/POS** (fila com reenvio automático, gaveta, vias e
  logotipo; ver [Impressão térmica](#impressão-térmica)), Leitura X e Redução Z gerenciais. Não há emissão
  fiscal nem homologação de periféricos.
- **Dados para nuvem:** `SyncController` monta lotes identificados por UUID e
  registra apenas confirmações explícitas do servidor.
- **Qualidade:** a suíte cobre regras de caixa, estoque, cadastro, formatação,
  segurança e banco local. Rode os testes antes de integrar alterações.

## A tela do caixa

Visual escuro em três colunas, no azul-noite do menu principal.

- **Cabeçalho:** a casa e os indicadores do turno: posições **abertas**, as **aguardando acerto** (conta enviada, pagamento
  suficiente ou comissão a pagar), o que está **em aberto na casa** e o turno com o operador e a hora. **Sair** fica no canto.
- **Esquerda, "Mesas e comandas":** cartões grandes de cada posição aberta, com a **busca** (número, `M5` ou o nome da
  comanda) e as **abas** Todas, Abertas, Pago em parte, Aguardando acerto e Comissões. O cartão mostra o tipo, o número em
  destaque, a identificação (nome da comanda, pessoas na mesa, itens ou "N drinks marcados" da garota), a situação numa pílula
  colorida (Aberta, Parada, Acerto, Parcial, Concluir, Comissão), o total e há quanto tempo está aberta. O da **garota** traz o
  nome e o número dela; a comanda com consumo e comissão a pagar ganha o selo de estrela. As colunas de cartões (3, 2 ou 1)
  acompanham a largura da janela. Busca e abas só controlam o que aparece: não fecham, cancelam nem transferem nada.
- **Centro, venda atual:** o título (`Comanda 12 · Carlos`) com o **selo da situação** (Aberta, Conta enviada, Pago em parte,
  Concluir acerto), a linha de **entrada do item** (código, descrição, quantidade e preço, com o texto-guia) e a lista de itens
  (Produto, Preço, Qtd e Total; a observação aparece em janela larga e continua pelo atalho **O**).
- **Direita:** o **total a pagar** com a origem do acréscimo embaixo (serviço, taxa, taxa do crédito, desconto), o valor
  já recebido, **Pagar (F12)** e as ações do dia a dia em duas colunas: Lançar produto, Escolher comanda (F4), Pré-conta (F8),
  Transfere (F10), Repique (F9), Comissões, Sangria (F7), Gaveta (F11), Consulta comanda e Cancelar. **Mais opções** reúne
  Nomear comanda, delivery, caderneta, impressora, balança, leitor e o fechamento do turno. Os atalhos F valem também lá;
  as setas abrem essa janela quando chegam a uma ação dela. **Enter** com código vazio entra na barra de ações.

**Navegar pelas comandas** (clientes e garotas): **PgDn** e **PgUp**, ou os botões ▶ e ◀ ao lado de "Venda atual", vão para a
comanda seguinte ou anterior da lista do painel, respeitando a aba e a busca (na aba Comissões, passam só pelas garotas).
Na lista de itens, as setas andam pelas linhas (a seta para cima na primeira volta ao código) e **Enter** ou duplo clique abre
as **ações da linha**: no item, observação, transferir e cancelar; na comanda da garota, pagar a comissão ou cancelar aquele
lançamento. Para dar nome a uma comanda ou mesa, clique no título (ou use Mais opções > Nomear comanda).

**Pagamento (F12):** as formas (Dinheiro, Débito, Crédito e Pix) são linhas grandes com a **tecla** de cada uma: **1 a 4**, ou
a inicial (**D** alterna Dinheiro e Débito, **C** é Crédito, **P** é Pix); um clique na forma já leva ao valor, e o valor sugerido é o
que falta. O valor só aceita número (sem `1e5`, sinal ou mais de 2 casas; `1.000` é mil); **Débito, Crédito e Pix não aceitam mais
do que falta** (só o dinheiro dá troco) e um **troco acima de R$ 500** pede confirmação, para um zero a mais não virar um troco
absurdo. **Remover (Delete)** tira o pagamento selecionado (sem seleção, o último). F10 duas vezes seguidas grava uma venda só, e
se o cupom não puder ser preparado a venda continua gravada e a tela avisa para reimprimir pelo botão Impressora.

## Modo claro e modo escuro

Em **Configurações > Aparência** (a primeira aba) escolha **Modo escuro** (o padrão) ou **Modo claro**. Vale para tudo: entrada,
menu, caixa e as telas de cadastro, relatórios, estoque e configurações. Ao gravar, o visual muda na hora: o menu é refeito e as
telas que estavam abertas são fechadas (cada uma guarda as cores de quando abriu), então termine o que estiver editando antes de
trocar. A escolha fica gravada e o programa já abre no modo escolhido. As cores dos dois modos estão em `src/ui/paleta.py`, com
teste de contraste para o texto continuar legível em ambos.

## Mesas e comandas

No caixa, o campo **Comanda** (tecla **F4**) recebe só o número: digite `123` e Enter para abrir a comanda 123 (vai até
10 mil), e depois os **códigos dos produtos** no campo ao lado (ex.: `2` para a Skol). A **mesa** leva um `M`: `M5` é a
mesa 5. `C123` também vale. O `0` é o balcão. O número sem letra nunca é lido no campo do código, porque lá ele é o código do
produto; para trocar de comanda sem sair de lá, digite `C123` ou `M5` (ou bipe o cartão): se não existir produto com esse
código/atalho, a posição é aberta e os itens seguintes caem nela.

Quem prefere a notação de restaurante (o número sem letra é a mesa e a comanda leva `C`) muda em **Configurações > Mesas e
serviço > Número digitado sem letra no caixa é**. As telas, as listas e os relatórios sempre mostram a posição do mesmo jeito
que se digita.

Na **coluna da esquerda** do caixa ficam os cartões das posições abertas (ver [A tela do caixa](#a-tela-do-caixa)): o
**Balcão** (uma faixa fina no alto, com o total, para não ocupar o lugar de uma comanda), as **mesas**, as **comandas** (ex.: `123`) e as **garotas** com comissão a pagar
(ver [Comissão das garotas](#comissão-das-garotas)). Uma conta enviada aparece como **Acerto** e a parada além do tempo de
inatividade ganha o **relógio**. O cartão da venda que está na tela tem a borda grossa. Havendo mais cartões que espaço,
a coluna rola (barra ou roda do mouse).

- **Esc volta ao "marcar comanda":** com a venda em andamento, Esc leva ao campo da posição, com o número selecionado:
  digite `7` (comanda 7) ou `M7` (mesa 7) e Enter. Com um produto escolhido (esperando a quantidade), o Esc só cancela o produto. Um segundo Esc
  volta ao balcão; as mesas e comandas abertas continuam gravadas.
- **Escolher um cartão:** clique nele, ou seta para baixo no campo da posição e então setas, **Enter** (chama), **T**
  (outras posições vêm para a escolhida) e **Esc** (volta ao campo). Digitar um número, `C` ou `M` com o foco nos cartões já
  começa a marcar a posição; `0` é o balcão.
- A comanda funciona como uma mesa com **numeração própria**: a comanda 2 e a mesa 2 (`M2`) existem ao mesmo tempo.
- Tudo o que vale para a mesa vale para a comanda: serviço, desconto, pré-conta (impressa como "CONTA DA COMANDA"),
  F10 (transfere tudo), T (várias para uma) e a transferência de parte dos itens, inclusive entre mesa e comanda
  (ex.: F10 e `2` levam a mesa 5 para a comanda 2; `M5` leva uma comanda para a mesa 5).
- Em **Configurações > Mesas e serviço**: *Número digitado sem letra* (comanda ou mesa), *Número de comandas* (padrão 10000; **0 desliga as comandas**), *Cobrar serviço
  nas comandas* e *Mostrar sempre o painel das mesas e comandas abertas no caixa* (desligado, ele só aparece
  com Esc/F4 e some ao escolher uma posição).
- Relatórios: "Mesas e comandas" mostra a posição como `123` (comanda) ou `M5` (mesa); o filtro *Modalidade* separa `mesa` de `comanda`.

## Comissão das garotas

Na boate as garotas ganham comissão pelas bebidas. O número de cada garota (156, 180...) é o mesmo da comanda dela, e o
**código 50** do caixa é o das comissões. Tudo acontece **na própria tela do caixa**, a mesma do balcão, sem abrir janela:

1. No campo **Comanda**, digite o número da garota (ex.: `180`) e Enter.
2. No campo do código, digite `50` e Enter. A linha de entrada vira **Garota nº** (já com o 180; a Descrição mostra o nome,
   se ela estiver cadastrada) e **Valor (R$)**, e o cursor já vai para o valor.
3. Digite o **valor da comissão** (ex.: `25` ou `25,00`) e Enter. Ficou marcado no número dela e **a via da garota sai na
   impressora**.

Fora de comanda (no balcão, por exemplo) o cursor começa em *Garota nº*: digite o número e Enter para ir ao valor. A seta
para cima volta do valor ao número (para lançar em outra garota) e **Esc cancela** a comissão. O 50 nunca vira produto nem
entra na venda: a comanda da garota continua vazia e some sozinha, e a comissão fica guardada.

- **A via da garota:** a cada comissão lançada sai uma via (não fiscal) só com o *valor desta comissão* (o que acabou de ser
  marcado, sem somar o que já estava marcado na comanda), com hora e operador. O total que ela tem a receber aparece no recibo
  do acerto. Sem impressora configurada (modo "tela") a via só fica gravada na pasta `impressao/` e a barra de estado avisa; falha na
  impressora nunca desfaz o lançamento. Em Configurações > Caixa: *Imprimir a via da garota a cada comissão lançada*.
- **As garotas ficam à vista no painel:** junto com o balcão, as mesas e as comandas, a garota com comissão a pagar ganha um
  cartão (o nome dela, quantos drinks estão marcados e o valor a pagar); clicar abre a comanda dela. Se ela também tem
  consumo aberto, o cartão da comanda ganha um selo com a estrela. Em Configurações > Mesas e serviço: *Mostrar no caixa as
  garotas com comissão a pagar*.
- **A comanda mostra o que foi marcado nela:** ao abrir a comanda da garota (ex.: `180`), as comissões marcadas aparecem
  na lista, em verde (código 50, `COMISSÃO (a pagar)`, valor, hora e operador), e a faixa verde de cima mostra o total a pagar.
  As pagas neste turno ficam em cinza, para saber se já foi paga; as canceladas somem. É só leitura e não é venda: o
  Total continua sendo o dos itens. Comanda de cliente e mesa não mostram nada disso (mas uma comissão lançada por engano no
  número de um cliente aparece nela, o que ajuda a achar o erro).
- **Pagar e cancelar sem sair da tela:** **F12** na comanda da garota paga tudo o que está pendente: o dinheiro sai da gaveta
  (uma sangria "Comissão garota 180 NOME", então a conferência do caixa já conta), a gaveta abre e saem dois papéis: o **recibo**
  do acerto, com a linha de assinatura, e o **comprovante da saída financeira** (o mesmo da sangria) com o valor que saiu do
  caixa (a parte paga por Pix não entra nele); desmarcando a opção, paga fora do caixa (só dá baixa). Se a comanda também tem consumo, o F12 pergunta o
  que pagar. **Delete** numa linha de comissão cancela aquele lançamento (pede confirmação e, se o operador não tem nível, a
  senha de supervisor, como no cancelamento de item); comissão já paga não se cancela.
- **Shows no acerto da garota:** ao fechar a conta dela (F12, ou o botão *Comissões*), a janela *Pagar comissão* tem o campo
  **Quantidade de shows** e a escolha do **valor de cada show (R$ 50,00 ou R$ 60,00)**. Os shows são lançados **pelo operador**,
  nunca contados sozinhos, e a janela só mostra isso na hora de fechar a conta da garota. O total é a comissão marcada mais
  quantidade x valor: comissão de R$ 25,00 (5 pontos) + 10 shows de R$ 50,00 = **R$ 525,00**. O recibo impresso traz a comissão,
  a linha `SHOWS: 10 x 50,00`, o total e a assinatura; o dinheiro (comissão + shows) sai da gaveta como uma só sangria
  "Acerto garota 180 NOME" (desmarcando a opção, paga fora do caixa). Sem comissão marcada dá para acertar só os shows, pelo número da
  comanda dela: F12 na comanda vazia abre o acerto direto para garota cadastrada e ativa; garota inativa ou fora do cadastro
  pergunta antes (responder Não mantém o aviso de sempre). Sem comissão e sem shows dá para **fechar a conta sem valor**: a
  janela pergunta se confirma, grava um acerto de R$ 0,00 (nada sai da gaveta) e imprime o recibo com "Conta fechada, nada a
  pagar." Os shows aparecem na janela mesmo com a pergunta de shows desligada quando não há comissão. O recibo não lista os
  lançamentos um a um: traz a quantidade e o total; ele e o comprovante de saída da gaveta saem com as linhas importantes em
  letra mais alta (dobro da altura). O fechamento do turno lista os shows pagos por garota. Em Configurações > Caixa:
  *Valores do show* (padrão `50;60`, separados por ponto e vírgula) e *perguntar quantos shows ela fez* (ligado).
- **Pix no acerto:** sem dinheiro no caixa, ou só com uma parte dele, a janela *Pagar comissão* tem o campo **Parte paga por Pix
  (R$)** e o botão **Tudo no Pix**. A tela mostra a divisão (`Dinheiro R$ 60,00 + Pix R$ 40,00`): só a parte em dinheiro vira
  sangria e abre a gaveta; o Pix nunca sai dela. O recibo separa *Dinheiro* e *Pix*, e o fechamento do turno traz a linha
  *Pago às garotas por Pix* (para o dono conferir no banco).
- **Vale da garota:** na mesma janela, o campo **A garota pegou vale?** desconta o vale do **total do acerto**, seja o resto pago em
  dinheiro ou em Pix. O vale **não sai do caixa de novo** (aquele dinheiro já saiu quando ela o pegou). Exemplo: acerto de R$ 250,00
  com vale de R$ 50,00 = R$ 200,00 a pagar; em dinheiro, a sangria e o comprovante de saída são de R$ 200,00. O Pix digitado é sobre o
  que sobra depois do vale. O vale não pode passar do total; aparece no recibo (*Vale (já recebido)*) e fica guardado no acerto.
- **Contra erro de digitação:** havendo garotas cadastradas, um número que não está no cadastro (ou de garota inativa) pede
  confirmação, e valor acima de R$ 500,00 também.
- **Comissões** (botão na barra do caixa): a lista geral, com o que há a pagar a cada garota e os lançamentos dela, para pagar
  ou cancelar de uma vez. É um atalho: o dia a dia se faz na tela do caixa.
- **Troca de turno:** avisa se há comissão a pagar (pague antes de contar a gaveta). O fechamento e a Leitura X trazem a seção
  *Comissões das garotas*: o lançado no turno, por garota, e o total que ainda falta pagar. O pagamento aparece nas sangrias.
- **Relatório:** Relatórios > Caixa > *Comissão das garotas*, por garota (total, pago e a pagar) ou lançamento a lançamento, com
  filtro de período, turno, garota e situação.
- **Cadastro:** Manutenção de Cadastros > *Garotas* (número, nome, ativa). É opcional: serve para mostrar o nome e conferir o número.
- **Configurações > Caixa:** o *código* que lança a comissão (50; vazio desliga; não pode ser o de um produto), *Exigir senha
  de supervisor para lançar comissão* (desligado de fábrica) e *Marcar, pagar e cancelar a comissão na própria tela do caixa*
  (ligado; desligado, o 50 abre a janela *Comissão da garota* e o pagamento e o cancelamento ficam só no botão *Comissões*).
  Pagar segue a regra da sangria e cancelar a do cancelamento.
- A comissão **não é venda**: não entra no faturamento, no estoque nem na nuvem. Só vira movimento do caixa quando é paga.

## Fechamento do turno

Além dos totais e da conferência do dinheiro, o fechamento (e a Leitura X) traz a **conferência do turno**, para auditar a
noite:

- **Posições em aberto:** mesas e comandas com consumo que ficaram abertas, com o total de cada uma e a soma. Ao trocar o
  turno, o caixa avisa quais são (elas continuam abertas no turno seguinte).
- **Cupons cancelados** (cupom, onde era, valor, motivo e quem cancelou) e **itens cancelados** (hora, onde, produto,
  quantidade, valor e quem cancelou).
- **Transferências** entre mesas e comandas (inteira, várias para uma ou parte dos itens): de onde para onde, valor e quem fez.

- **Conferência da maquininha:** ao tocar em *Fecha Turno*, **antes** de pedir o dinheiro da gaveta, a tela *Conferir maquininha*
  mostra quanto foi lançado no turno em **Cartão Débito**, **Cartão Crédito** e Pix (quantidade e valor de cada um, mais o
  total) para comparar com o fechamento do lote da maquininha. Se não bate, cancele e confira os pagamentos. Não mostra o
  dinheiro esperado: a contagem da gaveta continua às cegas. A fita do fechamento repete o bloco *CONFERIR NA MAQUININHA*.

No painel do fechamento aparecem as contagens e o botão **Conferência do turno** mostra o detalhe na tela; na fita
impressa as seções só saem quando há ocorrências (a linha das posições abertas sai sempre, com "nenhuma" se não houver).

### Fechamento para passar o caixa

Ao **trocar o turno** o fechamento sai **sozinho na impressora**, pronto para o caixa que sai entregar ao gerente ou ao
caixa que entra. Ele mostra tudo da noite e termina com o que o gerente precisa para receber o caixa:

- os totais, os recebimentos, o **valor esperado**, o **valor final** que o operador declarou e o resultado em letra grande:
  **SOBROU R$ x**, **FALTOU R$ x** ou **CAIXA CONFERIDO**;
- a lista das **sangrias e suprimentos** do turno (hora, valor, motivo e quem fez), com os pagamentos de comissão;
- a conferência do turno e a seção das comissões das garotas;
- no fim, o espaço da **justificativa da diferença** (só se sobrou ou faltou) e as linhas de assinatura do **caixa responsável**
  (quem fechou o turno, com o nome) e do **gerente / quem recebe o caixa**.

Em Configurações > Caixa: *Imprimir o fechamento ao trocar o turno* (ligado) e *Vias do fechamento* (1 a 3; ex.: uma fica no
caixa e outra com o gerente). Sem impressora configurada (modo "tela") nada sai sozinho: o painel do fechamento tem o botão
*Imprimir Fechamento*, que serve também para reimprimir. Falha ao imprimir avisa e o turno fecha do mesmo jeito. A Leitura X
(parcial, no meio do turno) lista as sangrias, mas não leva resultado nem assinatura.

## Controles de caixa de boate

Pesquisando como funciona o caixa de uma boate (comanda de consumo, conferência na saída, sangrias, cancelamentos), entraram
dois controles. Outras ideias, que mudam regras ou o banco, estão em `docs/ESPECIFICACAO.md` (seção 3).

- **Consulta Comanda** (botão da barra do caixa): na saída, digite a comanda (ou `M5`) e veja se está **PAGA** (cupom, valor e
  hora), **ABERTA - A PAGAR** (valor e itens) ou sem registro. Vale a venda mais recente daquele número, porque o cartão da
  comanda é reutilizado a noite toda. Não mexe na venda que está na tela; no número de uma garota mostra também a comissão a pagar.
- **Alerta de sangria** (Configurações > Caixa > *Avisar para fazer sangria quando o dinheiro da gaveta passar de*, em R$; 0
  desliga): ao fechar uma venda, se o dinheiro esperado na gaveta passou do limite, a barra de estado fica laranja pedindo a
  sangria (F7). Só avisa que passou: não mostra quanto há, para o operador seguir contando a gaveta sem ver o esperado.
- **Motivo do cancelamento** (Configurações > Caixa > *Exigir o motivo para cancelar item ou venda*, desligado de fábrica):
  ligado, o caixa pede o motivo ao cancelar um item ou a venda inteira e não aceita em branco. O motivo sai no fechamento
  e na Leitura X, em *Itens cancelados* e *Cupons cancelados*.
- **Consumação mínima** (Configurações > Mesas e serviço, desligada de fábrica): informe o valor mínimo por comanda. Na saída,
  a comanda com consumo abaixo do mínimo paga a diferença, que aparece no cupom e na pré-conta como *Compl. consumação mín.*
  Comanda sem nenhum item nunca é cobrada, e *vale a partir/até a comanda nº* deixa de fora as comandas das garotas. Mesa e
  balcão não são afetados. O desconto não burla o mínimo (vale o consumo já com desconto).
- **Sangria por horário** (Configurações > Caixa > *Horários de sangria*, ex.: `02:00, 04:30`): passou o horário e ninguém fez
  sangria depois dele neste turno, o caixa avisa na barra de estado ao fechar a próxima venda, junto do aviso por limite.
- **Auditoria por operador** (Relatórios > Caixa): por operador, cupons, vendido, ticket médio, desconto, cupons e itens
  cancelados e sangrias, para achar cancelamento ou desconto fora do normal.
- **Sem programação nova:** *taxa de comanda perdida* e *consumação mínima na entrada* se fazem cadastrando um produto
  (ex.: `TAXA COMANDA PERDIDA`) e lançando-o na comanda.

## Impressão térmica

> **Elgin i9 (ou outra térmica) não imprime?** Abra Configurações > Máquinas > *Assistente de impressora*: ele aponta o que
> está errado, configura o caixa de uma vez e imprime o teste. Guia: [`docs/IMPRESSORA.md`](docs/IMPRESSORA.md).

O caixa imprime em impressora térmica ESC/POS (Epson TM, Bematech, Elgin, Tanca e compatíveis; 58 mm ou 80 mm). Cupom,
pré-conta, pedido de entrega, comprovante de sangria, fechamento do turno, recibo e via da comissão das garotas e Leituras X/Z saem por ela. Todos são
**não fiscais**.

**Configurar** (Configurações > Máquinas):

1. *Impressão de cupons e relatórios* = **Impressora térmica (ESC/POS)** e *Colunas da fita* = 48 (80 mm) ou 32 (58 mm).
2. **Escolha a impressora na lista do computador:** clique em *Escolher impressora do computador* (ou em *Escolher da
   lista...* ao lado do endereço). O PDV mostra as impressoras instaladas neste Windows, com a porta, o driver e a
   situação, e as portas COM. As que parecem de cupom (Epson TM, Bematech, Elgin, POS-80...) vêm primeiro; PDF e fax
   ficam por último. Use *Imprimir página de teste* na linha escolhida e então *Usar esta*: a conexão e o nome são
   preenchidos sozinhos. Não apareceu a sua? Instale o driver dela no Windows, ligue o cabo e clique em *Atualizar*.
   Sem a lista, preencha *Conexão* e *endereço* à mão:

   | Conexão | Endereço | Observação |
   |---|---|---|
   | Rede (TCP/IP) | `192.168.0.50` ou `192.168.0.50:9100` | Não instala nada; a porta padrão é 9100. |
   | Serial (COM) | `COM3` ou `COM3:19200` | Velocidade padrão 9600; exige `pip install pyserial`. |
   | Impressora do Windows | o nome que o Windows mostra, como `CAIXA` | Usa o spooler do Windows, sem instalar nada. Se a impressora estiver desligada, o Windows guarda o trabalho. |
   | Arquivo/dispositivo | `C:\saida.prn` ou `\\.\COM3` | Grava os bytes; serve para conferir sem impressora. |
3. *Página de código* (CP850 é o padrão; troque se os acentos saírem errados), *cortar o papel*, *gaveta ligada à
   impressora* e *pino da gaveta* (0 ou 1).
4. Confira em Utilitários > **Fila de impressão** > *Imprimir página de teste*.

**Como imprime**

- **Fila:** o documento é gravado no banco na hora e uma thread o envia. Impressora desligada ou fora da rede não
  trava o caixa: o documento espera e sai sozinho quando ela volta (novas tentativas após 5, 10, 20, 40 e 60 s,
  e depois a cada minuto; passada cerca de uma hora vira *erro* e aguarda o operador). A ordem de cada destino (caixa e
  cozinha/bar) é preservada. Os já impressos ou cancelados saem da lista depois de 7 dias; pendentes e com erro nunca
  são apagados sozinhos.
- **Indicador:** o alto do caixa mostra *Impressora: ok*, *Impressora fora? N na fila* ou *N com erro (reenviar)*. Clicar
  nele abre a **fila**, onde se reenvia, cancela e limpa (também em Impressora > Fila de impressão, no caixa, e em
  Utilitários).
- **Gaveta:** abre pelo pulso da própria impressora (com *Gaveta ligada à impressora* marcada) quando alguma forma de
  pagamento da venda tem a marca *Fica na gaveta* (dinheiro, cheque e ticket, de fábrica) ou quando há troco, e também
  na sangria e na tecla **F11**. Cartão e Pix não abrem a gaveta.
- **Vias:** o cupom sai com o maior *Nº de vias* (1 a 3) entre as formas de pagamento usadas (Manutenção de Cadastros >
  Tipos de Pagamento), com corte entre as vias; a gaveta abre uma vez só. O fechamento do turno usa *Vias do fechamento*
  (Configurações > Caixa).
- **Logotipo:** informe o caminho de um BMP em Configurações > Loja e ligue *Imprimir o logotipo da loja no cupom*
  (Configurações > Máquinas). Vale BMP sem compressão de 1, 4, 8, 24 ou 32 bits; imagem mais larga que o papel é
  reduzida. Só o cupom, a pré-conta e o pedido de entrega levam o logotipo. Arquivo ausente ou inválido não impede a
  venda: o cupom sai sem logotipo e o motivo fica no log (`logotipo_invalido`).
- **2ª via:** Impressora > Reimprimir último cupom (ou por número) reimprime o cupom marcado como 2ª via.
- **Cozinha/bar:** a *impressora remota*, em rede ou do Windows (também escolhida na lista), usa a mesma fila. A opção
  *Pasta de arquivos* só grava os pedidos.

**Limites:** não há ECF, NFC-e, SAT nem TEF. A lista de impressoras foi conferida num Windows real (achou uma Epson TM-T
USB), mas a impressão em papel ainda não foi validada: os testes usam impressora TCP simulada, spooler simulado e arquivos. A página de código, o corte, a gaveta e a velocidade serial variam por modelo; use a página de teste.
A fila só sabe se a impressora aceitou os bytes: falta de papel e tampa aberta não são detectadas (o documento conta
como impresso; reimprima pela 2ª via).

## Proteção dos dados

- **Backup automático:** ao abrir o caixa (se a última cópia tem 12 h ou mais), a cada **troca de turno** e ao sair. Cada cópia é
  conferida depois de gravada; uma cópia danificada é descartada e o erro aparece. O painel inicial fica **vermelho** se o
  último backup tem 24 h ou mais, falhou ou nunca foi feito. Em Configurações > Utilitários, *Cópia extra do backup* grava a
  cópia também em pendrive, outro disco ou pasta de rede (o backup só no mesmo disco não protege de defeito no disco).
- **Restaurar backup** (Utilitários): escolhe a cópia; a restauração acontece na próxima abertura do programa e o estado de
  agora é guardado antes.
- **Integridade ao abrir:** o banco é conferido; se estiver danificado, o sistema oferece restaurar o último backup válido e
  guarda o banco ruim ao lado (`loja_offline.db.antes-AAAAMMDD-HHMMSS`), sem apagar nada.
- **Erros:** erro inesperado em qualquer tela ou thread vai para `logs/pdv.log` (com o traceback) e o operador vê uma mensagem
  clara. Utilitários > *Pacote de suporte* gera um zip só com os logs (nunca o banco) para enviar ao fornecedor.
- **Uma janela só:** abrir o PDV duas vezes no mesmo banco é recusado.
- **Comanda aberta na troca de turno:** continua aberta no turno seguinte; o dinheiro conta no turno em que for **pago**, então
  o caixa que passou o turno não dá falta e o que recebeu a comanda não dá sobra (teste em `tests/test_protecao.py`).

## Estrutura do repositório

Tudo está em <https://github.com/GodFather-byte/PDV-CASA->. As pastas principais:

| Pasta / arquivo | O que é |
| --- | --- |
| [`src/`](src) | o **PDV** (WillPDV): `controllers/` (regras de negócio), `database/` (esquema e acesso ao SQLite), `hardware/` (impressora térmica ESC/POS, balança, gaveta), `core/` (dinheiro, segurança, licença, erros), `sync/` (transporte PDV ↔ nuvem), `ui/` (telas Tkinter; `app.py` é a janela principal e `caixa_ui.py` o caixa) |
| [`licenciador/`](licenciador) | o programa **WillPDV Licenças** (gerador de licenças, do fornecedor): `nucleo.py` (regras), `tela.py` (janela), `autoteste.py`, `app.py` (entrada) |
| [`tools/`](tools) | ferramentas do fornecedor: `gerar_licenca.py` (licenças pela linha de comando) e `gerar_logos.py`; não vão no instalador do PDV |
| [`backend/`](backend) | API de nuvem (FastAPI) de licença e atualizações; não é usada pelo PDV local |
| [`instalador/`](instalador) | scripts do Inno Setup (`WillPDV.iss`, `WillLicencas.iss`), ícones e imagens dos dois instaladores |
| [`build_pdv.py`](build_pdv.py) · [`build_licenciador.py`](build_licenciador.py) | geram o executável (PyInstaller) e o instalador de cada programa |
| [`tests/`](tests) | regras de negócio, telas (com um robô que opera as janelas modais), nuvem, licenças e o teste de fumaça |
| [`docs/`](docs) | guias passo a passo (ver [Documentação](#documentação-pasta-docs)) |
| [`.github/workflows/`](.github/workflows) | `testes.yml` (suíte em Windows e Linux) e `build-windows.yml` (gera e testa os dois instaladores) |
| [`LICENSE`](LICENSE) | licença do software: proprietária, código visível |

## Banco local e dados

O banco padrão é `loja_offline.db`, na raiz do projeto (no executável, em `%LOCALAPPDATA%\WILL-PDV`). Para usar outro arquivo no
PowerShell:

```powershell
$env:PDV_DB = "$PWD\dados\loja_offline.db"
python -m src.app
```

Ao detectar o banco do protótipo antigo, o sistema arquiva uma cópia
`*.legado-*.bak` e cria o esquema atual. **O backup não é uma migração:** os
registros antigos não são importados para o banco novo. Faça e confira uma cópia
antes de apontar o PDV para dados importantes.

Convenções obrigatórias entre as camadas:

- valores monetários são inteiros em centavos (`350` = R$ 3,50), nunca `float`;
- quantidades usam até quatro casas decimais;
- timestamps locais são armazenados em ISO (`YYYY-MM-DD HH:MM:SS`);
- UUID identifica a venda e permite reenvio idempotente.

## Licença do software (copyright)

O código é público para leitura e avaliação, mas o WillPDV **não é software livre**: todos os direitos reservados a
WillyanPHP. Dá para ler, estudar e rodar para testar sem fins comerciais; usar numa loja de verdade exige a licença comercial
(o código de licença assinado, veja [WillPDV Licenças](#willpdv-licenças-o-gerador-de-licenças)); copiar, modificar e distribuir, revender, gerar instaladores para
terceiros ou contornar a verificação de licença é proibido. Os termos completos estão em [`LICENSE`](LICENSE).

## WillPDV Licenças: o gerador de licenças

O **WillPDV Licenças** é o programa, **separado do PDV**, que cria as licenças. Você escolhe a loja e o tipo, toca em **Gerar
licença** e copia o código (ou uma mensagem pronta) para mandar ao cliente. Tem tela, instalador próprio e confere a chave de
segurança; **não precisa de Python, de servidor, de bot nem de internet**.

> **Não entregue este programa a clientes.** O cliente recebe só o *código* da licença. Quem tem o programa **e a chave de
> segurança** emite licenças. Guia completo, também em [`docs/LICENCIADOR.md`](docs/LICENCIADOR.md).

### Onde ele está no GitHub

| O quê | Link |
| --- | --- |
| **Código-fonte do programa** | [`licenciador/`](https://github.com/GodFather-byte/PDV-CASA-/tree/main/licenciador): [`nucleo.py`](licenciador/nucleo.py) (regras: chave, emissão, histórico), [`tela.py`](licenciador/tela.py) (a janela), [`autoteste.py`](licenciador/autoteste.py), [`app.py`](licenciador/app.py) (entrada) |
| **Onde baixar o instalador pronto** | [GitHub Actions > Gerar instalador (Windows)](https://github.com/GodFather-byte/PDV-CASA-/actions/workflows/build-windows.yml) > abrir a execução mais recente > **Artifacts** > `WillLicencas-Instalador-<versão>-<commit>` (passo a passo [abaixo](#baixar-e-instalar)) |
| Guia de uso (documentação) | [`docs/LICENCIADOR.md`](docs/LICENCIADOR.md) |
| Gerar o `.exe` e o instalador | [`build_licenciador.py`](build_licenciador.py) e o script do Inno Setup [`instalador/WillLicencas.iss`](instalador/WillLicencas.iss) |
| Automação que gera e testa o instalador | job `licenciador` de [`.github/workflows/build-windows.yml`](.github/workflows/build-windows.yml) |
| Testes | [`tests/test_licenciador.py`](tests/test_licenciador.py) |
| Alternativa pela linha de comando | [`tools/gerar_licenca.py`](tools/gerar_licenca.py) (ver [Emitir licenças pela linha de comando](#emitir-licenças-pela-linha-de-comando)) |

O programa **não está na aba Releases** de propósito: a Release é pública e o gerador é só seu. Por isso ele só existe nos
*Artifacts* do GitHub Actions (entra com a sua conta do GitHub; ficam guardados por 30 dias, e dá para gerar de novo quando quiser).

### Baixar e instalar

1. Abra a página do workflow: <https://github.com/GodFather-byte/PDV-CASA-/actions/workflows/build-windows.yml>. (Se preferir:
   aba **Actions** do repositório > **Gerar instalador (Windows)**, na lista da esquerda.)
2. Clique na execução **mais recente com o ✔ verde** (a primeira da lista).
3. Role até o fim da página, em **Artifacts**, e baixe `WillLicencas-Instalador-<versão>-<commit>`. Vem um `.zip`: extraia.
4. Dê dois cliques em `WillLicencas-Setup-<versão>.exe` > Avançar > Instalar. **Não pede senha de administrador** e pode ficar
   instalado no mesmo computador do PDV.
5. Se o Windows avisar *"O Windows protegeu o seu computador"*, clique em **Mais informações > Executar assim mesmo** (o
   instalador ainda não tem assinatura digital paga). Se o antivírus reclamar, libere o arquivo.

**Não há execução recente, ou o artifact venceu (30 dias)?** Abra a mesma página do workflow, clique em **Run workflow**, escolha
a branch (`main`) e confirme. Em uns 6 a 12 minutos a execução termina e o artifact reaparece. O mesmo vale se a execução mais
recente estiver vermelha: use a última verde.

**Atualizar ou desinstalar:** rode o instalador novo por cima (se o programa estiver aberto, o instalador avisa e fecha). A
**chave de segurança e o histórico não são apagados** nem ao atualizar nem ao desinstalar.

### Primeira vez: a chave de segurança

A chave de segurança é o que prova que a licença é sua. É um arquivo, `licenca_privada.key`, que fica **só neste computador**, em
`C:\Users\SEU_USUARIO\.pdv-casa\`. Abra a aba **Chave de segurança**:

| Situação | O que fazer |
| --- | --- |
| Já emitia licenças pelo PC (linha de comando) e tem a chave neste computador | Nada: aparece *"Chave de segurança conferida: combina com a do PDV"* |
| Tem a chave, mas em outro computador | **Importar chave...** e escolher o arquivo `licenca_privada.key` |
| Aparece *"Esta chave NÃO é a do PDV"* | É uma chave diferente da que está dentro do PDV: os caixas recusariam as licenças. Importe a chave certa (a que gerou o PDV) |
| Nunca criou uma chave | **Criar chave nova**, depois cole a *chave pública* mostrada na tela em `CHAVE_PUBLICA_HEX` ([`src/core/licenca.py`](src/core/licenca.py)) e gere o PDV de novo. **Só faça isso uma vez** |

- O programa **nunca sobrescreve** uma chave existente (trocar a chave invalida todas as licenças já emitidas); ao importar por
  cima de outra, a antiga vira `licenca_privada.key.bak`.
- Faça logo a **cópia de segurança** (botão da mesma aba, num pendrive). **Sem a chave não se emite mais licença**, e ela não
  está no GitHub nem em lugar nenhum além do seu computador e das suas cópias. **Nunca** a coloque no GitHub nem no PC do cliente.
- O programa só emite quando a chave está *conferida* (combina com a chave pública que vai dentro do PDV).

### Emitir uma licença

1. Aba **Emitir licença**. Digite a **loja**: a mesma chave de loja do PDV (as já usadas aparecem na lista). Maiúsculas e
   minúsculas não importam, mas o nome tem de ser o mesmo da loja.
2. Escolha o **tipo** (a tela mostra até quando vale):

   | Tipo | Quando usar | Validade |
   | --- | --- | --- |
   | **Mensal** | a loja que paga todo mês (ou a cada 3, 6, 12 meses) | de 1 a 60 **meses de calendário**: 1 mês a partir de 09/10 vai até 09/11 |
   | **Permanente** | a loja que comprou o sistema | sem vencimento na prática (100 anos) |
   | **Teste** | demonstração para quem ainda não contratou | de 1 a 90 dias |
3. **Gerar licença**. Aparece o código, que começa por `PDVL1.`.
4. Use **Copiar mensagem pronta para o cliente** (traz o código e o passo a passo, boa para WhatsApp ou e-mail), **Copiar código**
   ou **Salvar em arquivo...**.
5. No caixa do cliente: tela de entrada > **Código de licença...** > colar o código inteiro > confirmar.

### Acompanhar e renovar

- Aba **Lojas e vencimentos:** cada loja aparece uma vez, com a licença mais nova; quem vence primeiro fica no alto.
  **Vermelho** = vencida, **amarelo** = vence em até 7 dias. Selecione a loja e use **Renovar a selecionada** (o formulário já
  vem com o mesmo tipo e prazo), **Copiar o código dela** ou **Remover do histórico**.
- Renovar é emitir um código novo e mandar de novo: a loja cola no mesmo lugar. Um código mais antigo que o atual é recusado.
- O histórico (com o código de cada licença emitida) fica em
  `C:\Users\SEU_USUARIO\AppData\Local\WillPDV-Licencas\historico.json`.

### Conferir um código

Aba **Conferir um código:** cole um código `PDVL1....` e veja de que loja é, quando foi emitido e até quando vale. Útil quando o
cliente liga dizendo que "não entra".

### Resumo das abas

| Aba | Para quê |
| --- | --- |
| Emitir licença | criar o código (mensal, permanente ou teste) e copiar a mensagem pronta |
| Lojas e vencimentos | ver quem vence, renovar com um clique |
| Conferir um código | ver loja e validade de um código já emitido |
| Chave de segurança | importar, criar, conferir e fazer cópia da chave; abrir a pasta dela |

### Problemas comuns

| Mensagem ou sintoma | Causa e solução |
| --- | --- |
| *Ainda não há chave de segurança neste computador* | Importe a sua chave (se já tem) ou crie uma na aba Chave de segurança |
| *Esta chave NÃO é a do PDV* | A chave é de outro par. Importe a que gerou o PDV; senão, os caixas recusam as licenças |
| *Já existe uma chave... Não vou sobrescrever* | Proteção de propósito: trocar a chave invalida todas as licenças emitidas |
| O caixa diz que o código é de outra loja | Depois da 1ª ativação o caixa só aceita códigos **da mesma loja**: confira o nome (maiúsculas não importam) |
| O caixa recusa o código | Confira o código na aba **Conferir um código**; se for mais antigo que o atual do caixa, emita um novo |
| O artifact não aparece / venceu | Rode o workflow de novo (**Run workflow**), como explicado em [Baixar e instalar](#baixar-e-instalar) |
| SmartScreen ou antivírus bloqueia | Instalador sem assinatura digital paga: **Mais informações > Executar assim mesmo** e libere no antivírus |

### Para quem mantém o programa

- Gerar localmente (Windows): `pip install pyinstaller` e, na raiz do repositório, `python build_licenciador.py` (gera
  `dist\WillLicencas\WillLicencas.exe` e, com o [Inno Setup 6](https://jrsoftware.org/isdl.php), o instalador em
  `instalador\saida\WillLicencas-Setup-<versão>.exe`). Para só o `.exe`: `python build_licenciador.py --sem-instalador`.
- Rodar do código-fonte: `python -m licenciador.app` (precisa do Tkinter, que vem com o Python do Windows). Autoteste:
  `python -m licenciador.app --autoteste`.
- Testes: `python -m unittest tests.test_licenciador`.
- A versão do programa fica em `VERSAO` em [`licenciador/nucleo.py`](licenciador/nucleo.py) (hoje 1.1.0); o número do
  instalador vem dela. Ele usa o mesmo formato de chave e de código do `tools/gerar_licenca.py`, então os dois conversam.
- O job `licenciador` do workflow gera o instalador, abre o `.exe` (autoteste), instala de verdade (silencioso), roda o autoteste
  do instalado e atualiza por cima com o programa aberto. Se qualquer etapa falhar, a execução fica vermelha e não há artifact.
- Logotipo: troque `instalador/willlicencas.ico`, `willlicencas-assistente.bmp` (164x314) e `willlicencas-assistente-pequena.bmp`
  (55x55) mantendo os nomes (os do PDV são os `willpdv-*`). Para regenerar os desenhos padrão: `pip install pillow` e
  `python -m tools.gerar_logos`.

## Como a licença funciona no caixa do cliente

A licença é um código assinado (Ed25519) que leva a **chave da loja** e o **último dia de validade**. O PDV só guarda a chave
**pública** (`CHAVE_PUBLICA_HEX`, em [`src/core/licenca.py`](src/core/licenca.py)) e **confere a assinatura sem internet**. A
privada fica só com você, fora do repositório (`~/.pdv-casa/licenca_privada.key`).

- O operador cola o código em **Código de licença...**, na tela de entrada. A primeira ativação grava o nome da loja; depois o
  caixa só aceita códigos **da mesma loja**.
- Avisa **7 dias antes** de vencer, dá **5 dias de carência** depois do vencimento e só então bloqueia a entrada. **Nunca**
  bloqueia com um turno recente aberto, e não deixa abrir turno novo com a licença bloqueada.
- Voltar o relógio do Windows não reabre o prazo. A validade máxima é 36500 dias (a licença permanente).
- No `.exe` a licença é **sempre** exigida; rodando do código-fonte (desenvolvimento) só vale com `licenca_exigir = S` nas
  configurações.
- A renovação automática pela nuvem ([abaixo](#licença-renovada-pela-nuvem)) é **opcional**: sem endereço da nuvem configurado
  ela não faz nada.

**Limites:** o código vale para a **loja** (nome), não para um computador específico, então funciona em qualquer PC dessa loja, e
uma cópia do código funciona onde for colada. Não dá para revogar um código já emitido (só deixar vencer ou trocar o par de
chaves, o que invalida todos).

## Emitir licenças pela linha de comando

> **Mais fácil:** use o programa [WillPDV Licenças](#willpdv-licenças-o-gerador-de-licenças). Os comandos abaixo fazem o mesmo,
> com a mesma chave e o mesmo formato de código (precisa de Python 3.10+; na raiz do repositório).

**Uma vez só (se ainda não tiver a chave):**

```powershell
python -m tools.gerar_licenca novo-par
```

Grava a chave **privada** em `C:\Users\SEU_USUARIO\.pdv-casa\licenca_privada.key` e mostra a **pública**. Cole a pública em
`CHAVE_PUBLICA_HEX` ([`src/core/licenca.py`](src/core/licenca.py)) e gere o instalador de novo. **Faça backup da privada e nunca a
coloque no GitHub nem no PC do cliente**; trocar o par invalida todos os códigos já emitidos.

**Para cada loja:**

```powershell
python -m tools.gerar_licenca emitir --loja BOATE-ESTRELA --dias 30        # mensal: vence em 30 dias
python -m tools.gerar_licenca emitir --loja BOATE-ESTRELA --permanente     # sem vencimento na prática (100 anos)
python -m tools.gerar_licenca ver CODIGO                                   # confere um código já emitido
```

Mande a linha impressa (começa por `PDVL1.`) ao cliente, que cola em **Código de licença...** na tela de entrada.

## Gerar o executável e o instalador

### O PDV (WillPDV)

`python build_pdv.py` gera o executável (PyInstaller) em `dist/WillPDV/`. No executável os dados (banco, Backup, impressao,
logs) ficam em `%LOCALAPPDATA%\WILL-PDV`.

**Sem Python no seu PC?** O GitHub Actions gera o instalador, testa o programa empacotado e o publica na aba **Releases**
("WillPDV - última versão"): [baixar o instalador](https://github.com/GodFather-byte/PDV-CASA-/releases/download/ultima-versao/WillPDV-Instalador.exe)
ou [abrir a página da Release](https://github.com/GodFather-byte/PDV-CASA-/releases/tag/ultima-versao). Passo a passo em
[`docs/INSTALAR_E_TESTAR.md`](docs/INSTALAR_E_TESTAR.md).

**Gerar na sua máquina** (Windows, uma vez só): instale o Python 3.10+ (64 bits), rode `pip install -r requirements.txt "pyinstaller>=6,<7"`
e instale o [Inno Setup 6](https://jrsoftware.org/isdl.php) (6.3 ou mais novo). A cada versão:

1. Suba o número em `src/versao.py`.
2. Na raiz do repositório: `python build_pdv.py`. Ele gera o executável e, achando o Inno Setup, o instalador
   `instalador\saida\WillPDV-Setup-<versão>.exe` (o script é `instalador\WillPDV.iss`; dá para abri-lo no Inno Setup e clicar em
   *Compile*). Ícone opcional: `instalador\willpdv.ico`.
3. Leve o `WillPDV-Setup-<versão>.exe` ao PC do caixa (pendrive ou link) e execute: Avançar, Avançar, Instalar. Ele instala em
   `Arquivos de Programas\WillPDV`, cria o atalho e, se marcado, abre o caixa ao ligar o computador.

Para atualizar, rode o instalador novo no mesmo PC (com o turno fechado): ele substitui o programa e mantém as vendas, que ficam
em `%LOCALAPPDATA%\WILL-PDV`. Desinstalar também não apaga esses dados; faça o backup antes de trocar de PC.

### O gerador de licenças (WillPDV Licenças)

`python build_licenciador.py` (ver [Para quem mantém o programa](#para-quem-mantém-o-programa)). Ele é do fornecedor e **não** vai
para a aba Releases.

### Como o GitHub Actions gera tudo

O workflow [`build-windows.yml`](.github/workflows/build-windows.yml) roda a cada push na `main` ou numa branch `claude/**`, numa
tag `v*` e sob demanda (**Run workflow**). Tem dois jobs de geração, ambos com autoteste e instalação de verdade:

| Job | Gera | Onde fica |
| --- | --- | --- |
| Programa e instalador | WillPDV (instalador e versão portátil) | Artifacts; na `main`, também na [Release "última versão"](https://github.com/GodFather-byte/PDV-CASA-/releases/tag/ultima-versao); numa tag `v*`, numa Release de versão |
| Programa de licenças | WillPDV Licenças (instalador) | **só** nos Artifacts (30 dias) |

A suíte de testes ([`testes.yml`](.github/workflows/testes.yml)) roda a cada push e pull request, em Windows e Linux, com Python
3.10 e 3.12.

## Telegram do dono (acompanhar a casa pelo celular)

> Passo a passo para o dono, botões do bot e perguntas frequentes: [`docs/TELEGRAM.md`](docs/TELEGRAM.md).

Opcional e desligado por padrão. Em **Configurações > Telegram** o dono liga o PDV a um bot do Telegram (token do @BotFather +
código de pareamento) e passa a receber no celular: caixa aberto/fechado com a diferença, cupons e itens cancelados, sangrias,
falha de backup e o resumo da noite; e a consultar vendas, caixa, estoque, mesas abertas e cancelamentos pelos botões do bot.
O PDV só faz conexões de saída (nada de servidor nem porta aberta) e, sem internet, o caixa segue normal e os avisos esperam na
fila. Só vão totais, nomes de operadores e números de comanda, nunca dados de clientes; as vendas continuam guardadas só no PDV.

## Nuvem (só licença e atualizações)

> Passo a passo para colocar a nuvem no ar, cadastrar boates e acompanhar as licenças: [`docs/NUVEM.md`](docs/NUVEM.md).

Cada boate tem o seu PDV e as vendas ficam só nele (use o backup). A nuvem (`backend/`, FastAPI) **não recebe vendas e não
tem painel**: ela guarda até quando cada loja pagou, entrega o código de licença e avisa sobre versão nova.

1. No servidor (`pip install -r backend/requirements.txt`), na raiz do repositório:

   ```powershell
   $env:PDV_API_TOKEN = "um-segredo-longo-e-aleatorio"      # token do administrador (lista de lojas)
   python -m backend.lojas criar BOATE-CENTRO "Boate Centro"  # uma vez por loja: mostra o token DESSA loja
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

   O token da loja aparece só na criação (a nuvem guarda apenas o hash); `python -m backend.lojas novo-token BOATE-CENTRO`
   troca um token vazado e `desativar`/`ativar` bloqueiam e liberam a loja.
2. No PDV, em Configurações > Nuvem, informe o endereço (`http://servidor:8000`), o token da loja e a chave da loja (a
   mesma usada no `criar`).
3. Deixe a verificação rodando em outra janela: `python -m src.app --sync` (no executável: `WillPDV.exe --sync`). Ela
   registra em `logs/sync.log`, espera cada vez mais se a nuvem cair e não faz nada se o endereço estiver vazio.

### Licença renovada pela nuvem

Com a chave privada do fornecedor no servidor (o mesmo arquivo de `tools.gerar_licenca`, em `PDV_LICENCA_CHAVE` ou
`~/.pdv-casa/licenca_privada.key`), basta registrar até quando cada loja pagou:

```powershell
python -m backend.lojas assinatura BOATE-CENTRO 2026-11-30   # pagou até 30/11
python -m backend.lojas assinatura BOATE-CENTRO cancelar     # não renova mais
```

O PDV da loja busca o código sozinho (pela verificação em segundo plano, a cada 6 horas, e na entrada quando a licença está vencida) e o
ativa se estender o prazo. Se a loja não pagar, a data não avança e a licença vence normalmente, com aviso e carência.
O código manual (`python -m tools.gerar_licenca emitir`) continua valendo para lojas sem internet.

### Avisar as lojas sobre uma versão nova

A versão do PDV fica em `src/versao.py` (aparece no canto da tela principal). Para cada entrega:

1. Suba o número em `src/versao.py` (ex.: `1.1.0` → `1.2.0`) e gere o executável.
2. Publique na nuvem, com as notas que o dono da loja vai ler:

   ```powershell
   python -m backend.atualizacoes publicar 1.2.0 --notas "Corrige o troco em dinheiro." --url https://seu-site/WillPDV-1.2.0.zip
   python -m backend.atualizacoes publicar 1.2.1 --notas "Corrige perda de vendas na transferência." --critica
   python -m backend.atualizacoes listar
   ```

Cada caixa conectado consulta a nuvem ao abrir o menu e a cada 6 horas pela verificação, e mostra uma faixa no painel
("Nova versão 1.2.0 disponível"). Ao clicar, aparecem as notas de todas as versões que a loja ainda não tem e o botão
para baixar. `--critica` deixa a faixa vermelha e tira a opção "Não avisar desta versão": use para correções de dinheiro
ou de dados. O aviso some sozinho quando a loja instala a versão anunciada. O PDV não se atualiza sozinho de propósito:
uma instalação que falhasse no meio do expediente pararia o caixa.

Antes de operar comercialmente ainda é necessário: HTTPS (proxy reverso ou túnel), teste em loja com a
rotina real do caixa, backup e restauração testados, hardware fiscal/periféricos e homologação no ambiente da loja.

## Documentação (pasta `docs/`)

| Documento | Para quê |
| --- | --- |
| [`INSTALAR_E_TESTAR.md`](docs/INSTALAR_E_TESTAR.md) | gerar, baixar, instalar e testar o WillPDV no Windows (GitHub Actions) |
| [`LICENCIADOR.md`](docs/LICENCIADOR.md) | o programa WillPDV Licenças (gerador de licenças) |
| [`NUVEM.md`](docs/NUVEM.md) | colocar a nuvem no ar (Render + Neon), cadastrar boates, acompanhar licenças e avisar versões |
| [`TELEGRAM.md`](docs/TELEGRAM.md) | o bot do Telegram do dono: passo a passo, botões e perguntas frequentes |
| [`ESTOQUE.md`](docs/ESTOQUE.md) | o painel de estoque, pedido e lista de compras; fardos e as regras da adega (gelada, atacado, cascos) |
| [`ADEGA.md`](docs/ADEGA.md) | checklist de implantação numa adega/depósito de bebidas e o treinamento do operador |
| [`PAINEL_DONO.md`](docs/PAINEL_DONO.md) | painel do dono no celular (app web instalável, servido pela nuvem) |
| [`PILOTO.md`](docs/PILOTO.md) | checklist do piloto na boate (o que já foi verificado e o que falta provar em loja) |
| [`ESPECIFICACAO.md`](docs/ESPECIFICACAO.md) | liga cada seção dos manuais Willyan ao código |
| [`COORDENACAO.md`](docs/COORDENACAO.md) | notas de coordenação entre os agentes que escrevem o projeto |
