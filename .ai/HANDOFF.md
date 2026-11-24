# Handoff: fila da importação #4 parada depois do deploy

A Importação #4 da loja EA-SUPERACOES2 (E&A SUPERACOES 2) ficou em
"Aguardando o caixa" porque o deploy da #149 zerou a memória do Render. O aviso
que faz o caixa ocioso buscar a fila dura 90 s e só é visto se o token da loja
já estiver na memória. O último envio autenticado dessa loja foi 23:25 BRT,
antes do deploy das 23:26. As sondas seguintes não acharam a loja e o aviso
expirou. A retaguarda está ligada; há um caixa (1.14.21, "EeAsuperaçoes").

O texto "custo de 1 produto(s)" contava o lote, não as linhas. O comando 8 tem
67 linhas, todas com custo e nenhuma com quantidade. O comando 7 tem as 67
linhas de nome, preço e estoque. Nada foi reenviado nem apagado na produção.

## O que este PR muda

- `GET /v1/sync/pedido`: token ainda desconhecido olha a loja no banco uma vez
  e guarda o resultado. Token que não é de loja não volta ao banco por 10 min.
  `/health` continua sem abrir o banco.
- No boot, a nuvem rearma o aviso das lojas que ainda têm comando pendente.
- O resumo do segundo comando passa a dizer "custo de 67 produto(s)". O texto
  já gravado na #4 não muda.

## O que o dono faz agora, sem esperar o deploy

No caixa da loja, feche o turno (ou registre uma venda). O programa que já está
rodando manda na hora, porque a janela de 15 minutos desde o último envio
(23:25) já passou. O comando "56 novos, 11 atualizações" deve aplicar no
1.14.21. O comando de custo deve ser recusado de novo até instalar o programa
que contém a #149; depois, em Alterações enviadas, use Enviar de novo.

## Testes
`tests/test_ociosidade_neon.py` (primeira pergunta acha a loja; a segunda de um
token inválido não abre o banco) e `tests/test_importacao_painel.py` (resumo
conta as linhas).

## Fora
Não houve alteração de dados em produção, reenvio, merge nem deploy.
