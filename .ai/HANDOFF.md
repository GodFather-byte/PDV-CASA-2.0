# Handoff de 24/11/2026: auditoria de segurança (branch `cursor/auditoria-seguranca-7e21`)

Relatório em `docs/seguranca/auditoria-2026-11.md`. Não houve merge nem deploy. A produção só foi lida
(cabeçalhos e se `/docs` responde). Nenhum segredo foi copiado para o relatório.

## O que o código passa a fazer

- `/v1/pagamentos/webhook` exige `x-signature` (`MP_WEBHOOK_SECRET`), como a mensalidade. Sem segredo, 503.
- Respostas HTTP ganham `X-Frame-Options: DENY`, CSP (`frame-ancestors 'none'`), `nosniff` e, em HTTPS, HSTS.
- `/docs`, `/redoc` e `/openapi.json` ficam desligados.
- Leitura de XLSX limita entradas e tamanho e recusa DTD. CSV de relatório, painel, hotel e central
  neutraliza fórmula. Número brasileiro negativo continua número.
- Hash PBKDF2 acima de 2.000.000 iterações é recusado (PIN do porteiro e senha do painel).
- `PDV_CENTRAL_SENHA`, se existir no Render, substitui `PDV_API_TOKEN` só no login da central.

O caixa 1.14.21 não muda de contrato: mesmo Bearer, mesmo JSON, sem comando novo.

## O que o dono faz

1. Confirmar `MP_WEBHOOK_SECRET` no Render, igual ao segredo da aplicação no Mercado Pago, antes de
   contar com a confirmação automática do site.
2. Criar `PDV_CENTRAL_SENHA` diferente do token da API e entrar de novo em `/central/`.
3. Depois do deploy: `/docs` e `/openapi.json` em 404; painel com `X-Frame-Options: DENY`.
4. Não cifrar o backup da nuvem enquanto o caixa 1.14.21 precisar do gzip atual.
5. Pillow e cryptography têm avisos fora da faixa do `requirements.in`. Subir versão é outro trabalho.

## Testes

`python -m tools.verificar` (fumaça do caixa, 55 módulos, `node --check`).

## Fora

Sem mudança de preço, dado de produção, merge ou deploy. Backup cifrado na nuvem e troca de
Pillow/cryptography ficaram de propósito.
