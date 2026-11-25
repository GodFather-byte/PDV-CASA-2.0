# Handoff de 25/11/2026: downloads da home no GitHub (branch `cursor/downloads-github-site-97b2`)

- `backend/site.py`: `{{download_willpdv}}` e `{{download_willadega}}` usam `link_instalador`, como restaurante, variedades e hotel. `url_instalador` saiu. O endereço antigo do R2 (`site_precos.R2_BASE`) continua no arquivo de preços e não entra mais na página.
- Os cinco botões da home apontam para `https://github.com/GodFather-byte/willpdv-downloads/releases/download/...` (WillPDV em `ultima-versao`, Will Adega em `ultima-versao-adega`).
- Teste: `tests/test_site.py`.
