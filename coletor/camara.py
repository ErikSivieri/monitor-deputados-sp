"""Deputados federais eleitos por SP: cadastro, histórico de partido/exercício, cota parlamentar,
proposições e participação em votações nominais do Plenário."""
import bisect
import collections
import datetime as dt
import re

import pandas as pd

from .util import (ANO_ATUAL, HOJE, INICIO, baixar, abrir_zip, col, com_cache, log, num,
                   paginar, get_json, protegido, registrar)

API = "https://dadosabertos.camara.leg.br/api/v2"
ARQ = "https://dadosabertos.camara.leg.br/arquivos"
COTAS = "https://www.camara.leg.br/cotas"
ANOS = list(range(INICIO, ANO_ATUAL + 1))

TIPOS_PRINCIPAIS = {"PL", "PLP", "PEC", "PDL", "PDC", "PRC"}


def ler_csv(caminho, **kw):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(caminho, sep=";", dtype=str, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"não consegui ler {caminho}")


# ----------------------------------------------------------------- parlamentares

@protegido("camara_deputados")
def deputados():
    legs = [l for l in paginar(f"{API}/legislaturas", {"itens": 100})
            if (l.get("dataFim") or "9999") >= f"{INICIO}-02-01"]
    ids_leg = sorted(int(l["id"]) for l in legs)
    params = [("siglaUf", "SP"), ("itens", 1000)] + [("idLegislatura", i) for i in ids_leg]
    lista = paginar(f"{API}/deputados", params)
    por_id = {}
    for d in lista:
        e = por_id.setdefault(d["id"], {"id": d["id"], "legislaturas": set()})
        e["legislaturas"].add(d.get("idLegislatura"))
    log("federais SP desde", INICIO, ":", len(por_id))

    saida = []
    for i, (did, e) in enumerate(sorted(por_id.items())):
        det = get_json(f"{API}/deputados/{did}")["dados"]
        hist = paginar(f"{API}/deputados/{did}/historico")
        us = det.get("ultimoStatus") or {}
        saida.append({
            "id": did,
            "nome": us.get("nome") or us.get("nomeEleitoral") or det.get("nomeCivil"),
            "nomeCivil": det.get("nomeCivil"),
            "cpf": det.get("cpf"),
            "sexo": det.get("sexo"),
            "nascimento": det.get("dataNascimento"),
            "escolaridade": det.get("escolaridade"),
            "municipio": det.get("municipioNascimento"),
            "ufNasc": det.get("ufNascimento"),
            "partidoAtual": us.get("siglaPartido"),
            "situacaoAtual": us.get("situacao"),
            "legislaturaAtual": us.get("idLegislatura"),
            "legislaturas": sorted(x for x in e["legislaturas"] if x),
            "historico": [{"data": h.get("dataHora"), "partido": h.get("siglaPartido"),
                           "situacao": h.get("situacao"), "condicao": h.get("condicaoEleitoral"),
                           "leg": h.get("idLegislatura"), "desc": h.get("descricaoStatus")} for h in hist],
        })
        if i % 20 == 0:
            log("detalhes", i, "/", len(por_id))
    registrar("camara_deputados", total=len(saida), legislaturas=ids_leg,
              exemplo_historico=saida[0]["historico"][:3] if saida else None)
    return {"deputados": saida, "legislaturas": legs}


class Linha:
    """Linha do tempo de partido e exercício de um deputado, montada a partir do histórico oficial."""

    def __init__(self, dep, fim_legs):
        ev = sorted((h for h in dep["historico"] if h.get("data")), key=lambda h: h["data"])
        self.datas = [h["data"][:10] for h in ev]
        self.ev = ev
        self.fim_legs = fim_legs
        self.reserva = dep.get("partidoAtual")
        # intervalos em exercício
        self.exerc = []
        for i, h in enumerate(ev):
            if (h.get("situacao") or "").lower().startswith("exerc"):
                ini = self.datas[i]
                if i + 1 < len(ev):
                    fim = self.datas[i + 1]
                else:
                    fim = min(fim_legs.get(h.get("leg"), HOJE.isoformat()), HOJE.isoformat())
                self.exerc.append((ini, fim))

    def partido(self, data):
        i = bisect.bisect_right(self.datas, data) - 1
        j = i
        while j >= 0:
            p = self.ev[j].get("partido")
            if p:
                return p
            j -= 1
        for h in self.ev:
            if h.get("partido"):
                return h["partido"]
        return self.reserva or "S/PARTIDO"

    def em_exercicio(self, data):
        return any(a <= data < b for a, b in self.exerc)


# ----------------------------------------------------------------- cota parlamentar

def _despesas_ano(ano, ids):
    arq = baixar(f"{COTAS}/Ano-{ano}.csv.zip")
    if arq is None:
        return None
    f, _ = abrir_zip(arq, ".csv")
    df = ler_csv(f)
    c_id = col(df, "ideCadastro", "nuDeputadoId")
    c_uf = col(df, "sgUF")
    df = df[df[c_uf] == "SP"]
    df = df[df[c_id].isin({str(i) for i in ids})]
    c_val = col(df, "vlrLiquido")
    c_mes = col(df, "numMes")
    c_cat = col(df, "txtDescricao")
    c_forn = col(df, "txtFornecedor")
    c_cnpj = col(df, "txtCNPJCPF")
    c_part = col(df, "sgPartido")
    df = df.assign(v=df[c_val].map(num))
    df = df[pd.to_numeric(df[c_mes], errors="coerce").notna()]
    agg = df.groupby([c_id, c_mes, c_cat, c_part], dropna=False)["v"].agg(["sum", "count"]).reset_index()
    linhas = [[int(r[c_id]), ano, int(float(r[c_mes])), r[c_cat], r[c_part], round(float(r["sum"]), 2), int(r["count"])]
              for _, r in agg.iterrows()]
    fa = df.groupby([c_id, c_forn, c_cnpj], dropna=False)["v"].sum().reset_index()
    forn = [[int(r[c_id]), ano, str(r[c_forn])[:80], str(r[c_cnpj]), round(float(r["v"]), 2)]
            for _, r in fa.iterrows() if r["v"] > 0]
    return {"linhas": linhas, "forn": forn, "colunas": list(df.columns)[:40]}


