# Estoque, quartos e painéis de operação

## Venda com estoque zerado

Em Configurações gerais > Parâmetros e módulos, a opção **Permitir vender sem saldo** nasce ligada.
Assim, uma venda com saldo insuficiente pode ser concluída: o estoque fica negativo e permanece visível
para conferência/reposição. Não se inventa uma entrada de mercadoria nem se zera artificialmente o saldo.
A ocorrência é registrada na auditoria (`venda_sem_estoque`, resultado `permitida`). Composições e insumos
fracionados seguem a mesma regra. Cancelar a venda estorna exatamente a quantidade baixada.

O administrador pode desligar essa opção para voltar ao bloqueio por saldo insuficiente. Saídas e ajustes
manuais de estoque não passam a ser liberados por essa opção; mantêm suas permissões e validações.

## Quartos em todos os caixas

Com **usar_quartos** ligado, operadores ativos dos níveis **0 a 4** podem visualizar e operar quartos,
independentemente do turno e do nível mínimo antigo gravado para util_quartos. Configurações de módulos,
acessos e cadastros continuam com suas permissões normais. Sessão trocada, operador inativo e módulo
desligado continuam bloqueando a operação. Turno da manhã e da noite usam a mesma regra.

O painel do caixa mostra até oito quartos por página. Use as setas para navegar; Q + número continua
alcançando qualquer quarto. O painel completo também pagina de oito em oito, sem cortar os cartões.
Relógio, histórico e avisos continuam considerando todos os quartos, inclusive os de outra página.

## Telas sem rolagem geral

- Menu principal organizado por grupos de botões, com status em abas Caixa, Licença, Backup, Impressão e Nuvem.
- Caixa com controles compactos e pagamento organizado em linhas. A área de produtos/pagamento não é mais rolável.
- Busca de produtos abre uma lista sobreposta; não empurra os quartos nem os botões de pagamento.
- Acerto de comissão/shows em duas colunas; quantidade automática/manual e valores continuam separados.
- Relatórios com filtros em grade e altura reservada para exibir todos os campos.
- Janelas abertas pelo menu são limitadas inicialmente à área útil do monitor, considerando a barra de tarefas.

As listas de produtos, vendas, pagamentos e históricos continuam podendo rolar, pois não têm tamanho fixo.
Formulários extensos de configuração/cadastro continuam organizados em abas. Os testes de layout usam área
cliente de 1280×680 (menor que a tela de referência 1366×768), incluindo quartos e painéis de caixa,
estoque, contas, cadastros, cozinha, relatórios e acerto. Conferir no Windows real se houver escala de tela diferente.
