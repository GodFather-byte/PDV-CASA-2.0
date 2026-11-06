# Controle de quartos

Conta o tempo de cada quarto. O cliente **paga antes, no caixa** (venda normal). O painel registra os shows a pagar
na comanda da profissional identificada, separados do consumo do cliente.

## Jeito mais rápido: o quarto vai na comanda do cliente

No campo do produto do caixa, na conta do cliente, digite só **o número da garota**: **`113`** + Enter. Pronto: o
sistema escolhe o quarto na hora do pagamento. Para forçar um quarto, **`113Q3`** (garota 113 no quarto 3). Vale a
regra **a partir de 100** (`quartos_garota_minimo`): número de garota cadastrada de 100 em diante é sempre a garota, mesmo
que algum produto tenha o mesmo código (lance esse produto pelo leitor ou pelo nome); abaixo de 100 é sempre produto.
Dentro da própria comanda da garota, o número dela não vira quarto. **Repetir o número soma meia hora na mesma linha**:
`113` e depois `113` = 1h (2 shows para ela), e a tela mostra "agora 1h". Para abrir a comanda 113, use o campo **Número** (não o do produto). Entra o item **QUARTO 30 min** (o show, no
valor do bloco, por exemplo R$ 90) já ligado à garota. A **quantidade** são os blocos: `2*113Q3` (ou 2 na quantidade)
= 1h. (`G113` / `G113Q3` também funcionam.) Lançar o produto do quarto pelo código ou
pelo nome também funciona: o caixa pergunta o número da garota (obrigatório). Bebidas e o resto vão na mesma conta.

**Ao pagar a conta**, o sistema faz sozinho:
- **Garota já num quarto** (cliente pagou mais tempo): soma no quarto dela e conta mais show.
- **Senão**: inicia no quarto pedido (`Q3`) ou no **livre há mais tempo** (reveza os quartos e dá tempo de arrumar), e
  os shows vão para a comanda dela (acerto), como no início manual.
- **Nenhum quarto livre**: ela fica **na fila** com o tempo já pago; quando um quarto for liberado, o caixa pergunta se
  começa ali.
- Uma janela mostra **qual chave entregar** ("QUARTO 2 → ANA (25) · 1h. Entregue a chave do 2.").

Nada começa antes do pagamento. **Cancelar o cupom** tira o tempo e os shows que ele gerou (recusa se o show já foi
pago no acerto dela). O produto do quarto é criado sozinho na primeira vez (preço = `quartos_valor_bloco`); dá para
mudar nome e preço no cadastro. O início manual pelos cartões (Q3 no campo Número) continua igual.

## Shows e acerto da profissional

Ao iniciar com **Q3 + Enter**, informe o código cadastrado da profissional, escolha o tempo e confirme.
Cada 30 minutos contratados somam **1 show** imediatamente: 1h = 2 shows, 1h30 = 3 shows.
**+ Tempo** soma apenas o acréscimo; liberar o quarto ou deixar o relógio passar não gera shows adicionais.
Com blocos configurados diferentes de 30 minutos, a contagem considera as meias horas completas do tempo total contratado.

A comanda e a lista de comissões mostram a quantidade de shows dos quartos separada dos valores de comissão.
No acerto, com Quartos ligado, **Shows dos quartos (automáticos)** é uma contagem protegida. Use o campo separado
**Shows manuais / anteriores** para os shows feitos antes da atualização ou ainda não registrados pelos quartos.
Informe apenas shows que não estejam nos automáticos e não tenham sido pagos. A tela mostra
**automáticos + manuais = total de shows**, inclusive quando não há automáticos. Escolha **R$ 50 ou R$ 60
por show** (tarifas configuradas em `show_valores`). O total é comissão + shows × tarifa, descontado o vale;
a parte em Pix e a parte em dinheiro continuam separadas. Os shows pagos ficam vinculados ao acerto e não retornam
como pendentes ao reabrir o programa. Tempo acrescentado depois de um acerto gera nova pendência.

A integração vale para lançamentos novos. A atualização do banco não transforma históricos antigos em shows a pagar,
pois esses tempos já podem ter sido acertados manualmente.

## Ligar

Configurações > Módulos:

