# Confiabilidade e operação — 1.9

As melhorias gerais atendem os perfis comerciais existentes, sem depender do perfil
Adega. A interface Tk foi removida; o PDV usa só Qt/PySide6, ainda em homologação gradual.
Não ative NFC-e, iFood, cobrança automática ou serviços bancários por causa desta entrega.

## 1. Roteiro automático isolado

Execute no código-fonte:

```powershell
python -m src.app --homologacao resultado-homologacao.json
```

No executável que inclua esta versão, use
`WillPDV.exe --homologacao resultado-homologacao.json`.
O arquivo de saída deve ser novo e ter extensão `.json`; não é sobrescrito.
Código de saída zero e `"ok": true` indicam que os cinco cenários passaram.
O relatório traz os cenários aprovados e eventual erro; uma falha não vira aprovação.

O roteiro cria exclusivamente um banco fictício numa pasta temporária, ignora
`PDV_DB`, não abre a loja e não contata Telegram, nuvem, impressora ou banco/cartão.
Confere retomada da mesma venda/pagamento parcial, reversão transacional de
fechamento interrompido, ausência de duplicação ao fechar novamente, impressão
incerta e cópia SQLite restaurada isoladamente. A suíte de desenvolvimento
também encerra abruptamente um processo filho para conferir recuperação real do
SQLite; isso não equivale a desligar fisicamente o PC.

## 2. Retomada após interrupção

O balcão aberto e os pagamentos já confirmados permanecem no banco e são retomados.
Confira a venda existente antes de lançar de novo um pagamento recebido.
Uma transação ainda não confirmada é revertida pelo SQLite.
Não há consulta automática ao extrato bancário para descobrir se um Pix/cartão ocorreu.

A fila grava **Em envio** antes de chamar o dispositivo. Ao reiniciar o serviço,
um envio abandonado vira **Interrompido: conferir papel** e bloqueia os documentos
seguintes do mesmo destino, sem parar o outro destino. O indicador do caixa,
a visão geral Qt e os alertas operacionais mostram a pendência.

Em **Utilitários > Fila de impressão**, selecione o envio interrompido:

- **Confirmar papel**: somente depois de conferir que saiu completo; não reenvia.
- **Autorizar reenvio interrompido**: permite nova tentativa, com aviso de possível
  duplicata. A escolha registra operador e data no log.

Envios incertos não entram em reenvio em lote, cancelamento comum nem limpeza.
**Enviado** significa comando aceito pelo transporte, não confirmação física.
Falhas comuns de comunicação mantêm a espera progressiva existente.
Não há garantia de impressão física exatamente uma vez: pode haver queda depois
de sair o papel e antes de gravar o resultado.

## 3. Recuperação de backup comprovada em isolamento

Além de criar o arquivo, use o teste de recuperação para verificar uma cópia
restaurada em pasta temporária, sem substituir o banco em uso.
Confira a data e o resultado da última verificação.
Backup externo cifrado exige a senha correta, mantida somente em memória durante
a verificação. Ver [backup externo](BACKUP_EXTERNO.md).
Arquivo criado, upload concluído e restauração possível são verificações distintas.

## 4. Acabamento Qt para notebook e teclado

A visão geral tem rolagem independente no menu e no conteúdo. `Ctrl+K` foca a
busca de módulos; a busca ignora acentos e não modifica permissões.
A fila distribui suas ações em linhas, sem exigir uma barra horizontal gigante.
O diagnóstico e as configurações de periféricos permitem conferir os equipamentos
sem lançar uma venda. Ver [interface Qt](INTERFACE_QT.md).

## 5. Fechamento explicativo

Confira o esperado, o informado e a diferença por forma de recebimento.
Uma diferença exige justificativa e autorização antes de encerrar; não impede
fechar quando o procedimento de autorização é concluído.
Os pagamentos de vendas que atravessam turnos pertencem ao turno do recebimento,
não são deslocados pela data do fechamento da venda.
O fechamento já confirmado não é desfeito por falha na impressão do relatório.

## 6. Devolução depois da venda fechada

A devolução parcial ou total deve apontar o cupom original e registrar motivo,
autorização, itens, retorno opcional ao estoque e reembolso explícito.
A venda original permanece no histórico; não apague pagamentos ou edite o cupom.
**Troca é devolução mais nova venda**, não alteração retroativa de preço.
O registro no PDV não efetua um estorno bancário.
Consulte os limites e o procedimento em [devoluções](DEVOLUCOES.md).

## 7. Diagnóstico de periféricos

O painel reúne impressora, gaveta, balança e leitor.
Nenhum teste físico deve rodar ao abrir a tela. Envie comandos apenas após
confirmação; confira separadamente papel, abertura da gaveta, leitura de peso e
leitura do código. Um comando enviado não é uma homologação.
Ver [impressão e periféricos](IMPRESSORA.md).

## 8. Resumo Telegram agendado

O agendamento diário fica ativo às **23:00 locais**, conforme autorizado.
O horário é editável nas duas interfaces. Bot ligado, token e pareamento do dono
continuam obrigatórios; não se habilita um bot sem configuração.
Se o PC estiver desligado, o envio pendente é recuperado quando o programa voltar;
não existe serviço local funcionando com o PC desligado.
Consulte a política de recuperação e os estados em [Telegram](TELEGRAM.md).

## Antes de instalar na loja

1. Guarde o backup e a senha de recuperação fora do PC. Teste a restauração isolada.
2. Rode o roteiro automático e os autotestes da interface escolhida.
3. Para ensaiar dados reais, use **uma cópia** com `PDV_DB`; outra pasta de
   instalação sozinha não isola `%LOCALAPPDATA%\WILL-PDV`.
4. Confira venda parcial, fechamento, devolução, conta/estoque e resumo do dono.
5. Homologue impressora, falta de papel, gaveta, balança, leitor, escala e teclado
   no equipamento da loja. Faça ensaio controlado de interrupção apenas na cópia.
6. Use uma interface/instância por banco. Não confunda ZIPs antigos com esta versão.

A aprovação automática não certifica hardware, energia elétrica, sincronização de
pasta, estornos bancários ou disponibilidade do Telegram.
