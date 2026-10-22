# Telegram do dono e central do fornecedor

## Estado e decisões aprovadas

Implementação de 21/10/2026: PDV **1.7.0**, licenciador **1.2.0**.
**Precisa de implantação e homologação com bots/lojas de teste antes de produção.**

- Painel do dono no Telegram, limitado à própria loja.
- Central do fornecedor em outro computador exclusivo, com interface pelo Telegram.
- Central acompanha lojas, licenças, versão e último contato; não recebe faturamento.
- Reaproveitar inicialmente a API existente em Render/Neon como ponte mínima.
- Cadastro central e assinatura das licenças ficam no computador do fornecedor.
- **Cobrança foi excluída expressamente desta entrega.** A emissão exige autorização
  do fornecedor; nenhuma consulta ou solicitação do dono cobra ou renova sozinha.
- Regra aprovada para emissão mensal: acrescentar meses de calendário à maior entre
  a validade atual e hoje. Licença permanente não é estendida automaticamente.
- As oito melhorias operacionais anteriores permanecem pausadas.

## Arquitetura

```text
Celular do dono <-> Telegram da loja <-> PDV e banco local
                                         |
                               HTTPS com token do caixa
                                         |
                             API existente / ponte mínima
                                         |
                           HTTPS iniciado pela central
                                         |
Seu celular <-> Telegram administrativo <-> Central no PC exclusivo
                                             |
                                  Licenciador e chave privada
```

O computador central consulta a ponte por conexões de saída. Nesta etapa não precisa
de porta aberta no roteador, domínio próprio ou túnel para recebimento na central.
O painel do dono consulta o PDV da loja, não o computador do fornecedor.
Os dois bots são interfaces independentes; a comunicação entre loja e central passa
pela API, não por mensagens de um bot para outro.

O uso normal do Telegram não implica assinatura da Bot API, mas há limites de envio.
Render/Neon continuam necessários nesta etapa e seus planos/custos devem ser
conferidos antes da implantação. Não prometer custo zero ou disponibilidade contínua.

## Responsabilidades e privacidade

| Componente | Guarda e faz | Não deve receber/fazer |
|---|---|---|
| PDV | Vendas, estoque, licença recebida e validação offline | Chave privada de emissão ou credencial administrativa |
| Bot da loja | Consultas e alertas do dono autorizado | Gestão de outras lojas ou autorização de pagamento |
| Ponte | Identificação técnica mínima, licença assinada publicada e solicitações | Chave privada, emissão ou faturamento para a central |
| Central | Cadastro administrativo, histórico, emissão e publicação | Consultar dados financeiros da operação dos clientes |
| Bot administrativo | Consultas do fornecedor e solicitações autorizadas | Distribuir chaves, tokens ou bancos pelo chat |

O painel web existente não é removido automaticamente. Seu envio de vendas é um
fluxo opcional separado; impedir que a nova central consulte esses dados.
Antes de desligar esse envio, explicar ao dono a perda das consultas web e confirmar
a migração. Eventual exclusão dos dados já hospedados exige decisão própria.

Mensagens de bots passam pela infraestrutura do Telegram e não são conversas com
criptografia de ponta a ponta. Não enviar senhas, chaves privadas, tokens ou cópia do
banco. Nomes de lojas e informações técnicas também exigem acesso restrito.

## Reaproveitamento verificado no código

- [TelegramController](../src/controllers/telegram_controller.py) já oferece pareamento,
  consultas, fila e serviço de envio/escuta. Cada bot precisa de um único consumidor.
- [licenca.py](../src/core/licenca.py) valida assinatura, loja e prazo offline.
- [licenciador/nucleo.py](../licenciador/nucleo.py) já emite, confere e mantém histórico.
  O histórico atual não substitui um cadastro transacional da nova central.
- [licenca_nuvem.py](../src/sync/licenca_nuvem.py) consulta a licença e aplica somente
  códigos aceitos pelo validador local.
- [backend/main.py](../backend/main.py) já autentica lojas e administrador e possui
  `GET /v1/licenca` e `GET /v1/admin/lojas`. Para loja migrada, a rota entrega somente
  licença publicada pela central, **sem assinar nem fazer fallback na nuvem**.
  As lojas legadas não migradas mantêm o comportamento anterior.
- [backend/lojas.py](../backend/lojas.py) já cadastra lojas e troca credenciais.
  O modelo de loja examinado não oferece identidade individual de caixa; não
  confundir isso com os retratos de caixa que já existem no painel web.

