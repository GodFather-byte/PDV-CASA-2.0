# Handoff de 28/11/2026: importar planilha na retaguarda (branch `cursor/importar-planilha-retaguarda-d0b9`)

- Defeito: em "Importar planilha de produtos" (`backend/retaguarda_web/app.js`), escolher qualquer arquivo
  estourava `Cannot read properties of undefined (reading 'firstChild')`. `Element.append()` devolve
  `undefined`; a prévia encadeava `.firstChild` / `.lastChild` em cima disso e a tabela (e o botão Enviar)
  não apareciam. A mesma cadeia existia na prévia do "Cadastro com IA".
- Leitura: CSV com `;` ou `,`, decimal com vírgula ou ponto, e `.xlsx`. Título "Venda" vale como preço.
  Coluna Código com 8 a 14 dígitos, sem coluna de barras, vira o EAN (`promover_codigo_de_barras`).
  Código curto continua o código interno do caixa.
- Envio: o comando `produtos.importar` casa pelo código de barras (`casar_barras`) e a quantidade substitui
  o estoque. Nome ou código de barras que já existe na loja atualiza o produto; não cria outro.
- Só nuvem + a leitura compartilhada da planilha. O caixa que já está na loja aplica o comando. Testes:
  `tests/test_importacao_produtos.py`, `tests/test_retaguarda.py`.
