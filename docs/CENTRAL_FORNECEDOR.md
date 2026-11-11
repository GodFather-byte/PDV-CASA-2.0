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
a credencial em localStorage nem a inclui no endereço. O login tem limite de tentativas (8 erros por endereço em 15 minutos; quem não errou nunca é
bloqueado pelos erros dos outros)
por processo; para instalações com múltiplas réplicas, aplicar também limitação na borda.

As novas tabelas `fornecedor_sessoes`, `fornecedor_auditoria`, `fornecedor_chamados`
e `fornecedor_emissao_nuvem` são criadas na inicialização. Não altera o esquema SQLite
dos caixas. A chave privada fica no arquivo secreto do servidor, nunca no navegador.

## Cadastrar e instalar uma loja sem terminal

1. **Cadastrar loja**: identificação, nome, programa (WillPDV ou Will Adega) e motivo. A central mostra uma vez o
   **código de instalação** (`WILL1-...`), que junta o endereço da nuvem, a loja e o token. Guarde como senha.
2. Registre a validade (liberação manual) ou o plano mensal da loja.
3. No caixa, tela de entrada, **Ativar licença ou instalar loja**: colar o código configura a nuvem (endereço, loja,
   token), liga o envio do painel do dono e já busca a licença. Se o caixa estava em outra loja, ele pergunta antes.
4. No detalhe da loja, **Instalação e acesso do dono**:
   - **Gerar senha do painel do dono**: senha nova para o celular (endereço da nuvem + `/painel/`); a antiga cai.
   - **Gerar novo código de instalação**: troca o token (por exemplo, se vazou). Os caixas instalados precisam
     receber o código novo pelo mesmo botão.

5. **Gerar kit de implantação** (mesma seção): junta num texto, para imprimir ou copiar, o link do instalador do
   programa da loja, o código de instalação com QR, o endereço e a senha do painel do dono e o aviso de cupom não
   fiscal. Gera código e senha novos (os anteriores caem). O QR pode ser lido no caixa por leitor 2D em vez de colar.

Os comandos `python -m backend.lojas ...` continuam funcionando, mas não são mais necessários para o dia a dia.

**Alertas de vencimento:** o topo da lista mostra as lojas ativas vencendo em até 7 dias ou vencidas há até 30. Um
resumo sai por e-mail uma vez por dia (Brevo ou SMTP já configurados) para `PDV_AVISOS_EMAIL`, ou para `EMAIL_FROM`.
O botão **Enviar resumo por e-mail agora** serve também para testar o e-mail.

**Variáveis opcionais no servidor:** `PDV_AVISOS_EMAIL` (destino do resumo) e `PDV_INSTALADOR_WILLPDV` /
`PDV_INSTALADOR_WILLADEGA` (link do instalador no kit; sem elas, vale o link fixo das Releases do GitHub).

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
- **Programa da loja:** cada loja tem o programa que usa (WillPDV ou Will Adega), escolhido no
  cadastro e alterável em "Programa da loja" (com motivo, auditado). Toda licença assinada pela
  nuvem (renovação automática, "Obter código da licença" e a consulta antiga do caixa) sai para
  esse programa: licença do WillPDV não abre a Will Adega e vice-versa. Lojas antigas sem programa
  contam como WillPDV.
- Para lojas sem plano, uma validade futura pode ser registrada manualmente. O código
  assinado pode ser obtido no painel. O prazo definido é explícito, inclusive para
  demonstração ou licença de longa duração (no máximo 100 anos). A liberação manual **nunca
  reduz** a validade já concedida. Não troca a chave pública dos caixas.
- Desativar bloqueia acesso à nuvem; não revoga instantaneamente o código já recebido
  pelo caixa nem interrompe uma venda em andamento.

Se a chave de emissão faltar na nuvem ou dois pedidos chegarem juntos, a consulta do caixa
continua devolvendo o último código publicado; a renovação pendente fica registrada no log.

### Saúde das lojas

A lista mostra, por loja, a situação do caixa: **Online** (envio nos últimos 35 minutos), **Hoje**,
**Parada** (mais de 24 h sem enviar) ou **Sem envio**, com a versão mais antiga em uso, os erros
recebidos em 7 dias e os chamados em aberto. Loja abaixo da versão mais nova vista em qualquer caixa
aparece como **Desatualizada**. Nenhum valor de venda chega à central.

- **Precisa de você hoje:** licenças vencidas ou a vencer, caixas parados, erros e chamados.
- **Indicadores:** tocar em um deles filtra a lista. Há ordenação por urgência, nome, validade e contato.
- **Cobrar no WhatsApp:** abre a conversa do responsável (o WhatsApp do plano) com a mensagem pronta;
  sem WhatsApp no plano, copia a mensagem.
- **Baixar planilha (CSV):** a carteira inteira, para abrir no Excel.
- **Versões em uso:** em Correções e atualizações, quantas lojas estão em cada versão.

### Gerente esqueceu a senha do caixa

1. No caixa, na tela de entrada, **Esqueci a senha** mostra um pedido de 8 letras e números (ex.: `K7QF-3MZD`),
   válido por 24 horas. Nada é apagado.
2. O dono envia o pedido. Confirme que é ele por um contato que você já conhece.
3. Na central, abra a loja > **Suporte e caixas** > **Gerente esqueceu a senha do caixa**, digite o pedido e o motivo.
4. Com internet, o caixa clica em **Buscar liberação na nuvem**. Sem internet, envie o código (`PDVR1...`) para
   colarem na tela.
5. O caixa escolhe o gerente (o ADM vem primeiro) e cadastra a senha nova.

A liberação é assinada com a chave das licenças: vale só para aquela loja e aquele pedido, por 24 horas, uma vez.
Fica no histórico de ações da central e no log do caixa. Quem tem o código-fonte ou acesso ao banco da loja não
consegue gerar a liberação. Sem a chave de emissão na nuvem, use no seu computador:

```
python -m tools.gerar_licenca recuperar-senha --loja CHAVE --pedido K7QF-3MZD
```

## Transferir lojas da central local

1. Fazer backup externo da chave privada e dos dados locais do licenciador/central.
2. Configurar no servidor `PDV_LICENCA_CHAVE` com o arquivo secreto da **mesma** chave.
3. Abrir uma loja identificada como emissão local e selecionar **Transferir emissão
   para nuvem**. A operação exige confirmação e motivo e só funciona com chave conferida.
4. A nuvem preserva o maior prazo já concedido e registra a transferência por loja. O programa
   da loja vem do último código publicado pela central local; se o cadastro disser outro
   programa, a transferência é recusada até corrigir.
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
