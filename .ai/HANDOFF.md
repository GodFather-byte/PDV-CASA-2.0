# Handoff: importar planilha no painel

O dono importa vários produtos pela aba **Produtos** do painel (`Importar planilha`), com a mesma planilha do caixa.
Na rede (`/painel/?grupo=CHAVE`), escolhe a loja e abre a importação dela. Nada é gravado na prévia: confirmar
enfileira `produtos.importar` e o caixa aplica na sincronização. O mesmo código de barras atualiza; não duplica.
A quantidade **substitui** o estoque (padrão) ou **soma**, à escolha na tela.

O assistente usa a mesma rota com a sessão do painel ou com um token `wpdv_...` gerado nessa tela (aparece uma vez;
no banco só fica o hash). `POST /v1/painel/importacao` sem `dry_run: false` só devolve a prévia.

## O que entrou
- Prévia: criados, atualizados, erros com motivo, aviso de dígito EAN-8/EAN-13.
- Texto colado, arquivo `.csv`/`.xlsx` e lista JSON. Modelo para baixar. Busca e exportação CSV/XLSX.
- Histórico e desfazer a última (o caixa restaura o preço/estoque e desativa o produto novo se ainda não foi vendido).
- Testes em `tests/test_importacao_painel.py`.

## Fora deste pedido
- Não houve merge nem deploy. Caixa antigo recusa `produtos.desfazer` até atualizar; a importação em si usa o comando
  que ele já conhece (`produtos.importar`). Somar e casar por código de barras também pedem o programa novo.
- A rota genérica de comandos continua sem deixar o dono mandar lote; só esta tela libera.

## Pendências
- Dono: `MP_ACCESS_TOKEN` (e `MP_WEBHOOK_SECRET`) no Render para o checkout do site; `ANTHROPIC_API_KEY`.
- Lojas desatualizadas: Resenha (1.14.9, ainda com o erro ao sair), Império, EA Superações 1/2/3.
