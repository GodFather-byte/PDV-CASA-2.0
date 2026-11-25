# Handoff de 25/11/2026: IA na retaguarda (branch `retaguarda-ia`)

- Menu "Cadastro com IA" (grupo Produtos) para o dono e para a central. Foto da nota, lista de preços ou prateleira
  (reduzida no navegador para 1600 px JPEG) -> `POST .../retaguarda/ia/foto` -> linhas no formato da planilha para
  conferir; "Arrumar nomes com IA" (`/ia/nomes`); "Enviar para o caixa" (`/ia/enviar`) cria `produtos.importar`
  (nota de compra já sugere somar ao estoque). `GET .../ia` mostra se está ligada e os usos.
- `backend/ia.py`: `ler_foto` e `padronizar_nomes` viraram funções usadas pelo caixa e pela retaguarda;
  `linhas_para_importar` converte para o formato da importação. Mesma cota e liga/desliga da central.
- Só a nuvem muda. Teste: `tests/test_retaguarda_ia.py`.

# Handoff de 25/11/2026: combos na retaguarda e relatório diário por e-mail (branch `retaguarda-combos-relatorio`)

- Combos: a retaguarda ganhou o menu "Combos" (lista, economia contra os avulsos, "Novo combo"). O comando
  `produto.combo` chega ao caixa e usa `ProdutoController.criar_combo`; o espelho sobe a seção `combos`
  (`SECAO_VALIDA` na nuvem). Precisa de versão nova do caixa (1.14.27). Teste: `tests/test_retaguarda_combos.py`.
- Relatório diário: `backend/relatorio_diario.py` (tabela `relatorios_diarios`). O dono liga e põe até 3 e-mails no
  painel, aba Relatórios. A partir das 08:00 (Brasília), qualquer requisição chama `disparar_em_segundo_plano()`
  (middleware em `main.py`), que manda o relatório do dia anterior uma vez por loja; a linha é reservada no banco e
  volta a ficar pendente se o e-mail falhar (nova tentativa em 30 min). O agendamento
  `.github/workflows/relatorio-diario.yml` acorda o Render às 08:05 e 08:40. Botão "Enviar o de ontem agora"
  (3 por hora). Usa `enviar_email` (Brevo/SMTP). Teste: `tests/test_relatorio_diario.py`.

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
