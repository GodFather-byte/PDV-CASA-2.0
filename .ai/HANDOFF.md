# Handoff — Tutoriais no topo do menu (12/11/2026)

Pedido do dono: colocar um menu Tutoriais bem no topo, antes de Operação.
Branch `tutoriais-no-topo`, criada de origin/main (1.14.2).

## Pronto

- `src/ui_qt/app.py`: Tutoriais é a primeira categoria do menu lateral,
  seguida de Operação. Reutiliza a antiga categoria Ajuda, mantendo sete
  categorias e o espaçamento compacto que passou no Windows.
- Botão Cadastrar um produto inicia o guia diretamente, sem seletor repetido.
  Mantém verificação de acesso, repetição do guia e entrada Primeiros passos.
- Texto comum às três edições. Próximos guias ainda não implementados:
  grupo/subgrupo; operador com senha; cliente/caderneta.
- Versão preparada 1.14.3 e MAPA atualizado.

## Validação

31 testes de tutorial, primeiros passos e operação responsiva passaram em
QT_QPA_PLATFORM=offscreen. Novo caso confere ordem das categorias e abertura
real do guia pelo botão. diff --check passou. CI Windows e build final ainda
precisam ser conferidos antes de disponibilizar o instalador.

## Produção e pendências preservadas

Casa Verde foi recuperada pelo instalador manual 1.14.1. Correção de retomada
1.14.2 foi integrada pelo PR #81 e publicada. A causa local não foi confirmada
por logs. Render continua com PDV_ATUALIZACAO_PAUSADA=1 e
PDV_ATUALIZACAO_CLIENTE_MINIMO=1.14.2; NÃO reativar automaticamente por causa
desta alteração visual. Não houve alteração em backend, sincronizador, banco,
licença, assinatura ou variáveis da nuvem neste trabalho.

A primeira correção de clientes antigos pode exigir instalador completo manual.
Ainda falta confirmação da instalação da correção na Casa Verde e homologação
de UAC/antivírus/reboot nas lojas antes de retirar a pausa. Publicação do pacote
não comprova instalação em cada caixa. Não expor segredos nem apagar dados.
