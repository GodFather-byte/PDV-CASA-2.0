# Handoff: painel controla cadastro e relatórios

O dono acompanha e mexe na loja pelo painel, sem comando novo no caixa. A aba **Relatórios**
mostra curva ABC, categoria, operador, por dia, estoque baixo, parados, sugestão de compra (7 dias)
e o histórico do que foi pedido ao caixa. CSV e planilha saem do mesmo período. **Hoje** lista os
mais vendidos do dia. Na rede, cada loja mostra o ticket e o comparativo baixa em CSV.

Na retaguarda, em Produtos: **Reajuste %** por categoria e **Editar marcados** (preço, categoria,
estoque mínimo, inativar), sempre com prévia. A entrada de mercadoria continua na ficha, com motivo.

O assistente usa a sessão ou o token `wpdv_` (o mesmo da importação). Sem `dry_run: false` a escrita
só devolve a prévia. Guia em `docs/api-assistente.md`.

## O que entrou
- `GET/POST /v1/painel/gestao/...` (resumo, relatórios, produtos, auditoria, preços, reajuste, estoque).
- Testes em `tests/test_gestao_painel.py`.

## Fora deste pedido
- Não houve merge nem deploy.
- Não mexe na recusa de custo na importação nem na velocidade em que o caixa aplica a fila.
- Reajuste e estoque usam `cadastro.salvar` e `estoque.movimento`. Caixa com a retaguarda ligada
  não precisa atualizar. Sem a retaguarda ligada, a escrita espera o cadastro subir.
- Sugestão de compra e parados leem o espelho da retaguarda. Fechamento e sangria vêm do retrato
  (cerca de 31 dias). Custo e lucro só entram quando o caixa já enviou o custo do item.

## Pendências
- Dono: `MP_ACCESS_TOKEN` (e `MP_WEBHOOK_SECRET`) no Render para o checkout do site; `ANTHROPIC_API_KEY`.
- Lojas desatualizadas: Resenha (1.14.9, ainda com o erro ao sair), Império, EA Superações 1/2/3.
