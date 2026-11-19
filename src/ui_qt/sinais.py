"""Sinal do Qt para método de objeto comum (que não é QObject): sempre por `ligar_metodo`.

Por quê: no executável o código de `src/` é compilado (Nuitka). O PySide reconhece o método compilado pelos atributos
(`im_func`, `im_self`) e, nesse caminho (libpyside, `DynamicSlot::create`), não conta a referência da função; quando a
ligação morre (a janela que emite fecha, ou alguém chama `disconnect`), solta uma referência que nunca pegou. A função
do método é destruída ainda presa à classe, e a próxima chamada cai em outra função ou derruba o programa. Foi o erro
"descrever_garota() got an unexpected keyword argument 'confirmar'" ao fechar o WillPDV 1.14.9: `App.encerrar` tinha
sido destruída quando a tela de entrada fechou.

Não acontece com: método de QObject (janela, diálogo, widget), lambda, função solta nem `functools.partial`. Por isso
`botao.clicked.connect(self.salvar)` dentro de uma janela continua certo. O que não pode é `sinal.connect(obj.metodo)`
quando `obj` é de uma classe comum (App, travas, serviços, controladores). O teste `tests/test_qt_sinais.py` varre o
código atrás disso, e o autoteste do executável confere a contagem das funções (`fotografar_funcoes`).
"""
from __future__ import annotations

import gc
import sys
import weakref

# Quantas referências a mais o autoteste segura de cada função: é quantas vezes o defeito pode repetir na mesma
# função sem destruí-la antes da conferência.
GUARDA = 64


def ligar_metodo(sinal, objeto, nome: str):
    """Liga `sinal` a `objeto.nome(...)` e devolve a função ligada (é ela que se passa a `sinal.disconnect`).

    A referência ao objeto é fraca, como o PySide faz com método: a ligação não segura o objeto vivo, e depois que ele
    morre o sinal não chama mais nada."""
    fraca = weakref.ref(objeto)

    def chamar(*argumentos):
        alvo = fraca()
        if alvo is not None:
            getattr(alvo, nome)(*argumentos)

    sinal.connect(chamar)
    return chamar


def _contar(foto) -> list[int]:
    """Um caminho só para contar, na fotografia e na conferência: assim as referências de passagem são as mesmas."""
    gc.collect()        # lixo em ciclo (quadro de exceção antiga, gerador) segura função e depois some
    return [sys.getrefcount(item[1]) for item in foto]


def compilado(funcao) -> bool:
    """Se a função veio do código compilado (no código-fonte o defeito do PySide não aparece)."""
    return type(funcao).__name__.startswith("compiled_")


def fotografar_funcoes(prefixo: str = "src") -> list[list]:
    """Fotografa a contagem de referências de toda função definida em classe dos módulos `prefixo` já importados.
    Cada item é [rótulo, função, guarda, contagem].

    É para chamar antes de criar qualquer janela: nessa hora ninguém segura método de ninguém, então a contagem é a
    menor que a função pode ter. Cada função fica com `GUARDA` referências a mais (a guarda), para que o defeito
    apareça como contagem menor em vez de destruir a função."""
    foto = []
    for nome_modulo, modulo in sorted(sys.modules.items()):
        if modulo is None or not (nome_modulo == prefixo or nome_modulo.startswith(prefixo + ".")):
            continue
        for classe in list(vars(modulo).values()):
            if not isinstance(classe, type) or classe.__module__ != nome_modulo:
                continue
            for nome, valor in list(vars(classe).items()):
                funcao = valor.__func__ if isinstance(valor, (staticmethod, classmethod)) else valor
                if type(funcao).__name__ in ("function", "compiled_function"):
                    foto.append([f"{nome_modulo}.{classe.__qualname__}.{nome}", funcao, [funcao] * GUARDA, 0])
    del funcao, valor, classe, modulo
    for item, contagem in zip(foto, _contar(foto)):
        item[3] = contagem
    return foto


def funcoes_soltas(foto) -> list[str]:
    """As funções que perderam referência desde a fotografia: cada uma foi ligada direto a um sinal do Qt por um
    objeto que não é QObject. Lista vazia é o certo."""
    return [f"{item[0]} (perdeu {item[3] - agora})" for item, agora in zip(foto, _contar(foto)) if agora < item[3]]
