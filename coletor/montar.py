"""Junta as fontes num único arquivo compacto (data/painel.json) que alimenta o painel."""
import collections
import datetime as dt
import re

from .camara import Linha, TIPOS_PRINCIPAIS
from .util import HOJE, norm, registrar

# Siglas sucessoras (fusões, incorporações e mudanças de nome registradas no TSE).
# Usadas apenas quando o leitor do painel liga a opção "agrupar siglas sucessoras".
SUCESSORAS = {
    "PMDB": "MDB", "PR": "PL", "PRB": "REPUBLICANOS", "PPS": "CIDADANIA", "PTN": "PODE",
    "PHS": "PODE", "PSC": "PODE", "PEN": "PATRIOTA", "PRP": "PATRIOTA", "PATRIOTA": "PRD",
    "PTB": "PRD", "DEM": "UNIÃO", "PSL": "UNIÃO", "SD": "SOLIDARIEDADE", "PROS": "SOLIDARIEDADE",
    "PPL": "PCdoB", "PTC": "AGIR", "PT do B": "AVANTE", "PTdoB": "AVANTE", "SDD": "SOLIDARIEDADE",
}


class Indice:
    def __init__(self):
        self.lista, self.mapa = [], {}

    def __call__(self, v):
        v = v or "N/I"
        if v not in self.mapa:
            self.mapa[v] = len(self.lista)
            self.lista.append(v)
        return self.mapa[v]


def _grupo_tipo(t):
    t = (t or "").upper()
    if t == "PDC":
        return "PDL"
    if t in TIPOS_PRINCIPAIS or t in {"REQ", "INC", "RIC", "EMC", "PRL"}:
        return t
    return "Outros"


def _perfil_tse(regs):
    if not regs:
        return None
    ult = max(regs, key=lambda r: r["ano"])
    return {
        "genero": ult.get("genero"), "nascimento": ult.get("nascimento"), "instrucao": ult.get("instrucao"),
        "corRaca": ult.get("corRaca"), "ocupacao": ult.get("ocupacao"), "estadoCivil": ult.get("estadoCivil"),
        "eleicoes": [{"ano": r["ano"], "partido": r["partido"], "situacao": r["situacao"], "bens": r.get("bens"),
                      "urna": r["urna"]} for r in sorted(regs, key=lambda r: r["ano"])],
    }


def federal(cad, desp, props, vots, tse):
    deps = cad["deputados"]
    fim_legs = {int(l["id"]): l.get("dataFim") or HOJE.isoformat() for l in cad["legislaturas"]}
    linhas = {d["id"]: Linha(d, fim_legs) for d in deps}
    pi = {d["id"]: i for i, d in enumerate(deps)}
    P, C, T = Indice(), Indice(), Indice()

    tse_cpf = collections.defaultdict(list)
    tse_nome = collections.defaultdict(list)
    for r in tse or []:
        if r["cargo"] != "F":
            continue
        if r["cpf"]:
            tse_cpf[r["cpf"]].append(r)
        tse_nome[r["kUrna"]].append(r)
        tse_nome[r["kNome"]].append(r)

    parl = []
    sem_tse = []
    for d in deps:
        regs = tse_cpf.get((d.get("cpf") or "").zfill(11)) or tse_nome.get(norm(d.get("nomeCivil"))) or tse_nome.get(norm(d.get("nome"))) or []
        regs = list({r["sq"]: r for r in regs}.values())
        if not regs:
            sem_tse.append(d["nome"])
        hp, ult = [], None
        for h in sorted((h for h in d["historico"] if h.get("data")), key=lambda h: h["data"]):
            if h.get("partido") and h["partido"] != ult:
                hp.append([h["data"][:10], h["partido"]])
                ult = h["partido"]
        parl.append({
            "id": d["id"], "nome": d["nome"], "nomeCivil": d.get("nomeCivil"),
            "partidoAtual": d.get("partidoAtual"), "situacao": d.get("situacaoAtual"),
            "emExercicio": (d.get("situacaoAtual") == "Exercício"),
            "legislaturas": d.get("legislaturas"), "sexo": d.get("sexo"), "nascimento": d.get("nascimento"),
            "escolaridade": d.get("escolaridade"), "municipio": d.get("municipio"), "ufNasc": d.get("ufNasc"),
            "partidos": hp, "tse": _perfil_tse(regs),
            "url": f"https://www.camara.leg.br/deputados/{d['id']}",
        })

    # despesas
    dl, divergencias = [], 0
    for did, ano, mes, cat, sg, v, n in (desp or {}).get("linhas", []):
        if did not in pi:
            continue
        part = linhas[did].partido(f"{ano}-{mes:02d}-15")
        if sg and part != sg:
            divergencias += 1
        dl.append([pi[did], ano, mes, C(cat), P(part), v, n])
    forn = collections.defaultdict(lambda: collections.defaultdict(float))
    nome_forn = {}
    for did, ano, nome, cnpj, v in (desp or {}).get("forn", []):
        if did in pi:
            forn[pi[did]][cnpj or nome] += v
            nome_forn[cnpj or nome] = nome
    forn_top = {i: [[nome_forn[k], k, round(v, 2)] for k, v in sorted(m.items(), key=lambda x: -x[1])[:10]]
                for i, m in forn.items()}

    # proposições
    pa = collections.Counter()
    normas = []
    for did, pid, tipo, numero, ano, data, principal, sit, ementa in props or []:
        if did not in pi or not data:
            continue
        part = linhas[did].partido(data)
        g = _grupo_tipo(tipo)
        pa[(pi[did], int(data[:4]), P(part), T(g), principal, sit)] += 1
        if ementa:
            normas.append([pi[did], tipo, numero, ano, sit, ementa, pid, principal])
    prop = [[*k, v] for k, v in pa.items()]

    # votações nominais do Plenário
    vot = collections.defaultdict(lambda: [0, 0])
    if vots:
        votou = collections.defaultdict(set)
        for did, vid in vots["votos"]:
            votou[did].add(vid)
        for vid, data in vots["datas"].items():
            for did, ln in linhas.items():
                presente = vid in votou.get(did, ())
                if presente or ln.em_exercicio(data):
                    k = (pi[did], int(data[:4]), int(data[5:7]), P(ln.partido(data)))
                    vot[k][0] += 1
                    vot[k][1] += 1 if presente else 0
    votl = [[*k, e, r] for k, (e, r) in vot.items()]

    registrar("montagem_federal", parlamentares=len(parl), sem_tse=sem_tse[:30], n_sem_tse=len(sem_tse),
              divergencia_partido_arquivo_cota=divergencias, linhas_despesa=len(dl))
    return {"parlamentares": parl, "partidos": P.lista, "categorias": C.lista, "tipos": T.lista,
            "desp": dl, "forn": forn_top, "prop": prop, "normas": normas, "vot": votl}


