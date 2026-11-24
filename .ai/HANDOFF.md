# Handoff de 24/11/2026: painel do dono com autoridade de dono no caixa (branch `painel-autoridade-dono`)

A importação de produtos da EA-SUPERACOES2 seguia recusada com "Custo e lucro só aparecem para o gerente": o caixa
aplicava o comando do painel com a autoridade de quem estava logado nele (operador comum) ou, sem gerente ativo na
loja, sem autoridade nenhuma. Agora `RetaguardaController._como_gerente` marca `banco._autoridade_dono` durante o
comando e `entidades` aceita o custo com essa marca; `_gerente()` prefere um gerente ao operador comum para assinar.
No caixa, o operador comum continua sem mexer no custo. Teste em `tests/test_retaguarda.py`.

Depois de instalar a versão com a correção: no painel, Alterações enviadas > Enviar de novo nos comandos recusados.

## Antes: Handoff: painel com a main atual

A branch do painel está em cima da main. Continuam valendo os dois lados: os relatórios e o
reajuste deste pedido, e o que a main já mergeou (custo da importação em comando separado, com
autoridade de gerente; aviso rápido da fila; no boot a nuvem rearma o aviso das alterações
pendentes; a primeira pergunta de um token desconhecido olha a loja no banco uma vez).

## O que o painel acrescenta
A aba **Relatórios** mostra curva ABC, categoria, operador, por dia, estoque baixo, parados,
sugestão de compra (7 dias) e o histórico do que foi pedido ao caixa. CSV e planilha saem do
mesmo período. **Hoje** lista os mais vendidos do dia. Na rede, cada loja mostra o ticket e o
comparativo baixa em CSV.

Na retaguarda, em Produtos: **Reajuste %** por categoria e **Editar marcados** (preço, categoria,
estoque mínimo, inativar), sempre com prévia. A entrada de mercadoria continua na ficha, com motivo.
O assistente usa a sessão ou o token `wpdv_`. Sem `dry_run: false` a escrita só devolve a prévia.
Guia em `docs/api-assistente.md`.

Reajuste e estoque usam `cadastro.salvar` e `estoque.movimento`. Caixa com a retaguarda ligada
não precisa atualizar. O custo da planilha continua no segundo comando `produtos.importar`: o
caixa antigo grava o produto e pode recusar só o custo, que se reenvia em Alterações enviadas.

## O que o dono faz na loja EA-SUPERACOES2
A Importação #4 ficou em "Aguardando o caixa" porque o deploy zerou a memória do aviso. No caixa,
feche o turno (ou registre uma venda): o programa que já está rodando manda na hora. O comando
de produtos deve aplicar no 1.14.21. O comando de custo pode ser recusado até instalar o programa
que contém a #149; depois, em Alterações enviadas, use Enviar de novo.

## Testes
`tests/test_gestao_painel.py`, `tests/test_importacao_painel.py` e `tests/test_ociosidade_neon.py`.

## Fora
Não houve merge deste PR nem deploy.
