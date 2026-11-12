# Handoff — Pix integrado no caixa (12/11/2026)

Branch `pix-integrado`, criada da main depois do #86 (NFC-e) e do #87 (Enter no pagamento sem mesas).
Pedido do dono: Pix integrado, desligado por padrão; liga quando o cliente pedir. Guia: `docs/PIX.md`.

## O que foi feito

- Esquema v53: tabela `pix_cobrancas`. Configs `pix_integrado` (N), `pix_mp_token` (segredo), `pix_email_pagador`,
  `pix_expira_min` em Integrações.
- `src/pagamentos/mercadopago_pix.py`: cria, consulta e cancela pelo `/v1/payments` do Mercado Pago (Bearer, chave de
  idempotência).
- `PixController`: só forma Pix (fiscal 17) com a integração ligada; Pix não dá troco; cancelamento confere se já foi
  pago; vincula a cobrança ao pagamento; imprime o QR na fila do caixa.
- `src/ui_qt/pix.py`: janela do QR com consulta em thread a cada 2,5 s. `receber` no caixa só grava o pagamento
  depois de "aprovado".

## Não testado

- Mercado Pago de verdade (precisa do Access Token de uma loja). Teste: Pix de R$ 0,01.
- Impressão do QR na impressora real.

## Decidido com o dono

- NFC-e em contingência quando a internet da loja cai: fica para depois do teste do empório em homologação.
  A Focus já cobre a queda da SEFAZ. A contingência completa exige assinar a nota no caixa, com o certificado no PC.

## Pendências

- Empório: conta Focus, certificado e CSC no painel da Focus, token de homologação (ver `docs/NFCE.md`).
- Atualização sem UAC (#85): teste em PC real ainda pendente; Render segue com PDV_ATUALIZACAO_PAUSADA=1.
- Antigravity: a nuvem não recebe `nfce_notas` nem `pix_cobrancas` (só locais).
