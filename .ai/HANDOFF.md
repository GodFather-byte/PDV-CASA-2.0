# Handoff — 05/11/2026

## Identificação nos comprovantes de comissão/acerto

- Pedido: comprovante das profissionais sem a palavra "Garota", apenas número e nome.
- `impressao_controller.py`: via de comissão e recibo de acerto identificam `180 MARIA`, sem rótulo; removido "VIA DA GAROTA" e assinatura passa a "Assinatura". Estilo térmico mantém identificação em letra alta pelo prefixo numérico.
- `ui_qt/comissao.py`: comprovante de saída financeira também imprime só número/nome como motivo. Descrição contábil gravada, valores, shows, comissões e demais cálculos permanecem como antes.
- Atualizadas as verificações existentes dos textos e do tamanho de letra. Teste do pagamento real pela UI confere que recibo e comprovante de saída contêm número/nome e não contêm "garota".
- Validação: 212 testes de comissões, shows, fechamento, acerto Qt e comanda vazia aprovados; após fortalecer a asserção dos dois documentos, teste específico passou. `git diff --check` limpo.

## Continuidade

- Main anterior `2103b7a`: corrige migração v17 do banco antigo (14 campos dos itens para DDL atual de 20) copiando campos pelo nome, sem perder os defaults novos. Backup e rollback preservados. 85 testes aprovados. Não apagar banco da loja; instalar executável com correção.
- `9324c64` continua na branch work como ajuste local de impressora; não foi incluído na publicação da migração. Codex no PC do usuário está ajustando impressora; evitar sobrepor arquivos.
- `fb13f93`: shows automáticos dos quartos + manuais/anteriores no acerto (50/60); esquema 36, sem backfill, IDs vinculados ao acerto evitam repetição. Seleção de tempo/profissional e correção de corte das telas já publicadas.
- Tabela de 160 sugestões em /workspace/entregas/bar_adega (fora do checkout), CSV/XLSX validados; preencher preços zerados antes de importar. Usuário preferiu tabela; consulta online GTIN não implementada.
- Ambiente Python 3.12/.venv. Gerar/homologar instalador Windows e periféricos. Ficha código 31 pendente; credenciais fora do chat. Demais detalhes no histórico deste arquivo.