@protegido("camara_despesas")
def despesas(ids):
    res = {"linhas": [], "forn": []}
    for ano in ANOS:
        r = com_cache("camara_despesas", ano, lambda a: _despesas_ano(a, ids))
        if r:
            res["linhas"] += r["linhas"]
            res["forn"] += r["forn"]
            registrar("camara_despesas", colunas=r.get("colunas"))
        log("despesas", ano, "ok" if r else "sem arquivo")
    registrar("camara_despesas", linhas=len(res["linhas"]))
    return res


# ----------------------------------------------------------------- proposições

def _situacao(desc):
    d = (desc or "").lower()
    if "norma jur" in d:
        return "norma"
    if "arquivad" in d:
        return "arquivada"
    if "aguardando sanç" in d or "aguardando promulga" in d or "remetida ao senado" in d or "enviada ao senado" in d:
        return "aprovada_camara"
    return "tramitando"


def _proposicoes_ano(ano, ids):
    a = baixar(f"{ARQ}/proposicoesAutores/csv/proposicoesAutores-{ano}.csv")
    p = baixar(f"{ARQ}/proposicoes/csv/proposicoes-{ano}.csv")
    if a is None or p is None:
        return None
    au = ler_csv(a)
    c_dep = col(au, "idDeputadoAutor")
    au = au[au[c_dep].isin({str(i) for i in ids})]
    c_prop = col(au, "idProposicao")
    c_ord = col(au, "ordemAssinatura")
    c_prop2 = col(au, "proponente")
    pr = ler_csv(p)
    c_id = col(pr, "id")
    pr = pr[pr[c_id].isin(set(au[c_prop]))]
    situacoes = {}
    info = {}
    for _, r in pr.iterrows():
        sit = r.get("ultimoStatus_descricaoSituacao")
        situacoes[sit] = situacoes.get(sit, 0) + 1
        info[r[c_id]] = {"tipo": r.get("siglaTipo"), "numero": r.get("numero"), "ano": r.get("ano"),
                         "data": (r.get("dataApresentacao") or "")[:10], "sit": _situacao(sit),
                         "sitDesc": sit, "ementa": (r.get("ementa") or "")[:400]}
    linhas = []
    for _, r in au.iterrows():
        i = info.get(r[c_prop])
        if not i:
            continue
        principal = 1 if str(r[c_ord]).strip() == "1" else 0
        linhas.append([int(r[c_dep]), int(r[c_prop]), i["tipo"], i["numero"], i["ano"], i["data"],
                       principal, i["sit"], i["ementa"] if i["sit"] in ("norma", "aprovada_camara") and i["tipo"] in TIPOS_PRINCIPAIS else ""])
    return {"linhas": linhas, "situacoes": situacoes}


@protegido("camara_proposicoes")
def proposicoes(ids):
    linhas, sits = [], collections.Counter()
    for ano in ANOS:
        r = com_cache("camara_proposicoes", ano, lambda a: _proposicoes_ano(a, ids))
        if r:
            linhas += r["linhas"]
            sits.update(r["situacoes"])
        log("proposições", ano, "ok" if r else "sem arquivo")
    registrar("camara_proposicoes", linhas=len(linhas), situacoes_mais_comuns=sits.most_common(25))
    return linhas


# ----------------------------------------------------------------- votações nominais

def _votacoes_ano(ano, ids):
    v = baixar(f"{ARQ}/votacoes/csv/votacoes-{ano}.csv")
    vv = baixar(f"{ARQ}/votacoesVotos/csv/votacoesVotos-{ano}.csv")
    if v is None or vv is None:
        return None
    vot = ler_csv(v)
    c_id = col(vot, "id")
    c_org = col(vot, "siglaOrgao")
    c_data = col(vot, "data")
    plen = vot[vot[c_org] == "PLEN"]
    votos = ler_csv(vv)
    c_vid = col(votos, "idVotacao")
    c_dep = col(votos, "deputado_id")
    nominais = set(votos[c_vid]) & set(plen[c_id])
    datas = {r[c_id]: str(r[c_data])[:10] for _, r in plen.iterrows() if r[c_id] in nominais}
    sp = votos[votos[c_dep].isin({str(i) for i in ids}) & votos[c_vid].isin(nominais)]
    pares = sorted({(int(r[c_dep]), r[c_vid]) for _, r in sp.iterrows()})
    return {"datas": datas, "votos": [[d, v] for d, v in pares]}


@protegido("camara_votacoes")
def votacoes(ids):
    datas, votos = {}, []
    for ano in ANOS:
        r = com_cache("camara_votacoes", ano, lambda a: _votacoes_ano(a, ids))
        if r:
            datas.update(r["datas"])
            votos += r["votos"]
        log("votações", ano, "ok" if r else "sem arquivo")
    registrar("camara_votacoes", votacoes_nominais_plenario=len(datas), votos_sp=len(votos))
    return {"datas": datas, "votos": votos}
