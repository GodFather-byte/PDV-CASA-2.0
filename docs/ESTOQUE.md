# Estoque do WillPDV

O estoque abre pelo menu **Lançamentos > Estoque**, pelo atalho **Lançar estoque** ou clicando nos cartões de estoque da tela
principal (o cartão "Sem estoque" já abre a lista só com os produtos zerados).

## Painel de Estoque (visão geral)

* **Cartões:** produtos controlados, sem estoque, para repor, normais e o **valor parado** (quantidade × último preço de
  compra). Clicar num cartão filtra a lista.
* **Lista:** cor por situação (vermelho = sem estoque, amarelo = no ponto de pedido ou abaixo, normal), barrinha de nível,
  quanto repor e valor parado. Clique no título da coluna para ordenar. A busca filtra enquanto você digita (nome ou código) e
  dá para filtrar por grupo.
* **Detalhe do produto** (ao clicar numa linha): quantidade, mínimo, último preço, sugestão de compra e os últimos movimentos.
  Quatro botões resolvem o dia a dia sem montar lançamento:
  * **Entrada** (chegou mercadoria; duplo clique ou Enter na linha também abre),
  * **Saída** (saiu sem ser venda),
  * **Perda / quebra**,
  * **Contei e ajustar** (o que você digitar vira o estoque; a diferença fica registrada),
  * e **Definir estoque mínimo**.

  O diálogo mostra "Vai ficar com X" antes de gravar. Cada ação cria o lançamento do dia e entra no histórico, igual a um
  lançamento feito à mão, e pode ser desfeita em *Novo lançamento > Abrir anterior > Excluir*.
* **Produto cadastrado sem controle de estoque** (ex.: o RedBull cadastrado sem a marca "Controla estoque"): ele não entra
  nos cartões, mas **aparece na busca** e no filtro **Sem controle**. Clique nele e use **Contei e ajustar** (ou Entrada)
  informando quanto tem agora: o controle liga sozinho e ele passa a ser contado e baixado nas vendas.
* **Editar cadastro do produto:** o botão abre o cadastro já no produto escolhido (nome, preço, estoque mínimo...). No próprio
  cadastro de produtos (Cadastros > Produtos) há também o botão **Ajustar estoque**, que faz a mesma contagem. O campo
  "Qt. atual" do formulário é só leitura de propósito: toda mudança de quantidade vira um movimento no histórico.
* **Gerar pedido do que falta:** cria um *pedido* ao fornecedor escolhido com todos os produtos sem estoque ou no ponto de
  pedido, na quantidade sugerida (repor até o **dobro do mínimo**). O pedido não mexe no estoque até você confirmar a entrega,
  quando vira compra. Produtos sem estoque mínimo definido não entram na sugestão.
* **Lista de compras:** a mesma sugestão em texto, para imprimir ou levar ao fornecedor.

## Novo lançamento (completo)

A janela de lançamento continua com todos os tipos (compra com nota e conta a pagar, entrada, saída, descarte, contagem,
estoque inicial, pedido e descarte de produtos acabados). Agora cada tipo aparece como um cartão com uma frase simples do
que ele faz, e uma linha de explicação mostra o efeito no estoque antes de lançar. No campo do produto, a lista suspensa
filtra enquanto você digita, e "150 skol" continua lançando 150 unidades de uma vez.

## Fardo e caixa fechada (adega, depósito)

O fardo (ou a caixa fechada) é criado no Cadastro de Produtos pelo botão **Fardo / caixa**, a partir do produto unitário
(ex.: "SKOL LATA - FARDO" com 12 "SKOL LATA"). Ele **não tem estoque próprio**: o estoque fica sempre na unidade.

* **Venda:** vender 1 fardo baixa 12 latas.
* **Compra, entrada, saída e perda de fardos** (na janela de lançamento ou no painel): pode lançar no fardo, em fardos. O
  sistema grava nas unidades: 10 fardos de 12 entram como 120 latas, pelo mesmo valor da nota, e o último preço de compra
  fica por lata. O painel mostra a prévia já em latas.
* **Contagem e estoque inicial:** conte as latas no produto unitário. No fardo eles são recusados, porque as latas soltas
  da prateleira também fazem parte do estoque.

Permissões: o painel e o lançamento usam o módulo **Lançamento de estoque**; quem só tem o relatório de estoque continua
abrindo o relatório pelos cartões.

## Regras de saldo, perdas e acesso

