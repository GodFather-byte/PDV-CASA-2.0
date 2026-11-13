# Handoff — atualização com loja piloto + app da rede (13/11/2026)

## Agora (branch `verificar-com-piloto`, versão 1.14.7)

- Defeito visto na Casa Verde (13/11): em Atualizações do programa, o "Verificar" só consultava o aviso antigo
  (`/v1/atualizacoes`, `src/sync/atualizacoes.py`), que não conhece a loja piloto, e dizia "Nenhuma atualização
  pendente" com a 1.14.6 oferecida. Agora a consulta manual também chama a rota do pacote com `chave_loja`
  (`consultar_pacote` em `src/ui_qt/atualizacoes.py`) e mostra a versão que o "Instalar com o caixa livre" instala.
  Testes em `tests/test_qt_atualizacoes.py`. Roteiro do piloto corrigido em `docs/ATUALIZACAO.md`.
- Teste da loja piloto em andamento: 1.14.6 publicada (#94); Render com `PDV_ATUALIZACAO_PAUSADA=1` e
  `PDV_ATUALIZACAO_PILOTO` = chave da Casa Verde. Falta o dono confirmar a versão no caixa; depois, com o OK dele,
  apagar o piloto e tirar a pausa.
- Vídeos de tutorial: `python -m tools.videos_tutoriais produto operador venda fechamento --saida videos/` (#95).
- Próximos: deixar o repositório privado (conferir Render antes), rede EA Superações na central.

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
