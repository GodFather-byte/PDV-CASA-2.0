# HANDOFF

## Último trabalho
- **Módulo Adega / depósito de bebidas**, pedido com urgência pelo titular (instalação num cliente de adega no dia
  seguinte: "cadastro de bebidas, não por mesa nem comanda, sistema de adega completo"). Vem depois do Pré-pago e do
  Perfil do estabelecimento (todos em `main`).
  - Perfil `adega` em `perfil_controller.py`: venda só no balcão, delivery, caderneta (fiado), desconto liberado, sem
    serviço, garotas e portaria. Ao aplicar, cria as categorias que faltam (`CATEGORIAS`: BEBIDAS com Cervejas,
    Destilados, Vinhos e espumantes, Refrigerantes, Águas e sucos, Energéticos; CONVENIÊNCIA com Gelo e carvão,
    Tabacaria, Petiscos, Descartáveis). A confirmação nas Configurações lista as categorias que serão criadas.
  - Módulo **Mesas e comandas** (`usar_mesas`, nasce "S"; Comércio pequeno e Adega desligam; esconde `rel_comandas` e
    `rel_garcons`): o caixa Tk vira só balcão (`JanelaCaixa.com_mesas`): sem painel, campo da posição, setas ◀▶,
    indicadores de posições do topo e ações de mesa; F4/Esc só limpam a entrada, F9/F10/PgUp/PgDn não fazem nada, F8
    avisa que no balcão não há pré-conta (mas segue imprimindo o pedido de entrega), "M5" no código não vira mesa.
    `CaixaController.abrir_mesa` recusa quando desligado.
  - **Cadastro na hora pelo código de barras** (vale para qualquer negócio): código só de números com 8+ dígitos que não
    existe → confirma "Cadastrar o produto agora?" → senha de supervisor se o operador não tem `cad_produtos` →
    `cadastro_rapido_ui.pedir_produto` (nome, preço, categoria, estoque opcional) → lança. Códigos curtos continuam com
    "Produto não encontrado" (os testes antigos dependem disso).
  - **Fardo / caixa fechada**: botão no Cadastro de Produtos (`cadastros_tk._criar_embalagem` →
    `cadastro_rapido_ui.pedir_embalagem` → `ProdutoController.criar_embalagem`): produto novo com preço e código de barras
    próprios, unidade FD/CX/PCT, composição N × unitário (a venda baixa as unidades pelo mecanismo de composição que já
    existia); o unitário passa a controlar estoque. Unidades "Fardo" (FD) e "Caixa" (CX) entraram nas sementes (só banco
    novo).
  - `ProdutoController.proximo_codigo` virou a regra única do próximo código (o `CadastroController.proximo_codigo_produto`
    delega): pula os códigos especiais em uso (antes sugeria 50 e o cadastro recusava por ser o da comissão) e ignora
    código de barras usado como código.
  - Testes: `tests/test_adega.py` (18 casos: perfil, categorias, próximo código, cadastro rápido, fardo, caixa só de
    balcão, cadastro pela tela com e sem permissão, botão do fardo e primeiro acesso como adega).
  - **Qt não recebeu nada disto** (o caixa Qt continua com mesas; o controlador já recusa abrir mesa com `usar_mesas`
    desligado).

## Pendências
- **Adega, possíveis próximos passos** (nenhum pedido ainda): casco/vasilhame retornável (perguntar se o cliente
  trabalha com retornável: o simples hoje é cadastrar "CASCO 600ML" como produto e lançar quando o cliente não traz);
  quantidade antes do bipe (ex.: "12*" + código); agrupar o mesmo produto bipado várias vezes numa linha só; preço de
  atacado por quantidade (hoje o fardo resolve); etiqueta de gôndola.
- **NFC-e**: o sistema não emite documento fiscal (cupom "NÃO FISCAL"). Para adega/comércio isso pode ser exigido pela
  SEFAZ do estado; não dá para resolver sem certificado digital e integração (provável API de terceiros). Avisar o
  titular antes de cada instalação nesse ramo.
- **Pré-pago, risco a confirmar com o titular**: a sobra de recarga feita no cartão de crédito volta em dinheiro
  ("saque" no cartão). Se ele quiser, limitar a devolução em dinheiro ao que entrou em dinheiro/Pix.
- Pré-pago, evoluções: comprovante impresso da recarga; pulseira RFID com número próprio; relatório de recargas.
- Outras evoluções do ecossistema: split por item consumido; rodízio com preço por faixa (adulto/criança); etiqueta de
  balança no leitor (EAN de peso/preço embutido); consumação mínima por tipo de entrada e cobrança da comanda sem
  consumo (`docs/ESPECIFICACAO.md` seção 3).
- **Valores de cada perfil** (`PERFIS`) foram decididos por mim; titular pode querer ajustar.
- **Homologar a balança com equipamento real** (Toledo ou Filizola, porta serial): `Balanca.ler_peso` nunca foi testado
  fora do código.
- **Qt dos módulos de operação**: alinhar `src/ui_qt/caixa.py` com o Tk: impressão por setor, "Dividir conta", balança
  automática, "Rodízio", perfil do estabelecimento, corte das garotas, pré-pago e agora o caixa só de balcão, o cadastro
  na hora e o fardo/caixa.
- Qt (`src/ui_qt/`, opt-in) ainda tem a regra antiga do acerto da garota (`_acerto_so_de_shows`, `comissao.py`) e o
  recibo/comprovante com o tipo antigo (letra normal). Alinhar com o Tk se o Qt for substituir o Tk. O painel Qt do
  balcão/comandas também não foi redimensionado.
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