## Dados e contratos

Rotas implementadas em [backend/ponte.py](../backend/ponte.py).

- **Loja:** identificador estável, chave compatível com licenças atuais, nome e estado
  de vínculo. O cadastro local é a autoridade; a ponte recebe somente o necessário.
- **Caixa:** identificador persistente, loja vinculada e credencial própria revogável.
  Terminal/nome do computador não são autenticação. Cadastro inicial exige aprovação
  pelo fornecedor; sem inscrição livre usando apenas o nome da loja.
- **Contato técnico:** versão, instante recebido pela ponte e situação de licença
  informada pelo PDV. É um retrato declarado, não prova independente de funcionamento.
  Exibir data e horário; não chamar ausência de contato de bloqueio ou inadimplência.
- **Licença publicada:** identificador, loja, código assinado, emissão, validade e
  revisão de publicação. A ponte verifica a assinatura pública e o vínculo.
- **Solicitação:** identificador único, loja, tipo, criação e andamento. Não carrega
  autorização para emitir. Repetir consulta ou mensagem não cria nova emissão.
- **Confirmação:** distinguir publicada, recebida e aplicada. O PDV confirma aplicação
  só depois de gravar e validar; central não anuncia renovação concluída só por enviar.

Credenciais de caixa e de central devem ter escopos separados. O bot administrativo
não pode reutilizar os pareamentos dos donos. O primeiro administrador é cadastrado
localmente na central; recuperar acesso não depende de um comando aberto no Telegram.
Operações de escrita exigem confirmação de uso único, prazo de validade, auditoria
e identificação do solicitante. Reprocessamento e reinício devem ser idempotentes.

A licença atual é por loja: identificar caixas não altera o formato Ed25519 nem
introduz limite de instalações ou licença por equipamento sem nova autorização.

## Entregas e critérios de aceite

### 1. Consultas e alertas

- Organizar o menu do dono sem consultas entre lojas.
- Adicionar situação e vencimento de licença sem expor o código ou credenciais.
- Alertas de vencimento sem repetição a cada consulta/reinício.
- Testar com Telegram falso, banco isolado e datas controladas.
- Sem mudança de permissões ou operações financeiras remotas nesta entrega.

### 2. Central local

- Banco próprio, migrações e backup restaurável; separado dos bancos de clientes.
- Cadastro administrativo e importação validada do histórico do licenciador,
  sem sobrescrever ou perder o original.
- Bot administrativo separado, autorização local e consultas paginadas.
- Mostrar licença emitida, licença aplicada e último contato como estados distintos.
- Testar isolamento dos papéis, recuperação de backup e reinício.

### 3. Ponte e entrega de licenças

- Cadastro aprovado de caixa, credencial individual e contato técnico mínimo.
- Central publica somente códigos assinados localmente; ponte não emite no novo modo.
- Compatibilidade explícita por loja durante a migração; nada de alternância silenciosa
  para emissão na nuvem quando o computador central estiver desligado.
- Testar licença adulterada, de outra loja, mais curta, repetida e recebida fora de ordem;
  revogação de credencial; queda após assinatura, publicação e aplicação.
- Retirar a chave privada do ambiente hospedado somente depois da transição validada,
  sem trocar o par de chaves e invalidar os códigos atuais. Não é ação desta etapa.

### 4. Cobrança automática, separadamente

- **Não implementada nesta entrega, por decisão do titular.**
- Escolher provedor e confirmar custos, conta de recebimento e homologação.
- Receber confirmação autenticada na infraestrutura do provedor/ponte e conciliar
  pela API do pagamento. Comprovante ou texto no Telegram não comprova pagamento.
- Central processa autorizações válidas com identificadores únicos e trilha de auditoria;
  a emissão aguarda a central quando seu computador estiver indisponível.
- Definir com o titular data-base de renovação, estorno, pagamento duplicado e atrasado
  antes de implementar. Preservar a regra atual enquanto não houver decisão.

## Migração e operação

1. Backup e restauração comprovados em cópia dos dados.
2. Testes automatizados sem rede, chaves reais ou cobrança.
3. Homologação com bots e lojas de teste; nenhum token real no repositório ou logs.
4. Piloto opt-in com um caixa; verificar consultas por celular e entrega ponta a ponta.
5. Ampliar somente após revisar erros, duplicidades e recuperação.

