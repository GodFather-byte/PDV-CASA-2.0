# Entrega 1.13.0 — vários caixas na mesma loja

A versão do programa passou para 1.13.0 e o esquema do banco para 47.

Dois ou mais computadores vendem na mesma loja, no mesmo estoque. Um deles é o caixa principal e guarda o banco.
Os outros se ligam a ele pela rede da loja com um código copiado em **Manutenção > Caixas da loja (rede)** e
colado na tela de entrada do outro computador.

Cada caixa tem o seu número, o seu turno, a sua gaveta e a sua impressora. Produtos, preços, estoque, fiado,
entregas e numeração de cupons são da loja inteira.

Se o caixa principal desligar ou a rede cair, os caixas adicionais param de vender até a ligação voltar. A operação
que estava no meio é desfeita.

Ainda não foi testado com dois computadores Windows reais. Guia e limites em `docs/VARIOS_CAIXAS.md`.
