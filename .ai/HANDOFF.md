# HANDOFF

## Escopo autorizado

- Retomadas as oito melhorias operacionais para **todos os perfis, Tk e Qt**.
  O titular também pediu completar a modernização PySide6 mantendo Tk disponível.
- Regras preservadas: cancelamento parcial só de quantidade não paga com motivo;
  reposição por caixa com giro de 30 dias e cobertura de 7; retornáveis sem caução;
  promoções sem acúmulo. Sem ativar cobrança nem integrações fiscais.
- PDV **1.8.0**, licenciador permanece **1.2.0**, esquema **27**.
- Base publicada anteriormente: `df0864f`, main local/remota sincronizadas ao começar.
  Entrega operacional commitada em `7fb7cb1`. Titular autorizou integrar a
  main remota `e3484dd` (PR #15); merge preserva ambas as linhas de trabalho.
  Não houve push novo nesta etapa.

## Endurecimento remoto preservado (PR #15)

- PBKDF2 de senha de operador com 600 mil iterações; hashes antigos (60 mil) seguem válidos e
  são regravados no login correto (`seguranca.precisa_atualizar`, `AcessoController.autenticar`).
- `BancoDados.inserir/atualizar` recusam tabela/coluna fora de `[A-Za-z0-9_]`.
- `servico_pct` vai direto a `Decimal` (sem `float`). Zip duplicado removido da raiz.
- Testes: `tests/test_seguranca_auditoria.py` (inclui vetores RFC 8032 do Ed25519).
- Pendências sugeridas: lint/tipos/cobertura no CI; piloto em loja real (impressora, balança, queda de energia).

## Implementação

- Caixa: cancelamento parcial com histórico e divisão por item/valor pelo
  `CaixaController`, interfaces Tk/Qt e testes novos. Migração 27 registra vínculo
  pagamento/item; sem inventar atribuições para pagamentos antigos.
- Alertas operacionais: estoque, comandas sem lançamento, entregas, filas e
  integrações; acesso por seção e revalidação. Telegram do dono ganhou Alertas
  e Gerencial, sem mandar faturamento à central do fornecedor.
- Reposição por giro: escolha do caixa, sugestão revisável e confirmação para
  criar pedido. Etiquetas naturais/geladas e fardo, prévia textual/impressão
  existente e CSV; não é driver de impressora de etiquetas.
- Retornáveis: ledger explícito por cliente/produto com saída/devolução, saldo
  não negativo, motivo, operador e auditoria. Migração 26; não altera estoque,
  vendas ou caução e não converte trocas históricas em dívidas.
- Promoções: gestão e simulação Tk/Qt sobre as três regras temporais existentes
  e uma faixa por temperatura. Menor preço elegível, sem somar promoções/faixas.
- PySide6: cozinha/bar com preparo e timer, setores no menu de cadastros,
  extras de cadastro e busca lateral sem acentos. Cadastros ganharam filtros
  estruturados e ordenação. Caixa Qt inclui pré-pago/rodízio, leitor F3,
  sangria F7, nome de comanda, Leitura X/Redução Z e acesso à fila de impressão.
  Não certifica paridade de cada detalhe ergonômico com o Tk.
- Menus Tk/Qt conectados; os recursos gerais não dependem do perfil Adega.
  Novos módulos incluídos no inventário e na abertura de telas do autoteste.
- Guias: `docs/MELHORIAS_1_8.md`, `CAIXA_MELHORIAS.md`, `PROMOCOES.md`,
  `RETORNAVEIS.md`, seções de Estoque, Telegram e Interface Qt.

## Validação

- Menus/ciclo Qt: 75 casos passaram, incluindo 7 novos Tk/Qt de permissões,
  reabertura, busca e todos os seis perfis.
- Autoteste integrado: 128 módulos carregam e novas telas abrem em Tk/Qt.
- Frentes independentes passaram em testes focados; a suíte geral preliminar
  executou 2614 casos durante a implementação, com 1 falha de inventário
  (já corrigida) e 8 erros de fixtures/compatibilidade enviados aos responsáveis.
- Após ajustes: **2628 casos, 10 ignorados, sem falhas** na suíte completa
  (Windows/Python 3.15, 1244 s). Últimas seis funções Qt também cobertas por
  rodada focada de 101 casos; complemento final do titular com 30 casos passou.
- `compileall` e `git diff --check` passaram. Pylance expirou nesta rodada;
  validação sintática foi feita pelo Python, sem alegar type-check Pylance.
- Log da suíte contém exceções simuladas de propósito e avisos Tk de callbacks
  destruídos; resultado final do unittest foi OK. Não foram ocultados.
- Após integrar PR #15: **154 testes direcionados passaram** (segurança,
  acesso, caixa, cancelamento parcial, divisão por item, retornáveis, promoções
  e menus Tk/Qt). Não repetida a suíte inteira após este merge.

## Homologação e pendências

- Não há binário/Setup novo desta entrega. Os ZIPs portáteis 1.7.0 são anteriores
  inclusive à mesclagem e **não incluem** as melhorias 1.8.0.
- Validar primeiro uma **cópia** do banco com `PDV_DB`; extrair o programa em
  outra pasta não isola `%LOCALAPPDATA%\WILL-PDV`. Uma interface por vez.
- Homologar periféricos reais, teclado e escala. Paridade de menus não certifica
  cada detalhe ergonômico nem impressão/gaveta/balança reais.
- Merge do PR #15 validado e concluído na main local. Não usar force push.
  Publicação e novos pacotes permanecem pendentes.
- Divisão por item não atende caderneta, pré-pago ou itens inclusos no rodízio.
  Alteração que reprecifica item pago é recusada até remover o pagamento;
  pagamentos legados por valor não recebem atribuição automática a itens.
- Telegram/central entregues anteriormente continuam sem homologação real:
  configurar bot separado no PC exclusivo, importar chave existente, aprovar
  caixa de teste, conferir pedido/publicação/aplicação e backup/restauração.
  Preservar Render/Neon. PC desligado não oferece disponibilidade do bot local.
- Cobrança automática excluída; Asaas não ativado. iFood/NFC-e SP seguem
  base interna desativada, sem homologação fiscal.
- Nuvem: validar caixa/celular; trocar credenciais anteriormente expostas.
  Nenhuma chave real, cobrança ou banco de produção usado nesta implementação.
