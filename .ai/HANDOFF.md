# HANDOFF

## Último trabalho

Investigação dos checks do commit `c0c36ef`. O workflow `Testes` falhou nos dois
jobs Windows em `test_migracao_v23_nao_inventa_regra_e_mantem_backup_reabrivel`:
o diretório temporário não podia ser removido porque `with sqlite3.connect(...)`
não fecha a conexão SQLite. O teste agora fecha explicitamente a conexão com
`contextlib.closing`.

## Validação

- Pendente: executar `python -m unittest tests.test_adega_retrato`.
- Os jobs Linux e PostgreSQL do commit referenciado passaram; os dois jobs Windows
  falharam somente ao limpar o arquivo de backup aberto pelo teste.

## Pendências

- Confirmar a correção em execução Windows/CI.
