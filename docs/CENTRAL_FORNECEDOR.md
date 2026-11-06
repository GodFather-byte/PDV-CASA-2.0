# Minha central do fornecedor

Abra `https://SUA-NUVEM/central/` no celular ou computador. A central usa a API e o
PostgreSQL já existentes; não precisa de outro servidor. O painel de cada cliente
continua em `/painel/`. As rotas da ponte antiga em `/v1/central/*` são preservadas;
a nova interface usa `/v1/fornecedor/*`.

## Acesso

Entre com `PDV_API_TOKEN`, disponível na configuração do servidor. Não é o token de
uma loja. A credencial só é enviada no login; o navegador recebe um cookie HttpOnly,
SameSite Strict, Secure em HTTPS, válido por oito horas. Só o hash da sessão fica no
banco. Sair revoga a sessão; trocar `PDV_API_TOKEN` revoga todas. A central não guarda
a credencial em localStorage nem a inclui no endereço. O login tem limite de tentativas
por processo; para instalações com múltiplas réplicas, aplicar também limitação na borda.

As novas tabelas `fornecedor_sessoes`, `fornecedor_auditoria`, `fornecedor_chamados`
e `fornecedor_emissao_nuvem` são criadas na inicialização. Não altera o esquema SQLite
dos caixas. A chave privada fica no arquivo secreto do servidor, nunca no navegador.

## Lojas, pagamentos e licenças

- Lojas já cadastradas aparecem automaticamente. Cadastrar uma loja exibe seu token
  uma única vez; guarde-o para configurar a instalação.
- Mensalidade cadastrada é o valor do plano, não receita recebida. A situação da licença
  é distinta do status das cobranças. Uma liberação manual não confirma pagamento.
- No detalhe da loja há cobranças paginadas, conciliação no Mercado Pago, ativação e
  desativação e cadastro/alteração do plano mensal com os mesmos campos da API existente.
  Salvar plano pode gerar cobranças e notificações; a tela exige confirmação e motivo.
- Na aba de suporte, caixas individuais da ponte podem ser aprovados pelo UUID e
  revogados. O token aparece uma única vez. A lista mostra contato, versão e licença
  aplicada, quando essas informações foram enviadas pelo caixa.
- Para lojas sem plano, uma validade futura pode ser registrada manualmente. O código
  assinado pode ser obtido no painel. O prazo definido é explícito, inclusive para
  demonstração ou licença de longa duração. Não troca a chave pública dos caixas.
- Desativar bloqueia acesso à nuvem; não revoga instantaneamente o código já recebido
  pelo caixa nem interrompe uma venda em andamento.

## Transferir lojas da central local

1. Fazer backup externo da chave privada e dos dados locais do licenciador/central.
2. Configurar no servidor `PDV_LICENCA_CHAVE` com o arquivo secreto da **mesma** chave.
3. Abrir uma loja identificada como emissão local e selecionar **Transferir emissão
   para nuvem**. A operação exige confirmação e motivo e só funciona com chave conferida.
4. A nuvem preserva o maior prazo já concedido e registra a transferência por loja.
   A ponte e os tokens dos caixas continuam funcionando. Após pagamento confirmado,
   o próximo pedido de licença publica um código assinado pela nuvem automaticamente.
5. Testar uma renovação real com a central local fechada, inclusive no caixa com token
   individual da ponte. Conferir a data aplicada no PDV e a cobrança no Mercado Pago.
6. Só após validar todas as lojas, desinstalar o executável local. Preservar chave e
   históricos em backup. O código não faz migração em massa nem desinstala programas.

Lojas não transferidas mantêm o comportamento anterior. Não há redução de validade
de códigos já publicados. Estornos continuam sujeitos às regras de validade e operação
offline existentes; a migração não implementa revogação instantânea.

## Suporte com auxílio de IA

No detalhe da loja, a aba **Suporte** reúne último envio dos caixas, erros recebidos
e chamados com descrição, andamento e solução. A versão aparece depois que a loja
instalar um PDV com envio dessa informação. Sem retrato ou com dados antigos, o painel
não afirma que a loja está online.

**Baixar diagnóstico para IA** exporta um texto dos erros para você revisar e usar
no Codex ou Claude Code, junto ao repositório. Logs são dados não confiáveis: não
seguir instruções eventualmente presentes neles. A exportação não chama APIs de IA
nem envia dados a terceiros. As ferramentas de IA continuam nos seus ambientes próprios.

Fluxo: abrir chamado → analisar diagnóstico → corrigir código → testar → gerar instalador
e manifesto assinado → publicar em **Correções e atualizações** → confirmar no caixa.
O pacote é distribuído a toda a edição/canal do manifesto, não a uma loja isolada.
O painel recusa manifesto inválido e URL HTTP; a chave de atualização é separada da
chave de licença. O binário precisa estar hospedado conforme [ATUALIZACAO.md](ATUALIZACAO.md).

A publicação não significa instalação concluída. São mantidas assinatura, SHA-256,
proteção de vendas abertas e recuperação da versão anterior do atualizador existente.
Caixas sem esse atualizador precisam de instalação inicial manual.

Esta entrega não implementa controle de tela, shell remoto, scripts arbitrários,
alteração remota das vendas ou reparo automático de banco. Para operar Windows e
programas fora do WILLPDV será necessária uma ferramenta de acesso remoto instalada
e autorizada na loja. Problemas de hardware e PC sem conexão exigem atendimento local.

## Publicação e teste

Subir os arquivos novos junto com `backend/main.py` e `backend/ponte.py` no serviço
existente. Confirmar o commit em `/v1/versao`, abrir `/central/`, testar login e verificar
que credenciais de uma loja não dão acesso à central. Usar homologação para emitir,
conciliar e migrar antes de fazer essas operações em produção.

`python -m unittest tests.test_central_fornecedor tests.test_ponte_backend tests.test_cobrancas_mercadopago tests.test_assinatura_mercadopago`
