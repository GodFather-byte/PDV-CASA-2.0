# Revisão do WillPDV

Quem revisa um PR (agente ou pessoa) lê este arquivo **da main**, nunca da branch do PR: uma mudança não edita o
próprio juiz. Olhe só o diff (`git diff main...HEAD`). Classifique cada achado como **Importante**, **Detalhe** ou
**Já existia**. Um achado Importante diz o porquê, num cenário concreto (entrada → resultado errado).

## Sempre

- Dinheiro em centavos inteiros (`*_cent`), nunca `float`; quantidade com até 4 casas; datas ISO local.
- Venda só pelo `CaixaController`; regra nova com teste em `tests/`; textos e mensagens em português.
- Coluna ou tabela nova no caixa: migração em `src/database/esquema.py` (`VERSAO_ESQUEMA`, `MIGRACOES`).
- Nada de token, senha, URL do banco, e-mail de cliente ou certificado em log, teste, commit ou resposta de rota.
- A mensagem do commit traz `Verificado: ...` (ver `.claude/skills/verify`).

## Lista por gatilho

Confira só os itens cujo gatilho aparece no diff. Cada um nasceu de um problema real.

| Gatilho no diff | Confira | Origem |
|---|---|---|
| Coluna nova num modelo SQLAlchemy de tabela que já existe na nuvem | `create_all` não altera tabela existente: precisa de `ALTER TABLE` idempotente (como `retaguarda.garantir_colunas`, `cobranca_mercadopago._COLUNAS_NOVAS`) | `retaguarda_servicos` nasceu sem as colunas do Pix (#114) |
| Tipo novo em `TIPOS_COMANDO` da retaguarda | Caixa antigo recusa com "Atualize o programa da loja": exige versão nova publicada; a nuvem valida tamanho e quem pode mandar | `produtos.importar` (#113) |
| `src/ui_qt/` (layout, botões, `tema.py`) | Cabe em 1280 px (`tests/test_tema_moderno.py`); botão sem negrito/padding maior; seta do combobox visível; coluna de tabela sem corte | Menu e Estoque estouraram 1280 px; seta sumiu com `QComboBox::drop-down`; padding de `QTableView::item` cortou colunas (#107) |
| Troca de texto em massa (`replace`, regex) em arquivo com várias janelas | Só a ocorrência pretendida mudou | Edição da prévia pegou também a janela de NF-e |
| Licença, ponte, `renovar_ponte`, modo ponte | Caixa da ponte em loja fora do modo ponte recebe licença | Casa Verde 404 de hora em hora (#105) |
| Fluxo de pagamento no caixa | Dá para desfazer forma errada; com recebimento direto a venda fecha ao pagar | Troca de forma (#104), recebimento direto (1.14.10) |
| Consulta SQL nova em `produtos` | Nome real das colunas (`qt_atual`, não `estoque`; `ult_preco_cent`) | Teste escrito com coluna inexistente |
| Item novo no catálogo da adega | NCM do item igual ao `fiscal/ncm.sugerir` | `tests/test_catalogo.py` divergiu |
| Rota da central (`/v1/fornecedor/...`) que altera algo | Exige sessão da central e CSRF; entra na auditoria | Padrão de `instalar_fornecedor` |
| Rota do dono que altera algo | Só a loja da sessão; dono não usa recurso exclusivo do fornecedor | Cadastro em massa é serviço pago (#113) |
| Cobrança / Mercado Pago | Valor, moeda e `external_reference` conferidos na API (não no corpo do webhook); idempotência no POST | Webhook e Pix de serviço (#114) |
| `.github/workflows/` | Não usa artifacts para publicar (cota); publicação por rascunho; testes caros só onde precisa | Cota de artifacts estourada (#108–#110) |
| Teste Windows que cria/apaga `.exe` ou pasta | Limpeza tolera arquivo preso (tenta de novo) | Falha intermitente da Publicação assinada (#106) |
| Atualização automática / `atualizacao/` | Loja com turno aberto não instala no meio; versão antiga consegue chegar na nova | Casa Verde parada na 1.14.5 |

## Fora do escopo

Estilo pessoal, renomear o que funciona e "poderia ser mais elegante" não são achados. Para manter esta lista útil,
apague itens que nunca mais dispararam.
