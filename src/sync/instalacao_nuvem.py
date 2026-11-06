"""Instalação da loja pelo código da central: configura a nuvem do caixa e busca a licença numa ação só.

Substitui digitar, em Configurações > Nuvem, o endereço, a chave da loja e o token, e liga o painel do dono no celular.
A licença vem da nuvem quando a loja já tem validade ou plano pago registrado na central.
"""
from __future__ import annotations

import logging

from src.core import codigo_instalacao, licenca
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.sync import licenca_nuvem

log = logging.getLogger("pdv.instalacao")


class OutraLoja(ErroNegocio):
    """O caixa já está configurado para outra loja: trocar só com confirmação explícita."""

    def __init__(self, atual: str, nova: str):
        super().__init__(f"Este caixa está configurado para a loja {atual}. O código é da loja {nova}.")
        self.atual, self.nova = atual, nova


def instalar(banco, codigo: str, http=None, trocar_loja: bool = False, timeout=(3, 10)) -> dict:
    """Aplica o código. Devolve {"loja", "licenca_ativa", "mensagem"}. Código inválido ou outra loja: ErroNegocio."""
    dados = codigo_instalacao.ler(codigo)
    atual = banco.cfg("chave_loja").strip()
    if atual and atual != dados["chave"] and not trocar_loja:
        raise OutraLoja(atual, dados["chave"])
    with banco.transacao():
        banco.cfg_set("chave_loja", dados["chave"])
        banco.cfg_set("api_url", dados["url"])
        banco.cfg_set("api_token", dados["token"])
        banco.cfg_set("painel_dono", "S")
        banco.log("instalacao_nuvem", f"Loja {dados['chave']} configurada pelo código de instalação "
                                      f"({dados['url']})" + (f"; antes: {atual}" if atual and atual != dados["chave"] else ""))
    resultado = licenca_nuvem.consultar_resultado(dados["url"], dados["token"], http, timeout)
    licenca_nuvem.registrar_resultado(banco, resultado)
    problema = ""
    if resultado.codigo and resultado.codigo != banco.cfg("licenca_token").strip():
        try:
            licenca.ativar(banco, resultado.codigo)
        except ErroNegocio as erro:                 # outro programa, outra loja, mais antiga que a atual...
            problema = str(erro)
    estado = licenca.estado(banco)
    ativa = not estado.bloqueia and bool(banco.cfg("licenca_token").strip())
    inicio = f"Loja {dados['chave']} conectada à nuvem (envio de vendas e painel do dono ligados)."
    if problema:
        mensagem = f"{inicio} A licença da nuvem não serviu: {problema}"
    elif ativa:
        mensagem = f"{inicio} {estado.mensagem}"
    elif resultado.sucesso:
        mensagem = (f"{inicio} A nuvem ainda não tem licença para esta loja: registre a validade ou o plano na central "
                    "do fornecedor e clique em Ativar licença de novo (ou espere: o caixa consulta sozinho).")
    else:
        mensagem = (f"{inicio} Não foi possível buscar a licença agora ({resultado.erro or 'sem resposta'}). "
                    "Confira a internet; o caixa tenta de novo sozinho.")
    log.info("Instalação pela central: loja %s, licença %s.", dados["chave"], "ativa" if ativa else "pendente")
    return {"loja": dados["chave"], "licenca_ativa": ativa, "mensagem": mensagem,
            "configurado_em": fmt.agora()}