LEG_ESTADUAL = [("2011-03-15", 2010), ("2015-03-15", 2014), ("2019-03-15", 2018), ("2023-03-15", 2022), ("2027-03-15", 2026)]
PREFIXOS = {"DEPUTADO", "DEPUTADA", "DEP", "DR", "DRA"}


def _eleicao_da_data(data):
    el = 2010
    for ini, ano in LEG_ESTADUAL:
        if data >= ini:
            el = ano
    return el


def _tokens(nome):
    return frozenset(t for t in norm(nome).split() if len(t) > 1 and t not in PREFIXOS and t not in {"DA", "DE", "DO", "DOS", "DAS", "E"})


class Nomes:
    """Resolve nomes escritos de formas diferentes para a mesma pessoa."""

    def __init__(self):
        self.exato, self.lista = {}, []

    def add(self, nome, chave):
        k = norm(nome)
        if k and k not in self.exato:
            self.exato[k] = chave
            self.lista.append((_tokens(nome), chave))

    def achar(self, nome):
        k = norm(nome)
        if k in self.exato:
            return self.exato[k]
        t = _tokens(nome)
        if len(t) < 2:
            return None
        cand = {c for tk, c in self.lista if len(tk) >= 2 and (tk <= t or t <= tk)}
        return cand.pop() if len(cand) == 1 else None


def _match_tse(variantes, regs_e):
    """Para cada eleição, acha o registro do TSE que corresponde a algum nome usado pelo deputado."""
    por_ano = collections.defaultdict(list)
    for r in regs_e:
        por_ano[r["ano"]].append(r)
    achados = []
    nomes_k = {norm(v) for v in variantes}
    toks = [_tokens(v) for v in variantes]
    for ano, regs in por_ano.items():
        exatos = [r for r in regs if r["kUrna"] in nomes_k or r["kNome"] in nomes_k]
        if not exatos:
            exatos = []
            for r in regs:
                tu, tn = _tokens(r["urna"]), _tokens(r["nome"])
                if any((len(tu) >= 2 and tu <= t) or (len(t) >= 2 and t <= tn) for t in toks):
                    exatos.append(r)
        if not exatos:
            continue
        eleitos = [r for r in exatos if "ELEITO" in (r["situacao"] or "").upper()]
        escolha = eleitos or exatos
        if len({r["sq"] for r in escolha}) == 1:
            achados.append(escolha[0])
    return achados


