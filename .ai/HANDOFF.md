# Handoff de 23/11/2026: site com Will Hotel e Will Variedades

O site público (`/site/`) mostra as cinco versões. O preço do checkout continua no servidor.

## O que entrou
- **Will Hotel** no site: card em Programas e em Planos, FAQ, termos, meta e JSON-LD.
  Planos `hotel-mensal` R$ 199,99 e `hotel-anual` R$ 1.999,90 (12 meses pelo preço de 10).
  Instalador e teste grátis (`willhotel`) no formulário.
- **Will Variedades** no mesmo formato das outras versões: descrição, preço, baixar instalador e
  assinar mensal/anual. Entra no teste grátis (`willvariedades`). Preços: `variedades-mensal`
  R$ 159,99 e `variedades-anual` R$ 1.599,90.
- Grade `.edicoes.cinco`: 5 colunas a partir de 1200 px, 3+2 no meio, 2 colunas com o quinto card
  em largura cheia no tablet, 1 coluna no celular.

## Edições já na main
- Will Hotel: diárias e uso por horas. Guia `docs/WILL_HOTEL.md`. Sem channel manager, sem sinal
  antes do check-in, sem envio automático da FNRH nem NFS-e. Dados dos hóspedes só no computador.
- Will Variedades, etapa 1: balcão, caderneta, atacado, catálogo e etiqueta. Guia
  `docs/WILL_VARIEDADES.md`. Etapa 2 não começada: garantia e número de série/IMEI na venda.

## Próximo
- Nada pendente deste pedido do site. Não houve merge nem deploy.

## Pendências
- Dono: `MP_ACCESS_TOKEN` (e `MP_WEBHOOK_SECRET`) no Render para o checkout do site; `ANTHROPIC_API_KEY`.
- Lojas desatualizadas: Resenha (1.14.9, ainda com o erro ao sair), Império, EA Superações 1/2/3.
