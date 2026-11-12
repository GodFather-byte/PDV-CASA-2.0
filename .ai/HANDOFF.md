# Handoff — Retomada da atualização e Casa Verde (12/11/2026)

## Incidente e produção

Casa Verde informou abre/fecha rapidamente após atualização; voltou a abrir
normalmente após executar manualmente o instalador 1.14.1 do GitHub. A causa
local não foi confirmada por logs. Não atribuir o incidente definitivamente
a uma hipótese de código.

PR #80 integrado e Render PDV_ATUALIZACAO_PAUSADA=1: API conferida com cache
busting, retorna pausada=true e sem pacote nas três edições. A pausa não
reverte downloads já locais. Não alterar vendas, licença ou apagar banco.

## Correção neste branch (`corrigir-retomada-atualizacao`)

- Instaladores encerram o PDV sem /T, preservando cmd/instalador descendentes.
- Script verifica saída do instalador, usa a pasta de instalação original,
  registra log e exige comprovante da versão nova (retorno zero de executável
  antigo não basta). Em falha tenta restaurar a cópia e registra resultado.
- O pendente é consumido antes de disparar; uma tentativa não confirmada
  exige conferência, sem repetir instalação a cada abertura. Backup preservado
  por versão; arquivo ausente/versão inválida não disparam instalador.
- Confirmação verifica versão esperada e dependências Qt; comprovante novo só
  nasce depois de conferir. Botão Instalar passa o callback real (antes podia
  anunciar instalação sem executá-la).
- PDV_ATUALIZACAO_CLIENTE_MINIMO permite impedir oferta automática a clientes
  com o mecanismo antigo. Configurar 1.14.2 antes de retirar a pausa: a primeira
  correção pode exigir instalador manual, que o cliente pode executar remotamente
  orientado, sem visita. Não prometer que a versão antiga conserta a si própria.
- Versão preparada 1.14.2. Não reativar oferta sem homologar o fluxo completo.

## Validação

- 68 testes focados passaram em offscreen; quatro casos exclusivos Windows
  pulados localmente. Incluem regras de tentativa, confirmação e versão mínima.
- Casos Windows executam cmd real com executáveis controlados compilados em C#:
  sucesso; instalador falha; executável antigo retorna zero; instalador encerra
  o pai sem matar cmd/filhos. O comando taskkill vem do .iss real.
- actionlint e diff --check; resultado de CI Windows/build ainda a conferir.
- Suíte completa iniciada nesta revisão, aguarda relatório. Tk sem display é
  limitação conhecida. Não confundir processos controlados com UAC/antivírus/
  reboot homologados em todas as lojas.

## Próximos passos

Conferir CI e instalar/autotestar os executáveis no Windows antes de publicação.
Manter a oferta automática pausada até validar; preservar chave pública e privada
existentes. Não expor segredos. Estado de Casa Verde: recuperado, segundo o dono.
Próximos tutoriais: grupo/subgrupo, operador com senha, cliente/caderneta.
