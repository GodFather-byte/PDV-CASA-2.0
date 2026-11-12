"""Will Fiscal: NFC-e (cupom fiscal, modelo 65) em São Paulo.

- `nfce.py` monta a nota a partir da venda fechada (itens, rateio de desconto e acréscimo, pagamentos), em centavos.
- `focus.py` fala com o provedor (Focus NFe). Trocar de provedor, ou passar a falar direto com a SEFAZ, é trocar só
  esse arquivo: o resto do PDV conversa com a interface `Transmissor`.
- `danfe.py` imprime o cupom fiscal (DANFE NFC-e) na térmica, com o QR Code.
- `src/controllers/fiscal_controller.py` guarda a fila (`nfce_notas`), emite, consulta e cancela.
- `servico.py` roda a fila em segundo plano no caixa principal.

Desligado por padrão (`nfce_emissao = desligada`). Só as vendas fechadas depois de ligar viram NFC-e.
"""
