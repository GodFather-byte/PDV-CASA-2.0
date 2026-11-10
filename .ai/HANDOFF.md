# Handoff — 10/11/2026

## README comercial

A página inicial do repositório é o texto para o dono do negócio. O guia técnico
que estava no README foi para `docs/DESENVOLVIMENTO.md`. O número de WhatsApp e o
valor da mensalidade ficaram de propósito como placeholder.

## Repaginada dos painéis e instalação

Pedido direto do dono; por isso `backend/painel_web/` e `backend/central_web/` (área do Antigravity)
foram mexidos. As rotas e os ids que o `app.js` procura continuam os mesmos.

- **Janelas cortadas:** `tema.ajustar_janela` limita qualquer janela à área útil, rola o que não
  cabe e centraliza. `instalar_ajuste_de_janelas` liga isso ao sinal `focusWindowChanged`: cada
  janela é ajustada uma vez, quando recebe o foco. Não usar filtro de eventos global em Python:
  ele roda a cada evento do caixa e derrubou o processo no encerramento dos testes (CI).
  Na plataforma `offscreen` (tela fictícia 800x800 dos testes) fica desligado; `forcar=True` liga.
- **Saída do processo:** `tema.encerrar_janelas_restantes` (registrado no `atexit`) destrói as
  janelas que sobraram antes de o Python finalizar. Alguns testes antigos deixam
  `JanelaConfiguracoes` e `JanelaPrincipal` vivas; com o formulário novo isso derrubava o processo
  na saída (segmentation fault depois de todos os testes passarem).
- **Configurações gerais:** cartões por assunto (grupo do `CAMPOS_CONFIG`), texto com quebra de
  linha, busca por opção, módulos primeiro e só rolagem vertical.
- **Primeiros passos:** `controllers/primeiros_passos.py` + `ui_qt/primeiros_passos.py`. Abre na
  primeira entrada e fica no menu Configuração. Inclui a escolha do tipo de negócio. No Will Adega
  o passo do tipo não aparece (perfil fixo).
- **Central do fornecedor:** `saude_das_lojas` devolve por loja último contato, versão mais antiga
  em uso, erros de 7 dias e chamados abertos (nada de vendas). A página ganhou a fila "Precisa de
  você hoje", filtros, ordenação, cobrança pelo WhatsApp, planilha CSV e versões em uso.
- **Painel do dono:** identidade azul-noite/verde-água, menu lateral, meta do mês com projeção e
  botão de ocultar valores (os dois guardados no aparelho). `sw.js` está em `painel-v9`.
- **Papel econômico:** `src/core/fita.py` enxuga o cupom na hora do envio. Chaves `papel_economico`
  e `papel_linhas_juntas` nascem ligadas.
- **Logo no caixa:** `ui_qt/marca_dagua.py` desenha o logotipo da casa como papel de parede. Chave
  `caixa_papel_de_parede` (ligada).

## Custo e lucro (1.12.0, esquema 46)

O preço de custo editável é `produtos.custo_medio_cent`. A compra recalcula a média e grava
`custo_historico`. O painel do dono tem a aba Relatórios (`GET /v1/painel/lucro`). A NF-e entra
por XML ou ZIP (`nfe_vinculos`). Sem download na SEFAZ. Guia: `docs/CUSTO_LUCRO.md`.

## Pendências

- Trocar o WhatsApp e a mensalidade do README pelos dados comerciais reais.
- Fechar as janelas que os testes antigos deixam abertas (hoje a rede de proteção do `atexit` cobre).
- Antigravity: revisar o diff de `backend/central_fornecedor.py`, `central_web/` e `painel_web/`.
- Imprimir um cupom e um fechamento numa térmica de verdade: o espaço entre linhas (`ESC 3 26`) não
  foi testado em impressora física. Se alguma marca imprimir linhas encavaladas ou mais espaçadas,
  desligar "Linhas mais juntas".
- Conferir em um caixa Windows real com escala de 125% que as janelas abrem inteiras.
- Meta do mês do painel fica só no aparelho do dono; levar para a nuvem se ele usar mais de um.
- Ideias não feitas: dono com várias lojas trocar de loja sem sair; aviso push no celular.
- Checkout do site de vendas ainda é só WhatsApp.
- Atualização automática segue sem os segredos `PDV_ATUALIZACAO_*`.
