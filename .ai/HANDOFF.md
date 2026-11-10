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

- **Papel econômico:** `src/core/fita.py` (`compactar`) tira molduras de três linhas, linhas em
  branco e separadores repetidos na hora do envio (`ImpressaoController.enviar`); os textos
  montados por `cupom()` e `fechamento()` não mudaram. Na térmica, `ESC 3 26` aproxima as linhas
  e `ESC 2` volta ao padrão antes do corte. Chaves `papel_economico` e `papel_linhas_juntas`
  (as duas nascem ligadas; Configurações > Parâmetros > Impressão). Cupom de exemplo: 28 para 23
  linhas; fechamento: 96 para 79, fora os cerca de 13% do espaço entre linhas.
- **Logo no caixa:** `ui_qt/marca_dagua.py` desenha o logotipo como papel de parede (7% de
  opacidade, por cima de tudo, sem receber clique) e o topo mostra o logo num selo branco maior.
  Chave `caixa_papel_de_parede` (ligada; Configurações > Parâmetros > Aparência).

Testes novos: `test_primeiros_passos.py`, `test_qt_janelas_cabem.py` e dois casos em
`test_central_fornecedor.py`, `test_fita_economica.py` e `test_qt_marca_dagua.py`.

## Custo e lucro (1.12.0, esquema 45)

O preço de custo editável é `produtos.custo_medio_cent`. O último preço da nota
continua em `ult_preco_cent`. A compra recalcula a média ponderada e grava
`custo_historico`. O lucro da venda segue o custo congelado em `itens_venda_custos`.
Só o nível 4 vê custo e lucro (`rel_custo`). Guia: `docs/CUSTO_LUCRO.md`.

## Pendências

- Antigravity: revisar o diff de `backend/central_fornecedor.py`, `central_web/` e `painel_web/`.
- Imprimir um cupom e um fechamento numa térmica de verdade: o espaço entre linhas (`ESC 3 26`) não
  foi testado em impressora física. Se alguma marca imprimir linhas encavaladas ou mais espaçadas,
  desligar "Linhas mais juntas".
- Conferir em um caixa Windows real com escala de 125% que as janelas abrem inteiras.
- Meta do mês do painel fica só no aparelho do dono; levar para a nuvem se ele usar mais de um.
- Ideias não feitas: dono com várias lojas trocar de loja sem sair; aviso push no celular.
- Checkout do site de vendas ainda é só WhatsApp.
- Atualização automática segue sem os segredos `PDV_ATUALIZACAO_*`.
