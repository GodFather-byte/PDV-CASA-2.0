# NFC-e: emissão própria (direto na SEFAZ-SP)

A emissão própria é uma alternativa ao Focus NFe: o caixa monta a nota, assina com o certificado A1 da loja e envia
direto para a SEFAZ-SP. A SEFAZ não cobra por nota, então o custo por nota é zero. O Focus continua disponível como
reserva: trocar de um para o outro é uma configuração por loja (`nfce_provedor`).

## Como ligar numa loja

Em **Configurações > Integrações**:

1. **NFC-e: quem envia à SEFAZ** → *Emissão própria*.
2. **Caminho do certificado A1 (.pfx)** e **senha**. O arquivo fica no computador do caixa e não vai para a nuvem.
3. **Código IBGE do município** (São Paulo = 3550308, Osasco = 3534401) e **número do endereço**.
4. **Regime tributário** (Simples Nacional, MEI etc.).
5. **Série** (normalmente 1) e **próximo número**. Em produção, continue a numeração do sistema anterior da loja.
6. **Responsável técnico**: CNPJ, contato, e-mail e telefone da software house. Preencha quando o CNPJ da empresa
   existir.
7. Ligue a emissão em **Homologação** e faça vendas de teste. Só depois passe para **Produção**.

Os dados da loja (razão social, CNPJ, IE, endereço, bairro, cidade, UF, CEP) vêm de **Dados da loja**.

Antes de emitir, a loja precisa estar credenciada para NFC-e na SEFAZ-SP (portal da NFC-e, menu Credenciamento).
O QR Code versão 3 em emissão normal não usa CSC.

## O que já faz

| Parte | Arquivo |
|---|---|
| Chave de acesso e dígito verificador | `src/fiscal/sefaz/chave.py` |
| XML 4.00 (modelo 65), validado no schema oficial nos testes | `src/fiscal/sefaz/xml_nfce.py` |
| Assinatura XMLDSig (C14N, SHA-1, RSA) com o A1 | `src/fiscal/sefaz/assinatura.py` |
| QR Code v3 e urlChave de SP | `src/fiscal/sefaz/qrcode.py` |
| SOAP 1.2: status, autorização síncrona, consulta, cancelamento | `src/fiscal/sefaz/cliente.py` |
| Provedor na fila do caixa (numeração, XMLs, reenvio seguro) | `src/fiscal/sefaz/provedor.py` |

Tributação aceita hoje:

| Regime | Códigos aceitos |
|---|---|
| Simples Nacional (CSOSN) | 102, 103, 300, 400, 500, 900 |
| Regime Normal (CST) | 40, 41, 50, 60 |
| PIS/COFINS | 04 a 09 e 49 a 99 |

Se um produto usa um código que pede alíquota, a nota fica com **erro** e uma mensagem clara.

**Segurança da numeração.** O número e a chave são gravados antes do envio. Se a resposta se perder, o caixa consulta
a chave na SEFAZ antes de reenviar, para nunca autorizar duas vezes. Os XMLs ficam em `nfce/<ambiente>/` ao lado do
banco:

| Arquivo | O que é |
|---|---|
| `<chave>-assinada.xml` | A nota assinada, antes do envio |
| `<chave>-nfe.xml` | O nfeProc: guardar por 5 anos |
| `<chave>-cancelamento.xml` | O evento de cancelamento |

## Contingência e inutilização

- **Contingência off-line:** se a SEFAZ não responde ao status antes do primeiro envio de uma nota, ela sai em
  contingência (tpEmis 9) com o QR Code v3 assinado pelo A1 (RSA-SHA1 de `chave|3|tpAmb|dia|vNF|tp_idDest|idDest`).
  O cupom sai na hora com "EMITIDA EM CONTINGÊNCIA / Pendente de autorização" e a nota é transmitida sozinha, com o
  mesmo XML, quando a SEFAZ volta. Prazo legal: até o fim do primeiro dia útil seguinte. A tela Notas fiscais mostra
  quantas estão em contingência. Desligar: `nfce_contingencia = 0`.
- **Inutilização:** na tela Notas fiscais, selecione a nota rejeitada que não será corrigida > "Inutilizar número"
  (motivo de 15 a 255 letras). O protocolo fica na mensagem da nota e o XML em `nfce/<ambiente>/`.

## Roteiro da homologação (piloto DeliciOz)

1. Com o contador: credenciamento da NFC-e na SEFAZ-SP, IE, série e último número usado, CFOP/CSOSN dos produtos.
2. No caixa: Configurações > Integrações > NFC-e > emissão própria, certificado A1 (.pfx) e senha digitados ali
   (nunca mandados por chat), código do município, número do endereço.
3. Notas fiscais > **Testar SEFAZ**. Esperado: "SEFAZ-SP em operação (107)". Erro de SSL: avisar o suporte (cadeia
   ICP-Brasil).
4. Ligar em **homologação**, fazer 3 vendas (dinheiro, cartão, Pix) e uma com CPF; conferir "Autorizada" e o cupom.
5. Cancelar uma delas (até 30 min) e conferir "Cancelada".
6. Tirar o cabo de rede, vender, conferir o cupom de contingência; religar e conferir que vira "Autorizada".
7. Contador conferiu: ligar em **produção** e acertar `nfce_proximo_numero_producao` com o último número + 1.

## Ainda falta

- **Cópia dos XMLs na nuvem.**
- **IBS/CBS** na emissão própria. É obrigatório para o Simples a partir de 2027; o regime normal já deveria informar.
- **Primeiro teste real em homologação.** Se aparecer erro de SSL, é preciso incluir a cadeia de certificados
  ICP-Brasil para conferir o servidor da SEFAZ.