Manter aviso de 7 dias, carência de 5 dias e proteção do turno aberto. Falha de rede
não acrescenta bloqueio novo, mas também não prorroga automaticamente a licença.
Com a central desligada, as licenças já instaladas continuam seguindo a validade
normal; novas emissões ficam pendentes. O bot administrativo não responde sem a central.
O bot do dono depende do PDV da loja ligado e conectado.

Rollback é voltar ao caminho anterior de consulta/entrega preservando dados e códigos,
não restaurar cegamente um banco antigo nem reativar assinatura remota sem aprovação.

## Instalar e configurar

Não publique segredos neste documento nem no git. Os exemplos usam variáveis sem valores.

### Pacotes portáteis desta entrega

- PDV: `dist\WillPDV-1.7.0-portatil.zip`.
- Fornecedor: `dist\WillLicencas-1.2.0-central-portatil.zip` (**não entregar ao cliente**).

Extrair o ZIP inteiro em pasta nova e manter o executável junto da pasta `_internal`.
Não executar dentro do ZIP nem copiar somente o `.exe`. São pacotes portáteis,
não instaladores Setup; o Inno Setup não está disponível na máquina de desenvolvimento.
Os executáveis passaram nos autotestes isolados Tk/Qt e do licenciador.

**Não abrir o portátil sobre o banco de produção para experimentar.** Fazer backup,
usar cópia do banco em pasta separada e definir `PDV_DB` apontando para essa cópia
antes de abrir o PDV. O executável usa por padrão o mesmo diretório de dados comercial
em `%LOCALAPPDATA%\WILL-PDV`; uma pasta nova do programa não isola os dados sozinha.
A central também exige configuração e homologação da API e dos bots antes do uso real.

### API existente (Render)

1. Publicar o backend atualizado, sem desligar Render/Neon. As tabelas `ponte_*` são
   criadas pelo mecanismo de inicialização existente; não é migração do banco do PDV.
2. Gerar um segredo aleatório exclusivo com pelo menos 32 caracteres para
   `PDV_CENTRAL_TOKEN`, distinto do token administrativo, dos bots e dos caixas.
   Configurá-lo como segredo do serviço e no PC exclusivo do fornecedor.
3. Não instalar a chave privada nessa ponte para as lojas novas. Não remover a chave
   de um ambiente legado antes de concluir a migração das lojas que dependem dele.
4. Manter o painel web separado. A central não usa seus endpoints de faturamento.

### Computador exclusivo do fornecedor

- Instalar o **WillPDV Licenças 1.2.0**, nunca no cliente. Botão **Central Telegram**
  abre o painel de configuração e operação; também aceita `WillLicencas.exe --central`.
- O banco separado é `%LOCALAPPDATA%\WillPDV-Central\central.db`.
  `WILLCENTRAL_DADOS` permite outra pasta. Não apontar para o banco do PDV.
- Importar a chave já usada pelo licenciador pelo fluxo existente. Não criar outro
  par de chaves, não enviar a chave pelo Telegram e não colocá-la no repositório.
- Criar outro bot no BotFather para administração. Não reutilizar bot de loja.
- Preencher endereço HTTPS da API, token exclusivo da central e token do bot.
  A tela usa tokens apenas na sessão; para reinícios pode ler `WILLCENTRAL_API_URL`,
  `PDV_CENTRAL_TOKEN` e `WILLCENTRAL_TELEGRAM_TOKEN` do ambiente do fornecedor.
- Cadastrar localmente seu **ID numérico privado do Telegram**, não o nome de usuário.
  Para descobrir o ID, iniciar o bot e enviar `/start` em conversa privada:
  a resposta de acesso recusado informa somente o ID do próprio solicitante.
  A autorização depende de ação local; `/start` não cadastra administradores.
- Cadastrar lojas preservando exatamente a chave já usada nas licenças e na API
  (até 64 letras/números, ponto, hífen e sublinhado). Importar o histórico original
  do licenciador é opcional, validado e não altera o arquivo de origem.
- Aprovar cada UUID de caixa pela tela local. A credencial retornada aparece uma
  única vez; configurar diretamente no caixa por canal seguro, **não pelo bot**.
- Para migrar uma licença existente, importar seu histórico, tocar **Publicar licença**
  e confirmar a loja; depois **Sincronizar**. Importar sozinho não migra a entrega.
- Para emissão nova, usar `/emitir CHAVE MESES` e confirmar pelo código de uso único
  válido por 5 minutos. A emissão apenas registra código local; o serviço publica
  nas sincronizações seguintes. `/loja CHAVE` distingue emissão, publicação e aplicação.
