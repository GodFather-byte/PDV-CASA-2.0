# HANDOFF

## Último trabalho

**Melhorias incrementais da Adega**, sem mudar versão (PDV 1.6.0 / licenciador 1.1.0), esquema ou regras de cobrança.

- `ProdutoController.explicacao_preco_adega` centraliza rótulo, faixa e economia sobre o preço já aplicado.
  Caixa Tk mostra detalhe fora da grade, inclusive em notebook; Qt mostra descrição e dica nas células.
- Diálogo Tk de cascos: Todas trocas (F2), Sem troca (F3), prévia financeira e validação com correção sem fechar.
  Preservados `floor(quantidade)` e cancelamentos independentes de bebida/casco. Qt mantém seu diálogo anterior.
- Estoques Tk/Qt: seletor Geral/Adega, recorte por categorias/configurações, prioridade de reposição e resumo do recorte.
  Filtros continuam combináveis. Pedido e lista de compras continuam **gerais**, com aviso nas telas.
- Plano técnico/funcional, critérios de aceite, métricas, decisões e roteiro manual em `docs/ADEGA_MELHORIAS.md`,
  ligado pelo guia `docs/ADEGA.md`. Top 1 recomendado: reposição por giro e prazo, com aprovação humana.
- Sem alterações de pasta, ponto de entrada ou comandos; `.ai/MAPA.md` não precisou mudar.

### Validação

- Linux, Python 3.12, Xvfb 1920×1080×24, Qt offscreen: **2189 testes, OK, 15 ignorados** pelo ambiente.
- Recorte direcionado (preços, cascos, estoque e telas Tk/Qt): **161 testes, OK**, sem ignorados.
- `python -m src.app --autoteste /tmp/adega-autoteste-tk.txt` e
  `python -m src.app --autoteste-qt /tmp/adega-autoteste-qt.txt`: **OK**, bancos isolados.
- Consulta + resumo Adega: 5.000 produtos sintéticos em memória, aproximadamente 53 ms (não mede renderização/hardware da loja).
- Revisão automatizada de código e segurança: pendente ao registrar este estado.
- **Não homologado nesta entrega:** impressora/leitor físicos, Windows na prática e roteiro manual com operador da loja.

## Pendências

- Adega: executar checklist manual do novo documento antes de instalar. Faixa explicativa vem do cadastro atual;
  economia vem do preço-base gravado. Não editar faixa durante atendimento; snapshot histórico exigirá migração futura.
- Adega futura: reposição por giro/prazo, paridade de atalhos/prévia de cascos Qt, cancelamento parcial guiado,
  importação de atacado gelada, etiquetas, múltiplas faixas e saldo de cascos por cliente (exigem decisões do dono).
- Mantidas as pendências anteriores de publicação da 1.6.0 na nuvem e release versionada; homologar Render/Neon e
  PWA em celular real. Confirmar Auto-Deploy e providenciar rotação das credenciais anteriormente sinalizadas.
- Licença segue manual; nuvem só para painel do dono. Asaas continua fora de uso (PR #2 fechado; histórico preservado).
  Não abrir Tk e Qt ao mesmo tempo sobre o mesmo banco. Estoque continua por caixa, não somado entre caixas.
- Painel: limitar envio inicial ao período de retenção, senha no próprio app do celular e push.
- Qt fora da Adega: pré-pago, rodízio/perfil, impressão por setor, dividir conta, balança e acerto das garotas.
- Demais pendências anteriores (pré-pago, impressão física, backup em outra máquina, renovação de licença e recursos
  avançados) seguem sem alteração; detalhes no histórico anterior deste arquivo e nos guias existentes.
