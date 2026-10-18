# Importar produtos em massa (planilha)

Cadastros > Produtos > **Importar planilha**. Serve para cadastrar de uma vez a lista de produtos de uma casa nova, atualizar
preços em massa ou levar o cardápio de outro sistema. O PDV **não traz produtos prontos**: cada casa importa os seus.

## Passo a passo
1. **Baixar planilha modelo** (ou **Exportar produtos atuais**, para editar preços e importar de volta). Os arquivos são CSV com ";",
   que o Excel brasileiro abre direto; também dá para importar um `.xlsx`.
2. Preencha. Só **Produto** e **Preço** são obrigatórios; os títulos aceitam variações ("Bebida", "Valor", "Código"...).
3. **Escolher a planilha**. O PDV mostra a **prévia**: o que vai ser criado (verde), atualizado (azul) ou recusado (vermelho, com o
   motivo na última coluna). **Nada é gravado até você clicar em Importar** (botão verde logo acima da lista, à direita). Se algo falhar no meio, nada fica pela metade.

## Colunas
| Coluna | Para quê |
| --- | --- |
| Código | número do produto. Em branco: o PDV numera em sequência (1, 2, 3...), pulando os que já existem |
| Produto | nome (até 50 letras; vira MAIÚSCULAS, opção desligável) |
| Preço | preço de venda (`10,00` ou `R$ 10,00`) |
| Comissão (R$) | quanto a garota ganha por unidade; o PDV converte para o percentual do produto (R$ 15 em R$ 45 = 33,33%) |
| Grupo | cria o grupo se não existir; vazio = DIVERSOS |
| Unidade | UN, KG... (vazio = UN) |
| Quantidade | estoque inicial: o produto passa a controlar estoque e o saldo vira um lançamento "Inicial" |
| Estoque mínimo | ponto de pedido |
| Código de barras, Atalho | opcionais |
| Controla estoque | `S` para controlar começando em zero (para contar depois no painel de estoque) |
| Preço gelada | opcional (adega): preço da bebida gelada; `0` desliga; vazio não mexe no que já está cadastrado |
| Atacado a partir de, Preço atacado | opcionais (adega): quantidade mínima e preço unitário do atacado natural, sempre os dois (ou `0` nos dois para desligar); vazio não mexe. O atacado gelada se cadastra na tela do produto |

## Regras de código
* **Códigos reservados do caixa** (comissão das garotas, 50 por padrão, e saída da comanda, 1002) **nunca** são usados em produto: na
  numeração em sequência são pulados e, se a planilha trouxer um deles, a linha é recusada.
* *Usar o código da planilha*: respeita a coluna; os sem código recebem o próximo livre. *Numerar tudo em sequência*: ignora a coluna e
  numera a partir do número que você escolher.
* Produto que já existe (mesmo código, ou mesmo nome sem código) é **atualizado**; dá para desligar essa opção.
* **Código repetido na planilha:** cada código é de um produto só (é o que o caixa usa para achar o item). Se a mesma linha de código
  aparecer duas vezes, a segunda é recusada na prévia ("aparece de novo na linha N"): dê um número livre a ela.
* **Produto excluído:** não participa da busca de cadastro nem da importação. A planilha cria um produto novo,
  mesmo se trouxer o código ou o nome que já foi usado. O histórico continua ligado à identidade antiga, não à nova.
* **Produto apenas inativo:** ainda é um cadastro. A prévia pode reativá-lo explicitamente; se outro produto precisar
  do seu código, a exclusão do cadastro inativo preserva o histórico em separado. Produto ativo não cede código.

## Excluir um produto e reutilizar seu código

Em **Cadastros > Produtos**, selecione o produto e use **Excluir**, não apenas desmarque **Ativo**.
O produto sai definitivamente do cadastro comercial. Nome, código, código de barras e atalho ficam livres.
Por exemplo: exclua **Amarula (8)** e cadastre **Red Bull (8)**. As vendas antigas continuam mostrando Amarula;
as novas apontam para Red Bull. Os totais e as quantidades não são transferidos entre eles.

O banco mantém registros históricos separados, necessários para cupons, relatórios e estornos.
Isso não é apagamento de vendas nem limpeza de movimento. Cancelar uma venda antiga movimenta a identidade
antiga do estoque e não acrescenta mercadoria ao novo produto que reutilizou o código.

A exclusão individual é recusada se o produto estiver em item/parte de venda aberta, em pedido de compra pendente
ou for insumo de uma ficha técnica. Resolva essas dependências antes; elas não são removidas silenciosamente.
Na exclusão total, as fichas técnicas do catálogo são removidas juntas, depois do backup.

## Começar do zero: excluir todos os produtos
Para cadastrar a tabela inteira de novo, use **Excluir todos os produtos...** (botão no alto da janela de importação, ou
**Utilitários > Excluir todos os produtos**; só o administrador, nível 4). A tela mostra os números e só executa depois de você digitar
**APAGAR**.
* Um **backup é feito antes** (o caminho aparece no fim); para desfazer, restaure esse backup em Utilitários > Restaurar backup.
* Com mesa, comanda ou balcão **abertos com itens**, a exclusão é recusada: feche ou cancele antes.
* **Todos saem do cadastro**, inclusive os já vendidos. Os registros de cupons, vendas, compras e movimentos de estoque
  permanecem no histórico. Uma nova importação cria novas identidades, sem alterar os produtos das vendas antigas.
* Pedidos de compra pendentes devem ser concluídos ou ter seus itens removidos antes da exclusão.
* Grupos, subgrupos e unidades **ficam**; os códigos dos produtos excluídos ficam livres para a planilha nova.

### Atualização de banco existente

O esquema v17 separa o cadastro comercial dos registros históricos, migra os relacionamentos e preserva IDs e movimentos.
Antes de migrar um banco em arquivo, o programa cria uma cópia ao lado dele com nome
`<banco>.antes-migracao-v<versao>-<identificador>.bak`. Não apague essa cópia antes de conferir a atualização.
O programa antigo não deve ser usado para abrir um banco mais novo: a abertura agora é recusada.

## A tabela da casa (`docs/produtos_da_casa.csv`)
Planilha pronta com os 31 produtos da folha de preços do salão, já com os **códigos da folha** (use *Usar o código da planilha*, que é o
padrão). Na folha, os códigos 6 (Catuaba, Fogo Paulista e Montila), 25 (Whisk Nasc. e Capirinha) e 20 (Ice e Long Neck) se repetiam; como
cada código é de um produto só, Fogo Paulista ficou com 7, Montila com 8, Capirinha com 22 e Long Neck com 21 (números que não estavam
em uso). A Música não tem código na folha e recebe o primeiro número livre (9). Confira os preços e as comissões antes de importar.
