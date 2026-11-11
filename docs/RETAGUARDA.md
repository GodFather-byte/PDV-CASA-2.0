# Retaguarda na nuvem

A retaguarda é a parte do sistema que administra a loja sem estar no caixa: cadastros, preços, estoque,
contas e configurações. Ela fica na nuvem, em `/retaguarda/`, e vale para o WillPDV (boate e bar), o
Will Adega e o Will Restaurante. Quem usa:

- **o dono**, pelo painel do dono (aba Produtos, botão **Abrir a retaguarda**), nas lojas dele;
- **o fornecedor**, pela central (ficha da loja, aba Suporte, **Abrir a retaguarda da loja**), em qualquer loja.

## Como funciona

1. O caixa sobe um **espelho** dos cadastros, das configurações e do financeiro. É o que a página mostra.
2. Cada alteração feita na página vira um **comando** na fila da loja, com a situação *Aguardando o caixa*.
3. Na sincronização seguinte o caixa busca os comandos e aplica **pelas mesmas regras das telas do PDV**.
   O que a tela recusaria é recusado, com a mesma mensagem.
4. O caixa responde *Aplicada* ou *Recusada pelo caixa* (com o motivo) e sobe o espelho atualizado.

Nada muda na loja na hora: o prazo é o da sincronização (em geral até 15 minutos com a loja aberta e a
sincronização automática ligada). Com o caixa desligado, a alteração espera na fila; dá para cancelar
enquanto o caixa não buscou. Vale a alteração que chega por último, na retaguarda ou no caixa.

## Ligar (uma vez, no caixa)

Em **Configurações > Nuvem**, com o **Painel do dono** já ligado, marque **Retaguarda na nuvem**. Ela nasce
desligada: enquanto estiver assim, nada sobe e nenhuma alteração de longe é aceita (o caixa recusa todas).
Desligar no caixa é também o jeito de cortar o acesso remoto.

## O que dá para fazer

| Área | O quê |
|---|---|
| Produtos e estoque | Cadastrar, alterar (preço, custo, promoções, campos da adega, fiscal), desativar e excluir produtos; grupos, subgrupos, unidades, alíquotas, observações e setores de impressão. Na ficha do produto, **Movimentar estoque**: entrada, saída, contagem, quebra e descarte. |
| Pessoas | Operadores (com nível e senha), cargos, clientes, fornecedores, garotas e bairros de entrega. |
| Financeiro | Formas de pagamento, plano de contas e sub planos; **Contas a pagar** (lançar, quitar, desfazer a quitação e excluir); **Caderneta** (quem deve, só consulta). |
| Loja | Configurações de aparência, caixa, estoque, impressão, mesas e módulos. |
| Alterações enviadas | A fila e o histórico de 90 dias: quem pediu, quando, e a resposta do caixa. |

Só aparece o que a casa usa: cadastro de módulo desligado (garotas num restaurante, por exemplo) não sobe.

## O que não dá (de propósito)

- **Venda, caixa e turno** continuam só no PDV.
- **Endereço e token da nuvem, e-mail, pastas de backup e integrações** só mudam no próprio caixa.
- **Receber caderneta** é no caixa (entra no turno).
- **Nota de compra** segue o caminho das Notas do dono (`docs/PAINEL_DONO.md`): o XML sobe pelo painel e o
  gerente confere no caixa.
- Ver ou clicar na tela do caixa ao vivo: use um programa de acesso remoto (RustDesk, AnyDesk).

## Segurança

- Senha de operador, token e segredo **não sobem** no espelho. A senha digitada para um operador novo fica
  na fila só até o caixa buscar; depois a nuvem a apaga do comando, e a página nunca a mostra.
- O dono só alcança as lojas da sessão dele; o fornecedor entra pela sessão da central, e cada alteração
  pedida por ele fica na auditoria da central (ação `retaguarda`).
- No caixa, cada comando fica em `retaguarda_comandos` (quem pediu, quando, resultado) e as mudanças nos
  cadastros passam pela auditoria normal do PDV. Lançamentos de estoque e contas saem em nome do primeiro
  gerente ativo.
- Limites: 300 alterações esperando por loja, 64 KiB por alteração, 6 MiB por seção do espelho.

## Onde está no código

| Parte | Arquivo |
|---|---|
| Espelho e aplicação dos comandos no caixa | `src/controllers/retaguarda_controller.py` |
| Rede do caixa (sobe o que mudou, busca e confirma) | `src/sync/retaguarda.py`; gancho em `sincronizador.py` e `painel_envio.py` |
| Nuvem (espelho, fila, rotas do dono, do fornecedor e do caixa) | `backend/retaguarda.py` |
| Página | `backend/retaguarda_web/` |
| Testes | `tests/test_retaguarda.py` |

## Rotas da API

| Rota | Quem | O quê |
|---|---|---|
| `GET /v1/painel/retaguarda` | sessão do dono | esquema das telas, seções do espelho e quantas alterações esperam |
| `GET /v1/painel/retaguarda/cadastro/{entidade}?busca=&pagina=&inativos=` | sessão do dono | linhas do cadastro (100 por página) e as alterações pendentes dele |
| `GET /v1/painel/retaguarda/financeiro` | sessão do dono | contas e devedores |
| `GET /v1/painel/retaguarda/comandos` | sessão do dono | fila e histórico |
| `POST /v1/painel/retaguarda/comandos` | sessão do dono | pede uma alteração: `{tipo, dados, resumo}` |
| `DELETE /v1/painel/retaguarda/comandos/{id}` | sessão do dono | cancela, se o caixa ainda não buscou |
| as mesmas em `/v1/fornecedor/lojas/{chave}/retaguarda...` | sessão da central | o fornecedor, em qualquer loja (auditado) |
| `POST /v1/retaguarda/espelho` | token da loja | o caixa sobe uma seção do espelho |
| `GET /v1/retaguarda/comandos` | token da loja | o caixa busca as alterações pendentes (20 por vez) |
| `POST /v1/retaguarda/confirmar` | token da loja | o caixa conta o resultado de cada uma |

Tipos de comando: `cadastro.salvar`, `cadastro.excluir`, `estoque.movimento`, `config.salvar`,
`conta.incluir`, `conta.alterar`, `conta.quitar`, `conta.desfazer`, `conta.excluir`. Dinheiro em centavos
inteiros, quantidade em número, sim/não em 0 ou 1, data em `YYYY-MM-DD`.
