# HANDOFF

## Último trabalho

**Planejamento de Telegram e central do fornecedor — prioridade atual (21/10/2026).**

- O titular pediu oito melhorias para todos os perfis, Tk/Qt e uso de agentes. Depois mudou a prioridade:
  **planejar a substituição da nuvem e a gestão de licenças pelo Telegram antes de implementar novas funções**.
  As oito melhorias estão pausadas; não considerar esta conversa autorização para removê-las ou para desativar a nuvem atual.
- Dois painéis distintos: o dono consulta apenas sua loja; o fornecedor administra lojas, licenças e estado técnico,
  **sem faturamento das lojas**. Central em **outro computador exclusivo do fornecedor**.
- O titular quer cobrança e renovação automáticas, mas autorizou **planejar a integração de pagamento separadamente**.
  Não foi escolhido provedor nem autorizado ativar Asaas, contratar serviços ou emitir licenças reais.
- **Conexão aprovada na continuação:** reaproveitar a API atual como ponte mínima na primeira etapa, com cadastro central
  e assinatura no PC exclusivo. Central consulta a ponte por HTTPS de saída, sem porta/túnel de entrada no PC.
  Plano de entregas, privacidade, contratos propostos e homologação em `docs/CENTRAL_TELEGRAM.md`; nada implementado.
- Arquitetura proposta, ainda não implementada: manter validação Ed25519 offline e chave privada exclusivamente no
  licenciador/central do fornecedor; Telegram como interface, nunca como autoridade de pagamento ou assinatura.
  Bots não recebem mensagens de outros bots: não existe comunicação automática loja-central só por juntar os bots atuais.
  Uma central automática precisa de canal autenticado próprio entre PDVs e computador central (por exemplo API HTTPS,
  com conectividade a definir). Hospedar no PC reduz dependência de Render/Neon, mas exige disponibilidade, proteção,
  backup e manutenção; Telegram sozinho não substitui banco, servidor e confirmação de pagamento.
- Migração deve ser opt-in, preservar licenças e dados existentes e não interromper venda por indisponibilidade da rede.
  Preservar avisos de 7 dias, carência de 5 dias e proteção do turno aberto; nenhuma mudança de regra autorizada.
- Agentes de reposição/etiquetas e retornáveis receberam ordem de parar. Os dois rascunhos novos de controllers,
  sem testes/integração, foram removidos; a conferência do git mostrou apenas este handoff alterado.
  Nenhuma nova funcionalidade deve ser anunciada como pronta.
- Escopo previamente aprovado das oito melhorias: cancelamento parcial somente de quantidade não paga, com motivo
  e permissões; divisão por quantidade/valor sem perder centavos; reposição por caixa (30 dias, cobertura 7 dias e
  estoque mínimo, com aviso de histórico insuficiente); etiquetas; saldo de retornáveis sem cobrança automática;
  promoções sem acúmulo automático, aplicando preço mais vantajoso; central de alertas e Telegram, **sem push nesta etapa**.

### Próximas decisões do titular

- Implementar a ponte mínima sobre a API atual em etapas, sem prometer central automática exclusivamente pela Bot API
  nem expor tokens administrativos nos PDVs. Não desativar Render/Neon.
- Detalhar cadastro/vínculo de loja e caixa, autorização do administrador, revogação e recuperação de acesso.
- Planejar cobrança: provedor, custos, conciliação confiável, idempotência e homologação; comprovante enviado no chat
  não comprova pagamento. Bloqueio remoto imediato e mudança da data-base de renovação não foram aprovados.
- Implementar e testar primeiro consultas/alertas, depois central/entrega de licenças e só depois cobrança automática.
  Validar em cópia do banco antes de instalar em produção. Nenhuma mudança funcional foi validada nesta etapa de planejamento.

## Base anterior preservada

**Preparação local de iFood e NFC-e SP**, autorizada pelo titular depois de esclarecer os pré-requisitos:

- Escopo: módulos opcionais por loja para adega, bar, restaurante, churrascaria e comércio; boate fora desta etapa.
- O titular ainda não tem acesso de desenvolvedor ao iFood, não escolheu provedor fiscal e não sabe o regime tributário.
  Autorizou **apenas a base interna desativada**, sem contratação ou integração externa funcional.
- `integracoes_controller.py` consulta estado, elegibilidade do perfil e pendências. `operacional` é sempre falso.
  Configurações Tk/Qt oferecem só **Desativado** ou **Em preparação (sem operação)**, regime tributário e botão de pendências
  baseado nos dados já salvos. Não há credenciais, emissão, importação de pedidos, contratação ou comunicação externa.
- Novas preferências são inseridas pela semeadura idempotente na tabela `config` existente; sem migração de esquema.
  Perfis não ativam nada automaticamente. Voltar à boate preserva preferências mas informa a exclusão.
