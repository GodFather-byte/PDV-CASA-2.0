# Handoff — Notas de compra do dono (10/11/2026)

## Branch e escopo
Branch `notas-do-dono`, base main fab49a4 (1.14.0 candidata, esquema 49 -> 50).
Pedido do dono: subir a nota de compra pelo painel e ela aparecer no PDV da adega.
Decisão: a nota chega **pendente** e só entra no estoque depois da conferência no caixa.

## Implementação
- Nuvem `backend/notas_dono.py` (tabela `painel_notas`): o dono envia o XML em base64 (`POST /v1/painel/notas`),
  lista e exclui; o caixa busca (`GET /v1/notas-dono`, 5 por vez) e confirma (`POST /v1/notas-dono/confirmar`).
  Situações: pendente -> baixada -> lancada | recusada. O XML sai da nuvem na situação final. Só NF-e modelo 55,
  até 2 MiB, sem DTD/entidade; 40 pendentes por loja. A nuvem não lança estoque nem consulta a SEFAZ.
- `backend/painel.py`: a resposta de `/v1/painel/envio` ganha `notas_pendentes` só quando há nota (contrato
  antigo intacto). `backend/main.py` instala o módulo.
- PDV: `src/sync/notas_dono.py` busca só quando o envio do painel avisou (chave `notas_dono_na_nuvem`) ou há
  desfecho a contar; `Sincronizador._buscar_notas` chama a cada rodada. Tabela local `notas_dono` (v50, aditiva).
  `controllers/notas_dono_controller.py` dá a prévia pela `ImportacaoNFe.analisar_bytes` e registra o desfecho;
  nota cuja chave já está em `importacoes_nfe` sai da fila sozinha.
- Telas: `ui_qt/notas_dono.py` (fila, Conferir e lançar, Recusar, Buscar agora); botão em Lançamentos de
  estoque e botão "Notas do dono (N)" no menu, visível só com nota esperando. Conferir exige `lanc_estoque` e
  `rel_custo`, como a importação pelo arquivo.
- Painel `/painel/`: bloco "Notas de compra" na aba Produtos. `sw.js` em `painel-v10`.

## Validação e limites
- `tests/test_notas_dono.py` (19 casos: nuvem, caixa ponta a ponta com TestClient, tela Qt).
- Conferido por captura: painel no celular (envio de 2 XML e 1 arquivo inválido) e fila no PDV.
- Não testado em loja: XML real de fornecedor grande, vários caixas na mesma loja (a busca roda onde roda a
  sincronização do painel) e a publicação da nuvem.
- A nuvem precisa ser publicada antes dos caixas: caixa novo com nuvem antiga só não recebe o aviso.

## Pendências
- Antigravity: revisar `backend/notas_dono.py` e a linha nova em `backend/painel.py` e `sincronizador.py`.
- Avisar o dono por push quando o caixa lançar ou recusar (hoje ele vê ao abrir a aba Produtos).
- Foto ou PDF do DANFE não vira entrada: só o XML.
- Homologação do Will Restaurante (tablet/TV, impressora, dois Windows, escala 125%) continua pendente.
- Imprimir cupom e fechamento numa térmica de verdade (espaço entre linhas `ESC 3 26`).
