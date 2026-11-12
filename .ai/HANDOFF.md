# Handoff — Incidente Casa Verde e contenção (12/11/2026)

Após publicar 1.14.1 nas três edições, o dono relatou que o caixa da Casa
Verde abre e fecha rapidamente. Causa local ainda NÃO confirmada; sem acesso
ao Windows ou log da loja. Pedido de recuperação em andamento.

## Contenção

- Variável Render PDV_ATUALIZACAO_PAUSADA=1 adicionada por merge, preservando
  as demais variáveis do serviço srv-dbf5untg1s2s73ejihdg, workspace confirmado
  tea-d3ekasbuibrs73caqdog.
- Esta alteração faz GET /v1/atualizacao/ultima responder indisponível e sem
  pacote quando pausada. Não exclui manifestos, vendas ou licenças.
- Sete testes de atualização automática passaram localmente, incluindo pausa
  nas três edições. Falta confirmar pausa na API após deploy.
- A pausa na nuvem não desfaz downloads já guardados nos computadores.

## Recuperação orientada

Dono orientado a executar o instalador completo WillPDV 1.14.1 pelo navegador,
na mesma pasta do programa, sem desinstalar/apagar dados. Aguardar resultado.
Se persistir, coletar logs/pdv.log em %LOCALAPPDATA%/WILL-PDV e a mensagem
ou diagnóstico do executável. Não afirmar que o caixa foi recuperado.

## Falhas encontradas para correção do atualizador

- aplicar.cmd não confere o código de saída do instalador e confirma sem
  passar a versão esperada: uma versão antiga pode ser confundida com nova.
- PrepareToInstall usa taskkill /F /T, podendo encerrar descendentes do PDV,
  incluindo o cmd/instalador disparado pelo próprio processo. Hipótese, não
  prova da causa da Casa Verde.
- Retomada no início pode repetir tentativa pendente. Evitar novas instalações
  automáticas antes de corrigir e homologar no Windows com processo real.
- Não retirar PDV_ATUALIZACAO_PAUSADA até validação da correção e recuperação.

## Estado anterior preservado

PRs #78/#79 integrados, versão 1.14.1 publicada; assinaturas e hashes dos três
instaladores verificados. 88 testes focados de integração passaram; jobs
Windows específicos passaram. Chave de atualização original, URL e token
foram configurados pelo dono no GitHub. Não expor valores.
Próximos tutoriais: grupo/subgrupo, operador com senha, cliente/caderneta.
