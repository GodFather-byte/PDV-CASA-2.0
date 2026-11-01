# Telegram desligado

O bot do dono e o bot administrativo da central saíram do programa. A licença continua pela
linha de comando (`python -m licenciador.central_cli`) e pela ponte HTTPS. Não há serviço de
Telegram no Render.

O que desligar fora deste repositório:

- O bot criado no BotFather (o do dono e, se existir, o da central do fornecedor).
- A variável `WILLCENTRAL_TELEGRAM_TOKEN` no computador do fornecedor.
- O token que ficou gravado no caixa, em Configurações, chave `telegram_token`. O programa não
  lê mais essa chave; pode apagar o valor no banco se quiser. As tabelas `telegram_chats` e
  `telegram_fila` continuam no arquivo da loja, sem uso, para não apagar histórico.

O resumo do dono agora é o link do WhatsApp (Configurações > Nuvem > WhatsApp do dono).
