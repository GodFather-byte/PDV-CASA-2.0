# Handoff de 24/11/2026: auditoria de segurança (só documentação)

Relatório em `docs/auditoria-seguranca-2026-11.md`. Nenhum código de caixa, nuvem, site ou
painel foi alterado. O dono aprova cada correção antes de virar mudança.

O que a leitura e a consulta pública de 24/11/2026 mostraram, em ordem:

- O backup que o caixa sobe para a nuvem é o banco inteiro, com o Access Token do Pix da loja
  e a senha do certificado da NFC-e, sem criptografia.
- `/docs` e `/openapi.json` respondem na origem pública, a mesma do painel.
- Os dois webhooks do Mercado Pago, sem assinatura, respondem 401. O código do webhook do
  site ainda aceita seguir sem o segredo; o das mensalidades não.

## Fora

Sem correção, merge ou deploy. Pendência: o dono escolhe o que corrigir primeiro
(a lista está no fim do relatório).
