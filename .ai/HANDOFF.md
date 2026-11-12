# Handoff — Rede de lojas (11/11/2026)

Uma rede (`grupos`) tem um login no painel e pode ter uma mensalidade só. Cada loja
guarda o próprio caixa. `lojas.grupo_id` vazio = loja avulsa, com a cobrança de
antes. Guia: `docs/REDE_LOJAS.md`.

Link: `/painel/?grupo=CHAVE` (a chave também aceita o id numérico). A senha criada
pelo administrador nasce temporária (`deve_trocar_senha`): o dono troca em
`POST /v1/painel/grupo/senha` antes de ver os números.

API do administrador: `POST /v1/admin/grupos`, `.../lojas`, `.../senha`,
`.../assinatura`. A central tem a aba Redes (`/v1/fornecedor/grupos`).

Pagamento aprovado da rede grava `licenca_ate` em todas as lojas do grupo.
`gerar_recorrencias` não emite a cobrança individual de loja que está numa rede.

## Central da rede no painel (branch `rede-de-lojas`, 11/11/2026)

Pedido do dono (rede EA Superações): ao entrar numa loja não dava para voltar à lista de lojas.
Causa: a página guardava a sessão da rede em `sessionStorage` e deixava `willpdv.painel.grupo` gravado com o
token da loja; ao recarregar ou reabrir o app, abria a tela da rede com o token da loja (404) e o botão
"Rede" sumia.

- `backend/painel_web/app.js`: sessão da rede em `willpdv.rede.*` (localStorage, fora do prefixo que a troca de
  loja apaga); `voltarParaRede()` encerra a sessão da loja e reabre a central; sessão de loja vencida dentro
  da rede volta para a central; "Sair" encerra as duas. Migra quem estava logado na versão anterior.
- `index.html`/`estilo.css`: faixa fixa "‹ Todas as lojas" no topo da loja; tela da rede com cartão por loja
  (parte na rede, vendas, lucro, situação do envio) e botão Atualizar. `sw.js` subiu de versão.
- `backend/grupos.py` (`consolidado`): cada loja ganhou `vendas`, `atualizado_em` e `atraso_min`.
- `tests/test_rede_painel.py` (5 casos). Conferido no navegador: abrir loja, recarregar, trocar de aba,
  voltar, reabrir o app, sair. Não testado com a rede de produção.

A retaguarda na nuvem já está na main (`docs/RETAGUARDA.md`). Aplicar a mesma
alteração em várias lojas de uma vez continua pendente.

## Pendências

- Antigravity: revisar `backend/grupos.py`, a cobrança da rede e o painel.
- Homologação do Will Restaurante e impressão em térmica de verdade.
- Checkout do site de vendas ainda é só WhatsApp.
- Atualização automática segue sem os segredos `PDV_ATUALIZACAO_*`.
