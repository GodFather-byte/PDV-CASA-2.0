# Handoff — atualização com loja piloto + app da rede (13/11/2026)

## Agora (branch `versao-1.14.6`, versão 1.14.6)

- 1.14.6 só sobe o número: é o pacote do teste da loja piloto (Casa Verde).
- Roteiro (`docs/ATUALIZACAO.md`, "Loja piloto"): Casa Verde com a 1.14.5 instalada à mão; publicar a 1.14.6
  (dispatch de `build-windows.yml`); no Render, manter `PDV_ATUALIZACAO_PAUSADA=1` e pôr
  `PDV_ATUALIZACAO_PILOTO` = chave da Casa Verde (o dono passou a chave no chat, 13/11); verificar no caixa e na
  central. Depois do teste: apagar o piloto e, se deu certo, tirar a pausa.
- Fora do git ainda: `tools/videos_tutoriais.py` (vídeos de tutorial com as telas reais; roteiros produto, operador,
  venda e fechamento). Entra num PR próprio.

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
