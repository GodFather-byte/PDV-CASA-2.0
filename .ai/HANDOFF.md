# Handoff (17/11/2026, noite): apagar vendas de teste (branch `apagar-vendas-teste`)

Estado geral: repositório **público** (Actions de graça), build sem Nuitka, sem runner do PC. Versão no ar 1.14.13.

## O que entrou
- **Senha de segurança do dono** (`seguranca_dono`, só o hash, fora de `config` porque a retaguarda espelha a config).
  Cria/troca em Utilitários > "Senha de segurança do dono…" (gerente; trocar pede a atual). Sobe para a nuvem
  (`seguranca_hash` no envio do painel) e vale no painel.
- **Apagar vendas de teste no caixa** (Utilitários > "Apagar vendas de teste…", módulo `util_vendas_teste`, nível 4):
  período, marca, total, confirma com a senha. Regra em `src/controllers/vendas_teste_controller.py`.
  Travas: só fechada/cancelada; bloqueia NFC-e (qualquer situação menos `erro`), devolução/troca, fiado, Pix aprovado;
  turno fechado pede confirmação (`TurnoFechado`); 5 erros = 15 min de bloqueio. Tudo ou nada. Estoque volta
  (`estornar_venda`, idempotente). Registro permanente em `vendas_apagadas` + `auditoria_eventos`.
- **Nuvem** (`backend/vendas_teste.py`): `vendas_apagadas` do lote apaga `PainelVenda` e grava `painel_exclusoes`
  (um reenvio atrasado do mesmo uuid é confirmado sem guardar). Painel: `GET /v1/painel/vendas-teste`,
  `POST /v1/painel/vendas-teste/apagar` (sessão + senha de segurança, bloqueio próprio). O pedido do painel fica
  "aguardando" e vai ao caixa em `apagar_no_caixa`; o caixa aplica as mesmas travas e confirma (aí some da nuvem) ou
  recusa com motivo (`vendas_apagar_recusadas` -> `vendas_recusadas`). A nuvem não sabe de NFC-e, por isso quem
  decide é o caixa. Bloco "Apagar vendas de teste" na aba Produtos do painel.
- Esquema **v57** (tabelas aditivas). Testes: `test_vendas_teste`, `test_vendas_teste_nuvem`, `test_qt_vendas_teste`.

## Pendências
- Merge (pedir OK do dono) e publicar 1.14.14.
- Loja com vários caixas: o pedido do painel vai a todos; só o caixa que tem a venda apaga. Se esse caixa sumiu,
  o pedido fica "aguardando".
- Backlog: homologação NFC-e DeliciOz (A1 na loja, roteiro em docs/NFCE_PROPRIA.md); alíquotas IBS/CBS de 2027;
  instalação manual na Casa Verde (1.14.5); valor da mensalidade EA Superações.
