# Pix integrado (Mercado Pago)

Vem **desligado** em todas as edições. Liga por loja, quando o cliente pede.

## O que faz

No caixa, ao receber numa forma de Pix (a forma fiscal 17 ou o nome "Pix"), abre uma janela com o QR Code já com o
valor. O pagamento **só entra na venda quando o Mercado Pago confirma**. Isso acaba com o golpe do comprovante falso.
Depois é só Enter para fechar, como sempre.

- Esc ou "Cancelar Pix" desiste e cancela a cobrança no Mercado Pago. Se o cliente pagou no mesmo instante, o pagamento vale.
- "Imprimir QR" manda o QR Code para a impressora do caixa (para quando o cliente não alcança a tela).
- Pix não dá troco: o valor não pode passar do que falta.
- Sem internet, o caixa avisa. Dá para receber pela forma comum e conferir no aplicativo do banco, ou desligar a
  integração até a internet voltar.
- Se o Pix foi confirmado mas a venda recusou o pagamento (raro), o caixa avisa para lançar à mão. Esses ficam em
  `PixController.aprovados_sem_pagamento()`.

## Ligar numa loja

1. A loja precisa de conta Mercado Pago com chave Pix cadastrada. O dinheiro cai direto nessa conta. A taxa do Pix é a
   do contrato da loja com o Mercado Pago.
2. No painel do Mercado Pago da loja: Suas integrações > criar aplicação > **Access Token de produção**.
3. No PDV: Configurações > Integrações:
   - colar o Access Token;
   - e-mail do pagador (o Mercado Pago exige; vazio usa o e-mail da loja);
   - ligar "Pix integrado".
4. Fazer um Pix de R$ 0,01 de teste e conferir que a venda fecha sozinha.

## Código

`src/pagamentos/mercadopago_pix.py` (API), `src/controllers/pix_controller.py` (regras e banco),
`src/ui_qt/pix.py` (janela do QR) e `receber` em `src/ui_qt/caixa.py`. Tabela `pix_cobrancas` (esquema 53).
Testes: `tests/test_pix.py`.
