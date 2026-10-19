# HANDOFF

## Último trabalho

- **Nuvem com cobrança Asaas, plano do titular (17-19/10/2026):** a API sobe no **Render** (instância paga `starter`) com o banco no
  **Neon**, e o worker do Asaas roda como **agendador no GitHub Actions** (sem serviço extra pago). Cobrança por Pix/boleto via
  link; licença manual segue valendo até a renovação automática ser homologada.
  - `.github/workflows/worker-asaas.yml`: `python -m backend.worker_asaas --uma-vez` a cada 5 min (sai sem falhar se os segredos não
    existirem). `.github/workflows/monitor-asaas.yml` + `tools/monitor_asaas.py`: consulta `/v1/admin/cobrancas/operacao` a cada
    30 min e falha (e-mail do GitHub) se houver erro, fila/conciliação atrasada ou worker parado há mais de 30 min.
  - `render.yaml`: plano `starter`; `ASAAS_AMBIENTE`, `ASAAS_API_KEY` e `ASAAS_WEBHOOK_TOKEN` sem valor no arquivo (preencher no painel).
  - Guia: `docs/COBRANCA_LICENCAS_ASAAS.md` (seções 5.2 e 11). Testes: `tests/test_monitor_asaas.py`.
- Antes disso (adega, 1.5.0): ver `docs/ADEGA.md`; o painel do dono já está no código da nuvem (`docs/PAINEL_DONO.md`).

## Pendências

- **Colocar a nuvem no ar (titular):** o serviço do Render já subiu em `https://willpdv-nuvem-xezo.onrender.com` (`/v1/saude` 200).
  Falta: (1) conferir em *Environment* que `PDV_NUVEM_DB_URL` aponta para o Neon (a lista `GET /v1/admin/lojas` com o
  `PDV_API_TOKEN` deve mostrar uma loja criada pelo PC no mesmo banco), `ASAAS_*`, `TZ` e o Secret File da chave; (2) segredos do GitHub
  `PDV_NUVEM_DB_URL`, `ASAAS_API_KEY`, `PDV_API_TOKEN` e variáveis `ASAAS_AMBIENTE`, `PDV_API_URL` (os workflows agendados só valem depois
  deste PR estar na `main`); (3) homologar tudo no **sandbox** (seção 9 do guia) com uma loja de teste, banco Neon separado do de produção;
  (4) só então virar para produção (`ASAAS_AMBIENTE=producao`, chaves, webhook e assinatura de produção) e vincular a loja real,
  registrando antes a validade manual atual com `python -m backend.lojas assinatura`.
- Ao fazer o merge, o Render pode aplicar o plano `starter` (cobrança) se o serviço estiver ligado ao Blueprint; confira o preço em
  render.com/pricing. O agendamento do GitHub só roda a partir da `main`, pode atrasar alguns minutos e, em repositório público,
  é desativado após 60 dias sem atividade. A chave do Asaas fica nos secrets do repositório.
- O repositório é **público**: avaliar torná-lo privado (o Render segue funcionando). O `PDV-CASA--main.zip` na raiz pode sair.
- **Para a entrega da adega:** `git push` para a `main` gera o instalador (release `ultima-versao`) e roda a suíte; seguir `docs/ADEGA.md`.
- **Adega, evoluções não feitas:** cancelamento parcial de linha agrupada; promoção por período só no preço natural; empréstimo/saldo de
  cascos por cliente; etiqueta de gôndola; várias faixas de atacado; atacado gelada pela planilha.
- **Painel do dono:** campo no PDV para o dono trocar a própria senha (rota `POST /v1/painel/senha` já existe); push; mais de um terminal
  por loja; limpeza de dados antigos; homologar no Render/Neon e num celular real.
- **Qt fora da adega:** alinhar pré-pago, rodízio/perfil, impressão por setor, dividir conta, balança, acerto das garotas e tipografia
  dos comprovantes. Não abrir Tk e Qt ao mesmo tempo sobre o mesmo banco.
- **Pré-pago:** confirmar a devolução em dinheiro de saldo recarregado no cartão; comprovante de recarga, RFID, relatório de recargas.
- Demais: split por item, rodízio por faixa, EAN de balança, consumação mínima por entrada, cobrança de comanda sem consumo;
  backup/restauração em outra máquina; Google Drive e senha do cofre do licenciador; cartões 184x126 e faixa 52 na impressora real;
  regra de renovação a partir do vencimento (pede OK do titular). Painel web do fornecedor (todas as lojas) e múltiplos caixas seguem
  fora de escopo.
