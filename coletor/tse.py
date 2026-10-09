"""Candidaturas a deputado federal e estadual em SP (TSE): perfil declarado, partido na eleição e bens."""
import pandas as pd

from .util import abrir_zip, baixar, com_cache, log, norm, num, protegido, registrar

BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
ELEICOES = [2014, 2018, 2022]
CARGOS = {"DEPUTADO FEDERAL": "F", "DEPUTADO ESTADUAL": "E"}


def _ler(f):
    return pd.read_csv(f, sep=";", dtype=str, encoding="latin-1", low_memory=False)


def _eleicao(ano):
    cz = baixar(f"{BASE}/consulta_cand/consulta_cand_{ano}.zip")
    if cz is None:
        return None
    f, nomes = abrir_zip(cz, f"_{ano}_SP.csv")
    df = _ler(f)
    df = df[df["DS_CARGO"].str.upper().isin(CARGOS)]
    sit = df["DS_SIT_TOT_TURNO"].fillna("").str.upper()
    df = df[sit.str.contains("ELEITO") | sit.str.contains("SUPLENTE")]
    bens = {}
    bz = baixar(f"{BASE}/bem_candidato/bem_candidato_{ano}.zip")
    if bz is not None:
        fb, _ = abrir_zip(bz, f"_{ano}_SP.csv")
        b = _ler(fb)
        b["v"] = b["VR_BEM_CANDIDATO"].map(num)
        bens = b.groupby("SQ_CANDIDATO")["v"].sum().round(2).to_dict()
    saida = []
    for _, r in df.iterrows():
        saida.append({
            "ano": ano, "cargo": CARGOS[r["DS_CARGO"].upper()],
            "sq": r["SQ_CANDIDATO"], "nome": r["NM_CANDIDATO"], "urna": r["NM_URNA_CANDIDATO"],
            "cpf": (r.get("NR_CPF_CANDIDATO") or "").zfill(11) if (r.get("NR_CPF_CANDIDATO") or "").isdigit() else "",
            "partido": r["SG_PARTIDO"], "situacao": r["DS_SIT_TOT_TURNO"],
            "nascimento": r.get("DT_NASCIMENTO"), "genero": r.get("DS_GENERO"),
            "instrucao": r.get("DS_GRAU_INSTRUCAO"), "corRaca": r.get("DS_COR_RACA"),
            "ocupacao": r.get("DS_OCUPACAO"), "estadoCivil": r.get("DS_ESTADO_CIVIL"),
            "bens": bens.get(r["SQ_CANDIDATO"]),
            "kNome": norm(r["NM_CANDIDATO"]), "kUrna": norm(r["NM_URNA_CANDIDATO"]),
        })
    log("TSE", ano, len(saida), "eleitos/suplentes")
    return saida


@protegido("tse")
def candidaturas():
    todos = []
    for ano in ELEICOES:
        # resultados de eleições passadas não mudam: cache permanente
        r = com_cache("tse", ano, _eleicao)
        todos += r or []
    registrar("tse", registros=len(todos))
    return todos
