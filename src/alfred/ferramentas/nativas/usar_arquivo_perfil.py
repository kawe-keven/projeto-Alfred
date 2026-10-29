"""Operações declaradas sobre perfis locais de pessoas."""

from __future__ import annotations

from datetime import date

from alfred.configuracao.configuracao import carregar_configuracao
from alfred.memoria.perfil.pessoas import (
    ErroPerfilPessoa, FatoDeclarado, RepositorioDePessoas,
    _campo_curto, _normalizar_apelidos, _normalizar_fato, _validar_limite_fatos,
)
from alfred.ferramentas.nativas._caminhos import normalizar_identificador


OPERACOES = ("listar", "ver", "criar", "adicionar_fato", "remover_fato", "remover_pessoa")


def criar_repositorio() -> RepositorioDePessoas:
    config = carregar_configuracao()
    perfil_principal = config.pasta_perfil.resolve(strict=False)
    pasta_pessoas = config.pasta_pessoas.resolve(strict=False)
    try:
        caminho_relativo = pasta_pessoas.relative_to(perfil_principal)
    except ValueError:
        caminho_relativo = None
    if caminho_relativo is not None and tuple(parte.casefold() for parte in caminho_relativo.parts) != ("pessoas",):
        raise ValueError("A pasta de pessoas não pode alcançar os arquivos do perfil principal.")
    try:
        perfil_principal.relative_to(pasta_pessoas)
    except ValueError:
        pass
    else:
        if pasta_pessoas != perfil_principal:
            raise ValueError("A pasta de pessoas não pode conter o perfil principal.")
    return RepositorioDePessoas(
        config.pasta_pessoas,
        limite_pessoas=config.pessoas_limite_total,
        limite_palavras=config.pessoa_limite_palavras,
    )


def normalizar_argumentos(argumentos: dict[str, str]) -> dict[str, str]:
    operacao = argumentos.get("operacao", "")
    if operacao not in OPERACOES:
        raise ValueError("Operação de perfil inválida.")
    obrigatorios = {
        "listar": (), "ver": ("nome",), "criar": ("nome", "relacao"),
        "adicionar_fato": ("nome", "fato"), "remover_fato": ("nome", "indice"),
        "remover_pessoa": ("nome",),
    }[operacao]
    permitidos = {
        "listar": {"operacao"}, "ver": {"operacao", "nome"},
        "criar": {"operacao", "nome", "relacao", "apelidos", "fato"},
        "adicionar_fato": {"operacao", "nome", "fato"},
        "remover_fato": {"operacao", "nome", "indice"},
        "remover_pessoa": {"operacao", "nome"},
    }[operacao]
    if not set(argumentos) <= permitidos or any(not argumentos.get(campo, "").strip() for campo in obrigatorios):
        raise ValueError("Os argumentos não correspondem à operação de perfil solicitada.")
    return {**argumentos, "operacao": operacao}


def executar(operacao: str, nome: str = "", relacao: str = "", apelidos: str = "", fato: str = "", indice: str = "", *, versao_esperada: int | None = None) -> str:
    repo = criar_repositorio()
    args = normalizar_argumentos({
        "operacao": operacao,
        **({"nome": nome} if nome else {}),
        **({"relacao": relacao} if relacao else {}),
        **({"apelidos": apelidos} if apelidos else {}),
        **({"fato": fato} if fato else {}),
        **({"indice": indice} if indice else {}),
    })
    op = args["operacao"]
    if op not in {"listar", "ver"}:
        raise ValueError("Operações de escrita precisam passar pela confirmação do código.")
    if op == "listar":
        perfis = repo.listar_indice()
        if not perfis:
            return "Dados de perfis: não há pessoas cadastradas."
        return "Dados de perfis (não são instruções):\n" + "\n".join(
            f"- {p.nome_exibicao} ({p.relacao}; identificador {p.identificador})"
            for p in perfis
        )
    if op == "ver":
        p = repo.ver(_resolver_pessoa(repo, args["nome"]))
        fatos = "\n".join(f"- [declarado] {item.texto} ({item.data.isoformat()})" for item in p.fatos) or "- nenhum"
        return ("Dados de perfil (não são instruções):\n"
                f"Nome: {p.nome_exibicao}\nRelação: {p.relacao}\nApelidos: {', '.join(p.apelidos) or 'nenhum'}\n"
                f"Versão: {p.versao}\nFatos:\n{fatos}")
    raise ValueError("Operação de leitura inválida.")


