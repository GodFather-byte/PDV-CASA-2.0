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

A retaguarda na nuvem já está na main (`docs/RETAGUARDA.md`). Aplicar a mesma
alteração em várias lojas de uma vez continua pendente.

## Pendências

- Antigravity: revisar `backend/grupos.py`, a cobrança da rede e o painel.
- Homologação do Will Restaurante e impressão em térmica de verdade.
- Checkout do site de vendas ainda é só WhatsApp.
- Atualização automática segue sem os segredos `PDV_ATUALIZACAO_*`.
