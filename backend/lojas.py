"""Cadastro das lojas da nuvem. Cada loja tem o próprio token; o token aparece UMA vez e só o hash fica guardado.

    python -m backend.lojas criar BOATE-CENTRO "Boate Centro"   # mostra o token da loja
    python -m backend.lojas listar                              # todas as lojas e até quando pagaram (avisa as vencidas)
    python -m backend.lojas novo-token BOATE-CENTRO             # troca o token (o antigo para de funcionar)
    python -m backend.lojas desativar BOATE-CENTRO              # bloqueia envio e painel (ex.: assinatura vencida)
    python -m backend.lojas ativar BOATE-CENTRO
    python -m backend.lojas assinatura BOATE-CENTRO 2026-11-30  # pagou até essa data: o PDV renova a licença sozinho
    python -m backend.lojas assinatura BOATE-CENTRO cancelar    # não emite mais (a licença do caixa vence no prazo)
    python -m backend.lojas cobranca plano BOATE-CENTRO 9900 financeiro@boate.com
    python -m backend.lojas cobranca assinatura BOATE-CENTRO 9900 10 --email financeiro@boate.com --whatsapp "+55 11 99999-9999" --nome "Nome Completo" --documento 00000000000 --cep 00000000 --logradouro "Rua Exemplo" --numero 100 --bairro Centro --cidade "São Paulo" --uf SP
    python -m backend.lojas cobranca emitir BOATE-CENTRO
    python -m backend.lojas cobranca reenviar BOATE-CENTRO
    python -m backend.lojas cobranca gerar BOATE-CENTRO 2026-11-30
    python -m backend.lojas cobranca conciliar BOATE-CENTRO
    python -m backend.lojas cobranca listar
    python -m backend.lojas painel BOATE-CENTRO [senha]         # senha do painel do dono no celular (gera uma se omitir)
    python -m backend.lojas limpar-painel                       # apaga já o que passou da retenção do painel (a nuvem também faz sozinha)

No PDV da loja, em Configurações > Nuvem: a chave da loja (ex.: BOATE-CENTRO) e o token mostrado aqui.
Usa o mesmo banco da API (PDV_NUVEM_DB_URL).
"""
from __future__ import annotations

import re
import secrets
import sys
from datetime import date, datetime

from sqlalchemy.orm import Session

from backend.main import Loja, SessionLocal, hash_token, situacao_assinatura

CHAVE_VALIDA = re.compile(r"[A-Za-z0-9._-]{1,64}")


class ErroLoja(Exception):
    pass


def _gerar_token() -> str:
    return secrets.token_urlsafe(32)


def _obter(db: Session, chave: str) -> Loja:
    loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
    if loja is None:
        raise ErroLoja(f"Loja {chave} não encontrada.")
    return loja


def criar(db: Session, chave: str, nome: str) -> str:
    """Cadastra a loja e devolve o token (a única vez em que ele aparece)."""
    chave, nome = (chave or "").strip(), (nome or "").strip()
    if not CHAVE_VALIDA.fullmatch(chave):
        raise ErroLoja("A chave da loja deve ter de 1 a 64 letras, números, ponto, hífen ou sublinhado.")
    if not nome:
        raise ErroLoja("Informe o nome da loja.")
    if db.query(Loja).filter(Loja.chave_loja == chave).first() is not None:
        raise ErroLoja(f"A loja {chave} já existe. Para um token novo use: novo-token {chave}")
    token = _gerar_token()
    db.add(Loja(chave_loja=chave, nome=nome, token_hash=hash_token(token), ativa=True,
                criada_em=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    return token


def novo_token(db: Session, chave: str) -> str:
    loja = _obter(db, chave)
    token = _gerar_token()
    loja.token_hash = hash_token(token)
    db.commit()
    return token


def definir_ativa(db: Session, chave: str, ativa: bool) -> None:
    _obter(db, chave).ativa = ativa
    db.commit()


def definir_assinatura(db: Session, chave: str, ate: date | None) -> None:
    """Até quando a loja pagou (None cancela). A nuvem passa a emitir licença até essa data para o PDV dela."""
    from backend.cobranca_mercadopago import Plano
    if db.query(Plano).filter_by(chave_loja=chave).first():
        raise ErroLoja("Esta loja usa Mercado Pago: gere a cobrança e aguarde o pagamento. "
                      "Para uma liberação excepcional, emita um código no licenciador.")
    _obter(db, chave).licenca_ate = ate.isoformat() if ate else None
    db.commit()


def listar(db: Session) -> list[Loja]:
    return db.query(Loja).order_by(Loja.chave_loja).all()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    comando, resto = (args[0], args[1:]) if args else ("", [])
    if comando == "cobranca":
        from backend.cobranca_mercadopago import main as gerenciar_cobrancas
        return gerenciar_cobrancas(resto)
    db = SessionLocal()
    try:
        if comando == "criar" and len(resto) == 2:
            token = criar(db, resto[0], resto[1])
            print(f"Loja {resto[0].strip()} criada. Token (guarde agora, ele não aparece de novo):\n{token}")
        elif comando == "novo-token" and len(resto) == 1:
            print(f"Token novo da loja {resto[0]} (o antigo deixou de valer):\n{novo_token(db, resto[0])}")
        elif comando in ("ativar", "desativar") and len(resto) == 1:
            definir_ativa(db, resto[0], comando == "ativar")
            print(f"Loja {resto[0]} {'ativada' if comando == 'ativar' else 'desativada'}.")
        elif comando == "assinatura" and len(resto) == 2:
            if resto[1] == "cancelar":
                definir_assinatura(db, resto[0], None)
                print(f"Assinatura da loja {resto[0]} cancelada: a nuvem não emite mais licença para ela.")
            else:
                try:
                    ate = date.fromisoformat(resto[1])
                except ValueError:
                    raise ErroLoja("Informe a data como AAAA-MM-DD (ex.: 2026-11-30) ou 'cancelar'.") from None
                definir_assinatura(db, resto[0], ate)
                print(f"Loja {resto[0]} com assinatura paga até {ate.strftime('%d/%m/%Y')}. O PDV renova sozinho.")
        elif comando == "painel" and 1 <= len(resto) <= 2:
            from backend import painel
            _obter(db, resto[0])
            senha = resto[1] if len(resto) == 2 else painel.gerar_senha()
            try:
                painel.definir_senha(db, resto[0], senha)
            except ValueError as e:
                raise ErroLoja(str(e)) from None
            print(f"Senha do painel da loja {resto[0]} definida. Passe ao dono (ela não aparece de novo):\n{senha}\n"
                  f"No celular: abra o endereço da nuvem + /painel/ e entre com a loja {resto[0]} e esta senha.")
        elif comando == "limpar-painel" and not resto:
            from backend import painel
            removidas = painel.limpar_antigos(db)
            print(f"Limpeza do painel: {removidas['vendas']} vendas, {removidas['sessoes']} sessões vencidas e "
                  f"{removidas['caixas']} caixas parados removidos. A nuvem guarda as vendas dos últimos "
                  f"{painel.retencao_vendas_dias()} dias (PDV_PAINEL_RETENCAO_DIAS); o histórico completo fica no PDV.")
        elif comando == "listar" and not resto:
            lojas = listar(db)
            for loja in lojas:
                print(f"{loja.chave_loja:<24} {'ativa  ' if loja.ativa else 'INATIVA'}  {situacao_assinatura(loja.licenca_ate):<38} "
                      f"{loja.nome}")
            if not lojas:
                print("Nenhuma loja cadastrada.")
        else:
            print(__doc__)
            return 2
    except ErroLoja as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
