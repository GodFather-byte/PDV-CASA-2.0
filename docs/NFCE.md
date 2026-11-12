# NFC-e (Will Fiscal)

Cupom fiscal eletrônico (modelo 65) para São Paulo, por enquanto via **Focus NFe** (plano Varejo). Vem desligado
em todas as edições; liga por loja, quando o cliente pede.

## Como funciona

1. A venda fecha normalmente no caixa (o `CaixaController` não muda).
2. O `ServicoFiscal` (thread, a cada 4 s, só no caixa principal) vê as vendas fechadas desde que a emissão foi
   ligada e cria uma linha em `nfce_notas` (a referência é o `uuid` da venda, então nunca sai nota em dobro).
3. Monta a nota (`src/fiscal/nfce.py`) e manda para a Focus (`src/fiscal/focus.py`).
4. Autorizada: grava chave, número, QR Code e põe o cupom fiscal na fila de impressão do caixa (`src/fiscal/danfe.py`).
5. Sem internet ou provedor fora: tenta de novo em 1, 2, 5, 10 e 30 minutos. A venda nunca trava.
6. Rejeitada ou cadastro incompleto (sem NCM, sem CNPJ): fica na lista com o motivo; corrige e clica em Reenviar.
7. Venda cancelada no caixa: a nota é cancelada sozinha (se ainda estiver dentro dos 30 minutos).

Tela: menu **Gestão > Notas fiscais (NFC-e)** (permissão `fiscal_nfce`, nível 3): lista, reenviar, CPF na nota,
reimprimir, cancelar com motivo e ligar/desligar a emissão.

## Ligar numa loja (roteiro)

1. Criar a conta na Focus NFe e cadastrar a empresa lá. **O certificado A1 (.pfx), a senha e o CSC (token do QR
   Code, pego no site da SEFAZ-SP) vão no painel da Focus**, não no PDV e nunca por chat.
2. PDV: Cadastros da loja com razão social, CNPJ, IE e endereço. Produtos com **NCM** (8 dígitos); CFOP, CEST e
   origem só se forem diferentes do padrão. Tipos de pagamento: "Forma na nota fiscal" só se o nome não disser.
3. Configurações > Integrações: token de homologação, regime, CFOP/CST padrão (combinar com o contador).
4. Notas fiscais > Ligar / desligar > Homologação. Fazer vendas de teste: dinheiro, cartão, Pix, desconto, taxa,
   CPF na nota, cancelamento.
5. Contador confere. Token de produção em Configurações e liga em Produção.

## Padrões (Simples Nacional)

CFOP 5102, CSOSN 102, PIS/COFINS 49. Bebida com substituição tributária costuma ser CFOP 5405 e CSOSN 500: isso vai
no cadastro do produto. Regime Normal (lucro presumido/real) precisa do contador e do grupo IBS/CBS
(`nfce_ibscbs_enviar = S`, obrigatório para Regime Normal a partir de 03/08/2026).

## A conferir na homologação

- Troco: mandamos o pagamento líquido (pago menos troco), sem o campo de troco.
- Cartão: não mandamos o grupo do cartão (tipo de integração, bandeira). Se a SEFAZ-SP rejeitar, entra aqui.
- GTIN (código de barras) não vai; a Focus costuma preencher "SEM GTIN" sozinha.

## Ainda não tem

- Contingência offline (emitir sem internet e transmitir depois). Hoje a nota fica esperando a internet voltar.
- Inutilização de numeração e emissor direto na SEFAZ (sem a Focus): a troca fica só em `src/fiscal/focus.py`.