def estadual(cad, desp, props, pres, tse, normas):
    cad = cad or {"deputados": [], "partidos": {}}
    atuais = {d["matricula"]: d for d in cad["deputados"] if d.get("matricula")}
    id_para_matr = {d["idDeputado"]: d["matricula"] for d in cad["deputados"] if d.get("matricula")}
    variantes = collections.defaultdict(collections.Counter)
    for m, vs in (desp or {}).get("variantes", {}).items():
        variantes[m].update(vs)
    for m, d in atuais.items():
        variantes[m][d["nome"]] += 1000
    nomes = Nomes()
    for m, vs in variantes.items():
        for v in vs:
            nomes.add(v, m)

    # presenças: completa o universo com quem só aparece ali
    pres_res = []
    for nome, idd, ano, mes, c in pres or []:
        m = id_para_matr.get(idd) or nomes.achar(nome)
        if m is None:
            m = "n:" + norm(nome)
            variantes[m][nome] += 1
            nomes.add(nome, m)
        pres_res.append((m, ano, mes, c))

    regs_e = [r for r in (tse or []) if r["cargo"] == "E"]
    universo = sorted(variantes)
    pi = {m: i for i, m in enumerate(universo)}
    tse_de = {m: _match_tse(list(variantes[m]), regs_e) for m in universo}
    P, C, T = Indice(), Indice(), Indice()

    def partido(m, data):
        el = _eleicao_da_data(data)
        regs = tse_de.get(m) or []
        r = next((r for r in regs if r["ano"] == el), None)
        if r:
            return r["partido"]
        if m in atuais and el == 2022:
            return atuais[m]["partido"]
        if regs:
            return min(regs, key=lambda r: abs(r["ano"] - el))["partido"]
        if m in atuais:
            return atuais[m]["partido"]
        return "N/I"

    def nome_exib(m):
        if m in atuais:
            return atuais[m]["nome"]
        v = variantes[m].most_common(1)[0][0]
        return v.title() if v.isupper() else v

    parl, sem_tse = [], []
    for m in universo:
        regs = tse_de[m]
        if not regs:
            sem_tse.append(nome_exib(m))
        a = atuais.get(m)
        parl.append({"id": m, "nome": nome_exib(m), "partidoAtual": a["partido"] if a else None,
                     "situacao": a["situacao"] if a else None, "emExercicio": bool(a and a.get("situacao") == "EXE"),
                     "tse": _perfil_tse(regs), "matricula": None if m.startswith("n:") else m,
                     "url": f"https://www.al.sp.gov.br/deputado/?matricula={m}" if not m.startswith("n:") else None})

    dl = []
    for m, ano, mes, tipo, v, n in (desp or {}).get("linhas", []):
        if m in pi and 1 <= mes <= 12:
            dl.append([pi[m], ano, mes, C(tipo), P(partido(m, f"{ano}-{mes:02d}-15")), v, n])
    forn = collections.defaultdict(lambda: collections.defaultdict(float))
    nome_forn = {}
    for m, ano, nome, cnpj, v in (desp or {}).get("forn", []):
        if m in pi:
            forn[pi[m]][cnpj or nome] += v
            nome_forn[cnpj or nome] = nome
    forn_top = {i: [[nome_forn[c], c, round(v, 2)] for c, v in sorted(mm.items(), key=lambda x: -x[1])[:10]]
                for i, mm in forn.items()}

    pa, nao_casados = collections.Counter(), collections.Counter()
    if props:
        P_ = props["props"]
        for nome, doc, idautor in props["autores"]:
            m = nomes.achar(nome) or id_para_matr.get(idautor)
            if m is None or m not in pi:
                nao_casados[nome] += 1
                continue
            p = P_[doc]
            data = p["data"] or f"{p['ano']}-07-01"
            t = (p["tipo"] or "").upper()
            g = t if t in {"PL", "PLC", "PEC", "PDL", "PR", "REQ", "IND", "MOC"} else "Outros"
            pa[(pi[m], int(data[:4]), P(partido(m, data)), T(g), 1, "apresentada")] += 1
    prop = [[*k, v] for k, v in pa.items()]

    # normas: autoria vem do campo texto "Autores" da base de legislação
    nl, na, nsem = [], collections.Counter(), collections.Counter()
    for n_ in normas or []:
        partes = [x.strip() for x in re.split(r"[,;/]| e ", n_["autores"] or "") if x.strip()]
        for parte in partes:
            m = nomes.achar(parte)
            if m is None or m not in pi:
                nsem[parte] += 1
                continue
            data = n_["data"] or f"{n_['ano']}-07-01"
            na[(pi[m], int(data[:4]), P(partido(m, data)))] += 1
            nl.append([pi[m], n_["tipo"], n_["numero"], n_["ano"], "norma", n_["ementa"], n_["url"] or n_["id"], 1 if parte == partes[0] else 0])

    prl = [[pi[m], int(ano), int(mes), P(partido(m, f"{ano}-{int(mes):02d}-15")), c] for m, ano, mes, c in pres_res if m in pi]

    registrar("montagem_estadual", parlamentares=len(parl), n_sem_tse=len(sem_tse), sem_tse=sem_tse[:40],
              autores_nao_casados=nao_casados.most_common(25), normas_autores_nao_casados=nsem.most_common(25),
              normas_casadas=len(nl))
    return {"parlamentares": parl, "partidos": P.lista, "categorias": C.lista, "tipos": T.lista,
            "desp": dl, "forn": forn_top, "prop": prop, "normas": nl, "normasAgg": [[*k, v] for k, v in na.items()],
            "pres": prl}
