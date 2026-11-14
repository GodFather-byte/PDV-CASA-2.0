# Handoff — atualização com loja piloto + app da rede (13/11/2026)

## Agora (versão 1.14.8: emissão própria da NFC-e, #99)

- Emissão própria da NFC-e direto na SEFAZ-SP (decisão do dono: cobrar adicional menor e ganhar no volume). Guia em
  `docs/NFCE_PROPRIA.md`. Código em `src/fiscal/sefaz/` (chave, xml_nfce, assinatura, qrcode, cliente, provedor);
  provedor escolhido por `nfce_provedor` (focus | propria) em `FiscalController.transmissor()`; a fila não mudou.
- Testes: `tests/test_nfce_sefaz.py` valida o XML nos schemas oficiais (PL_010 v1.30, em `tests/dados/xsd_nfe/`,
  baixados de nfephp-org/sped-nfe), confere a assinatura e simula a SEFAZ (autoriza, rejeita, resposta perdida,
  cancelamento). Nova dependência: `lxml` (requirements.in/.txt regenerados com uv).
- Ainda não falou com a SEFAZ de verdade. Piloto: DELICIOZ (Osasco, Simples, A1 da própria loja), instalação marcada
  para 15/11; o dono levanta credenciamento NFC-e, IE, série/último número e CFOP/CSOSN com o contador. Primeiro teste: status do
  serviço em homologação; se der SSLError, embutir a cadeia ICP-Brasil.
- Falta: contingência off-line (QR v3 assinado; confirmar no Manual DANFE NFC-e v6), inutilização, XMLs na nuvem,
  IBS/CBS na emissão própria.
- Outras pendências: Casa Verde instalar a 1.14.7 (piloto `CASA-VERDE` no Render; 1.14.7 publicada); depois liberar
  as outras lojas; mensalidade da rede EA; repositório privado.

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
