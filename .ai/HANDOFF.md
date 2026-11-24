# Handoff de 24/11/2026: correções da auditoria (branch `cursor/correcoes-seguranca-e8a2`)

O dono aprovou os achados. Este trabalho só corrige; não publica nem faz merge.

- Backup da nuvem passa a ir cifrado (o mesmo AES-GCM do backup em pasta). A chave é o
  token da loja: a nuvem guarda só o cifrado. Backup antigo, em claro, ainda restaura.
  `POST /v1/fornecedor/lojas/{chave}/backups/apagar-abertos` apaga os antigos só se já
  existe um cifrado. Não roda sozinho.
- `/docs`, `/redoc` e `/openapi.json` só abrem com `PDV_ABRIR_DOCS=1`.
- O caixa não manda o token para HTTP público. HTTP fica em localhost, IP de rede local,
  nome `.local` e `testserver`.
- Central: a senha certa não conta tentativa e não fica presa. Trava de 2 minutos por IP.
  O `render.yaml` sobe o uvicorn com `--proxy-headers --forwarded-allow-ips=*`.
- Webhook do site sem `MP_WEBHOOK_SECRET` responde 503.
- Cabeçalhos de segurança em toda resposta. `X-Forwarded-Proto: http` em host público
  manda GET/HEAD para HTTPS (308) e recusa o resto (400).
- Porteiro: CORS sem `*`. PIN continua com limite por IP e ganhou limite por loja.
- Pillow 13 no Python 3.11+ (o caixa Windows é 3.12). O 3.10 fica no 12.3 porque o 13
  não instala nele.
- O navegador do painel usa cookie `HttpOnly` (`X-PDV-Painel: 1`). O assistente segue
  com o Bearer do login.

Precisa de versão nova do caixa para o backup cifrado e para recusar HTTP público.
Sem essa versão, a nuvem recusa backup em claro.