- Delivery manual, caixa e cupom NÃO FISCAL mantidos. Documentação em `docs/ESPECIFICACAO.md`, seção 3; mapa atualizado.
- Versão continua **1.6.0** (licenciador 1.1.0). A nuvem segue só para o painel do dono, licença manual e Asaas fora de uso.
  A 1.6.0 já inclui troca de senha do painel pelo PDV, retratos por caixa e retenção do painel; estoque segue por caixa.

### Validação

- Windows, `python -m unittest`: **167 testes passaram**, sem ignorados:
  - `tests.test_integracoes tests.test_integracoes_tk tests.test_qt_configuracoes tests.test_perfil`: 74.
  - `tests.test_caixa tests.test_modulos tests.test_base`: 83.
  - `tests.test_gestao.TesteConfig tests.test_gestao.TesteImpressao`: 10 (inclui entrega manual e cupom).
- Pylance: controlador novo sem erros de sintaxe; arquivos Python alterados sem diagnósticos reportados pelo editor.
- `git diff --check` passou. Não foi rodada a suíte completa nesta mudança.
- **Não validado nem implementado:** integração real com iFood/SEFAZ/provedor, homologação fiscal, contingência e produção.

## Pendências

- **Integrações:** obter acesso e loja de teste no iFood; escolher provedor fiscal depois de cotar CNPJ, volume, excedentes,
  certificado e contingência em SP. Confirmar regime, emitente e tributação com contador. Depois implementar conectores,
  pedidos idempotentes, pagamentos, cancelamentos e documentos fiscais; homologar ponta a ponta antes de oferecer ativação.
  Não prometer operação sem internet ou emissão fiscal com a base atual. Não há preços confirmados nem provedor contratado.
- **Publicar a 1.6.0 na nuvem** para os caixas conectados avisarem o dono (ação do titular, precisa do banco do Neon; exemplo):
  `python -m backend.atualizacoes publicar 1.6.0 --notas "Painel do dono: o dono troca a senha do painel em Configurações; lojas com mais de um caixa aparecem separadas no celular." --url https://github.com/GodFather-byte/PDV-CASA-2.0/releases/tag/ultima-versao`
  (trocar a `--url` se o repositório ficar privado ou se o instalador for entregue de outro jeito). Release versionada com o
  instalador `WillPDV-Setup-1.6.0.exe` é por tag (`git tag v1.6.0 && git push origin v1.6.0`, ver `docs/INSTALAR_E_TESTAR.md`): não foi criada.
- **Nuvem no ar (Render + Neon, grátis):** o Neon está ligado e a `LOJA-TESTE` existe; falta homologar de ponta a ponta com um
  caixa enviando e um celular real. O GitHub não aciona o deploy (falta o segredo `RENDER_DEPLOY_HOOK_URL`): conferir no Render
  se o Auto-Deploy está ligado. **Trocar o `PDV_API_TOKEN` e a senha do Neon** (apareceram numa conversa). Para o Render grátis
  não dormir: UptimeRobot em `GET /v1/saude` a cada 5 min (a rota é só GET: usar método GET ou palavra-chave; conferir se o plano
  grátis deles permite uso comercial).
- **Ao ligar o painel em loja com meses de histórico:** todo o histórico ainda não enviado sobe (lotes de 200, de uma vez) e a
  nuvem descarta o que passa de 120 dias. Se pesar, o PDV pode deixar de mandar vendas mais velhas que a retenção (não feito).
- **Painel:** campo para o dono trocar a senha também no próprio app do celular (hoje só pelo PDV ou pelo fornecedor); push;
  homologar a instalação como PWA no Android e no iPhone.
- **Estoque com dois caixas** é por caixa, por desenho. Um estoque único exige vários caixas no mesmo banco (fora de escopo, ver
  `docs/ESPECIFICACAO.md`).
- **Adega, evoluções não feitas:** cancelamento parcial de linha agrupada (hoje: Delete e relança `4*`); promoção por período só
  no preço natural; empréstimo/saldo de cascos por cliente; etiqueta de gôndola; várias faixas de atacado; atacado gelada pela
  planilha (só pela tela). Entrega da adega: `docs/ADEGA.md` e o aviso por escrito do cupom NÃO FISCAL.
- **Qt fora da adega:** alinhar pré-pago, rodízio/perfil, impressão por setor, dividir conta, balança, acerto das garotas e
  tipografia dos comprovantes. Não abrir Tk e Qt ao mesmo tempo sobre o mesmo banco.
- **Pré-pago:** confirmar a devolução em dinheiro de saldo recarregado no cartão; comprovante de recarga, RFID, relatório de
  recargas.
- **Demais:** split por item, rodízio por faixa, EAN de balança, consumação mínima por entrada, cobrança de comanda sem consumo;
  backup/restauração em outra máquina; Google Drive e senha do cofre do licenciador; cartões 184x126 e faixa 52 na impressora real;
  regra de renovação a partir do vencimento (pede OK do titular); cobrança Asaas só se voltar (o que existe: `backend/cobrancas.py`,
  `operacao_asaas.py`, `worker_asaas.py` e o commit `832bed9`). Painel web do fornecedor (todas as lojas) e vários caixas no mesmo
  banco seguem fora de escopo.
