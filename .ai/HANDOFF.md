# Handoff — Tutorial guiado de produto (12/11/2026)

Branch `tutorial-guiado`, criada de `origin/main`. Pedido do dono: abrir PR e parar,
sem merge. Não houve alteração em backend/ nem em src/sync/sincronizador.py.

## Pronto

- Roteiro de oito passos sem Qt em `src/controllers/tutoriais.py`: lista, Novo,
  nome, preço, código de barras opcional, estoque inicial opcional, conferência
  do código/subgrupo/unidade e Salvar. Não cria exemplo fictício.
- Conclusão em config por operador; refazer sempre disponível. Pular/Esc não
  concluem. Texto comum às três edições, sem migração.
- `src/ui_qt/tutorial.py`: sombra transparente a cliques com recorte e balão
  não modal. Alvos por objectName; condições liberam Próximo; erro de alvo
  encerra com aviso. Reposiciona durante o uso, seleciona aba e rola ao campo.
- Primeiros passos > Produtos > Me mostre como; Ajuda > Tutoriais para refazer.
- Integração pontual com cadastro existente; estoque opcional usa o controller
  de estoque com validação/permissão de gerente. Produto, lançamento e marca
  são transacionais. Sem estoque informado, preserva o cadastro normal.
- Voltar dentro do formulário não desfaz dados. Ao entrar em Novo não volta à
  lista pelo balão, para não descartar o formulário; Pular continua disponível.
- Novos módulos incluídos no autoteste/build.

## Validação

- `QT_QPA_PLATFORM=offscreen python -m unittest tests.test_tutorial_guiado`:
  10 testes passaram, incluindo alvos nas três edições, gravação real, rollback,
  condições, operador, Esc/Pular e geometria dos balões em 1024x600.
- Tutorial + primeiros passos + autoteste: 19 testes passaram.
- Suíte completa: 2.751 testes em 428 s, 24 pulados; duas falhas em
  test_licenciador e um erro em test_central_ui por falta de display Tk
  (sem $DISPLAY). Nenhuma outra falha no relatório final. A primeira execução
  revelou dependências de backend ausentes; instaladas antes da execução final.
- Não houve homologação visual no Windows, com leitor físico, fonte ampliada,
  nem em monitor físico 1024x600. Testes de geometria são Qt offscreen.

## Teste manual

1. Entrar com operador autorizado a cadastrar produtos. Em Primeiros passos,
   clicar Me mostre como no cartão Produtos; escolher Cadastrar um produto.
2. Avançar, clicar Novo, preencher nome e preço; conferir bloqueio de Próximo
   com nome vazio/preço inválido. Usar Voltar sem perder os valores.
3. Informar ou deixar vazio o código de barras. Estoque opcional: vazio não
   lança; quantidade informada requer permissão de gerente. Conferir código
   interno, subgrupo e unidade obrigatórios. Clicar Salvar.
4. Conferir produto e saldo; reabrir Ajuda > Tutoriais, verificar concluído e
   refazer. Outro operador mantém sua própria marca.
5. Repetir e apertar Esc/Pular: formulário permanece operável; não marca
   conclusão. Repetir em 1024x600 nas três edições.

## Pendências

- Próximos tutoriais, nesta ordem: grupo e subgrupo; operador com senha;
  cliente (caderneta).
- Homologação visual/física descrita acima e revisão do PR; não fazer merge.
- Pendências anteriores continuam fora deste escopo: homologar térmica do
  Will Restaurante; checkout do site por WhatsApp; segredos PDV_ATUALIZACAO_*;
  revisão da rede de lojas pelo dono da área e aplicação em várias lojas.
