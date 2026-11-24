# Will Hotel

Edição do WillPDV para hotel e pousada, com diárias e uso por horas. Mesmo código, outra marca e outra pasta de dados
(`%LOCALAPPDATA%\WILL-HOTEL`).

- Código-fonte: `python -m src.app --edicao willhotel`
- Executável e instalador: `python build_pdv.py --edicao willhotel` (instalador `instalador/WillHotel.iss`)
- Publicação: Actions > **Will Hotel** > Run workflow na main (como o Will Restaurante)
- Regras: `src/controllers/hotel_controller.py`. Tela: `src/ui_qt/hotel.py`. Testes: `tests/test_hotel.py` e
  `tests/test_qt_hotel.py`.

## Primeira configuração (no hotel)

1. Menu **Operação > Hotel • recepção**, aba **Quartos e tarifas** (precisa do nível de Configurações):
   - **Tipos de quarto**: nome, pessoas, preço da diária e se o café está incluso. Cada tipo cria o produto
     `DIÁRIA <TIPO>` no grupo HOSPEDAGEM: é o que o caixa cobra.
   - **Quartos**: número, tipo e andar.
   - **Períodos** (uso por horas): nome, duração e preço (ex.: 2 horas, 4 horas, Pernoite 12 h).
   - **Serviços**: café da manhã avulso (por pessoa) e hora adicional do período.
2. **Configurações gerais > Hotel**: horários de check-in (14:00) e check-out (12:00), tolerância (15 min), aviso do
   período (15 min) e o número da primeira conta (500).

## No dia a dia

Depois da entrada, o Will Hotel abre direto a **Recepção do hotel** em tela cheia, inclusive para quem só faz caixa.
O menu mostra só o que é de hotel: cozinha, promoções, retornáveis, portaria, quartos por tempo, composição, devoluções e
contagem ficam escondidos. O caixa continua existindo para três coisas: abrir e fechar o turno, a sangria e receber a
conta (cupom e NFC-e). Na aba Hoje, a linha "Caixa" mostra se o turno está aberto e tem o botão
**Caixa: turno e recebimentos**. **Receber a conta** abre o caixa já na conta do hóspede.

- **Nova reserva**: diária (datas) ou período (hora). Só aparecem quartos livres que cabem as pessoas; os prontos vêm
  primeiro. O hóspede cadastrado é opcional na reserva.
- **Check-in**: exige o titular maior de idade com a ficha completa (documento e nascimento; brasileiro adulto, também
  o CPF). Acompanhante menor de idade pede o responsável e o parentesco. Quarto sujo pergunta antes; em manutenção, não
  entra. O check-in **abre a conta** da estadia no caixa: uma comanda a partir da 500, com o nome `Q101 Maria...`.
- **Check-in sem reserva**: o mesmo, para quem chega no balcão (se desistir no meio, a reserva é cancelada).
- **Consumo e pagamento**: no **caixa**, chamando a comanda da conta (botão *Conta no caixa*). Dá para receber
  adiantado; o adiantamento fica no turno em que entrou.
- **Café avulso**: lança na conta quantas pessoas tomaram. O café incluso não se cobra.
- **Lançar diárias vencidas**: põe na conta as noites já dormidas de todas as estadias (útil em estadia longa).
- **Check-out**: lança as diárias que faltam (no mínimo uma), avisa o atraso depois do horário e só cobra a diária a
  mais se marcar; no período, cobra a hora adicional por hora começada depois da tolerância. O quarto fica **sujo**.
  Em seguida pergunta se abre a conta no caixa para receber.
- **Prorrogar / antecipar**, **trocar de quarto**, **cancelar** (com motivo) e **não compareceu**.
- **Mapa de reservas**: 14 noites por tela; dois cliques num dia livre reservam; num bloco, mostram a estadia.
- **Governança**: limpo, sujo, arrumando, manutenção (com o motivo; sai da venda).
- **Relatórios**: ocupação por noite, diária média (receita das diárias ÷ noites vendidas), RevPAR (receita das
  diárias ÷ noites disponíveis), períodos, café da manhã do dia e **Exportar fichas (FNRH)** em planilha.

## Obrigações do governo (o sistema não envia nada)

- **FNRH Digital** (Ficha Nacional de Registro de Hóspedes): obrigatória desde 20/04/2026. O hotel registra no site do
  Ministério do Turismo (conta gov.br e Cadastur). O Will Hotel guarda os mesmos dados e exporta a planilha para
  conferir ou digitar. A integração automática pela API do governo fica para quando o cliente pedir: precisa do
  Cadastur e da chave da API gerada pelo hotel.
- **Nota fiscal**: hospedagem é serviço, com **NFS-e** (ISS da prefeitura), não NFC-e. Fica com o contador do hotel.
  Deixe a NFC-e desligada para as diárias.

## Limites conhecidos

- Sem channel manager (Booking, Airbnb) e sem motor de reservas no site: a venda é direta.
- Sem sinal de reserva antes do check-in: o pagamento adiantado é na conta, a partir do check-in.
- A receita das diárias conta no dia em que a diária entra na conta (lançamento), não na noite dormida.
- Os dados dos hóspedes ficam só no computador da loja (não sobem para a nuvem nem para o painel do dono).
