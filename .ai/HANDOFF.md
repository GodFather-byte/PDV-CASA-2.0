# Handoff (18/11/2026): backup do caixa na nuvem (branch `backup-nuvem`)

No ar: 1.14.16 (delivery com esgotado, Insta pela central, IA da vitrine paga) e o site novo (4 programas, sob medida).

## O que entrou
- **Nuvem** `backend/backup_nuvem.py`: `POST /v1/backup` (corpo = gzip do banco, cabeçalhos com hora, esquema e
  SHA-256; confere que é SQLite), `GET /v1/backup/lista`, `GET /v1/backup/{id}` (token da loja, só a própria loja).
  Tabela `backups_nuvem` no Postgres (Neon). Retenção: último de cada um dos 7 dias mais recentes + último de cada mês
  (4 meses), até 80 MB por loja (o mais novo nunca sai). Central: lista e baixa (`baixar_backup_nuvem` na auditoria).
- **Caixa** `src/sync/backup_nuvem.py`: no sincronizador, manda o backup local mais novo no máximo a cada 3 h (o caixa
  já faz backup na troca de turno, saída e início). Caixa adicional não envia. `restaurar` baixa, confere SHA-256 e
  banco, mantém endereço/token/licença da instalação atual e marca a restauração para o próximo início (o mesmo
  caminho do backup local, com cópia de segurança do banco atual).
- **Tela** `src/ui_qt/backup_nuvem.py`: Utilitários → "Recuperar a loja pelo backup da nuvem…".
- Testes: `tests/test_backup_nuvem.py` (envio, intervalo, recuperação, isolamento entre lojas, retenção, central, tela).

## Pendências
- Medir o tamanho real dos bancos (aparece na lista da central). O Neon tem limite de 1 GB (hoje 16 MB); se crescer,
  trocar o armazenamento para o R2 mantendo as mesmas rotas.
- IA: chave da Claude Platform em `ANTHROPIC_API_KEY` no Render; ligar lojas na central.
- Ideias aprovadas para depois: RustDesk (suporte), sugestão de compra simples (Will Adega), etiquetas com código de
  barras (python-barcode, para o Will Variedades). Headscale e statsforecast: não agora.
- Backlog: homologação NFC-e DeliciOz; IBS/CBS 2027; Casa Verde na 1.14.5 (instalação manual); mensalidade EA.
