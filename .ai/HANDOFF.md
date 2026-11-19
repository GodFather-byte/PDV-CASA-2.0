# Handoff de 19/11/2026

Branch local `reformulacao-visual-pdv`, baseada em `d7511fa` da main (1.14.18).

## Interfaces

- As três edições do PDV usam os novos temas Qt claro e escuro. Login, menu, mesas, caixa, recebimento e fechamento foram reorganizados. Os atalhos de consulta do menu seguem o acesso do operador. A fotografia usada na entrada acompanha o empacotamento.
- Estoque mostra falta e reposição. O relatório de vendas apresenta total apurado, cupons e ticket médio. Cadastros, configurações, contas, utilitários, diagnose, cozinha, portaria e janelas auxiliares compartilham os estilos dos formulários, tabelas e avisos.
- O painel do dono, a central do fornecedor, a retaguarda, o cardápio, o site comercial, a fila da cozinha e o porteiro receberam layouts para suas tarefas e tamanhos de tela. As três PWAs versionam seus próprios caches.
- O licenciador Tk separa os dados de emissão da entrega do código e agrupa os campos de conexão da central local.

## Conferência

Usado Python 3.12 no Linux com as dependências travadas, Qt offscreen e X virtual para Tk. O verificador de geometria examinou 56 capturas em 1366 × 728 sem detectar cortes. Em 1024 × 728, a grade de produtos de 12 colunas requer rolagem horizontal no cadastro e em seu tutorial, como na base. Os fluxos web foram exercitados no Chromium com dados de demonstração. Passaram os 211 módulos da suíte Python, os testes Node do painel e das PWAs e o autoteste Qt pelo ponto de entrada das três edições. O instalador Windows aguarda o processo de build e homologação da versão.

## Operação pendente da base

Publicação pelo fluxo de nuvem com Deploy Hook para o commit testado. Permanecem no backlog operacional a configuração da chave da IA no Render, a instalação na Casa Verde, o servidor RustDesk, as sugestões de compra, as etiquetas, a homologação NFC-e DeliciOz, IBS/CBS 2027, a mensalidade EA e o tamanho dos backups no Neon.
