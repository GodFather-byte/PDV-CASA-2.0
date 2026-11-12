# Handoff — NFC-e de São Paulo (Will Fiscal, via Focus NFe) (12/11/2026)

Branch `will-fiscal`, criada da main depois do #85 (atualização sem UAC). Pedido do dono: NFC-e para SP, primeiro
cliente é um empório. Provedor escolhido: Focus NFe, plano Varejo (~R$ 63/mês, 500 notas). Regime do cliente ainda
não sabido: padrões do Simples, tudo configurável. Guia: `docs/NFCE.md`.

## O que foi feito

- Esquema v52: tabela `nfce_notas`; `produtos` ganha cfop, cest, origem_mercadoria, ibscbs_cst, ibscbs_class;
  `tipos_pagamento` ganha forma_fiscal. Configs `nfce_*` em Integrações (tokens como segredo).
- `src/fiscal/nfce.py` monta a nota (rateio de desconto e taxa, pagamento líquido por tPag, homologação no item 1).
- `src/fiscal/focus.py` cliente HTTP (Basic com o token); `src/fiscal/danfe.py` cupom ESC/POS com QR Code.
- `src/controllers/fiscal_controller.py` fila, reenvio com espera, cancelamento (15–255 letras, 30 min), cancelamento
  automático de venda cancelada, impressão. `src/fiscal/servico.py` roda em segundo plano (iniciado em `ui_qt/app.py`).
- Tela `src/ui_qt/notas_fiscais.py`, menu Gestão > Notas fiscais (NFC-e), permissão `fiscal_nfce` (nível 3).
- Testes: `tests/test_nfce.py` (22) e `test_qt_app` (menu e ligar).

## Não testado (precisa da conta Focus em homologação)

- Envio real. Campos sem confirmação: troco, grupo do cartão, GTIN (ver "A conferir" em `docs/NFCE.md`).
- Impressão do QR Code na impressora real do cliente (`GS ( k`, modelo 2).

## Próximos passos

1. Dono cria a conta Focus, cadastra a empresa e sobe certificado + CSC no painel deles.
2. Token de homologação em Configurações > Integrações; ligar em Homologação; vendas de teste.
3. Ajustar o que a SEFAZ rejeitar. Depois: contingência offline.

## Pendências

- Antigravity: a nuvem ainda não recebe `nfce_notas` (só local). Se o dono quiser ver notas na retaguarda, entra no lote.
- Atualização sem UAC (#85): roteiro de teste em PC real ainda pendente; Render segue com PDV_ATUALIZACAO_PAUSADA=1.
- Tutoriais seguintes (grupo e subgrupo, operador com senha, cliente) continuam pendentes.
