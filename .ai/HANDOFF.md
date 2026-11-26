# Handoff de 25/11/2026: tamanho do cupom na térmica (branch `impressora-tamanho`)

- Pedido do dono: impressora KA 1445 imprimindo grande. Causas comuns: modo "documento do Windows" (Bloco de Notas,
  folha A4) ou colunas maiores que o papel (linha quebra). `src/hardware/perfis_impressora.py`: papel 58/80 mm x
  letra normal/pequena (fonte B, `ESC M 1`) -> 32/42/48/64 colunas; palpite do papel pelo nome/driver.
- Esquema v60: `maquinas.impressora_papel_mm` (0 = não escolhido) e `impressora_letra`. `salvar_maquina` recalcula
  `colunas_fita` quando papel/letra mudam. NFC-e (danfe) e pedido remoto seguem a mesma letra; logotipo usa a largura
  da letra normal.
- Assistente: `configurar(..., papel_mm, letra, driver)`, `ajustar_tamanho`, `ajustar_e_ligar` (liga a térmica se o
  caixa imprime como documento), diagnóstico acusa modo Windows e colunas maiores que o papel. Tela Qt ganhou "Tamanho
  do cupom". Página de teste com régua do tamanho exato. KA-xxxx, XP-, GP-, 58mm/80mm entram como térmica.
- Retaguarda: seção `impressora` no espelho, comando `impressora.ajustar` (papel, letra, cortar, testar) e tela
  "Impressora do cupom" (grupo Loja). Precisa do caixa 1.14.29. Teste: `tests/test_tamanho_cupom.py`.

# Handoff de 25/11/2026: lojas desativadas fora da central (branch `cursor/lojas-desativadas-central-2b67`)

- `GET /v1/fornecedor/lojas` esconde loja com `ativa == False`. `incluir_inativas=true` devolve todas, como antes.
  `resumo.total` é sempre a contagem das ativas; `resumo.inativas` é a das desativadas. Vigentes, vencidas, erros,
  desatualizadas e chamados contam só as ativas. Mensalidade, online, parada e teste ficam como estavam.
- A ficha da loja, alterar (inclusive reativar), cobranças, backups e suporte não filtram inativa. Nada de apagar loja.
- Na central web, "Todas as lojas" é a carteira ativa. O filtro "Lojas desativadas" busca `incluir_inativas=true` e
  mostra só `!ativa`. "Ativar loja" continua no POST `.../alterar` e a lista atualiza. O CSV exporta o que foi carregado.
- Só a nuvem muda. Teste: `tests/test_central_fornecedor.py` (`test_lista_omite_loja_desativada_resumo_so_das_ativas_e_reativar`).