* O fechamento da venda confere, em uma transação, o saldo total necessário por produto e pelos insumos da composição.
  Sem saldo suficiente, a venda continua aberta, o estoque não muda e o operador recebe a lista do que falta. A tentativa
  fica na auditoria.
* No cadastro, marque **Aceita decimal** para permitir quantidades fracionadas. Quantidades e movimentos aceitam até
  quatro casas decimais; valores com precisão maior são recusados. Produtos sem essa opção aceitam somente inteiros.
* Para perdas, escolha **Quebra**, **Oxidação** ou **Devolução**. Todas registram a baixa; em Devolução, informe a
  devolução ao fornecedor. A observação é opcional. Tipo, quantidade, operador e data ficam no histórico/auditoria.
* Ajustes manuais de saldo e custo exigem operador nível 4 (gerente/administrador). O lançamento normal de compra continua
  registrando o custo informado na nota.

## Operação de adega: natural, gelada, atacado e cascos

No Cadastro de Produtos, a seção **Adega** complementa o preço de venda normal:

* **Natural** usa o preço normal, incluindo as promoções já cadastradas.
* **Gelada** tem preço próprio opcional. Deixe zero para não perguntar a temperatura.
  Natural e gelada são o **mesmo produto e o mesmo estoque**: vender duas naturais
  e três geladas baixa cinco unidades, somente no fechamento.
* **Atacado natural e gelada** têm, cada um, uma quantidade mínima e um preço
  unitário. Preencha os dois campos da faixa ou deixe ambos zerados para desativar.
  No balcão, ao atingir o mínimo, o preço vale para **todas as unidades daquele
  produto e daquela temperatura** na venda. Temperaturas, produtos e fardos
  diferentes não se somam. A regra funciona mesmo com várias linhas.
  Para natural, vale o menor preço entre a promoção vigente na leitura e o atacado;
  gelada compara seu preço próprio com seu atacado próprio.
  Cancelar uma linha e ficar abaixo do mínimo restaura o preço-base das linhas
  restantes. Mesas, entregas e caderneta não recebem atacado automático.
* **Casco** aponta para outro produto vendável (ex.: CASCO 600 ML, com preço próprio).
  O vínculo é para bebidas vendidas por unidade, sem fracionamento, montagem ou
  composição/fardo. Cadastre o casco antes de vinculá-lo à bebida.
  Ao lançar a bebida, informe quantos cascos devem ser cobrados: zero quando
  o cliente trouxe todas as trocas, até a quantidade de bebidas quando não trouxe.
  Bebida e cascos são lançados juntos, ou nenhum é lançado se houver erro/desistência.
  O casco aparece como **produto separado** no cupom e segue o estoque de seu cadastro.
  Não há empréstimo, depósito reembolsável, saldo por cliente ou entrada automática
  das embalagens devolvidas. Para cancelar a compra inteira, confira **as duas linhas**:
  cancelar somente a bebida não cancela os cascos, nem o inverso.

O perfil **Adega** liga **Configurações > Caixa > Agrupar produtos iguais e da mesma
temperatura no balcão**. Leituras compatíveis ficam em uma linha, sem misturar
temperatura, observação, operador ou preço-base diferentes, nem produtos montados,
itens já preparados ou categorias com impressão remota (para não reenviar quantidades
acumuladas à cozinha/bar). Delete cancela a linha inteira, com toda a quantidade agrupada.
O agrupamento pode ser desligado; os demais perfis mantêm o padrão anterior.

O leitor continua aceitando **6*código** para lançar seis unidades diretamente.
Código de barras numérico desconhecido com oito ou mais dígitos oferece cadastro
rápido (nome, preço, categoria e, opcionais, estoque e preço gelada), com autorização de supervisor quando o operador não
pode cadastrar produtos. A **Tabela de preços** impressa (Cadastro de Produtos > Imprimir Tabela) traz, sob cada produto,
o preço gelada e as faixas de atacado. A importação por planilha aceita as colunas "Preço gelada", "Atacado a partir de" e
"Preço atacado" ([IMPORTAR_PRODUTOS.md](IMPORTAR_PRODUTOS.md)).

Antes da instalação, homologue em cópia do banco: seis unidades atingindo o atacado,
natural e gelada sem somar mínimos, cobrança com/sem troca de casco, cancelamento,
estoque de fardo e impressão. O cupom continua **NÃO FISCAL**: este módulo não emite
NFC-e e não substitui a verificação das exigências fiscais da loja.
