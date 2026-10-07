"""Erros de negocio da area de chamados. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class ChamadoNaoEncontrado(ErroDeNegocio):
    """Tambem cobre chamado de outra loja: nao revelamos que ele existe."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Chamado nao encontrado"


class ChamadoFinalizado(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Este chamado ja foi resolvido"


class ChamadoJaAssumido(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, nome: str | None = None, *, voce: bool = False) -> None:
        if voce:
            self.detalhe = "Voce ja assumiu este chamado"
        else:
            self.detalhe = f"{nome or 'Outro atendente'} ja assumiu este chamado"
        super().__init__(self.detalhe)


class ChamadoSemResponsavel(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Assuma o chamado antes de resolver"


class SemPermissaoNoChamado(ErroDeNegocio):
    status_code = status.HTTP_403_FORBIDDEN
    detalhe = "Somente quem assumiu o chamado, o gerente ou o administrador pode fazer isso"


class CadastroInativo(ErroDeNegocio):
    """O token e valido, mas nao ha usuario ativo ligado a ele no cadastro."""

    status_code = status.HTTP_403_FORBIDDEN
    detalhe = "Seu cadastro nao esta ativo"
