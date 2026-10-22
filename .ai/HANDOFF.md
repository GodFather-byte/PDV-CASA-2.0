# HANDOFF

## Estado do trabalho

- Titular autorizou resolver a mesclagem, validar, commitar na `main` e publicar no
  GitHub sem force. Trabalho local da central em `9951e3c`, integrado com a main
  remota `730fd76` (PR #14). Publicação será confirmada após o push.
- PDV **1.7.0**, licenciador **1.2.0**, esquema SQLite **25**.
- Conflitos resolvidos preservando os dois trabalhos: configurações Tk/Qt mantêm
  seleção/preview de logotipo, proteção dos campos secretos e botão de pendências.
  Handoff reescrito com o estado integrado, sem descartar mudanças remotas.

## Entregue e preservado

- Telegram do dono consulta somente sua loja: licença, suporte, renovação e ajuda.
  Renovar solicita; não cobra nem emite. Avisos locais persistentes sem credenciais.
- Central do fornecedor em PC exclusivo, outro bot e banco separado:
  `licenciador/central.py`, `central_bot.py`, `central_cli.py`, `central_tela.py`.
  Entrada: `python -m licenciador.app --central`. Administradores autorizados
  localmente; emissão Ed25519 com confirmação temporária e recuperação idempotente.
- API Render/Neon continua como ponte HTTPS, sem faturamento na central.
  `PDV_CENTRAL_TOKEN` exclusivo e token revogável por caixa; assinatura no fornecedor.
  Cliente em `src/sync/ponte.py`, opt-in, iniciado antes do login Tk/Qt.
  Publicação não equivale a aplicação: confirmação é vinculada ao caixa.
- Meses de calendário sobre o maior entre hoje e validade atual. Permanente não
  renova automaticamente. Licença mantém aviso de 7 dias, carência de 5 e proteção
  de turno. Restauração da central exige reconciliar com a ponte antes de emitir.
- Main remota preservada: melhorias de adega/estoque, importação NF-e, identidade
  visual, migrações e CI. NF-e Tk reconsulta operador/permissão antes da prévia e
  gravação, preservando preço manual sem depender do teclado.
- Guia operacional: `docs/CENTRAL_TELEGRAM.md`; melhorias remotas:
  `docs/ADEGA_MELHORIAS.md`. Não substituir a nuvem por mensagens de bots.

## Validação e pacotes

- Antes da mesclagem: suíte local com 2333 casos (10 ignorados), depois 192
  direcionados; autotestes dos binários PDV Tk/Qt e licenciador passaram.
- Primeira rodada da mesclagem: 108 casos, uma falha de importação por Pillow
  ausente. Instalado Pillow 12.3 conforme `requirements.txt`; sem alteração do manifesto.
- Suíte completa pós-mesclagem em execução; registrar resultado antes do commit.
- Os ZIPs `dist\WillPDV-1.7.0-portatil.zip` e
  `dist\WillLicencas-1.2.0-central-portatil.zip` são **anteriores à mesclagem**:
  não contêm as melhorias remotas agora integradas. Não anunciar novos binários.
  Sem Setup novo (Inno Setup indisponível).
- Nenhum deploy, bot real, chave real, cobrança ou banco de produção usado nesta etapa.

## Pendências e homologação

1. Conferir CI após o push; publicação de código não comprova deploy/homologação.
2. Recompilar pacotes integrados antes de instalar esta versão; usar cópia do banco
   via `PDV_DB`. Extrair ZIP em outra pasta não isola `%LOCALAPPDATA%\WILL-PDV`.
3. Publicar backend e configurar segredo exclusivo; preservar Render/Neon.
   Configurar bot administrativo no PC exclusivo, autorizar ID localmente e importar
   a chave existente, sem gerar outro par para a migração.
4. Homologar loja/caixa de teste: aprovação, publicação, pedido e aplicação confirmada;
   testar reinício, interrupção, backup/restauração. Piloto opt-in só depois disso.
5. Não remover chave/rota legada antes de migrar as lojas; não eliminar histórico.
   PC desligado não oferece disponibilidade do bot local.
- Cobrança automática excluída; Asaas não ativado. Estorno futuro só avisa/suspende
  novas renovações, sem revogar automaticamente código emitido.
- As oito melhorias operacionais inicialmente propostas não foram implementadas
  nesta linha local; a main remota já traz melhorias próprias, preservadas no merge.
- iFood/NFC-e SP seguem base interna desativada, sem homologação fiscal.
- Nuvem: validar caixa/celular reais; trocar `PDV_API_TOKEN` e senha do Neon
  anteriormente expostos. Painel web opcional e histórico existentes preservados.
