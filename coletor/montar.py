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


LEG_ESTADUAL = [("2015-03-15", 2014), ("2019-03-15", 2018), ("2023-03-15", 2022), ("2027-03-15", 2026)]


def _eleicao_da_data(data):
    el = None
    for ini, ano in LEG_ESTADUAL:
        if data >= ini:
            el = ano
    return el or 2014


def _sit_alesp(p):
    t = norm(" ".join([p.get("etapa", ""), p.get("tpAnd", ""), p.get("ultDesc", "")])).lower()
    if re.search(r"\blei\b.*\b(promulg|sancion|publicad)", t) or "transformad" in t or "norma juridica" in t:
        return "norma"
    if "arquiv" in t:
        return "arquivada"
    if "veto" in t or "vetad" in t:
        return "vetada"
    return "tramitando"


def estadual(cad, desp, props, pres, tse):
    cad = cad or {"deputados": [], "partidos": {}}
    atuais = {norm(d["nome"]): d for d in cad["deputados"]}
    tse_e = collections.defaultdict(list)
    for r in tse or []:
        if r["cargo"] == "E":
            tse_e[r["kUrna"]].append(r)
            tse_e[r["kNome"]].append(r)

    universo = set(atuais)
    if desp:
        universo |= set(desp["nomes"])
    if pres:
        universo |= {k for k, *_ in pres}
    # autores: só entram nomes já conhecidos como deputados (exclui Governador, Mesa, comissões etc.)
    conhecidos = universo | set(tse_e)
    nomes = {}
    if desp:
        nomes.update(desp["nomes"])
    for k, d in atuais.items():
        nomes[k] = d["nome"]
    if props:
        for k, _, _ in props["autores"]:
            if k in tse_e and k not in universo:
                universo.add(k)
                nomes.setdefault(k, (tse_e[k][0]["urna"] or k).title())
    universo = sorted(universo)
    pi = {k: i for i, k in enumerate(universo)}
    P, C, T = Indice(), Indice(), Indice()

    def regs_de(k):
        return list({r["sq"]: r for r in tse_e.get(k, [])}.values())

    def partido(k, data):
        el = _eleicao_da_data(data)
        regs = regs_de(k)
        r = next((r for r in regs if r["ano"] == el), None)
        if r:
            return r["partido"]
        if k in atuais and el == 2022:
            return atuais[k]["partido"]
        if regs:
            return min(regs, key=lambda r: abs(r["ano"] - el))["partido"]
        if k in atuais:
            return atuais[k]["partido"]
        return "N/I"

    parl, sem_tse = [], []
    for k in universo:
        regs = regs_de(k)
        if not regs:
            sem_tse.append(nomes.get(k, k))
        a = atuais.get(k)
        parl.append({"id": k, "nome": nomes.get(k, k.title()), "partidoAtual": a["partido"] if a else None,
                     "situacao": a["situacao"] if a else None, "emExercicio": bool(a and a.get("situacao") == "EXE"),
                     "tse": _perfil_tse(regs),
                     "url": f"https://www.al.sp.gov.br/deputado/?matricula={a['matricula']}" if a and a.get("matricula") else None})

    dl = []
    for k, ano, mes, tipo, v, n in (desp or {}).get("linhas", []):
        if k in pi and 1 <= mes <= 12:
            dl.append([pi[k], ano, mes, C(tipo), P(partido(k, f"{ano}-{mes:02d}-15")), v, n])
    forn = collections.defaultdict(lambda: collections.defaultdict(float))
    nome_forn = {}
    for k, ano, nome, cnpj, v in (desp or {}).get("forn", []):
        if k in pi:
            forn[pi[k]][cnpj or nome] += v
            nome_forn[cnpj or nome] = nome
    forn_top = {i: [[nome_forn[c], c, round(v, 2)] for c, v in sorted(m.items(), key=lambda x: -x[1])[:10]]
                for i, m in forn.items()}

    pa, normas, sits = collections.Counter(), [], collections.Counter()
    if props:
        P_ = props["props"]
        for k, doc, _ in props["autores"]:
            if k not in pi:
                continue
            p = P_[doc]
            data = p["data"] or f"{p['ano']}-07-01"
            sit = _sit_alesp(p)
            sits[sit] += 1
            t = (p["tipo"] or "").upper()
            g = t if t in {"PL", "PLC", "PEC", "PDL", "PR", "REQ", "IND", "MOC"} else "Outros"
            pa[(pi[k], int(data[:4]), P(partido(k, data)), T(g), 1, sit)] += 1
            if sit == "norma" and (p["tipo"] or "").upper() in {"PL", "PLC", "PEC", "PDL", "PR"}:
                normas.append([pi[k], p["tipo"], p["numero"], p["ano"], sit, p["ementa"], doc, 1])
    prop = [[*k, v] for k, v in pa.items()]

    prl = []
    for k, ano, mes, c in pres or []:
        if k in pi and ano and mes:
            prl.append([pi[k], int(ano), int(mes), P(partido(k, f"{ano}-{mes}-15")), c])

    registrar("montagem_estadual", parlamentares=len(parl), n_sem_tse=len(sem_tse), sem_tse=sem_tse[:40],
              situacoes_proposituras=dict(sits))
    return {"parlamentares": parl, "partidos": P.lista, "categorias": C.lista, "tipos": T.lista,
            "desp": dl, "forn": forn_top, "prop": prop, "normas": normas, "pres": prl}
