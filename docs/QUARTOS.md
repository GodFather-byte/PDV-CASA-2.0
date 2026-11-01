# Controle de quartos

Conta o tempo de cada quarto. O cliente **paga antes, no caixa** (venda normal); o painel não lança nada na comanda.

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

Acesso: módulo `util_quartos` (nível 1, o caixa já abre). Na edição E&A Superações (adega) o módulo não existe.

## Operação

1. Cliente pagou no caixa → **Iniciar** no cartão do quarto → escolhe os blocos (1 = 30 min, 6 = 3h = R$ 540).
2. Verde: em uso. Amarelo: faltam 5 min (bipe no caixa e LED piscando no quarto).
3. Vermelho piscando: tempo esgotado. Bipe, a janela vem para a frente e a campainha toca, repetindo a cada minuto
   até **Liberar**.
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

Comandos aceitos pelo aparelho: `/ping`, `/alerta`, `/tocar`, `/parar`. Campainha de 220 V com relé: chame um
eletricista para a parte da tomada.

Código: regra em `src/controllers/quartos_controller.py`, envio em `src/hardware/campainha.py`, tela em
`src/ui_qt/quartos.py`, testes em `tests/test_quartos.py`.
