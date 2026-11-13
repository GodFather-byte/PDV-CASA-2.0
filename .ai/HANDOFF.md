# Handoff — proteger o código (13/11/2026)

Branch `proteger-codigo`, criada da main depois do #89 (tutoriais); traz a main depois do #90 (venda de treino).
Pedido do dono: proteger o código. O repositório `PDV-CASA-2.0` é público hoje (licença proprietária, mas visível).
Guia passo a passo do dono: `docs/PROTEGER_CODIGO.md`.

## O que foi feito

- `testes.yml`: os 3 trabalhos de Windows usam o runner do PC do dono quando o repositório é privado e a variável
  `RUNNER_WINDOWS` existe; senão `windows-latest`. Linux da suíte só em Python 3.12 (3.10 fica no Windows). Node
  instalado pelo próprio workflow (o runner próprio não tem).
- `build-windows.yml`, `will-restaurante.yml`, `publicar-pacote.yml`: instaladores e pacotes de atualização vão para
  `vars.DOWNLOADS_REPO` com `secrets.DOWNLOADS_TOKEN` quando configurados; sem eles, tudo continua igual (este repo).
  No outro repositório a Release não aponta para o commit (ele não existe lá).
- `build-windows.yml` e `will-restaurante.yml` sem gatilho de push: versão (instalador + atualização assinada) só sai
  quando o dono manda (workflow_dispatch na main, ou o Claude dispara pela API). Vários PRs viram uma versão.
- Geração de instalador continua sempre no GitHub: ela cria usuário do Windows e mexe em direitos (secedit) para
  testar a atualização; isso nunca pode rodar no PC do dono. `tests/test_ci_protecao.py` garante.

## Ordem para virar privado (o dono faz; detalhes no guia)

1. Repositório público `willpdv-downloads` + token fine-grained (Contents RW só nele) como `DOWNLOADS_TOKEN` +
   variável `DOWNLOADS_REPO`.
2. Uma publicação na main para encher o repositório de downloads.
3. `PDV_INSTALADOR_<PROGRAMA>` no Render apontando para o repositório de downloads (o backend já lê essa variável).
4. Runner no PC Windows + variável `RUNNER_WINDOWS = ["self-hosted","Windows"]`.
5. Change visibility > Private.

## Próximo

- Nuitka no lugar do PyInstaller (o .exe hoje entrega o código Python). Trabalho grande: testar o autoteste do
  programa empacotado, PySide6 com Nuitka e o instalador nas 3 edições.
- Ver no Render se `api_url` + caminho relativo de pacote (`url_absoluta`) não depende do repositório do código.

## Pendências

- Tutoriais: próximos no caixa de treino (fechar caixa, desconto, cancelar item) em `ui_qt/treino.py`; entrada de
  estoque guiada (decidir treino ou de verdade).
- Empório: conta Focus, certificado e CSC no painel da Focus, token de homologação (`docs/NFCE.md`).
- Pix integrado: testar com o Mercado Pago real (Pix de R$ 0,01), `docs/PIX.md`.
- Atualização sem UAC (#85): teste em PC real pendente; Render segue com PDV_ATUALIZACAO_PAUSADA=1.
