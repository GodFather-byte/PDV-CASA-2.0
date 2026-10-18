# HANDOFF

## Último trabalho
- **Perfil do estabelecimento** (o "modo de operação" que o titular escolheu no início do ecossistema; vem depois dos
  quatro módulos Cozinha/Bar, Split de conta, Venda por peso e Rodízio, todos em `main`). Antes disto o sistema vinha
  configurado como boate para qualquer cliente: código 50 de comissão, ticket da portaria, "Cadastro de Garotas" e
  relatório de comissão apareciam para restaurante e padaria, sem como esconder.
  - `src/controllers/perfil_controller.py` (novo): `PERFIS` com Boate / casa noturna, Bar, Restaurante, Churrascaria /
    rodízio e Comércio pequeno. Cada perfil define 11 chaves de liga/desliga (`ITENS`): os módulos `usar_*` e as regras
    posição padrão, serviço na mesa e na comanda, perguntar pessoas e desconto. **Nunca toca em código, preço,
    percentual ou número digitado pelo dono.** `mudancas(perfil)` lista o que muda, em palavras; `aplicar(perfil)` grava
    tudo ou nada por `ConfigController.salvar_config` (mesmas validações) e registra no `log_eventos`. A Boate é igual a
    `CONFIG_PADRAO` (há teste): banco existente não muda nada.
  - Dois módulos novos que **nascem "S"** (exceção documentada à convenção `usar_* = N`, porque o sistema nasceu boate):
    `usar_garotas` (esconde `cad_garotas`, `caixa_comissao`, `caixa_pagar_comissao` e `rel_comissao_garotas` via
    `MODULOS_OPCIONAIS`; no caixa Tk tira o botão Comissões, a aba Comissões do painel, os cartões das garotas, o nome
    da garota na situação, o acerto pelo F12 em comanda vazia, as linhas de comissão e as linhas zeradas do painel de
    fechamento) e `usar_portaria` (ticket de saída ao pagar e o código 1002).
  - Códigos especiais centralizados em `config_controller.py` (`CODIGOS_ESPECIAIS`, `codigo_especial`): os quatro pontos
    que liam `codigo_comissao`/`codigo_saida` direto (comissão, caixa, cadastro de produto, importação por planilha)
    passaram a usar a mesma função. Com o módulo desligado o código deixa de existir e fica livre para produto. A
    conferência de conflito (produto com o código, comissão = saída) saiu do laço de `salvar_config` e foi para o fim
    (`_conferir_codigos_especiais`), com os módulos já no estado novo: religar garotas/portaria com um produto no código
    é recusado, e gravar a tela inteira com o módulo desligado não acusa conflito falso.
  - UI: botão "Perfil do estabelecimento..." na janela de Configurações (`config_ui.escolher_perfil`: grava a tela,
    lista os perfis, confirma mostrando o que muda, aplica e recarrega) e escolha do tipo de negócio no primeiro acesso
    (`cadastro_loja_ui.py`, só para quem tem `cfg_configuracoes`; o texto da janela deixou de citar a "via da garota").
  - Testes: `tests/test_perfil.py` (24 casos: perfis, módulos da casa noturna, caixa sem garotas, painel do fechamento,
    primeiro acesso e botão das Configurações).
  - **Qt não recebeu a tela do perfil nem o corte do botão Comissões/aba no caixa Qt.** Os menus Qt já escondem (usam
    `modulos_desligados`) e o código 50/1002 já some no Qt também (vem do controlador).

## Pendências
- Possíveis evoluções do ecossistema, nenhuma pedida ainda:
  - **Pré-pago / cartão consumação** (boate e eventos): crédito carregado na entrada, debitado no consumo, devolução da
    sobra na saída. Anotado também em `docs/ESPECIFICACAO.md` seção 3.
  - **Split por item consumido**: cada pessoa paga o que pediu, não uma fração igual (mudança de esquema).
  - **Rodízio com preço por faixa** (adulto/criança, dia da semana): hoje é um valor único (`valor_rodizio_pessoa`);
    `vendas.pessoas` teria que virar mais de um campo. Decidir o desenho com o titular antes.
  - **Etiqueta de balança no leitor** (EAN de peso/preço embutido, prefixo 2): para padaria/açougue com balança que
    imprime etiqueta. Só vale se o titular tiver esse equipamento.
- **Valores de cada perfil**: foram decididos por mim (ex.: Bar com Cozinha/Bar ligado e sem portaria; Restaurante com
  delivery). Titular pode querer ajustar; é só mudar `PERFIS` em `perfil_controller.py` (os testes de valores válidos
  pegam erro de digitação).
- **Homologar a balança com equipamento real** (Toledo ou Filizola, porta serial): `Balanca.ler_peso`
  (`src/hardware/dispositivos.py`) nunca foi testado fora do código.
- **Qt dos módulos de operação**: alinhar `src/ui_qt/caixa.py` com o Tk: roteamento de impressão por setor
  (Cozinha/Bar), "Dividir conta", acionamento automático da balança, "Rodízio", e agora o perfil do estabelecimento e o
  corte das garotas (botão Comissões e aba do painel Qt).
- Qt (`src/ui_qt/`, opt-in) ainda tem a regra antiga do acerto da garota (`_acerto_so_de_shows`, `comissao.py`) e o
  recibo/comprovante com o tipo antigo (letra normal); o texto do recibo já vem sem os lançamentos. Alinhar com o Tk se o
  Qt for substituir o Tk. O painel Qt do balcão/comandas também não foi redimensionado.
- Titular: conferir na prática o tamanho dos cartões (184x126) e da faixa (`ALTURA_FAIXA = 52`), e a letra do recibo na
  impressora real; ajustar as constantes se precisar.
- Titular: instalar o Google Drive para computador, escolher a pasta na aba Backup do WillPDV Licenças e anotar a senha
  da chave.
- Ideia aberta (pede OK do titular, regra de licença): renovar a partir do vencimento atual para o cliente não perder
  dias.
- Homologar em cópia do banco, com periféricos reais: comissão/acerto/saída, gaveta, teclado/escala. Backup do PDV:
  escolher pasta e senha no caixa e ensaiar recuperação em outra máquina.
- Asaas (quando houver nuvem): homologar sandbox/credenciais/webhook e hospedar API e `python -m backend.worker_asaas` sob
  supervisão; validar custos antes de contratar.
- Painel web e múltiplos caixas seguem fora de escopo.
