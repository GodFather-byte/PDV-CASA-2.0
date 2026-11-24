# Handoff: custo da importação e fila rápida

Importação pedida pelo painel com coluna de custo era recusada pelo caixa com
"Custo e lucro só aparecem para o gerente" quando quem estava logado não era gerente
(ou ninguém estava). O lote inteiro caía, inclusive os produtos sem problema de custo.
O custo agora entra com autoridade de gerente, só nessa aplicação da retaguarda. Na tela
do caixa, operador continua sem ver nem gravar custo.

Planilha com custo vira dois comandos: o primeiro grava nome, preço e estoque; o segundo
só o custo, sem repetir a quantidade. Caixa antigo aplica o primeiro e pode recusar o
segundo. Em Alterações enviadas, **Enviar de novo** recoloca o comando recusado na fila.

A fila não espera os 15 minutos: ao gravar o comando a nuvem toca o mesmo aviso em memória
que o botão do celular (`GET /v1/sync/pedido`, sem abrir o banco). Caixa já instalado, com
o envio para a nuvem ligado, busca em até cerca de 30 s. Programa atualizado pergunta a
cada 5 s com a retaguarda ligada.

## Testes
`tests/test_importacao_painel.py`: custo com operador de caixa logado, separação do custo,
aviso que acorda o caixa, reenvio só do que foi recusado.

## Fora
Não houve merge nem deploy. Outro agente mexe nas telas grandes do painel; este pedido não.

## Pendências
- Dono: `MP_ACCESS_TOKEN` (e `MP_WEBHOOK_SECRET`) no Render; `ANTHROPIC_API_KEY`.
- Lojas desatualizadas: Resenha (1.14.9), Império, EA Superações 1/2/3. O custo da
  importação e a pergunta a cada 5 s pedem o programa novo. O aviso de meio minuto e o
  reenvio já valem no programa que está na loja.
