# Handoff (18/11/2026): IA nos caixas, recurso pago (branch `ia-nos-caixas`)

No ar: 1.14.14 (apagar vendas de teste com a senha de segurança do dono).

## O que entrou
- **Nuvem** `backend/ia.py`: chave da API só na nuvem (`ANTHROPIC_API_KEY` no Render; `IA_MODELO` opcional, padrão
  `claude-haiku-5-5`). Por loja: `ia_lojas` (ativa, desligada por padrão; cota de usos/mês, padrão 300; custo do mês
  em nanodólares) e `ia_usos` (cada chamada). Rotas do caixa: `GET /v1/ia/situacao`, `POST /v1/ia/produtos/foto`,
  `POST /v1/ia/produtos/nomes`. Saída forçada por ferramenta (JSON com esquema) e limpa antes de devolver.
  403 não contratada, 429 cota, 503 sem chave. Central: `GET/POST /v1/fornecedor/lojas/{chave}/ia` (auditado) e
  `GET /v1/fornecedor/ia/uso`; bloco "IA no caixa" no detalhe da loja.
- **Caixa** `src/sync/ia.py` (cliente) e telas em `src/ui_qt/importar_produtos.py`: "Ler foto com IA…" (a foto vira
  a mesma prévia da planilha; nada grava antes de Importar) e "Arrumar nomes com IA" na prévia da NF-e (só itens
  novos; `ItemNFe.nome_xml` guarda o nome da nota).
- Testes: `test_ia_nuvem`, `test_ia_caixa`.

## Pendências
- Dono: criar a chave na Claude Platform (organização ligada ao Max, para usar o crédito mensal) e colar em
  `ANTHROPIC_API_KEY` no Render. Depois ligar a IA por loja na central.
- Próximas ideias: "pergunte ao caixa" no painel (a IA só escolhe o relatório; o número vem do banco), resumo do dia
  comentado no WhatsApp.
- Backlog: homologação NFC-e DeliciOz; alíquotas IBS/CBS de 2027; Casa Verde na 1.14.5 (instalação manual);
  mensalidade EA Superações.
