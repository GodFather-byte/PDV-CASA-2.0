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

Permissões: o painel e o lançamento usam o módulo **Lançamento de estoque**; quem só tem o relatório de estoque continua
abrindo o relatório pelos cartões.
