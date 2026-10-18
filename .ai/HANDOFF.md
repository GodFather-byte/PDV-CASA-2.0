# HANDOFF

## Último trabalho
- **Venda por peso** (terceira peça do ecossistema de operação, depois de Cozinha/Bar e Split de
  conta). Descoberta ao investigar: o caixa **já tinha** o fluxo de pesagem pronto — F2
  (`JanelaCaixa.balanca`, `src/ui/caixa_ui.py`) já lê a balança configurada (ou pede o peso
  digitado, se não houver) e o cálculo preço-por-quilo × peso já funcionava e já tinha teste
  (`test_quantidade_fracionada_so_se_o_produto_aceita`). O que faltava era só uma coisa: o campo
  `produtos.balanca` (cadastro, "Balança") **não acionava nada** — o operador tinha que lembrar
  de apertar F2 na mão, e nada impedia confirmar "1" por engano num produto vendido a quilo.
  - Corrigido: `selecionar_produto()` (`caixa_ui.py`) agora chama a pesagem direto quando
    `p["balanca"]` está marcado, em vez de sugerir quantidade "1". Extraí a lógica de pesagem de
    `balanca()` (F2) para `_capturar_peso()`, reaproveitada pelos dois caminhos — o F2 continua
    funcionando igual, manual, em qualquer produto (não só os marcados "Balança").
  - Sem flag em `CONFIG_PADRAO`: é opt-in por produto (`balanca = 1` no cadastro), então uma casa
    que nunca marca nenhum produto não vê nenhuma mudança — mesmo raciocínio do Split de conta
    (ver abaixo), nenhum dos dois precisou de `usar_<modulo>`.
  - **Achado à parte, documentado mas não mudado**: `src/hardware/dispositivos.py` já tem a
    leitura serial real da Toledo/Filizola implementada (`Balanca.ler_peso`), mas a documentação
    antiga (docstring do arquivo e `docs/ESPECIFICACAO.md`) dizia que só existia o modo manual —
    corrigido o texto; o código em si não mudou. **Nunca foi homologado com equipamento real**
    (mesma pendência de sempre, só reforçada abaixo).
  - Testes novos em `tests/test_ui.py` (`TesteFluxosCaixa`): selecionar produto de balança pesa
    direto e calcula o total certo; F2 continua funcionando manualmente num produto comum (não
    havia nenhum teste do fluxo de balança antes disso).

## Pendências
- **Homologar a balança com equipamento real** (Toledo ou Filizola, porta serial): o protocolo em
  `Balanca.ler_peso` nunca foi testado fora do código. Mesma observação já valia (genérica,
  "escala") desde o HANDOFF anterior ao módulo de operação — agora é específica.
- **Qt dos módulos de operação**: alinhar `src/ui_qt/caixa.py` com o Tk — roteamento de impressão
  por setor (Cozinha/Bar), "Dividir conta" (Split) e o acionamento automático da balança não foram
  portados. Mesma observação de sempre sobre o acerto da garota no Qt (ver linha abaixo).
- **Próximo módulo de operação** (mesma convenção documentada em `config_controller.py` e
  `docs/ESPECIFICACAO.md`): **Rodízio por pessoa** — cobrança fixa por pessoa no fechamento da
  conta (não em `itens_venda`); `usar_rodizio` + valor configurável; decidir como interage com
  desconto/serviço em `CaixaController.fechar`. Este sim precisa de flag (é um jeito de cobrar
  diferente, não um opt-in silencioso por produto/venda como os dois anteriores).
- **Split por item consumido** (evolução do split, só se o titular quiser depois): cada pessoa
  paga o que pediu, não uma fração igual — exige marcar os itens de cada pessoa (mudança de
  esquema); por ora o split cobre só divisão em partes (iguais ou ajustadas à mão).
- Qt (`src/ui_qt/`, opt-in) ainda tem a regra antiga do acerto da garota (`_acerto_so_de_shows`,
  `comissao.py`) e o recibo/comprovante com o tipo antigo (letra normal); o texto do recibo já
  vem sem os lançamentos. Alinhar com o Tk se o Qt for substituir o Tk. O painel Qt do
  balcão/comandas também não foi redimensionado.
- Titular: conferir na prática o tamanho dos cartões (184x126) e da faixa (`ALTURA_FAIXA = 52`),
  e a letra do recibo na impressora real; ajustar as constantes se precisar.
- Titular: instalar o Google Drive para computador, escolher a pasta na aba Backup do WillPDV
  Licenças e anotar a senha da chave.
- Ideia aberta (pede OK do titular, regra de licença): renovar a partir do vencimento atual para
  o cliente não perder dias.
- Homologar em cópia do banco, com periféricos reais: comissão/acerto/saída, gaveta,
  teclado/escala. Backup do PDV: escolher pasta e senha no caixa e ensaiar recuperação em outra
  máquina.
- Asaas (quando houver nuvem): homologar sandbox/credenciais/webhook e hospedar API e
  `python -m backend.worker_asaas` sob supervisão; validar custos antes de contratar.
- Painel web e múltiplos caixas seguem fora de escopo.
