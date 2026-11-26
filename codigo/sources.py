"""Fuentes de datos públicas para el cerebro de análisis (26-nov-2026).
Cada descarga queda en el estudio con URL exacta, fecha y SHA-256 (trazabilidad: cualquiera puede repetirla).
Sin claves ni cuentas: Banco Mundial (API v2), NOAA CPC (ONI), Atlas de Complejidad Económica de Harvard (GraphQL),
Crossref y arXiv (literatura). Nada de esto usa IA: los números salen de las APIs tal cual."""
import datetime as dt
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "bryan-ops-research/1.0 (analisis de datos publicos; mailto:theborboton7@gmail.com)"}
LATAM = ["ARG", "BOL", "BRA", "CHL", "COL", "CRI", "DOM", "ECU", "GTM", "HND", "MEX", "NIC", "PAN", "PER", "PRY", "SLV", "URY"]
NOMBRES = {"ARG": "Argentina", "BOL": "Bolivia", "BRA": "Brasil", "CHL": "Chile", "COL": "Colombia", "CRI": "Costa Rica",
           "DOM": "Rep. Dominicana", "ECU": "Ecuador", "GTM": "Guatemala", "HND": "Honduras", "MEX": "México", "NIC": "Nicaragua",
           "PAN": "Panamá", "PER": "Perú", "PRY": "Paraguay", "SLV": "El Salvador", "URY": "Uruguay", "USA": "EE. UU.",
           "ESP": "España", "WLD": "Mundo", "LCN": "América Latina y Caribe"}


class Prov:
    """Registro de procedencia de un estudio: cada archivo descargado con su URL, fecha y hash."""

    def __init__(self, d: Path):
        self.d = d; (d / "data").mkdir(parents=True, exist_ok=True); self.items = []

    def get(self, url, name, method="GET", payload=None, retries=3):
        for k in range(retries):
            try:
                r = (requests.post(url, json=payload, headers=UA, timeout=90) if method == "POST"
                     else requests.get(url, headers=UA, timeout=90))
                r.raise_for_status(); break
            except Exception:
                if k == retries - 1: raise
                time.sleep(3 * (k + 1))
        f = self.d / "data" / name; f.write_bytes(r.content)
        self.items.append({"archivo": f"data/{name}", "url": url, "metodo": method,
                           "consulta": payload, "descargado": dt.datetime.now().isoformat(timespec="seconds"),
                           "sha256": hashlib.sha256(r.content).hexdigest()})
        return r

    def save(self):
        (self.d / "procedencia.json").write_text(json.dumps(self.items, ensure_ascii=False, indent=1))


def worldbank(prov, indicators, countries, y0, y1):
    """Panel largo: iso3, year, una columna por indicador. Devuelve (df, nombres_de_indicadores)."""
    frames, names = [], {}
    for ind in indicators:
        url = (f"https://api.worldbank.org/v2/country/{';'.join(countries)}/indicator/{ind}"
               f"?format=json&date={y0}:{y1}&per_page=20000")
        js = prov.get(url, f"wb_{ind}.json").json()
        if len(js) < 2 or not js[1]:
            raise ValueError(f"Banco Mundial sin datos para {ind}")
        names[ind] = js[1][0]["indicator"]["value"]
        frames.append(pd.DataFrame([{"iso3": r["countryiso3code"], "year": int(r["date"]), ind: r["value"]}
                                    for r in js[1] if r["countryiso3code"]]).set_index(["iso3", "year"]))
    df = pd.concat(frames, axis=1).reset_index().sort_values(["iso3", "year"])
    df.to_csv(prov.d / "data" / "panel_banco_mundial.csv", index=False)
    return df, names


def wb_indicator_exists(ind):
    try:
        js = requests.get(f"https://api.worldbank.org/v2/indicator/{ind}?format=json", headers=UA, timeout=30).json()
        return len(js) > 1 and bool(js[1]) and js[1][0].get("id") == ind
    except Exception:
        return False


def oni(prov):
    """Índice Oceánico El Niño (NOAA CPC), estaciones trimestrales móviles. Devuelve df year, season, anom."""
    r = prov.get("https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt", "noaa_oni.txt")
    rows = [l.split() for l in r.text.splitlines()[1:] if l.strip()]
    df = pd.DataFrame([{"season": s, "year": int(y), "anom": float(a)} for s, y, _t, a in rows])
    df.to_csv(prov.d / "data" / "noaa_oni.csv", index=False)
    return df


ATLAS = "https://atlas.hks.harvard.edu/api/graphql"


def atlas_country_year(prov, y0, y1):
    """Complejidad económica (ECI) y comercio por país-año del Atlas de Harvard, con ISO3."""
    meta = prov.get(ATLAS, "atlas_paises.json", "POST", {"query": "{ locationCountry{ countryId iso3Code nameShortEs inRankings } }"}).json()
    iso = {m["countryId"]: m for m in meta["data"]["locationCountry"]}
    q = ("{ countryYear(yearMin:%d, yearMax:%d){ countryId year eci exportValue importValue gdppc gdppcConst population growthProj } }"
         % (y0, y1))
    js = prov.get(ATLAS, f"atlas_countryYear_{y0}_{y1}.json", "POST", {"query": q}).json()
    df = pd.DataFrame(js["data"]["countryYear"])
    df["iso3"] = df.countryId.map(lambda c: iso.get(c, {}).get("iso3Code"))
    df["en_ranking"] = df.countryId.map(lambda c: iso.get(c, {}).get("inRankings"))
    df.to_csv(prov.d / "data" / "atlas_country_year.csv", index=False)
    return df


def crossref(query, rows=8, since=2015):
    """Literatura relacionada (solo metadatos reales: título, autores, año, DOI). No se afirma lo que dicen."""
    try:
        r = requests.get("https://api.crossref.org/works", headers=UA, timeout=40,
                         params={"query.bibliographic": query, "rows": rows, "filter": f"from-pub-date:{since},type:journal-article",
                                 "select": "title,DOI,author,issued,container-title,is-referenced-by-count", "sort": "relevance"})
        out = []
        for it in r.json()["message"]["items"]:
            if not it.get("title"): continue
            out.append({"titulo": it["title"][0], "doi": it["DOI"], "anio": (it.get("issued", {}).get("date-parts") or [[None]])[0][0],
                        "revista": (it.get("container-title") or [""])[0], "citas": it.get("is-referenced-by-count", 0),
                        "autores": ", ".join(a.get("family", "") for a in (it.get("author") or [])[:3])})
        return sorted(out, key=lambda x: -x["citas"])[:5]
    except Exception:
        return []


def arxiv(query, n=10):
    """Papers recientes de arXiv (título, autores, fecha, resumen literal, URL)."""
    r = requests.get("https://export.arxiv.org/api/query", headers=UA, timeout=60,
                     params={"search_query": query, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": n})
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(r.content).findall("a:entry", ns):
        g = lambda t: re.sub(r"\s+", " ", (e.findtext(f"a:{t}", "", ns) or "")).strip()
        out.append({"titulo": g("title"), "resumen": g("summary"), "fecha": g("published")[:10], "url": g("id"),
                    "autores": ", ".join(a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)[:4])})
    return out
