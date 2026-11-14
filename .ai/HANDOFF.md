# Handoff — atualização com loja piloto + app da rede (13/11/2026)

## Agora (branch `drinks-garotas`, entra na 1.14.7, esquema 54)

- Consumo da garota (pedido do dono, para todas as boates): o código numérico que o dono escolhe em Configurações >
  Caixa (config `codigo_consumo_garota`, vazio de fábrica = desligado, só números; em CODIGOS_ESPECIAIS) lança na comanda da garota a bebida que ela consumiu, com o preço digitado
  (dose da casa, sem estoque, fora do faturamento). Linha VERMELHA na comanda ("CONSUMO (descontar)"), diferente da
  comissão (rosa). Tabela `consumos_garotas` (pendente/descontado/cancelado); `acertos_garotas.consumo_cent`.
- Acerto (`ComissaoController.pagar`): desconta sozinho todo o consumo pendente; a saída do caixa é só o que ela
  recebe (dinheiro = total - vale - consumo - Pix). Se o consumo passa do que ela tem a receber, ela paga a diferença:
  entrada no caixa (com "Registrar saída em dinheiro na gaveta" marcado) e comprovante de entrada. `consumos_ids` trava
  o acerto se o consumo mudou depois de abrir a janela. Recibo mostra "Consumo (n) descontado".
- Telas: `src/ui_qt/caixa.py` (lancar_comissao(tipo="consumo"), _consumo_confirmar, _cancelar_consumo, LINHAS_CONSUMO),
  `src/ui_qt/comissao.py` (DialogoAcerto mostra e desconta). Testes: `tests/test_drinks_garota.py`.
- Nome "consumo" e não "drink": na boate "drink marcado" já é a comissão (cartão da comanda).
- A saída em dinheiro no acerto depende de `comissao_paga_do_caixa` (padrão N): o dono quer S nas boates.
- Ainda de pé: Casa Verde instalar a 1.14.6 (piloto no Render = `CASA-VERDE`); publicar a 1.14.7 depois;
  mensalidade da rede EA; repositório privado (falta aprovar o GitHub Mobile).

---


Branch `rede-app-e-mensalidade`, criada da main depois do #91. Pedido do dono: PWA para a rede EA Superações
(cliente com 4 lojas) e juntar as assinaturas das lojas numa só ("depois eu coloco o valor"). Guia: `docs/REDE_LOJAS.md`.

## O que já existia

Rede (`backend/grupos.py`): login único no painel, central da rede, volta para a lista, e a mensalidade única
(`definir_assinatura`, que renova todas as lojas ao pagar e para as cobranças próprias delas), mas esta só pela API admin.

## O que foi feito

- `GET /painel/rede.webmanifest?grupo=CHAVE` (`backend/painel.py`, `grupos.manifesto`): o app instalado tem o nome da
  rede e abre no login dela. Rede desconhecida recebe o manifesto comum.
- Painel (`painel_web/app.js`): `aplicarAppDaRede` troca o manifesto, o título e o nome do iPhone quando há rede
  (link ?grupo=, sessão da rede guardada ou depois de entrar). Quadro "Ter o app da rede no celular" na tela da rede, com
  botão "Instalar agora" no Android. Service worker `painel-v15`.
- Central (`central_web/app.js` + `POST /v1/fornecedor/grupos/{chave}/plano`): formulário "Mensalidade da rede" em cada
  rede, preenchido com o plano atual (`grupos.plano` entra no `resumo`), com motivo na auditoria.
- Testes em `tests/test_grupos_rede.py`.

## Para o dono fazer (EA Superações)

1. Central > Redes: criar a rede (se ainda não existe) e incluir as 4 lojas.
2. Na rede: "Mensalidade da rede" com o valor, o dia e os dados do pagador. Salvar.
3. Mandar ao cliente o link `https://<nuvem>/painel/?grupo=CHAVE` e a senha temporária; ele instala pelo quadro
   "Ter o app da rede no celular".

## Pendências

- Proteger o código: `docs/PROTEGER_CODIGO.md`. Feito: repositório de downloads com token e variável, publicação lá
  conferida. Falta: conferir as variáveis `PDV_INSTALADOR_*` no Render e como o Render puxa o código (conector do Render
  não está ligado), runner no PC, mudar para privado. Depois: Nuitka.
- Tutoriais: próximos no caixa de treino (fechar caixa, desconto, cancelar item) em `ui_qt/treino.py`.
- Empório: conta Focus, certificado e CSC no painel da Focus, token de homologação (`docs/NFCE.md`).
- Pix integrado: testar com o Mercado Pago real (Pix de R$ 0,01), `docs/PIX.md`.
- Atualização sem UAC (#85): teste em PC real pendente; Render segue com PDV_ATUALIZACAO_PAUSADA=1.
