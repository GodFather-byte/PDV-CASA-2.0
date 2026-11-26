# Handoff de 26/11/2026: lote de 5 melhorias (branch `melhorias-lote`)

1. Login do dono por e-mail (`backend/painel_usuarios.py`): convite pela central (Financeiro > "Acesso do dono por
   e-mail"), o dono cria a senha pelo link `/painel/?senha=TOKEN`, código de 6 dígitos em aparelho novo (cookie
   `willpdv_aparelho`, 30 dias), "Esqueci a senha" (30 min). Vale para loja ou rede (`grupo_id`). Login antigo continua.
2. Envio ao contador (`backend/contador.py`): dia 1º a partir das 08:00, link de 7 dias `/v1/contador/TOKEN` com ZIP
   (XMLs + notas.csv). Aba Relatórios do painel. Disparo no middleware, como o relatório diário.
3. Bandeira 2 pelo painel (`backend/bandeira2.py`, `src/sync/bandeira2_nuvem.py`): cartão na aba Hoje, +% ou +R$ por
   item; versão na nuvem, o caixa aplica pela resposta do envio do painel (o botão acorda o caixa via memória).
4. Caixa: depois do fechamento volta à tela de operador (`voltar_login_apos_fechar`, padrão S); "Entrar como ADM"
   (Ctrl+Shift+A) abre o menu do ADM por cima do caixa parado, volta pelo botão ou 5 min sem uso (`app.py`).
5. Caixas sem depender do Wi-Fi da loja: `src/hardware/hotspot_windows.py` liga e vigia o Hotspot móvel do Windows no
   principal (opção em Caixas da loja); `rede.enderecos_locais` lista todos os IPs (o do hotspot primeiro), o principal
   anuncia no "ok" e o adicional guarda e tenta primeiro o que funcionou. Testar nos notebooks da EA Superações 2.
- Precisa do caixa 1.14.30 (3, 4 e 5). Testes: test_login_email, test_contador, test_bandeira2_painel,
  test_qt_modo_adm, test_hotspot_caixas.

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
