# Handoff — Correção da publicação de atualizações (12/11/2026)

Branch `corrigir-atualizacoes`, criada de `origin/main`. Separada do tutorial
(`tutorial-guiado`, PR próprio). Não fazer merge sem revisão. Pedido do dono:
parar de depender de visitas às lojas para atualizar.

## Diagnóstico comprovado (sem alterar produção)

- Último build main `ff93bf2`, job 130939306742, gerou 1.14.0 e saiu com sucesso
  mesmo informando chave ausente. A versão não foi publicada aos caixas.
- API em willpdv-nuvem-6sp0.onrender.com oferecia apenas 1.12.0 em PDV/Adega.
  Assinaturas conferidas com a chave pública do código; HEAD dos instaladores
  R2 retornou 200 e tamanho igual ao manifesto.
- Will Restaurante recebia 422 (edição não aceita).
- Render: serviço srv-dbf5untg1s2s73ejihdg, workspace tea-d3ekasbuibrs73caqdog
  previamente confirmado pelo dono; principal main com auto-deploy por commit.
  Não houve alteração de variáveis, deploy manual ou troca de chaves.

## Pronto no branch

- Publicação falha sem chave/token/URL; verifica a compatibilidade da assinatura
  e confere bytes/hash do instalador público antes de anunciar.
- Workflow reutilizável publica downloads permanentes em Releases públicos,
  por edição e commit. Não substitui instalador já anunciado. Jobs PDV/Adega e
  Restaurante chamam esse workflow. Continua havendo instalador manual separado.
- Manifesto JSON disponível em artefato/Release depois da conferência. `--saida`
  também permite guardar o JSON durante publicação pelo terminal.
- Restaurante aceito no protocolo/CLI. Versão 1.14.1.
- A API preserva os campos assinados quando a versão está abaixo da mínima;
  a exigência de instalar continua sendo calculada pelo cliente.
- Guia ATUALIZACAO.md atualizado; não altera src/sync/sincronizador.py.

## Validação

- 57 testes focados passaram: publicação, atualização automática, tela Qt,
  empacotamento e integração do build. O contrato de permissões do workflow
  foi ajustado para o novo job de publicação (build continua só leitura).
- actionlint 1.7.7 passou nos três workflows alterados/criados.
- Suíte completa executada: 2.746 testes, 24 pulados; duas falhas do
  licenciador e um erro da central por falta de display Tk. Houve também
  falha no contrato antigo que contava três jobs com escrita; ele foi
  atualizado para quatro (novo publicador assinado). Reexecução focada de
  57 testes incluindo esse contrato passou; a suíte completa não foi
  repetida depois desse ajuste do teste.
- Não houve build/instalação física Windows nem atualização de loja real nesta
  sessão. Não afirmar que as lojas já receberam 1.14.1.

## Pendências e continuidade

- O dono foi perguntado sobre a chave privada usada na 1.12.0. Não solicitar o
  valor em chat. Configurar no segredo PDV_ATUALIZACAO_CHAVE do GitHub, juntamente
  com PDV_NUVEM_URL e PDV_API_TOKEN, somente pelo cofre de segredos.
- Não gerar outra chave e substituir a pública: isso rompe a confiança dos
  caixas já instalados. Sem a original, não é possível assinar novas versões
  compatíveis com a confiança antiga; planejar migração explicitamente.
- Depois de revisão/merge e configuração: verificar job de publicação, API
  pública por edição, assinatura, download/hash e a versão relatada por cada
  loja. Publicação não confirma instalação. Caixas sem o atualizador exigem
  instalação inicial; confirmar versões das lojas (pergunta enviada).
- O repositório precisa continuar público para estes URLs de Release. Se for
  privado, o workflow falha e será necessário HTTPS público, como o R2 anterior.
- Tutorial pendente de revisão no outro branch; próximos tutoriais: grupo e
  subgrupo; operador com senha; cliente/caderneta.
