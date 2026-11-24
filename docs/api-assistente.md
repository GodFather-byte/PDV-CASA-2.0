# API do assistente no painel

O assistente da loja (e o dono, no navegador) usa a mesma autenticação da importação de planilha.
Custo e lucro aparecem nestas rotas porque quem entra no painel, ou gera o token, é o dono.
Não existe login de operador aqui. Trate o token como senha: ele ajusta preço e estoque.

Endereço da nuvem desta instalação: `https://willpdv-nuvem-6sp0.onrender.com`.

## Entrar

| Jeito | Cabeçalho |
|---|---|
| Sessão do painel | `Authorization: Bearer` com o token que o `POST /v1/painel/login` devolve. O navegador do `/painel/` não usa esse token: manda `X-PDV-Painel: 1` e a sessão fica num cookie `HttpOnly` (`willpdv_painel`). Sem esse cabeçalho, o login continua devolvendo o token para o assistente. |
| Token da loja | `Authorization: Bearer wpdv_...` gerado em Produtos → Token do assistente |

O token é de uma loja só. Na rede, a sessão pede `loja` (a chave, por exemplo `EA-SUPERACOES`) em toda chamada que mexe numa loja. O comparativo entre lojas usa a sessão da rede (`/painel/?grupo=EA-REDE`), sem token de uma loja só.

Sem `dry_run: false`, preço, reajuste e estoque só devolvem a prévia. Nada entra na fila.

Dinheiro em centavos inteiros (`350` = R$ 3,50). Quantidade com até 4 casas. Data `AAAA-MM-DD`.

## Ler

`GET /v1/painel/gestao/resumo?de=2026-11-24&ate=2026-11-24`

Resumo do período: faturamento, vendas, ticket médio, canceladas e os 5 produtos que mais venderam. Sem data, vale o dia de hoje na nuvem.

`GET /v1/painel/gestao/relatorio?tipo=TIPO&de=&ate=&formato=json`

`formato` pode ser `json`, `csv` ou `xlsx`. Tipos:

| tipo | O que devolve |
|---|---|
| `resumo` | Igual ao resumo acima |
| `vendas` | Por dia e por hora |
| `produtos` | Quantidade, faturamento e, quando o caixa enviou custo, lucro e margem |
| `categorias` | O mesmo, por grupo do item |
| `abc` | Curva ABC pelo faturamento: A até 80%, B até 95%, C o resto |
| `formas` | Por forma de pagamento |
| `operadores` | Vendas, faturamento, ticket e desconto de cada operador |
| `estoque` | Abaixo do mínimo, parados e sugestão de compra para 7 dias |
| `caixa` | Fechamentos e sangrias do retrato (cerca de 31 dias) |
| `rede` | Comparativo das lojas. Só com a sessão da rede |

`GET /v1/painel/gestao/painel?de=&ate=` junta ABC, categorias, operadores, dias e estoque para a aba Relatórios.

`GET /v1/painel/gestao/produtos?q=vinho` até 50 produtos do cadastro que o caixa subiu (preço, custo, estoque, mínimo, grupo).

`GET /v1/painel/gestao/auditoria?limite=30` quem pediu, quando, e se o caixa já aplicou. Senha de operador não aparece.

## Escrever

O caixa aplica na sincronização, com os comandos que ele já conhece (`cadastro.salvar` e `estoque.movimento`). Não há comando novo: caixa antigo com a retaguarda ligada aceita. Sem a retaguarda ligada no caixa (Configurações → Nuvem), a escrita responde que o cadastro ainda não subiu.

`POST /v1/painel/gestao/precos`

```json
{"itens": [{"id": 12, "preco_cent": 990, "estoque_minimo": 6, "subgrupo_id": 3, "ativo": 0}]}
```

Dá para achar o produto por `id`, `codigo_barras` ou `nome` (o nome tem de ser único). `ativo: 0` inativa. Campos aceitos: `preco_cent`, `custo_medio_cent`, `estoque_minimo`, `subgrupo_id`, `ativo`.

`POST /v1/painel/gestao/reajuste`

```json
{"categoria": "Vinhos", "percentual": 10}
```

`categoria` é o nome do grupo, o do subgrupo, ou `"Tinto - Vinhos"` quando o subgrupo se repete. `percentual` de -90 a 300, nunca zero. `10` soma 10%. Só produtos ativos com preço. O preço novo é absoluto: repetir antes do caixa aplicar manda o mesmo preço de novo, não acumula.

`POST /v1/painel/gestao/estoque`

```json
{"id": 12, "tipo": "entrada", "quantidade": 24, "motivo": "Compra do distribuidor"}
```

`tipo`: `entrada`, `saida`, `contagem`, `quebra` ou `descarte`. O motivo tem de 3 a 80 caracteres. Repetir depois de `dry_run: false` lança de novo.

Para gravar, mande `"dry_run": false`. A resposta traz `comandos`, `enviados` e `faltam`. Cada envio leva no máximo 200 alterações. Se `faltam` for maior que zero, chame de novo com o `inicio` que veio em `proximo`.

## Onde fica na tela

| O quê | Onde | Seletor |
|---|---|---|
| Mais vendidos do dia | Aba Hoje | `data-seletor="top-dia"` |
| ABC, categorias, operadores, parados, compra, auditoria, CSV/planilha | Aba Relatórios | `data-seletor="relatorios-gestao"` |
| Curva ABC | Aba Relatórios | `data-seletor="relatorio-abc"` |
| Operadores | Aba Relatórios | `data-seletor="relatorio-operadores"` |
| Sugestão de compra | Aba Relatórios | `data-seletor="sugestao-compra"` |
| Exportar | Aba Relatórios | `data-seletor="exportar-csv"` e `exportar-xlsx` |
| Comparativo da rede | Visão da rede | `data-seletor="rede-loja"` e `exportar-rede-csv` |
| Reajuste % | Retaguarda → Produtos | `data-seletor="reajuste-abrir"` |
| Editar marcados (preço, categoria, mínimo, inativar) | Retaguarda → Produtos | `data-seletor="massa-abrir"` |
| Entrada de mercadoria com motivo | Ficha do produto na retaguarda | `data-seletor="estoque-enviar"` |

Cadastro de um produto, grupo, operador, forma de pagamento e fornecedor continua na retaguarda (`/retaguarda/`), um registro por vez. A fila e o histórico ficam em Alterações enviadas.