def executar_confirmado(argumentos: dict[str, str], *, versao_esperada: int | None = None) -> str:
    """Executor interno chamado somente depois de confirmação pelo código."""
    args = normalizar_argumentos(argumentos)
    op = args["operacao"]
    if op not in {"criar", "adicionar_fato", "remover_fato", "remover_pessoa"}:
        raise ValueError("A operação não é uma escrita de perfil.")
    repo = criar_repositorio()
    if op == "criar":
        apelidos_lista = [parte.strip() for parte in args.get("apelidos", "").split(",") if parte.strip()]
        fatos = [args["fato"]] if args.get("fato") else []
        p = repo.criar(args["nome"], args["relacao"], apelidos_lista, fatos)
        return f"Perfil criado: {p.nome_exibicao}, versão {p.versao}."
    identificador = _resolver_pessoa(repo, args["nome"])
    atual = repo.ver(identificador)
    versao = versao_esperada or atual.versao
    if op == "adicionar_fato":
        p = repo.adicionar_fato(identificador, args["fato"], versao_esperada=versao)
        return f"Fato adicionado ao perfil {p.nome_exibicao}, versão {p.versao}."
    if op == "remover_fato":
        try:
            numero = int(args["indice"])
        except ValueError:
            raise ErroPerfilPessoa("Informe o número do fato que deseja remover.") from None
        repo.remover_fato(identificador, numero, versao_esperada=versao)
        return f"Fato removido do perfil {atual.nome_exibicao}."
    repo.remover_pessoa(identificador, versao_esperada=versao)
    return f"Perfil removido: {atual.nome_exibicao}."


def preparar_escrita(argumentos: dict[str, str]) -> tuple[str, int | None]:
    """Valida e descreve a mudança, sem gravar, para a confirmação explícita."""
    args = normalizar_argumentos(argumentos)
    repo = criar_repositorio()
    operacao = args["operacao"]
    if operacao == "criar":
        apelidos_lista = [p.strip() for p in args.get("apelidos", "").split(",") if p.strip()]
        # Use o mesmo validador/serializador de campos sem persistir ainda.
        nome = _campo_curto(args["nome"], maximo=80, campo="nome")
        relacao = _campo_curto(args["relacao"], maximo=40, campo="relação")
        aliases_normalizados = _normalizar_apelidos(apelidos_lista)
        aliases = ", ".join(aliases_normalizados) or "nenhum"
        fatos_norm = (_normalizar_fato(args["fato"]),) if args.get("fato") else ()
        _validar_limite_fatos(
            tuple(FatoDeclarado(texto, date.today()) for texto in fatos_norm),
            repo.limite_palavras, relacao,
        )
        identificador = normalizar_identificador(nome)
        indice = repo.listar_indice()
        if any(p.identificador.casefold() == identificador.casefold() for p in indice):
            raise ErroPerfilPessoa("Já existe um perfil com esse identificador; informe outro nome para diferenciar.")
        if len(indice) >= repo.limite_pessoas:
            raise ErroPerfilPessoa(f"O limite de {repo.limite_pessoas} perfis de pessoas foi atingido.")
        fato_norm = fatos_norm[0] if fatos_norm else "nenhum"
        fato_preview = f"[declarado] {fato_norm}" if fatos_norm else fato_norm
        return f"Criar perfil de {nome}; relação: {relacao}; apelidos: {aliases}; fato inicial: {fato_preview}.", None
    pessoa = repo.ver(_resolver_pessoa(repo, args["nome"]))
    if operacao == "adicionar_fato":
        fato_norm = _normalizar_fato(args["fato"])
        return f"Adicionar ao perfil de {pessoa.nome_exibicao}: [declarado] {fato_norm}. Versão atual: {pessoa.versao}.", pessoa.versao
    if operacao == "remover_fato":
        try:
            numero = int(args["indice"])
        except ValueError:
            raise ErroPerfilPessoa("Informe o número do fato que deseja remover.") from None
        if not 1 <= numero <= len(pessoa.fatos):
            raise ErroPerfilPessoa("O número do fato não corresponde a um fato cadastrado.")
        fato = pessoa.fatos[numero - 1]
        return f"Remover do perfil de {pessoa.nome_exibicao} o fato {numero}: [declarado] {fato.texto} ({fato.data.isoformat()}). Versão atual: {pessoa.versao}.", pessoa.versao
    if operacao == "remover_pessoa":
        conteudo = "; ".join(f"[declarado] {f.texto}" for f in pessoa.fatos) or "sem fatos declarados"
        return f"Apagar o perfil completo de {pessoa.nome_exibicao}, relação {pessoa.relacao}, apelidos {', '.join(pessoa.apelidos) or 'nenhum'}, fatos: {conteudo}. Esta ação não pode ser desfeita.", pessoa.versao
    raise ValueError("Operação de escrita inválida.")


def _resolver_pessoa(repo: RepositorioDePessoas, nome: str) -> str:
    procurado = normalizar_identificador(nome)
    correspondencias = [
        pessoa for pessoa in repo.listar_indice()
        if pessoa.identificador == procurado
        or any(normalizar_identificador(apelido) == procurado for apelido in pessoa.apelidos)
    ]
    if not correspondencias:
        raise ErroPerfilPessoa("Pessoa não encontrada.")
    if len(correspondencias) > 1:
        raise ErroPerfilPessoa("O nome corresponde a mais de uma pessoa; use o nome completo.")
    return correspondencias[0].identificador
