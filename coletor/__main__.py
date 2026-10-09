"""Executa a coleta completa: python -m coletor"""
import json
import datetime as dt

from . import alesp, camara, montar, transparencia, tse
from .util import DADOS, FORCAR, STATUS, log, registrar


def main():
    log("início; atualização completa:", FORCAR)
    cand = tse.candidaturas()

    desp = camara.despesas()
    vots = camara.votacoes()
    ids = {l[0] for l in (desp or {}).get("linhas", [])} | {v[0] for v in (vots or {}).get("votos", [])}
    cad = camara.deputados(ids)
    fed = None
    if cad:
        props = camara.proposicoes([d["id"] for d in cad["deputados"]])
        emds = transparencia.emendas(cad["deputados"])
        fed = montar.federal(cad, desp, props, vots, cand, emds)

    ecad = alesp.cadastro()
    edesp = alesp.despesas()
    eprops = alesp.proposituras()
    epres = alesp.presencas()
    enormas = alesp.normas()
    est = montar.estadual(ecad, edesp, eprops, epres, cand, enormas)

    agora = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M")
    resumo = {k: {"ok": v.get("ok", True), "erro": v.get("erro"), "aviso": v.get("aviso")} for k, v in STATUS.items()}
    painel = {"meta": {"geradoEm": agora, "inicio": 2015, "fontes": resumo,
                       "sucessoras": montar.SUCESSORAS},
              "federal": fed, "estadual": est}
    antigo = DADOS / "painel.json"
    anterior = json.loads(antigo.read_text(encoding="utf-8")) if antigo.exists() else {}
    falhou = lambda pref: any(k.startswith(pref) and not v.get("ok", True) for k, v in STATUS.items())
    avisos = []
    # Se alguma fonte de uma casa falhou, mantém a versão anterior inteira daquela casa (melhor um dia de atraso do que número errado)
    if (fed is None or falhou("camara") or falhou("tse")) and anterior.get("federal"):
        painel["federal"] = anterior["federal"]
        avisos.append("Câmara: mantidos os dados da coleta anterior (falha em alguma fonte hoje).")
    # emendas falharam ou sem chave: aproveita as da coleta anterior, se houver
    if painel.get("federal") and painel["federal"].get("emendas") is None and (anterior.get("federal") or {}).get("emendas"):
        novo, velho = painel["federal"], anterior["federal"]
        ids_novos = {p["id"]: i for i, p in enumerate(novo["parlamentares"])}
        rows = []
        for pi_, ano, part, f, *vals in velho["emendas"]:
            did = velho["parlamentares"][pi_]["id"]
            if did not in ids_novos:
                continue
            nome_p = velho["partidos"][part]
            if nome_p not in novo["partidos"]:
                novo["partidos"].append(nome_p)
            rows.append([ids_novos[did], ano, novo["partidos"].index(nome_p), f, *vals])
        novo["emendas"], novo["funcoes"] = rows, velho["funcoes"]
    if (falhou("alesp") or falhou("tse")) and anterior.get("estadual"):
        painel["estadual"] = anterior["estadual"]
        avisos.append("ALESP: mantidos os dados da coleta anterior (falha em alguma fonte hoje).")
    painel["meta"]["avisos"] = avisos
    antigo.write_text(json.dumps(painel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    registrar("geral", geradoEm=agora, tamanho_painel_mb=round(antigo.stat().st_size / 1e6, 2))
    (DADOS / "status.json").write_text(json.dumps(STATUS, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log("fim")


if __name__ == "__main__":
    main()
