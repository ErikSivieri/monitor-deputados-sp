"""Emendas parlamentares individuais dos deputados federais de SP (Portal da Transparência / CGU).
A chave de acesso vem do segredo CGU_API_KEY do GitHub e nunca fica no código."""
import collections
import os
import time

from .util import ANO_ATUAL, INICIO, SESSAO, com_cache, log, norm, num, protegido, registrar

API = "https://api.portaldatransparencia.gov.br/api-de-dados/emendas"
CHAVE = os.environ.get("CGU_API_KEY", "").strip()


def _get(params, tentativas=4):
    for i in range(tentativas):
        r = SESSAO.get(API, params=params, headers={"chave-api-dados": CHAVE, "Accept": "application/json"}, timeout=90)
        time.sleep(0.75)  # limite do portal: cerca de 90 requisições por minuto em horário comercial
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(20 * (i + 1))
            continue
        if r.status_code in (401, 403):
            raise RuntimeError(f"chave recusada pelo Portal da Transparência (HTTP {r.status_code})")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Portal da Transparência indisponível para {params}")


def _campo(reg, *nomes):
    for n in nomes:
        if n in reg and reg[n] not in (None, ""):
            return reg[n]
    return None


def _leg(ano):
    return 55 + max(0, (ano - 2015) // 4)


def _ano(ano, alvos, consultas):
    """consultas: [(nome, id)] dos deputados com mandato no ano ou no anterior (a emenda do orçamento de um ano
    é apresentada no ano anterior). alvos: {nome_normalizado: id} para conferir o autor devolvido pelo portal."""
    linhas = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    exemplo, chaves = None, None
    for k_nome, did in consultas:
        pagina = 1
        while True:
            dados = _get({"ano": ano, "nomeAutor": k_nome, "pagina": pagina})
            if not dados:
                break
            for reg in dados:
                chaves = chaves or sorted(reg.keys())
                exemplo = exemplo or reg
                autor = norm(_campo(reg, "nomeAutor", "autor") or "")
                if alvos.get(autor) != did:
                    continue  # nome parecido de outra pessoa: descarta
                tipo = norm(_campo(reg, "tipoEmenda") or "")
                if "INDIVIDUAL" not in tipo:
                    continue
                func = _campo(reg, "funcao", "nomeFuncao") or "N/I"
                a = linhas[(did, func)]
                a[0] += num(_campo(reg, "valorEmpenhado"))
                a[1] += num(_campo(reg, "valorLiquidado"))
                a[2] += num(_campo(reg, "valorPago"))
                a[3] += 1
            pagina += 1
            if pagina > 50:
                break
    registrar("cgu_emendas", **{f"chaves_{ano}": chaves, f"exemplo_{ano}": exemplo})
    return [[did, ano, f, round(e, 2), round(l, 2), round(p, 2), n] for (did, f), (e, l, p, n) in linhas.items()]


@protegido("cgu_emendas")
def emendas(deputados):
    if not CHAVE:
        registrar("cgu_emendas", aviso="segredo CGU_API_KEY não configurado; emendas não coletadas")
        return None
    alvos = {}
    for d in deputados:
        for nome in (d.get("nome"), d.get("nomeCivil")):
            if nome:
                alvos.setdefault(norm(nome), d["id"])
    saida = []
    for ano in range(INICIO, ANO_ATUAL + 1):
        legs = {_leg(ano), _leg(ano - 1)}
        consultas = sorted({(norm(d["nome"]), d["id"]) for d in deputados
                            if d.get("nome") and legs & set(d.get("legislaturas") or [])})
        r = com_cache("cgu_emendas", ano, lambda a: _ano(a, alvos, consultas))
        saida += r or []
        log("emendas", ano, len(r or []))
    registrar("cgu_emendas", linhas=len(saida), deputados_com_emendas=len({l[0] for l in saida}))
    return saida
