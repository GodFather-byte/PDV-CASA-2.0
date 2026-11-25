# Handoff de 25/11/2026: lojas desativadas fora da central (branch `cursor/lojas-desativadas-central-2b67`)

- `GET /v1/fornecedor/lojas` esconde loja com `ativa == False`. `incluir_inativas=true` devolve todas, como antes.
  `resumo.total` é sempre a contagem das ativas; `resumo.inativas` é a das desativadas. Vigentes, vencidas, erros,
  desatualizadas e chamados contam só as ativas. Mensalidade, online, parada e teste ficam como estavam.
- A ficha da loja, alterar (inclusive reativar), cobranças, backups e suporte não filtram inativa. Nada de apagar loja.
- Na central web, "Todas as lojas" é a carteira ativa. O filtro "Lojas desativadas" busca `incluir_inativas=true` e
  mostra só `!ativa`. "Ativar loja" continua no POST `.../alterar` e a lista atualiza. O CSV exporta o que foi carregado.
- Só a nuvem muda. Teste: `tests/test_central_fornecedor.py` (`test_lista_omite_loja_desativada_resumo_so_das_ativas_e_reativar`).
