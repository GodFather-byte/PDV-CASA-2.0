# Handoff de 23/11/2026: Will Hotel (branch `will-hotel`)

Edição nova para hotel e pousada: diárias e uso por horas. Guia em `docs/WILL_HOTEL.md`.

## O que entrou
- Banco v58 (tabelas aditivas `hotel_*`): tipos de quarto (a diária é um produto do grupo HOSPEDAGEM), quartos (UH) com
  a arrumação, períodos, hóspedes (campos da FNRH), estadias e acompanhantes.
- `src/controllers/hotel_controller.py`: reservas sem conflito (intervalo de datas e horas), check-in que confere a ficha
  e abre a conta como comanda (a partir de `hotel_conta_inicio`, 500), diárias vencidas, café avulso, check-out com
  atraso (diária extra só se pedir) e hora adicional do período, cancelar, não compareceu, trocar de quarto,
  prorrogar, painel do dia, mapa, ocupação/diária média/RevPAR, café do dia e exportação das fichas (CSV).
- `src/ui_qt/hotel.py`: menu "Hotel • recepção" com abas Hoje, Mapa, Reservas, Hóspedes, Governança, Relatórios e
  Quartos e tarifas (esta só com `cfg_hotel`). Cabe em 1366x768 sem corte.
- Edição `willhotel` (perfil `hotel`, fixas e padrões em `core/edicao.py`; o botão do hotel some nas outras edições),
  `instalador/WillHotel.iss` (AppId próprio), workflow `will-hotel.yml`, canal de atualização `willhotel` e link do
  instalador na central.

## Limites
- Sem channel manager, sem sinal antes do check-in, sem envio automático da FNRH nem NFS-e (o cliente faz à parte).
- Dados dos hóspedes só no computador da loja.

## Marca da loja (branch `marca-da-loja`)
- Menu principal: logotipo e nome de Dados da Loja no alto (`JanelaPrincipal.atualizar_marca`), "WillPDV · WB Sistemas"
  pequeno no rodapé; título da janela começa pelo nome da loja. Sem loja cadastrada fica a marca da edição.
- Tela de entrada: logotipo da loja no alto da capa, nome grande e o crédito do programa embaixo.

## Próximo
- Pedido do dono (23/11): ver o PR #118 (Will Variedades) e terminar.

## Pendências
- Dono: `MP_ACCESS_TOKEN` (e `MP_WEBHOOK_SECRET`) no Render para o checkout do site; `ANTHROPIC_API_KEY`.
- Lojas desatualizadas: Resenha (1.14.9, ainda com o erro ao sair), Império, EA Superações 1/2/3.
