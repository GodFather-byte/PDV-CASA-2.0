# Telegram do dono e central do fornecedor

## Estado e decisões aprovadas

Plano de 21/10/2026. **Não implementado nem homologado.**

- Painel do dono no Telegram, limitado à própria loja.
- Central do fornecedor em outro computador exclusivo, com interface pelo Telegram.
- Central acompanha lojas, licenças, versão e último contato; não recebe faturamento.
- Reaproveitar inicialmente a API existente em Render/Neon como ponte mínima.
- Cadastro central e assinatura das licenças ficam no computador do fornecedor.
- Cobrança e renovação automáticas são o objetivo posterior; o provedor e suas regras
  serão definidos em etapa separada. Não ativar Asaas ou cobranças reais nesta etapa.
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
  `GET /v1/licenca` e `GET /v1/admin/lojas`. Atualmente a rota de licença **pode assinar
  na nuvem** quando configurada com chave privada: precisa mudar no novo modo ponte.
- [backend/lojas.py](../backend/lojas.py) já cadastra lojas e troca credenciais.
  O modelo de loja examinado não oferece identidade individual de caixa; não
  confundir isso com os retratos de caixa que já existem no painel web.

## Dados e contratos propostos

São contratos de planejamento, não rotas disponíveis.

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

### 2. Central local, inicialmente de consulta

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
