# Handoff — 05/11/2026

## Correção da atualização sobre banco antigo

- Log da loja: PDV 1.10.0 falha ao abrir banco usado no 1.2.0, na migração v17: `_itens_venda_v17 has 20 columns but 14 values were supplied`. Erro Tk de outubro era outra ocorrência antiga.
- Reproduzido em banco descartável com 14 colunas reais dos itens. Causa: `_migracao_historico_produtos` usa o DDL atual de 20 colunas e fazia `INSERT ... SELECT *` sem nomear destino.
- Correção em esquema/conexao: passo `copiar_colunas` consulta campos reais por PRAGMA e copia todos por nome, mantendo defaults dos campos novos. Aplicado a itens de venda, estoque, movimentos e partes. Campo de origem sem destino interrompe sem descartar dados. Migração participa da transação existente.
- Sem aumento de versão: corrige a etapa 17 que falhou e será retomada. Backup anterior automático preservado; não editar ou apagar o banco da loja, nem usar versão antiga sobre banco já migrado.
- `tests/test_migracao_itens_antigos.py`: versões de origem 12/16 com 14 campos, preservação exata de linhas, valores, IDs/sequência, estoque/partes e vínculos, defaults, backup prévio, reabertura, rollback e recusa a campo sem destino.
- Validação: 85 testes de migração, histórico, SQLite, auditoria, exclusão de produtos, esquemas 19/21 e retornáveis aprovados; `git diff --check` limpo. Banco real da loja não foi acessado. Precisa gerar/instalar um executável Windows contendo a correção para resolver o computador da loja.
- Usuário autorizou publicar esta correção na main. Conferir remoto e preservar trabalho do Codex local; não incluir automaticamente mudanças locais de impressora que não façam parte da correção.

## Continuidade anterior

- `9324c64`: ajustes do assistente de impressora (largura/acentos/corte); estava local, não publicado nesta conversa. Usuário disse que Codex do PC já está ajustando a impressora: evitar sobrepor esses arquivos.
- `fb13f93` foi publicado: shows automáticos de quartos + campo de shows manuais/anteriores no acerto, tarifa 50/60. Esquema 36, sem backfill. Seleção de tempo/profissional e correção de corte de telas também publicadas.
- Tabela entregue fora do checkout em /workspace/entregas/bar_adega: 160 sugestões de produtos/doses, CSV/XLSX com preços zerados a preencher; ambos validados no importador descartável. Usuário preferiu tabela; consulta online por GTIN não foi implementada.
- Ambiente: Python 3.12, .venv e dependências fixadas. Homologar Windows/periféricos/central. Ficha código 31 pendente; não hardcodar globalmente. Credenciais fora do chat.
