# Handoff — 09/11/2026

## Repaginada dos painéis e instalação (branch `repaginada-paineis-instalacao`)

Pedido direto do dono; por isso `backend/painel_web/` e `backend/central_web/` (área do Antigravity)
foram mexidos aqui. As rotas e os ids que o `app.js` procura continuam os mesmos.

- **Janelas cortadas:** `tema.ajustar_janela` limita qualquer janela à área útil, rola o que não
  cabe e centraliza. O filtro `_AjusteDeJanelas` chama isso na primeira exibição de toda janela.
  Na plataforma `offscreen` (tela fictícia 800x800 dos testes) o filtro nasce desligado;
  `instalar_ajuste_de_janelas(app, forcar=True)` liga.
- **Configurações gerais:** cartões por assunto (grupo do `CAMPOS_CONFIG`), texto com quebra de
  linha, busca por opção, módulos primeiro e só rolagem vertical. A causa do corte era o texto
  longo empurrando os campos para fora.
- **Primeiros passos:** `controllers/primeiros_passos.py` + `ui_qt/primeiros_passos.py`. Abre na
  primeira entrada (no lugar do convite de cadastro, que virou um passo) e fica no menu
  Configuração. Inclui a escolha do tipo de negócio (`PerfilController`), que não existia no Qt.
  No Will Adega o passo do tipo não aparece (perfil fixo).
- **Central do fornecedor:** `saude_das_lojas` em `backend/central_fornecedor.py` devolve por loja
  último contato, versão mais antiga em uso, erros de 7 dias e chamados abertos (nada de vendas).
  A página ganhou fila "Precisa de você hoje", filtros, ordenação, cobrança pelo WhatsApp,
  planilha CSV e versões em uso.
- **Painel do dono:** identidade azul-noite/verde-água do PDV, cabeçalho com ícones, menu lateral
  e duas colunas no computador, meta do mês com projeção e botão de ocultar valores (os dois
  guardados no aparelho). `sw.js` foi para `painel-v9`.

Testes novos: `test_primeiros_passos.py`, `test_qt_janelas_cabem.py` e dois casos em
`test_central_fornecedor.py`.

## Custo e lucro (1.12.0, esquema 45)

O preço de custo editável é `produtos.custo_medio_cent`. O último preço da nota
continua em `ult_preco_cent`. A compra recalcula a média ponderada e grava
`custo_historico`. O lucro da venda segue o custo congelado em `itens_venda_custos`.
Só o nível 4 vê custo e lucro (`rel_custo`). Guia: `docs/CUSTO_LUCRO.md`.

## Pendências

- Antigravity: revisar o diff de `backend/central_fornecedor.py`, `central_web/` e `painel_web/`.
- Conferir em um caixa Windows real com escala de 125% que as janelas abrem inteiras.
- Meta do mês do painel fica só no aparelho do dono; levar para a nuvem se ele usar mais de um.
- Ideias não feitas: dono com várias lojas trocar de loja sem sair; aviso push no celular.
- Checkout do site de vendas ainda é só WhatsApp.
- Atualização automática segue sem os segredos `PDV_ATUALIZACAO_*`.
