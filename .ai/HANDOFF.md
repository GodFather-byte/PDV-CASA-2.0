# Handoff de 25/11/2026: painel único para o dono de rede (branch `painel-unico`)

- O login da rede entra direto no painel normal de uma loja: a última vista (`willpdv.rede.ultima`, fora do PREFIXO)
  ou a primeira ativa. No topo, o seletor `#seletor-loja-rede` troca de loja ou abre "Todas as lojas (resumo da
  rede)". No resumo, `#seletor-loja-resumo` abre uma loja. Para ir de uma loja a outra, a tela chama
  `/grupo/voltar` e depois `/grupo/entrar`.
- A nuvem (`_grupo_no_painel` em `backend/painel.py`) devolve as lojas da rede no login, no `/eu` e no
  `/grupo/voltar`.
- O login próprio de cada loja continua valendo e vê só a loja dele (gerente). A retaguarda da EA Superações segue
  só pela central do fornecedor, sem mudança.
- Testes: `tests/test_rede_painel.py`. Conferido no navegador: entrar, trocar de loja, resumo e recarregar.

# Handoff de 25/11/2026: CORREÇÃO DE SEGURANÇA no cache de leitura (branch `corrige-cache-sessao`)

- `backend/cache_leitura.py` montava a chave com o cabeçalho Authorization. Desde que o painel passou a usar cookie,
  esse cabeçalho vem vazio, então todas as sessões dividiam a chave: por 45 s, um dono recebia o resumo, as vendas e
  os produtos de outra loja, e um pedido sem login nenhum também recebia. Agora a chave leva o resumo (SHA-256) do
  Bearer e dos cookies `willpdv_painel`/`willpdv_rede`, e a leitura sem ninguém identificado não usa o cache (só o
  cardápio, que é público). Teste: `tests/test_cache_leitura_sessao.py`.
- Só a nuvem muda: o caixa não precisa de versão nova.

# Handoff de 25/11/2026: downloads da home no GitHub (branch `cursor/downloads-github-site-97b2`)

- `backend/site.py`: `{{download_willpdv}}` e `{{download_willadega}}` usam `link_instalador`, como restaurante, variedades e hotel. `url_instalador` saiu. O endereço antigo do R2 (`site_precos.R2_BASE`) continua no arquivo de preços e não entra mais na página.
- Os cinco botões da home apontam para `https://github.com/GodFather-byte/willpdv-downloads/releases/download/...` (WillPDV em `ultima-versao`, Will Adega em `ultima-versao-adega`).
- Teste: `tests/test_site.py`.
