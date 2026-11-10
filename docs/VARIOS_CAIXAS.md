# Vários caixas na mesma loja

Desde a 1.13.0, dois ou mais computadores podem vender na mesma loja, no mesmo estoque. Vale para o WillPDV e
para o Will Adega.

## Como funciona

Um computador é o **caixa principal**. O banco da loja fica nele, como sempre. Os outros são **caixas adicionais**:
não têm banco próprio em uso e trabalham no banco do principal pela rede da loja (cabo ou Wi-Fi).

O que é da loja inteira: produtos, preços, estoque, fiado, clientes, entregas, numeração dos cupons, operadores,
configurações e licença.

O que é de cada caixa: o número do caixa, o turno, a gaveta, a impressora (Máquinas e periféricos) e a venda de
balcão em andamento.

## O que o dono precisa saber

- **O caixa principal tem de estar ligado, com o programa aberto.** Se ele desligar ou a rede da loja cair, os caixas
  adicionais param de vender até a ligação voltar. O principal continua vendendo sozinho, sem internet, como antes.
- Uma venda que estava sendo gravada no momento da queda é desfeita inteira. Nada fica pela metade. O operador
  repete a operação quando a ligação voltar.
- Backup, restauração, nuvem, painel do dono, porteiro e atualização do programa rodam só no caixa principal.
- Todos os caixas precisam estar na **mesma versão** do programa. Depois de atualizar o principal, instale a mesma
  versão nos adicionais; até lá eles não entram, e a tela explica o motivo.
- Não copie o arquivo do banco para uma pasta compartilhada da rede. O SQLite corrompe o arquivo quando dois
  computadores o abrem.

## Ligar um segundo caixa

No caixa principal:

1. Menu **Configuração > Caixas da loja (rede)**. Precisa da permissão de Máquinas.
2. Marque **Atender outros caixas da loja neste computador**. Se o Windows perguntar, permita o acesso na rede
   privada.
3. Clique em **Copiar código**. O código começa com `WILLCAIXA1-`. Quem tem o código entra no banco da loja:
   passe só para o computador da loja.

No outro computador:

1. Instale o mesmo programa, na mesma versão.
2. Na tela de entrada, clique em **Ligar a outro caixa da loja**.
3. Cole o código e escolha o número do caixa (de 2 a 99; o 1 é o principal).
4. O programa confere a ligação, grava e pede para abrir de novo. Na volta, a tela de entrada e o título da janela
   mostram o número do caixa.
5. Em **Máquinas e periféricos**, configure a impressora e a gaveta deste caixa.

O que já estava gravado no banco do computador adicional não vai para o principal. Fica guardado lá, sem uso.

## Dia a dia

- Cada caixa abre e fecha o seu turno, com o seu fundo de troco e a sua conferência.
- O cupom sai na impressora do caixa que fez a venda.
- A venda em andamento num caixa não aparece no outro e não segura a troca de turno do outro.
- Fiado e entrega são da loja: abertos num caixa, podem ser recebidos em outro.
- Relatórios de vendas e a reposição pelo giro já filtram por caixa.

## Problemas comuns

| O que aparece | O que fazer |
|---|---|
| "Sem ligação com o caixa principal" na abertura | Ligue o principal e abra o programa nele. Confira se os dois estão na mesma rede. **Tentar de novo**. |
| "O caixa principal recusou a ligação" | O código foi trocado. Copie o código atual em Caixas da loja e ligue de novo. |
| "O caixa N já é de outro computador" | Escolha outro número. Se trocou a máquina, selecione o caixa em Caixas da loja e use **Liberar o número selecionado**. |
| "O caixa principal está na versão X e este caixa na Y" | Instale a mesma versão nos dois. |
| O principal mudou de endereço na rede | O código leva o endereço e o nome do computador. Se nenhum dos dois responder, copie o código de novo. O ideal é fixar o IP do principal no roteador. |
| Um computador deve voltar a ter banco próprio | Tela de entrada > **desligar do caixa principal**. |

## Para quem mantém o código

- `src/database/rede.py`: protocolo, `ServidorBanco` (principal), `BancoRemoto`/`ConexaoRemota` (adicional),
  código de ligação e `ServicoRedeCaixas`. `BancoDados("pdv://host:porta")` devolve um `BancoRemoto`, então serviços
  e controllers abrem o banco do mesmo jeito.
- Cada ligação tem uma thread e uma conexão SQLite no principal. Transação, `BEGIN IMMEDIATE` e SAVEPOINT valem
  como no arquivo local. Ligação que cai com transação aberta: o principal desfaz; o adicional recusa qualquer
  comando até o `ROLLBACK` que encerra a transação do lado dele, para não gravar o resto fora da transação.
- A conversa é cifrada e autenticada (ChaCha20-Poly1305, chaves derivadas do código por HKDF). A porta padrão é
  47811 (`rede_caixas_porta`). A chave fica em `config.rede_caixas_chave`.
- O número do terminal do adicional vem do arquivo `caixa_adicional.json`, na pasta de dados, e não do `config`
  (`BancoRemoto.cfg`). O principal guarda quem é dono de cada número em `config.rede_caixas_terminais`.
- Esquema 47: `fila_impressao.terminal`. Cada caixa só imprime, lista e reenvia o que ele enfileirou.
- `CaixaController.balcao_aberto` e a trava de troca de turno filtram pelo terminal.
- Testes: `tests/test_rede_caixas.py` (inclui dois caixas vendendo o mesmo produto ao mesmo tempo e queda no meio
  da transação) e `tests/test_qt_rede_caixas.py`.

## O que falta

- Homologar com dois computadores Windows reais na mesma rede (firewall, Wi-Fi fraco, queda de energia do principal).
- Atualização automática nos caixas adicionais (hoje é instalação manual da mesma versão).
- Aviso na tela do adicional quando a ligação cai fora de uma operação (hoje o erro aparece na ação seguinte).
- O logotipo da loja é um arquivo no computador principal. No caixa adicional o cabeçalho e o cupom saem com o
  nome da loja em texto.
- Telas que guardam dados em memória (lista de produtos aberta, por exemplo) só veem a mudança feita no outro
  caixa quando são recarregadas.
