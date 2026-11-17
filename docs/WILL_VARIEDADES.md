# Will Variedades

Edição do WillPDV para loja de eletrônicos, utilidades e presentes: fone, cabo, carregador, panela, meia, copo
personalizado. Mesmo código, outra marca, dados em `%LOCALAPPDATA%\WILL-VARIEDADES` e licença própria.

```
python -m src.app --edicao willvariedades        (Windows: iniciar_will_variedades.bat)
python build_pdv.py --edicao willvariedades      (instalador; ou o workflow "Will Variedades" no GitHub)
python -m tools.gerar_licenca emitir --loja LOJA-01 --dias 30 --edicao willvariedades
```

## O que muda em relação ao WillPDV

- Venda só no balcão, pelo leitor. Recebimento direto e sem a taxa do crédito (o dono pode religar).
- Caderneta (fiado), desconto e atacado ("leve 3 pague menos") ligados.
- Sem mesas, comandas, garotas, portaria, cozinha, quartos, retornáveis e pedido online.
- Sem preço "gelada" e sem casco: no cadastro do produto a aba se chama Atacado.
- Categorias prontas: Eletrônicos, Casa, Pessoal e Presentes, com 14 subgrupos.

## Cadastrar a loja

1. Produtos > Importar produtos > **Produtos prontos**: cerca de 280 itens sem marca, com subgrupo e NCM. Digite o preço
   do que a loja vende e clique em Adicionar. Alguns itens vêm sem NCM (pilha, fita adesiva, boné, mouse pad) porque a
   classificação depende do material: o contador informa.
2. Planilha (CSV/Excel) ou XML da nota de compra, como nas outras edições.
3. Pelo fornecedor: na central, Importar planilha > "Carregar catálogo de variedades e eletrônicos".

## Etiqueta com código de barras

Para mercadoria sem código de fábrica (meia, copo, utilidade importada).

1. Estoque > selecione os produtos > **Etiquetas**.
2. Escolha o papel: folha A4 com 33 etiquetas (63,5 x 25,4 mm), folha A4 com 65 (38,2 x 21,2 mm) ou rolo de
   impressora de etiquetas (40 x 25 ou 50 x 30 mm).
3. **Com código de barras...**: se algum produto não tem código, o programa pergunta se gera um código próprio da loja.
   O código (13 números, começando por 200) fica gravado no cadastro e o caixa passa a ler a etiqueta.
4. A folha abre no navegador. Imprima em **tamanho real (escala 100%)**, sem "ajustar à página". No rolo, escolha na
   impressora o papel do mesmo tamanho da etiqueta.

"Pular" deixa em branco as primeiras etiquetas de uma folha A4 que já foi usada. Produto com código de fábrica sai com
as barras do próprio código; código que não é EAN de 8 ou 13 números sai só com o número do cadastro.
