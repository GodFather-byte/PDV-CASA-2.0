# HANDOFF

## Último trabalho

**Implementação da central Telegram e ponte de licenças (21/10/2026).**
PDV **1.7.0**; licenciador **1.2.0**. Código implementado, ainda sem deploy/homologação real.

### Escopo confirmado pelo titular

- Dois painéis: dono consulta apenas a própria loja; fornecedor gerencia lojas, licenças e
  estado técnico, **sem faturamento**, em **outro PC exclusivo**.
- API atual Render/Neon preservada como ponte mínima; assinatura no PC do fornecedor.
- **Cobrança expressamente excluída desta entrega**, assim como as oito melhorias operacionais.
  Não ativar Asaas, cobrar clientes, contratar serviços ou remover a nuvem.
- Emissão mensal autorizada manualmente: meses de calendário a partir do maior entre hoje e
  validade atual. Permanente não é estendida automaticamente. Para cobrança futura, o titular
  aprovou aviso/suspensão de novas renovações em estorno, sem revogação automática do código.

### Entregue

- Telegram do dono: Licença, Suporte, Renovar e Ajuda; estado local sem códigos/credenciais;
  avisos persistentes de vencimento e renovação efetivamente aplicada, sem repetição diária.
  Renovar somente solicita; não cobra nem emite.
- Central em `licenciador/central.py`, `central_bot.py`, `central_cli.py`, `central_tela.py`.
  Botão **Central Telegram** no licenciador; `python -m licenciador.app --central`.
  Banco separado em `%LOCALAPPDATA%\WillPDV-Central\central.db`; administradores cadastrados
  localmente, consultas paginadas, cadastro de lojas, aprovação/revogação de caixas,
  importação validada do histórico, backup e restauração para arquivo novo.
- Emissão Ed25519 local com confirmação vinculada ao administrador, prazo de 5 minutos e
  identificação idempotente persistente. Publicação não equivale a aplicação.
  Histórico importado só é publicado após autorização local explícita.
  Restauração bloqueia novas emissões até reconciliar cadastros/licenças na ponte.
- `backend/ponte.py`: credencial exclusiva `PDV_CENTRAL_TOKEN` (>=32 caracteres e diferente
  das demais), token individual revogável por caixa, contato técnico e pedidos idempotentes.
  A primeira publicação migra a loja: a rota legada entrega código publicado, sem assinatura
  remota/fallback. Lojas não migradas preservam o comportamento anterior.
- `src/sync/ponte.py`: cliente opt-in, HTTPS salvo loopback, aplicação pelo validador existente,
  confirmação por caixa e dois ciclos de pedido (`pendente`, `enviada`, `atendida`).
  Tk/Qt configuram UUID e credencial mascarada; gerar outro ID limpa token e exige reaprovação.
  Serviço próprio iniciado antes do login em Tk/Qt: não depende de `--sync`, não faz rede
  desligado. O processo separado existente continua compatível.
- Nenhuma mudança no formato de licença, nos 7 dias de aviso, 5 dias de carência, proteção
  do turno ou estoque por caixa. Novas preferências via semeadura; esquema PDV continua 22.
- Guia de instalação, privacidade, recuperação e rotas em `docs/CENTRAL_TELEGRAM.md`;
  guias de Telegram, nuvem, licenciador e mapa atualizados.

### Validação

- Suíte completa: **2333 casos, sem falhas, 10 ignorados** (Windows/Python 3.15).
  Depois dos ajustes finais de serviço antes do login e recuperação, rodada dirigida
  de **192 testes passou**, incluindo Tk/Qt, cliente, central, backend real via TestClient,
  solicitação, assinatura, aplicação e isolamento de dados.
- Teste integrado usa central e cliente PDV reais com API real por TestClient, bancos e
  chave temporários; valida ausência de envio de vendas/faturamento.
- Pylance sem erros de sintaxe/diagnósticos nos arquivos centrais verificados;
  `git diff --check` passou.
- Executáveis finais compilados com PyInstaller em ambiente temporário isolado, sem instalar
  dependências globalmente. **Autotestes dos binários PDV Tk, PDV Qt e licenciador passaram.**
- ZIPs portáteis criados e integridade verificada:
  - `dist\WillPDV-1.7.0-portatil.zip`;
  - `dist\WillLicencas-1.2.0-central-portatil.zip` (somente fornecedor).
- **Não há instalador Setup novo:** Inno Setup indisponível. Builds em diretórios existentes
  do OneDrive sofreram bloqueios; os ZIPs acima foram feitos dos builds finais isolados
  validados, não de saídas incompletas anteriores.
- Nenhum deploy, bot real, chave real, emissão real, cobrança ou dado de produção foi usado.

## Próximo passo: homologar antes de produção

1. Publicar backend atualizado e configurar segredo exclusivo da central, sem chave privada
   na ponte para novas lojas. Não desativar Render/Neon.
2. Configurar bot administrativo separado no PC exclusivo, autorizar ID localmente e importar
   a chave já existente. Nunca gerar outro par de chaves para esta migração.
3. Loja/caixa de teste, UUID aprovado, código assinado publicado, token configurado no PDV,
   solicitação pelo dono e aplicação confirmada na central.
4. Validar interrupções/reinício e backup/restauração no segundo computador.
5. Testar **cópia do banco via `PDV_DB`**. Extrair ZIP em pasta nova NÃO isola o banco padrão
   do executável (`%LOCALAPPDATA%\WILL-PDV`). Não abrir duas interfaces sobre o mesmo banco.
6. Só depois piloto opt-in. Não remover chave de servidor legado sem migrar suas lojas,
   não eliminar histórico hospedado sem autorização e não prometer disponibilidade com PC desligado.

## Pendências preservadas

- Oito melhorias operacionais pausadas: cancelamento parcial não pago, alertas gerais,
  reposição 30/7 por caixa, etiquetas, retornáveis sem cobrança, divisão por item/valor,
  promoções/faixas sem acúmulo e evolução do painel. Push ficou fora.
- iFood/NFC-e SP continuam **somente base interna desativada**, sem integração externa,
  homologação fiscal, certificado ou provedor contratado; cupom NÃO FISCAL.
- Publicação da versão na nuvem/release/instalador é pendente, sem tag ou push nesta entrega.
- Nuvem: validar caixa/celular reais; configurar deploy hook se necessário.
  **Trocar `PDV_API_TOKEN` e senha do Neon** que apareceram em conversa anterior.
- Painel web existente continua independente e opcional; retenção/histórico antigos preservados.
- Alinhamento Qt fora da adega (pré-pago, rodízio, setores, divisão, balança, acertos e tipografia)
  e evoluções específicas da adega seguem pendentes; ver documentação por assunto.
- Cobrança automática só em nova etapa: provedor, custos, conciliação, idempotência e homologação.
  O Asaas preexistente não foi ativado nem alterado para cobrar nesta entrega.
