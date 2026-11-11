# Handoff — Dono com várias lojas no mesmo painel (11/11/2026)

## Branch e escopo
Três entregas de 11/11/2026 na main: notas de compra do dono (PR #73), esqueci a senha do gerente (PR #72)
e este, várias lojas no mesmo painel (PR #74, branch `painel-varias-lojas`). Detalhe das notas em
`docs/PAINEL_DONO.md` (seção Notas de compra) e no histórico do git.
Pedido do dono: quem tem várias lojas ver todas em um painel só. Só nuvem e página; o PDV não muda.

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

## Esqueci a senha do gerente (PR #72)
Regra em `src/core/recuperacao_senha.py`: o caixa gera um pedido aleatório (8 caracteres, 24 h, em `config`), o
fornecedor assina uma liberação `PDVR1...` com a chave privada das licenças (loja + pedido + prazo) e o caixa
confere com a chave pública antes de gravar a senha nova de um gerente ativo (nível 4). Uma liberação, uma troca.
- Central: `POST /v1/fornecedor/lojas/{chave}/recuperar-senha` (auditada) e formulário em Suporte e caixas.
- Nuvem: `backend/recuperacao_senha.py`; o caixa busca em `GET /v1/recuperacao-senha?pedido=`. Sem internet, cola o código.
- Ferramenta local: `python -m tools.gerar_licenca recuperar-senha --loja X --pedido Y`.
- Tela: `ui_qt/esqueci_senha.py`, botão "Esqueci a senha" em `ui_qt/login.py`. Testes: `tests/test_recuperacao_senha.py` (17).
- Limite: o caixa secundário (rede) usa o banco do principal; não testado nesse arranjo.

## Validação e limites
- `tests/test_painel_varias_lojas.py` (8 casos). Conferido no navegador com a nuvem de demonstração:
  senha errada não desloga, 3 lojas ligadas, troca de loja e recarga da página.
- Não testado em produção (Neon/Render). Não há migração: a tabela nova nasce no `create_all`.
- Os totais somam o que cada loja já enviou; loja com caixa desligado aparece como "sem enviar há X".

## Pendências
- Publicar a nuvem antes de atualizar os caixas (caixa novo com nuvem antiga só não recebe o aviso de nota).
- Antigravity: revisar `backend/painel_lojas.py` e a linha nova em `backend/main.py`.
- Antigravity: revisar também `backend/notas_dono.py` (PR #73) e `backend/recuperacao_senha.py` (PR #72).
- Comparativo entre lojas por período (hoje o bloco mostra só hoje e mês).
- Avisar o dono por push quando o caixa lançar ou recusar uma nota.
- Homologação do Will Restaurante e impressão em térmica de verdade continuam pendentes.
