# Melhorias operacionais 1.8

Os recursos gerais não dependem do perfil Adega: Boate, Bar, Restaurante,
Churrascaria, Comércio e Adega compartilham as mesmas regras e banco.
Módulos opcionais, como Cozinha/Bar, continuam respeitando sua configuração.

## Onde encontrar

| Recurso | Onde |
|---|---|
| Cancelamento parcial e divisão da conta | Abrir caixa |
| Alertas operacionais | Alertas da operação |
| Reposição por giro e etiquetas | Estoque |
| Controle de retornáveis | Retornáveis por cliente |
| Promoções e simulação de preço | Promoções e faixas |
| Painel do dono | Mesmo bot e banco da loja |
| Cozinha/Bar | Cozinha / Bar |
| Setores de impressão | Mais cadastros > Setores de impressão |

No Qt, a busca lateral localiza os módulos também sem acentos. Filtrar a navegação
não concede permissões. Painéis novos revalidam a sessão ao reabrir e nas ações.
As permissões de estoque, produtos, relatórios e cozinha continuam independentes.

Detalhes: [caixa](CAIXA_MELHORIAS.md), [estoque e etiquetas](ESTOQUE.md),
[retornáveis](RETORNAVEIS.md), [promoções](PROMOCOES.md),
[interface Qt](INTERFACE_QT.md). O Telegram foi desligado.

## Limites que continuam valendo

- Retornáveis são um controle explícito de posse por cliente, não cobrança de caução
  nem dedução automática de estoque. Trocas antigas de cascos não geram dívida.
- Reposição é sugestão para revisão do responsável, não compra automática.
- Promoções/faixas não somam descontos entre si. Confira as condições e o preço
  final na simulação; o preço cobrado é registrado pelo fluxo único do caixa.
- O Telegram do dono consulta os dados da loja. A central do fornecedor continua
  separada e não recebe faturamento. PC desligado não responde pelo bot local.
- Nenhuma operação nova ativa cobrança de mensalidade, emissão fiscal ou serviços
  externos. Não há promessa de impressão física sem testar a impressora real.

## Homologação antes de atualizar o caixa real

1. Faça backup e prepare uma cópia do banco fora da pasta de dados da produção.
2. Informe essa cópia por `PDV_DB` antes de executar o programa. Extrair um pacote
   em outra pasta não isola o banco padrão do usuário.
3. Abra o PDV com `python -m src.app` (interface Qt).
4. Confira saldo inicial, turno, pagamentos, cancelamentos, preços e estoque
   na cópia. Repita com as permissões reais dos operadores.
5. Homologue teclado, leitor, escala da tela, gaveta, balança, etiquetas e cozinha
   nos periféricos da loja. Testes automáticos não substituem esses testes físicos.
6. Guarde backup anterior à migração. Não faça downgrade do executável sobre
   o banco migrado; restaure a cópia compatível para testar uma versão anterior.

Os portáteis 1.7.0 gerados anteriormente não incluem esta entrega.
Código atualizado não significa que um novo executável ou instalador já foi gerado.
