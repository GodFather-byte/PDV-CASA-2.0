# Handoff — Retaguarda na nuvem (11/11/2026)

## Branch e escopo
Branch `retaguarda`, base main f5990cb (esquema 50 -> 51). Pedido do dono: um sistema de retaguarda completo
para mexer nos PDVs de longe (adega, restaurante e boate), para o dono e para o fornecedor, valendo a
alteração mais recente. Guia: `docs/RETAGUARDA.md`.

## Como ficou
- Caixa: `src/controllers/retaguarda_controller.py` monta o espelho (esquema das telas a partir de `ENTIDADES` e
  `CAMPOS_CONFIG`, linhas de cada cadastro sem senha, contas e devedores) e aplica os comandos pelas regras do PDV
  (`CadastroController`, `EstoqueController.registrar_rapido`, `ConfigController.salvar_config`, `ContasController`).
  Cada comando aplica uma vez (tabela local `retaguarda_comandos`, v51 aditiva). Dinheiro chega em centavos.
- Rede do caixa: `src/sync/retaguarda.py`. Sobe só a seção cuja impressão digital mudou; busca comandos quando a
  nuvem avisa (`retaguarda_pendentes` na resposta do envio do painel ou do espelho). Gancho `Sincronizador._retaguarda`.
- Opção `retaguarda_nuvem` (Configurações > Nuvem), **desligada por padrão**; exige o painel do dono ligado.
- Nuvem: `backend/retaguarda.py` (tabelas `retaguarda_espelhos` e `retaguarda_comandos`). Rotas do dono em
  `/v1/painel/retaguarda`, do fornecedor em `/v1/fornecedor/lojas/{chave}/retaguarda` (auditadas) e do caixa em
  `/v1/retaguarda/*`. A senha digitada sai do comando quando o caixa confirma.
- Página `backend/retaguarda_web/` em `/retaguarda/` (dono: token do painel no localStorage; fornecedor:
  `?loja=CHAVE` com a sessão da central). Atalhos: painel (aba Produtos, `sw.js` v12) e central (aba Suporte).

## Validação e limites
- `tests/test_retaguarda.py` (27 casos: caixa, ponta a ponta com TestClient, fornecedor com auditoria).
- Conferido no navegador com a nuvem de demonstração e um caixa de adega: alterar preço, movimentar estoque,
  quitar conta, mudar configuração, cadastro recusado com o motivo, celular.
- Não testado em loja nem na nuvem de produção. Não testado com cadastro grande (milhares de produtos).
- Vários caixas na mesma loja: aplica onde roda a sincronização do painel (o caixa principal).
- A nuvem precisa ser publicada antes dos caixas.

## Pendências
- Antigravity: revisar `backend/retaguarda.py`, as linhas novas em `backend/main.py`, `backend/painel.py`,
  `backend/central_fornecedor.py`, `backend/central_web/` e `src/sync/sincronizador.py`.
- Tela no PDV com o histórico do que a retaguarda mudou (`RetaguardaController.recentes` já existe, sem tela).
- Relatórios na retaguarda (hoje ficam no painel do dono) e comparativo entre lojas.
- Composição, combos, embalagens (fardo), fotos e adicionais de produto ainda só no caixa.
- Receber caderneta, sangria e fechamento continuam só no caixa (são do turno).
- Aplicar a mesma alteração em várias lojas de uma vez (grupo de lojas do dono).
- Antes: homologação do Will Restaurante e impressão em térmica de verdade continuam pendentes.
