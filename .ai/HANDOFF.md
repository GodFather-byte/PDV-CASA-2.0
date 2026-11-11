# Handoff — Dono com várias lojas no mesmo painel (11/11/2026)

## Branch e escopo
Branch `painel-varias-lojas`, empilhada sobre `notas-do-dono` (PR #73). Entra depois dela.
Pedido do dono: quem tem várias lojas ver todas em um painel só. Só nuvem e página; o PDV não muda.
Em paralelo, abertas e independentes: PR #73 (notas de compra do dono) e PR #72 (esqueci a senha do caixa).

## Implementação
- `backend/painel_lojas.py`: tabela `painel_grupos` (uma linha por loja, com o grupo). O dono, logado numa
  loja, liga outra provando a senha do painel dela (`POST /v1/painel/lojas/vincular`, mesmo limitador de
  tentativas do login). Dois grupos se juntam. `GET /v1/painel/lojas` devolve hoje, mês e atraso do envio de
  cada loja e o total. `POST /v1/painel/lojas/trocar` apaga a sessão atual e abre outra na loja escolhida
  (token novo, para o cache de leitura continuar por loja). `DELETE /v1/painel/lojas/{chave}` tira do grupo.
  Limite de 20 lojas. `backend/main.py` instala o módulo.
- Senha errada da outra loja devolve **403**: a página trata qualquer 401 como sessão vencida e deslogava o dono.
- Página `/painel/`: bloco "Minhas lojas" no topo da aba Hoje (some com uma loja só) e "Adicionar outra loja"
  no fim. `chamarApi` ignora 401 de token que já foi trocado. `sw.js` em `painel-v11`.

## Validação e limites
- `tests/test_painel_varias_lojas.py` (8 casos). Conferido no navegador com a nuvem de demonstração:
  senha errada não desloga, 3 lojas ligadas, troca de loja e recarga da página.
- Não testado em produção (Neon/Render). Não há migração: a tabela nova nasce no `create_all`.
- Os totais somam o que cada loja já enviou; loja com caixa desligado aparece como "sem enviar há X".

## Pendências
- Antigravity: revisar `backend/painel_lojas.py` e a linha nova em `backend/main.py`.
- Antigravity: revisar também `backend/notas_dono.py` (PR #73) e `backend/recuperacao_senha.py` (PR #72).
- Comparativo entre lojas por período (hoje o bloco mostra só hoje e mês).
- Avisar o dono por push quando o caixa lançar ou recusar uma nota.
- Homologação do Will Restaurante e impressão em térmica de verdade continuam pendentes.
