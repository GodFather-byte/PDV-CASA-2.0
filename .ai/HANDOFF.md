# Handoff — Consulta automática e novo assistente de produtos (12/11/2026)

## Atualizações: falha identificada

Sincronizador e serviço interno usam http=None por padrão. O cliente de
atualização retornava sem consultar nessa condição; a publicação do manifesto
não bastava para os caixas buscarem o pacote automaticamente.

Branch corrigir-consulta-automatica: rodada agora carrega requests quando não
há cliente injetado. Retomada na abertura usa somente_local=True, preservando
abertura sem rede e sem download síncrono. Versão 1.14.4 preparada.
66 testes focados passaram (retomada, atualização, Qt e rede de caixas).
Também havia dependência de sync_quase_tempo_real=N (padrão): serviço interno
nem rodava a busca. Criado ServicoAtualizacao independente, iniciado pelo App
no caixa principal com banco em arquivo, a cada 30 s (consulta HTTP respeita
intervalo de 6 h do cliente). Trava por banco serializa App e --sync para não
baixar/instalar duas vezes. Novos módulos registrados no autoteste.
70 testes focados passaram. Homologação nova no CI abre o executável instalado
com banco/nuvem fictícios e sync_quase_tempo_real=N, exigindo consulta real
HTTP automática sem fechar o programa, nas três edições.
A instalação automática agora espera turno fechado e nenhuma venda aberta;
o operador pode iniciar manualmente com o caixa livre. Downloads podem ocorrer
em segundo plano durante o trabalho.
71 testes focados passaram após proteção do turno. Geração, instalação,
autoteste e consulta HTTP real do executável instalado passaram nas três edições
(revisão e26204f). Ajustes posteriores preservaram Operação aberta por padrão
com Tutoriais no topo (46 testes de regressão passaram) e proteção de turno.
Suíte completa inicial: 2.773 testes, 28 pulados; falhas Tk conhecidas e três
expectativas de menu, corrigidas pelo padrão Operação e reexecutadas com sucesso.
Não houve nova suíte completa após esses ajustes. src/sync/sincronizador.py
não foi alterado. Falta publicação final e reativação com mínimo 1.14.4.

## Produção

Casa Verde recuperada manualmente em 1.14.1; 1.14.2 corrigiu instalação e
1.14.3 colocou Tutoriais no topo. Render ainda tem pausa global e mínimo
1.14.2. Não remover proteção para mecanismos antigos sem validar o caminho.
Uma primeira atualização de clientes antigos poderá precisar ser executada
pelo operador com link ou acesso remoto, sem visita do fornecedor. Não
prometer atualização remota de código que ainda não faz a consulta HTTP.

## Novo escopo pedido pelo dono (ainda não implementado)

Assistente com Gemini (preferência pela cota gratuita do Google AI Studio):
ler fotos/PDF de notas de fornecedor, preparar cadastro de produtos e custos,
e procurar fotos na internet para a adega. Para produtos existentes manter
preço de venda e alertar quando a margem cair. Produtos novos: preço definido
pelo operador. Conferência antes de gravar. Chave só na nuvem, nunca nos caixas.

Já existem importação XML e NotasDonoController; fotos via Open Food Facts,
inclusive busca em lote com aprovação. Reutilizar essas regras e evitar
cadastros duplicados/associação automática de embalagem errada. Necessária
configuração segura da chave Gemini para validar chamada real; não pedir valor
em chat. Preservar uso offline do caixa. Próximos tutoriais: grupo/subgrupo,
operador com senha, cliente/caderneta.
