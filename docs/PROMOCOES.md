# Promoções e faixas — sem acúmulo

Gestão compartilhada para todos os perfis com acesso `cad_produtos`, nas interfaces
Tk e Qt. O operador ativo e o nível atual são consultados ao abrir/reabrir, buscar,
simular e, novamente, na transação de gravação. A integração do menu é externa a
estas telas.

## Alcance

- **Uma promoção por período, uma por dias da semana e uma por horário**, existentes
  no cadastro do produto. Não há lista ilimitada de regras nem combos.
- **Uma faixa de quantidade natural e uma gelada** por produto. Mínimo e preço
  unitário devem ser positivos juntos, ou ambos zero para desligar.
- Promoções temporais aplicam-se ao preço **natural**. Gelada continua usando seu
  preço próprio e sua faixa, como no caixa existente; não herda promoção natural.
- Entre preços elegíveis, vale o menor preço unitário final. Não se somam descontos.
  Faixa pode vencer promoção ou vice-versa. Não se aumenta preço por promoção.
- Datas são inclusivas; horário considera o minuto completo. Ex.: 22:00–04:00
  inclui 04:00:59. Dias (1=domingo, 7=sábado) e horários admitem virada.
  As três modalidades temporais são alternativas, não condições cumulativas.

## Operação

Pesquise e selecione o produto. Os campos monetários recebem **reais** (ex. `7,50`);
o resultado mostra **inteiros em centavos**. Escolha os dias nos seletores; datas
aceitam `dd/mm/aaaa` ou ISO e horários `hh:mm`. Preço zero desliga a respectiva
promoção. Salvar usa o `CadastroController`, inclusive suas validações de quantidade
finita/4 casas, preços de faixa coerentes e restrições da unidade do produto.
Promoção ativa exige início/fim e preço não superior ao natural. Alterações parciais
também validam a regra completa já persistida.

Simular avalia os campos ainda não salvos, quantidade positiva, temperatura e
data/hora local `YYYY-MM-DD HH:MM:SS`. Mostra preço-base, cada promoção e respectivas
condições/elegibilidade, faixa/mínimo, preço final unitário e total. Não grava
produto, venda ou estoque. Pesquisar/recarregar descarta alterações não salvas.

Venda continua exclusivamente no `CaixaController`: retrato do preço aplicado
preservado; balcão mantém a reprecificação por quantidade já existente. A simulação
é de produto simples, não de montagem, partes ou composição de pedidos.

## APIs para integração

- Tk: `src.ui.promocoes_ui.abrir(master, ctx)` retorna `JanelaPromocoes`.
- Qt: `src.ui_qt.promocoes.JanelaPromocoes(ctx, parent=None)`.
- Ambas expõem `exigir_acesso()` para o menu validar antes de reabrir instância.
  Nenhuma tela importa a outra; Qt não cria raiz Tk.
- `PromocoesController(ctx)`: `listar(texto="")`, `obter(produto_id)`,
  `salvar(produto_id, valores)`, `simular(produto_id, quantidade="1",
  temperatura="natural", quando=None, valores=None)` e `descrever(resultado)`.
  `valores` usa os mesmos formatos de formulário do cadastro, não centavos brutos.
  `simular` retorna `base_cent`, `promocao_cent`, `faixa_cent`, `final_cent`,
  `total_cent`, condições e instante, sem persistência.

Sem migração: utiliza somente os campos existentes de produtos.

## Testes direcionados

`python -m unittest tests.test_promocoes` cobre sobreposição sem acúmulo, fronteiras
de período/dias/horário, faixa natural/gelada, rascunho sem escrita, validação,
revalidação de acesso, abertura/salvamento/simulação Tk/Qt e isolamento de imports.
Regressão: `tests.test_adega_cadastro`, `tests.test_adega_regras`,
`tests.test_adega_retrato`, `tests.test_adega`, `tests.test_caixa` e
`tests.test_regras_caixa`.