| Chave | Padrão | O que faz |
|---|---|---|
| `usar_quartos` | N | Liga o módulo e o botão **Quartos (tempo)** no menu |
| `quartos_qtd` | 7 | Quantidade de quartos (1 a 50) |
| `quartos_minutos_bloco` | 30 | Minutos de cada bloco de tempo |
| `quartos_valor_bloco` | 90 | Valor do bloco em R$ (só informativo na tela) |
| `quartos_alerta_min` | 5 | Minutos antes do fim para o aviso amarelo |
| `quartos_campainhas` | vazio | `quarto=endereço` separados por `;` (ex.: `1=192.168.0.51; 2=192.168.0.52`) |

Acesso: módulo `util_quartos` (nível 1, o caixa já abre). Na edição Will Adega (adega) o módulo não existe.

## Na tela do caixa

Com o módulo ligado, aparece uma linha **Quartos** embaixo dos produtos e do pagamento (Total e Troco ficam lado a
lado para sobrar altura; cabe em 1366×768): um cartão por quarto no mesmo desenho das comandas (verde livre; azul ocupado; amarelo acabando; vermelho com a borda piscando quando esgota,
mostrando quanto passou, ex.: +02:00).

O operador inicia o tempo depois que o cliente paga:
- clique no quarto livre → escolhe o tempo (30 min, 1h, 2h, 3h…) → Enter; ou
- digite **Q3** no campo *Número* (onde chama a comanda) e Enter → mesma escolha para o quarto 3.

No quarto ocupado, o clique (ou Q3) mostra **+ Tempo** e **Liberar**. **Painel** abre os cartões grandes. Os cartões não
tiram o foco do código do produto. Os avisos são os mesmos no caixa e no painel e não tocam em dobro.

## Operação

1. Cliente pagou no caixa → **Iniciar** no cartão do quarto → escolhe os blocos (1 = 30 min, 6 = 3h = R$ 540).
2. Azul: em uso. Amarelo: faltam 5 min — aparece um aviso grande no alto do caixa ("QUARTO 3 — faltam 5 minutos"),
   com som no caixa e, se houver campainha, um toque curto e o LED piscando no quarto. O aviso não trava o caixa: OK fecha.
3. Vermelho piscando: tempo esgotado. Aviso vermelho na tela, som diferente, a janela vem para a frente e a campainha
   toca, repetindo a cada minuto até **Liberar**.
4. Cliente pagou mais tempo → **+ Tempo** (soma ao fim previsto). **Liberar** devolve o quarto a livre e desliga a
   campainha.

O início fica gravado no banco (`quartos_uso`) e o restante é calculado pelo relógio: fechar o PDV ou faltar luz não
perde a contagem. O valor do bloco é guardado no início, então mudar o preço não altera quem já está no quarto.
O rodapé mostra a noite (virada em `virada_dia_hora`): entradas, tempo, valor e quantos passaram do tempo.

## Campainha no quarto (opcional)

Um ESP32 por quarto (cerca de R$ 60–80 com buzzer ou relé, LED e fonte USB), no Wi-Fi 2.4 GHz da casa, com IP fixo
reservado no roteador. Funciona sem internet. O cartão mostra 🔔 ok / 🔕 off (o PDV testa a cada 30 s).

1. Instale o Thonny e grave o MicroPython no ESP32.
2. Abra `tools/esp32_campainha/main.py`, ajuste `SSID`, `SENHA`, `IP` (um por quarto), `GATEWAY` e os pinos.
3. Salve no ESP32 com o nome `main.py`. Ele liga sozinho na tomada.
4. Em Configurações > Módulos, preencha `quartos_campainhas` com o número de cada quarto e o IP do aparelho.

Comandos aceitos pelo aparelho: `/ping`, `/alerta` (1 toque curto + LED; `TOQUES_AVISO`), `/tocar`, `/parar`. Campainha de 220 V com relé: chame um
eletricista para a parte da tomada.

Código: regra em `src/controllers/quartos_controller.py`, envio em `src/hardware/campainha.py`, tela em
`src/ui_qt/quartos.py`, testes em `tests/test_quartos.py`.

## Identificação por comandas e histórico

Na entrada, informe a comanda do cliente (ex.: 045) e o código da profissional (ex.: 167). São códigos de 1 a 6 dígitos e zeros à esquerda são preservados. Não há nova cobrança ou impressão. O painel exibe os códigos e oferece Histórico de quartos, pesquisável por qualquer código, com entrada, saída e operador. O sistema impede que a mesma profissional seja registrada em dois quartos simultaneamente. Usos antigos continuam no histórico sem códigos, pois não é possível reconstruí-los. O cronômetro e os avisos existentes permanecem.