- **Iniciar bot e sincronização** mantém serviço enquanto o programa estiver aberto.
  Não é serviço Windows nem inicia automaticamente com o computador. Há trava para
  impedir dois serviços no mesmo banco; evite o mesmo bot em outro programa/banco.

Sem ambiente configurado, a tela permite cadastro local, importação e backup, mas
não anuncia conexão nem publicação bem-sucedida.

### Computador do caixa

Em Configurações, configurar a ponte opcional, obter o UUID e aprová-lo na central.
Informar a credencial exclusiva desse caixa e ativar a ponte somente após a publicação
da licença correta. Usar o endereço HTTPS da API atual; token de caixa **não** é
`PDV_API_TOKEN`, `PDV_CENTRAL_TOKEN` nem o token legado de loja.

A ponte tem serviço próprio na interface Qt, iniciado antes do login e
sem rede enquanto a opção estiver desligada. Não é preciso iniciar `--sync` para
receber licença com o PDV aberto. O processo separado `python -m src.app --sync`
continua disponível, inclusive para o painel web legado; as operações da ponte
são idempotentes se os dois estiverem rodando. Manter o Telegram do dono configurado
na loja. A central não é consumidora desse bot.

Se perder a credencial, revogar o caixa antigo, gerar novo UUID nas configurações e
aprovar novamente. Revogar acesso à ponte não revoga nem apaga a licença já instalada.
Não copiar configuração de credencial entre computadores.

### Comandos locais alternativos (Python)

Rodar na raiz do projeto, com segredos definidos no ambiente local:

```powershell
python -m licenciador.central_cli loja LOJA-TESTE "Loja de teste"
python -m licenciador.central_cli administrador 123456789
python -m licenciador.central_cli importar "C:\backup\historico.json"
python -m licenciador.central_cli aprovar-caixa LOJA-TESTE UUID-DO-CAIXA
python -m licenciador.central_cli publicar-loja LOJA-TESTE
python -m licenciador.central_cli sincronizar
python -m licenciador.central_cli servir
```

Usar o UUID real mostrado no PDV, não a palavra `UUID-DO-CAIXA`. A mesma entrada está
disponível em `python -m licenciador.app --central-cli ...`.

### Backup, restauração e recuperação do administrador

O backup SQLite da central inclui cadastro, histórico, administradores, confirmações,
auditoria e retratos técnicos. **Não inclui a chave privada**: usar o backup
criptografado separado do licenciador e guardar a senha fora do computador.

```powershell
python -m licenciador.central_cli backup "C:\backup\central-2026-10-21.db"
python -m licenciador.central_cli --banco "C:\recuperacao\central.db" restaurar "C:\backup\central-2026-10-21.db"
```

Restauração exige caminho novo, sem sobrescrever o banco existente. Encerrar o serviço,
conferir administradores e apontar para o banco recuperado. Emissões ficam bloqueadas
até sincronizar e reconciliar licenças publicadas, evitando renovação duplicada ao
restaurar um backup anterior. Publicações nunca retornadas pelo servidor permanecem
pendentes e são reenviadas com o mesmo identificador.

Para perda do celular, remover localmente o ID antigo e cadastrar o novo; isso também
invalida suas confirmações pendentes. Comando local:

```powershell
python -m licenciador.central_cli administrador 123456789 --remover
```

Não existe comando Telegram para recuperar privilégios administrativos. A segurança
do Windows e do acesso físico ao PC do fornecedor continua essencial.

## Rotas e credenciais

| Credencial | Rotas | Finalidade |
|---|---|---|
| `PDV_CENTRAL_TOKEN` | `/v1/central/lojas`, `/estado`, `/caixas`, `/licencas` | Cadastro técnico e publicação, sem acesso ao painel financeiro |
| Token individual de caixa | `/v1/ponte/licenca`, `/contato`, `/solicitacoes` | Consultar/aplicar, contato técnico e pedir renovação |
| Token legado de loja | Rotas legadas já existentes | Compatibilidade; não autoriza administração da ponte |

Licenças publicadas têm assinatura pública verificada, loja, ID estável e prazo que
não retrocede. Pedidos repetidos retornam o mesmo estado; somente confirmação de
aplicação de uma licença nova pelo caixa solicitante atende o pedido. A central não
usa mensagens do Telegram como prova de pagamento ou de aplicação.
