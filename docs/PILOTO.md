# Piloto na boate: checklist

Piloto = a boate usa o WillPDV de verdade, com **plano B ligado** (o sistema atual ou papel) nas primeiras noites.
O que o projeto já provou e o que ainda falta provar em loja estão separados abaixo.

## Já verificado (sem loja)
- Suíte automática (regras e telas) passando em Windows e Linux, Python 3.10 e 3.12.
- Noite simulada: 576 vendas, 24 cancelamentos, 4 formas de pagamento e sangrias. A gaveta fechou ao centavo (resultado do turno 0)
  e tudo levou menos de 1 segundo.
- O programa abre, cria o banco, faz backup automático, recusa duas instâncias e confere a integridade do banco.

## Antes do dia (no seu computador e no PC do caixa)
1. **Licença.** No `.exe` a licença é sempre exigida. Confirme que você consegue emitir um código com a sua chave
   (`python -m tools.gerar_licenca emitir --loja NOME-DA-BOATE --dias 30` ou `--permanente`). Se der erro de chave que não
   corresponde, resolva **antes**: sem o código o caixa não entra. Teste a colagem do código num PC de teste.
2. **Instalador.** Baixe o instalador gerado pelo GitHub Actions (`docs/INSTALAR_E_TESTAR.md`) e instale num PC de teste. O
   Actions já abre o programa empacotado e o instalado num Windows (autoteste), mas **ninguém ainda operou o caixa** nele:
   faça o roteiro de teste do guia. Confira também antivírus/SmartScreen no PC da boate.
3. **Impressora térmica e gaveta.** Só foram testadas com impressora simulada. Teste no equipamento real: acentos, corte do
   papel, abrir a gaveta (Configurações > Máquinas). Se algo falhar, use o modo "tela" ou Windows e imprima pelo spooler.
4. **Cadastros.** Produtos com preço, "Controla estoque" nos que têm saldo, operadores e senhas (a de fábrica ADM/ADM é
   obrigada a trocar), comissão das garotas, consumação mínima, número de comandas. Lance o estoque (`150 skol`).
5. **Backup.** Configure a **cópia extra** (pendrive ou outro disco) em Configurações > Utilitários e **teste restaurar** um
   backup num PC de teste.
6. **Relógio do Windows** certo e fuso correto (a "virada do dia" é às 6h por padrão).

## Fiscal (decida antes, não depois)
O PDV **não emite documento fiscal** (NFC-e, SAT, ECF). O cupom é "NÃO FISCAL". Confirme com o contador do Eduardo se a boate
pode operar assim ou se mantém outro emissor fiscal em paralelo. Cartão: **sem TEF**, o operador digita o valor que passou na
maquininha.

## Primeiras noites
- Um operador de confiança e o dono presentes; o plano B ligado.
- Fechar o turno **sempre** e conferir a gaveta. Em Utilitários, gere o **pacote de suporte** se algo estranho acontecer.
- Anotar tudo que travou, confundiu ou demorou (foto da tela ajuda). O log de erros fica em `%LOCALAPPDATA%\WILL-PDV\logs`.
- Não atualizar o programa no meio do expediente; o instalador novo só com o turno fechado.

## Critério para sair do piloto
5 noites seguidas sem diferença de gaveta inexplicada, sem travar no horário de pico e com backup e restauração conferidos.

## Limites conhecidos
- Um caixa por banco (sem rede entre vários caixas).
- Pode vender acima do estoque lançado: o saldo fica negativo (é aviso, não bloqueio).
- A licença vale para a loja (nome), não para um computador, e um código emitido não se revoga.
