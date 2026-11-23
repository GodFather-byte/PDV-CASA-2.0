# Handoff de 23/11/2026

Branch `cursor/site-termos-privacidade-a6ba`, a partir da main `25141b4` (site comercial do #139).

## Site comercial

- Páginas `/site/termos` e `/site/privacidade` (com e sem barra final), no mesmo `estilo.css`, com o cabeçalho e o rodapé do site. Textos em pt-BR, data 23 de novembro de 2026, responsável WillPDV - Willyan Neres, Osasco-SP.
- O rodapé de `/`, `/site` e das duas páginas aponta para Termos de Uso e Política de Privacidade.
- Sob o botão do teste grátis: “Ao enviar, você concorda com os Termos de Uso e a Política de Privacidade”, com links. O POST `/v1/site/teste` e o `/v1/saude` não mudaram.
- `[CNPJ]` só existe em comentário HTML. Sem endereço de rua nem e-mail inventados.
- O site de vendas não grava cookie nem armazenamento local. A política descreve a sessão do painel, a memória do cardápio e o cookie do porteiro.

## Conferência

`tests.test_site` e `tests.test_site_teste`. Páginas abertas no navegador em desktop e celular.

## Operação pendente da base

Publicação da nuvem e o backlog operacional da main (chave da IA no Render, Casa Verde, RustDesk, NFC-e, backups no Neon). Este branch ainda não foi publicado no Render.
