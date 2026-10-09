"""Deputados estaduais (ALESP): cadastro atual, despesas de gabinete, proposituras e presença em comissões."""
import collections
import re

from lxml import etree

from .util import (ANO_ATUAL, INICIO, abrir_zip, baixar, iso, log, norm, num, protegido, registrar)

BASE = "https://www.al.sp.gov.br/repositorioDados"


def registros(fonte, campos_esperados):
    """Lê um XML em streaming e devolve dicionários {campo_normalizado: texto} para cada registro.
    O registro é o elemento cujos filhos são folhas e incluem algum dos campos esperados."""
    esperados = {c.lower() for c in campos_esperados}
    for _, el in etree.iterparse(fonte, events=("end",), recover=True, huge_tree=True):
        filhos = list(el)
        if not filhos or any(len(f) for f in filhos):
            continue
        tags = {norm(etree.QName(f).localname).lower(): (f.text or "").strip() for f in filhos}
        if esperados & set(tags):
            yield tags
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]


def _xml(caminho_url, nome_zip_xml=None):
    arq = baixar(caminho_url)
    if arq is None:
        return None
    if caminho_url.endswith(".zip"):
        f, _ = abrir_zip(arq, ".xml")
        return f
    return open(arq, "rb")


@protegido("alesp_cadastro")
def cadastro():
    partidos = {}
    f = _xml(f"{BASE}/deputados/partidos.xml")
    for r in registros(f, ["numero", "sigla"]):
        partidos[r.get("numero")] = r.get("sigla")
    deps = []
    f = _xml(f"{BASE}/deputados/deputados.xml")
    for r in registros(f, ["iddeputado", "nomeparlamentar"]):
        deps.append({"idDeputado": r.get("iddeputado"), "nome": r.get("nomeparlamentar"),
                     "partido": partidos.get(r.get("partido"), r.get("partido")),
                     "situacao": r.get("situacao"), "matricula": r.get("matricula"),
                     "idSPL": r.get("idspl"), "aniversario": r.get("aniversario")})
    registrar("alesp_cadastro", deputados=len(deps), partidos=len(partidos),
              exemplo=deps[0] if deps else None)
    return {"deputados": deps, "partidos": partidos}


@protegido("alesp_despesas")
def despesas():
    f = _xml(f"{BASE}/deputados/despesas_gabinetes.xml")
    agg = collections.defaultdict(lambda: [0.0, 0])
    forn = collections.defaultdict(float)
    nomes_matr = {}
    tipos = collections.Counter()
    n = 0
    for r in registros(f, ["ano", "valor", "deputado"]):
        try:
            ano = int(r.get("ano") or 0)
        except ValueError:
            continue
        if ano < INICIO:
            continue
        mes = int(re.sub(r"\D", "", r.get("mes") or "0") or 0)
        nome = r.get("deputado") or ""
        k = norm(nome)
        nomes_matr[k] = (nome, r.get("matricula"))
        tipo = r.get("tipo") or "N/I"
        tipos[tipo] += 1
        v = num(r.get("valor"))
        a = agg[(k, ano, mes, tipo)]
        a[0] += v
        a[1] += 1
        forn[(k, ano, (r.get("fornecedor") or "")[:80], r.get("cnpj") or "")] += v
        n += 1
    linhas = [[k, ano, mes, tipo, round(v, 2), c] for (k, ano, mes, tipo), (v, c) in agg.items()]
    fl = [[k, ano, nome, cnpj, round(v, 2)] for (k, ano, nome, cnpj), v in forn.items() if v > 0]
    registrar("alesp_despesas", registros=n, linhas=len(linhas), tipos=tipos.most_common(30),
              deputados=len(nomes_matr))
    return {"linhas": linhas, "forn": fl, "nomes": {k: v[0] for k, v in nomes_matr.items()},
            "matriculas": {k: v[1] for k, v in nomes_matr.items()}}


@protegido("alesp_proposituras")
def proposituras():
    nat = {}
    for url in (f"{BASE}/processo_legislativo/naturezasSpl.xml",):
        f = _xml(url)
        if f is not None:
            for r in registros(f, ["idnatureza", "sgnatureza"]):
                nat[r.get("idnatureza")] = (r.get("sgnatureza"), r.get("nmnatureza"), r.get("tpnatureza"))
    props = {}
    f = _xml(f"{BASE}/processo_legislativo/proposituras.zip")
    for r in registros(f, ["iddocumento", "anolegislativo"]):
        try:
            ano = int(r.get("anolegislativo") or 0)
        except ValueError:
            continue
        if ano < INICIO:
            continue
        sg, nm, tp = nat.get(r.get("idnatureza"), (r.get("idnatureza"), "", ""))
        props[r["iddocumento"]] = {"ano": ano, "tipo": sg, "nomeTipo": nm, "tpNat": tp,
                                   "numero": r.get("nrolegislativo"),
                                   "data": iso(r.get("dtentradasistema")),
                                   "ementa": (r.get("ementa") or "")[:400]}
    log("ALESP proposituras desde", INICIO, len(props))
    # último andamento de cada propositura
    ult = {}
    etapas = collections.Counter()
    f = _xml(f"{BASE}/processo_legislativo/documento_andamento_atual.zip")
    if f is not None:
        for r in registros(f, ["iddocumento", "descricao"]):
            d = r.get("iddocumento")
            if d in props:
                cur = ult.get(d)
                chave = (iso(r.get("data")), int(r.get("nrordem") or 0) if (r.get("nrordem") or "").isdigit() else 0)
                if cur is None or chave >= cur[0]:
                    ult[d] = (chave, r.get("nmetapa") or "", r.get("tpandamento") or "", r.get("descricao") or "")
        for d, (_, et, tp, ds) in ult.items():
            etapas[(et, tp)] += 1
    autores = []
    nomes_autor = collections.Counter()
    f = _xml(f"{BASE}/processo_legislativo/documento_autor.zip")
    for r in registros(f, ["iddocumento", "nomeautor"]):
        d = r.get("iddocumento")
        if d in props:
            autores.append([norm(r.get("nomeautor")), d, r.get("idautor")])
            nomes_autor[r.get("nomeautor")] += 1
    for d, p in props.items():
        u = ult.get(d)
        p["etapa"] = u[1] if u else ""
        p["tpAnd"] = u[2] if u else ""
        p["ultDesc"] = (u[3] if u else "")[:200]
    registrar("alesp_proposituras", proposituras=len(props), autorias=len(autores),
              naturezas=len(nat), etapas_finais_mais_comuns=[[list(k), v] for k, v in etapas.most_common(40)],
              autores_mais_comuns=nomes_autor.most_common(15))
    return {"props": props, "autores": autores, "naturezas": nat}


@protegido("alesp_presencas")
def presencas():
    f = _xml(f"{BASE}/processo_legislativo/comissoes_permanentes_presencas.xml")
    vistos = set()
    for r in registros(f, ["idreuniao", "iddeputado"]):
        data = iso(r.get("datareuniao"))
        ano = int(data[:4]) if data else 0
        if ano < INICIO:
            continue
        vistos.add((norm(r.get("deputado")), r.get("iddeputado"), r.get("idreuniao"), data))
    linhas = collections.Counter()
    for k, idd, reun, data in vistos:
        linhas[(k, data[:4], data[5:7] if len(data) >= 7 else "")] += 1
    registrar("alesp_presencas", presencas=len(vistos),
              exemplo=next(iter(vistos)) if vistos else None)
    return [[k, a, m, c] for (k, a, m), c in linhas.items()]
