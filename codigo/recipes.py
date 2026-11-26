"""Recetas de análisis deterministas (sin IA): cada una baja datos, estima, se comprueba a sí misma y devuelve
{"hallazgos": [frases con cifras calculadas], "cifras": {...}, "checks": [{nombre, ok, detalle}], "grafico": png, "metodo": md,
 "limitaciones": [...]}. Si un check crítico falla, el estudio queda "fallido" y no llega a LinkedIn.
Las frases de hallazgos las arma el código con los números calculados: el redactor de LinkedIn solo puede usar esas."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402

import sources as S  # noqa: E402

RNG = np.random.default_rng(20261126)
INK, MUTED, BG, GRID = "#E5E7EB", "#94A3B8", "#0B1220", "#1F2A40"
POS, NEG, NEU = "#38BDF8", "#F59E0B", "#475569"


def f2(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def pct(x, d=1):
    return f"{x:.{d}f}%".replace(".", ",")


def ols_np(y, X):
    """Reproducción independiente con álgebra lineal (check contra statsmodels)."""
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return b


def chart_base(title, subtitle, source):
    fig = plt.figure(figsize=(12, 12), dpi=100, facecolor=BG)
    fig.text(0.07, 0.93, title, color="white", fontsize=30, fontweight="bold", va="top", wrap=True)
    fig.text(0.07, 0.865, subtitle, color=MUTED, fontsize=17, va="top", wrap=True)
    fig.text(0.07, 0.05, source, color=MUTED, fontsize=12.5)
    fig.text(0.07, 0.02, "Bryan Román · Economista · análisis reproducible: bryan-roman-ai.github.io/laboratorio-datos", color=INK, fontsize=13, fontweight="bold")
    ax = fig.add_axes([0.30, 0.12, 0.63, 0.69], facecolor=BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=INK, labelsize=15); ax.grid(axis="x", color=GRID); ax.set_axisbelow(True)
    return fig, ax


# ---------------------------------------------------------------------------------------------------------------
# 1) ENSO (El Niño) → economía latinoamericana segmentada por país y por estructura exportadora
# ---------------------------------------------------------------------------------------------------------------
def _cum(m, a="oni", b="oni_l"):
    """Efecto acumulado (año del evento + año siguiente) con su error estándar desde la matriz de covarianzas."""
    v = m.cov_params(); est = m.params[a] + m.params[b]
    se = float(np.sqrt(v.loc[a, a] + v.loc[b, b] + 2 * v.loc[a, b]))
    from scipy import stats
    pv = 2 * (1 - stats.norm.cdf(abs(est / se))) if se > 0 else 1.0
    return est, se, pv


def enso(prov, p, out):
    y0, y1 = p.get("y0", 1981), p.get("y1", 2024)
    countries = p.get("countries", S.LATAM)
    outcome = p.get("outcome", "NV.AGR.TOTL.KD.ZG")
    seg = p.get("segment", "TX.VAL.FOOD.ZS.UN")
    on = S.oni(prov)
    ann = on.groupby("year").anom.mean().rename("oni")              # intensidad media del año calendario
    peak = on.groupby("year").anom.max().rename("oni_max")          # definición alternativa (robustez)
    lagd = ann.reindex(ann.index - 1).set_axis(ann.index).rename("oni_l")
    lagm = peak.reindex(peak.index - 1).set_axis(peak.index).rename("oni_max_l")
    df, names = S.worldbank(prov, [outcome, seg, "NY.GDP.MKTP.KD.ZG"], countries + ["WLD"], y0 - 1, y1)
    wld = df[df.iso3 == "WLD"].set_index("year")["NY.GDP.MKTP.KD.ZG"].rename("wld")
    d = df[df.iso3 != "WLD"]
    for s_ in (ann, peak, lagd, lagm, wld): d = d.merge(s_, left_on="year", right_index=True)
    d = d[(d.year >= y0) & (d.year <= y1)]
    if p.get("drop_covid", True): d = d[d.year != 2020]
    d = d.dropna(subset=[outcome, "oni", "oni_l", "wld"])
    checks, rows = [], []
    for c, g in d.groupby("iso3"):
        if len(g) < 25: continue
        X = sm.add_constant(g[["oni", "oni_l", "wld"]]); m = sm.OLS(g[outcome], X).fit(cov_type="HAC", cov_kwds={"maxlags": 2})
        mx = sm.OLS(g[outcome], sm.add_constant(g[["oni_max", "oni_max_l", "wld"]])).fit()
        est, se, pv = _cum(m)
        b_np = ols_np(g[outcome].values, X.values)
        rows.append({"iso3": c, "pais": S.NOMBRES.get(c, c), "beta": est, "lo": est - 1.96 * se, "hi": est + 1.96 * se, "p": pv,
                     "n": int(m.nobs), "dif_np": abs(b_np[1] + b_np[2] - est),
                     "beta_max": mx.params["oni_max"] + mx.params["oni_max_l"], "seg": df[(df.iso3 == c)][seg].dropna().tail(15).mean()})
    r = pd.DataFrame(rows).sort_values("beta")
    checks.append({"nombre": "reproducción numpy = statsmodels (por país)", "critico": True, "ok": bool(r.dif_np.max() < 1e-8),
                   "detalle": f"máx. diferencia {r.dif_np.max():.2e}"})
    checks.append({"nombre": "cobertura: ≥ 12 países con ≥ 25 años", "critico": True, "ok": len(r) >= 12,
                   "detalle": f"{len(r)} países, n mediano {int(r.n.median())}"})
    med = r.seg.median(); r["grupo"] = np.where(r.seg >= med, "alta", "baja")
    pan = d.merge(r[["iso3", "seg", "grupo"]], on="iso3")
    hi_ = (pan.grupo == "alta").astype(float)
    pan["oni_x"], pan["oni_l_x"] = pan.oni * hi_, pan.oni_l * hi_
    fe = pd.get_dummies(pan.iso3, prefix="c", drop_first=True, dtype=float)
    cols = ["oni", "oni_l", "oni_x", "oni_l_x", "wld"]
    Xp = sm.add_constant(pd.concat([pan[cols], fe], axis=1))
    mp = sm.OLS(pan[outcome], Xp).fit(cov_type="cluster", cov_kwds={"groups": pan.year})
    base, base_se, base_p = _cum(mp)
    dif, dif_se, dif_p = _cum(mp, "oni_x", "oni_l_x")
    # permutación: baraja la secuencia anual del ONI (con su rezago) entre años; conserva la estructura de los países
    yrs = np.sort(pan.year.unique()); perm = []
    pairs = np.c_[ann.reindex(yrs).values, lagd.reindex(yrs).values]
    for _ in range(999):
        sh = dict(zip(yrs, pairs[RNG.permutation(len(yrs))]))
        o = np.array([sh[t][0] for t in pan.year]); ol = np.array([sh[t][1] for t in pan.year])
        Xs = np.c_[np.ones(len(pan)), o, ol, o * hi_, ol * hi_, pan.wld.values, fe.values]
        b = ols_np(pan[outcome].values, Xs); perm.append(b[1] + b[2])
    p_perm = (np.sum(np.abs(perm) >= abs(base)) + 1) / (len(perm) + 1)
    sign_alt = float(np.mean(np.sign(r.beta) == np.sign(r.beta_max)))
    checks.append({"nombre": "definición alternativa (ONI máximo del año): mismo signo por país", "critico": False, "ok": sign_alt >= 0.7,
                   "detalle": f"{sign_alt:.0%} de los países conservan el signo"})
    loo = []
    for c in r.iso3:
        q = pan[pan.iso3 != c]; hq = (q.grupo == "alta").astype(float)
        Xq = np.c_[np.ones(len(q)), q.oni, q.oni_l, q.oni * hq, q.oni_l * hq, q.wld, pd.get_dummies(q.iso3, drop_first=True, dtype=float).values]
        b = ols_np(q[outcome].values, Xq); loo.append(b[1] + b[2])
    stable = bool(np.all(np.sign(loo) == np.sign(base)))
    checks.append({"nombre": "dejar un país fuera: el efecto regional conserva el signo", "critico": False, "ok": stable,
                   "detalle": f"rango {f2(min(loo))} a {f2(max(loo))}"})
    checks.append({"nombre": "prueba de permutación del efecto regional (999)", "critico": False, "ok": p_perm < 0.10,
                   "detalle": f"p={f2(p_perm, 3)}"})
    sig = r[r.p < 0.10]
    lab_es = {"NV.AGR.TOTL.KD.ZG": "crecimiento agrícola", "NY.GDP.MKTP.KD.ZG": "crecimiento del PIB",
              "NE.EXP.GNFS.KD.ZG": "crecimiento de las exportaciones", "NE.IMP.GNFS.KD.ZG": "crecimiento de las importaciones",
              "FP.CPI.TOTL.ZG": "inflación"}.get(outcome, names[outcome])
    seg_es = {"TX.VAL.FOOD.ZS.UN": "alimentos", "TX.VAL.FUEL.ZS.UN": "combustibles", "TX.VAL.AGRI.ZS.UN": "materias primas agrícolas"}.get(seg, seg)
    robust = p_perm < 0.10 and stable
    last = on.iloc[-1]; hist = on[on.anom >= last.anom]
    H = [f"El índice ONI de NOAA (anomalía de temperatura del Pacífico, la medida oficial de El Niño) marcó {f2(last.anom)} °C en {last.season} {int(last.year)}; "
         f"solo {len(hist) - 1} estaciones trimestrales desde 1950 lo igualan o superan."]
    if robust:
        H.append(f"En {len(r)} países de América Latina ({y0}-{y1}, sin 2020), +1 °C de ONI se asocia con {f2(base)} puntos porcentuales de {lab_es} "
                 f"(año del evento + año siguiente) en los países con menor peso de {seg_es} en sus exportaciones; el resultado es robusto "
                 f"(permutación p={f2(p_perm, 3)}, estable al quitar cualquier país).")
    else:
        H.append(f"En el promedio de {len(r)} países de América Latina ({y0}-{y1}, sin 2020) NO hay un efecto regional claro de El Niño sobre el {lab_es}: "
                 f"{f2(base)} pp por +1 °C (año del evento + siguiente), prueba de permutación p={f2(p_perm, 3)}. El promedio esconde países que se mueven en sentidos opuestos.")
    H.append(f"Separando por tipo de comercio, los países con más peso de {seg_es} en sus exportaciones difieren en {f2(dif)} pp por +1 °C "
             f"respecto de los demás (p={f2(dif_p, 3)}{'' if dif_p < .1 else ', no significativo'}).")
    H.append(f"País por país: {len(sig)} de {len(r)} muestran un efecto distinto de cero al 10%. Mayor efecto negativo: {r.iloc[0].pais} "
             f"({f2(r.iloc[0].beta)} pp por +1 °C; p={f2(r.iloc[0].p, 3)}); mayor positivo: {r.iloc[-1].pais} ({f2(r.iloc[-1].beta)} pp; p={f2(r.iloc[-1].p, 3)}).")
    if "ECU" in set(r.iso3):
        e = r[r.iso3 == "ECU"].iloc[0]
        H.append(f"Ecuador: {f2(e.beta)} pp de {lab_es} por cada +1 °C de ONI (IC 95%: {f2(e.lo)} a {f2(e.hi)}; p={f2(e.p, 3)}; {e.n} años)"
                 f"{'.' if e.p < .1 else ', no distinguible de cero con datos anuales.'}")
    fig, ax = chart_base(f"El Niño y el {lab_es}", f"Efecto de +1 °C de ONI (año del evento + siguiente), pp. {y0}-{y1}, sin 2020. "
                         f"Color = significativo al 10%; línea = IC 95%. ● = exporta mucho {seg_es}.", "Fuente: NOAA CPC (ONI), Banco Mundial (WDI). Cálculos propios: MCO con errores HAC.")
    colr = [NEG if (b < 0 and pv < .1) else POS if (b > 0 and pv < .1) else NEU for b, pv in zip(r.beta, r.p)]
    yy = np.arange(len(r)); ax.barh(yy, r.beta, color=colr, height=0.62)
    ax.hlines(yy, r.lo, r.hi, color=INK, lw=1.4, alpha=.55); ax.axvline(0, color=INK, lw=1)
    ax.set_yticks(yy, [f"{n} {'●' if g == 'alta' else '○'}" for n, g in zip(r.pais, r.grupo)])

    ax.set_xlabel("pp por +1 °C de ONI", color=MUTED, fontsize=14)
    fig.savefig(out / "grafico.png", facecolor=BG); plt.close(fig)
    r.drop(columns=["dif_np"]).to_csv(out / "resultados_por_pais.csv", index=False)
    (out / "panel_resumen.txt").write_text(mp.summary().as_text())
    return {"hallazgos": H, "checks": checks, "cifras": {"regional": base, "p_perm": p_perm, "dif": dif}, "robusto": robust,
            "metodo": (f"Variable climática: media anual del ONI de NOAA CPC y su rezago de un año (el efecto se mide como la suma: año del evento + "
                       f"año siguiente); robustez con el máximo anual. Resultado: {names[outcome]} ({outcome}). Por país: MCO con crecimiento mundial "
                       "como control y errores HAC (Newey-West, 2 rezagos). Panel: efectos fijos de país e interacción con el grupo de países con "
                       f"peso alto de {seg_es} en sus exportaciones ({seg}, promedio de los últimos 15 años, corte en la mediana), errores agrupados "
                       "por año. Prueba de permutación (999 barajas de la secuencia anual del ONI). Robustez: dejar un país fuera."),
            "limitaciones": ["Asociación, no causalidad: otros choques del mismo año (precios de materias primas) pueden coincidir con El Niño.",
                             "Datos anuales: el efecto dentro del año (temporada de lluvias) se diluye.",
                             f"La segmentación por tipo de comercio usa la participación de {seg_es} en las exportaciones de mercancías."]}


# ---------------------------------------------------------------------------------------------------------------
# 2) Panel con efectos fijos (p. ej. STIRPAT: huella de carbono vs urbanización, consumo y estructura generacional)
# ---------------------------------------------------------------------------------------------------------------
def fe_panel(prov, p, out):
    y, xs, logs = p["y"], p["x"], set(p.get("log", []))
    countries, y0, y1 = p.get("countries", S.LATAM), p.get("y0", 1995), p.get("y1", 2023)
    labels = p.get("labels", {})
    df, names = S.worldbank(prov, [y] + xs, countries, y0, y1)
    d = df.dropna(subset=[y] + xs).copy()
    for v in [y] + xs:
        if v in logs: d = d[d[v] > 0]; d[v] = np.log(d[v])
    # within (efectos fijos de país y de año): doble demeaning sobre panel completo de cada país
    def within(q):
        z = q[[y] + xs].copy()
        z = z - q.groupby("iso3")[[y] + xs].transform("mean") - q.groupby("year")[[y] + xs].transform("mean") + q[[y] + xs].mean()
        return z
    z = within(d)
    m = sm.OLS(z[y], z[xs]).fit(cov_type="cluster", cov_kwds={"groups": d.iso3})
    # check: dummies completas (LSDV) deben dar el mismo coeficiente que el within (en panel balanceado) → usamos LSDV como referencia
    D = pd.concat([d[xs], pd.get_dummies(d.iso3, drop_first=True, dtype=float), pd.get_dummies(d.year, drop_first=True, dtype=float)], axis=1)
    lsdv = sm.OLS(d[y], sm.add_constant(D)).fit(cov_type="cluster", cov_kwds={"groups": d.iso3})
    bnp = ols_np(d[y].values, sm.add_constant(D).values)
    checks = [{"nombre": "reproducción numpy = statsmodels (LSDV)", "ok": bool(np.allclose(bnp[1:1 + len(xs)], lsdv.params[xs].values, atol=1e-6)),
               "detalle": "; ".join(f"{labels.get(x, x)}: LSDV {f2(lsdv.params[x], 3)} vs within {f2(m.params[x], 3)}" for x in xs)}]
    main = lsdv  # LSDV es exacto también con panel desbalanceado
    checks.append({"nombre": "cobertura ≥ 10 países y ≥ 150 observaciones", "ok": d.iso3.nunique() >= 10 and len(d) >= 150,
                   "detalle": f"{d.iso3.nunique()} países, {len(d)} obs."})
    loo = {x: [] for x in xs}
    for c in d.iso3.unique():
        q = d[d.iso3 != c]
        Dq = pd.concat([q[xs], pd.get_dummies(q.iso3, drop_first=True, dtype=float), pd.get_dummies(q.year, drop_first=True, dtype=float)], axis=1)
        b = ols_np(q[y].values, sm.add_constant(Dq).values)
        for i, x in enumerate(xs): loo[x].append(b[1 + i])
    stable = {x: bool(np.all(np.sign(loo[x]) == np.sign(main.params[x]))) for x in xs}
    checks.append({"nombre": "dejar un país fuera: signos estables", "critico": False, "ok": all(stable.values()),
                   "detalle": "; ".join(f"{labels.get(x, x)}: {'estable' if stable[x] else 'CAMBIA de signo'}" for x in xs)})
    half = (d.year.min() + d.year.max()) // 2
    sub = {}
    for nm, q in (("primera mitad", d[d.year <= half]), ("segunda mitad", d[d.year > half])):
        Dq = pd.concat([q[xs], pd.get_dummies(q.iso3, drop_first=True, dtype=float), pd.get_dummies(q.year, drop_first=True, dtype=float)], axis=1)
        sub[nm] = sm.OLS(q[y], sm.add_constant(Dq)).fit().params
    checks.append({"nombre": "estabilidad por subperiodos (informativo)", "critico": False, "ok": True,
                   "detalle": "; ".join(f"{labels.get(x, x)}: {f2(sub['primera mitad'][x], 3)} → {f2(sub['segunda mitad'][x], 3)}" for x in xs)})
    vif = []
    for i, x in enumerate(xs):
        others = [o for o in xs if o != x]
        if others:
            r2 = sm.OLS(z[x], z[others]).fit().rsquared; vif.append((x, 1 / max(1e-9, 1 - r2)))
    checks.append({"nombre": "multicolinealidad (VIF < 10)", "critico": False, "ok": all(v < 10 for _, v in vif),
                   "detalle": "; ".join(f"{labels.get(x, x)} {f2(v, 1)}" for x, v in vif) or "una sola variable"})
    def interp(x):
        b, pv = main.params[x], main.pvalues[x]
        lo, hi = main.conf_int().loc[x]
        if y in logs and x in logs: txt = f"un aumento de 1% en {labels.get(x, x)} se asocia con {f2(b, 2)}% en {labels.get(y, y)}"
        elif y in logs:
            b, lo, hi = 100 * b, 100 * lo, 100 * hi
            txt = f"1 punto más de {labels.get(x, x)} se asocia con {f2(b, 2)}% en {labels.get(y, y)}"
        else: txt = f"1 unidad más de {labels.get(x, x)} se asocia con {f2(b, 3)} en {labels.get(y, y)}"
        return f"{txt} (IC 95%: {f2(lo, 2)} a {f2(hi, 2)}; p={f2(pv, 3)}; {'signo estable' if stable[x] else 'signo inestable'} al quitar países)."
    H = [f"Panel de {d.iso3.nunique()} países ({int(d.year.min())}-{int(d.year.max())}, {len(d)} observaciones) con efectos fijos de país y de año: "
         + interp(xs[0])] + [interp(x) for x in xs[1:]]
    # gráfico: coeficientes con IC
    fig, ax = chart_base(p.get("titulo_grafico", "Qué mueve la variable"), p.get("subtitulo_grafico", "Coeficientes con IC 95%, efectos fijos de país y año"),
                         "Fuente: Banco Mundial (WDI). Cálculos propios; errores agrupados por país.")
    ci = main.conf_int().loc[xs]; yy = np.arange(len(xs))
    ax.barh(yy, main.params[xs], color=[POS if main.pvalues[x] < .05 else NEU for x in xs], height=.55)
    ax.hlines(yy, ci[0], ci[1], color=INK, lw=2, alpha=.6); ax.axvline(0, color=INK, lw=1)
    ax.set_yticks(yy, [labels.get(x, x) for x in xs])
    fig.savefig(out / "grafico.png", facecolor=BG); plt.close(fig)
    (out / "panel_resumen.txt").write_text(main.summary().as_text()[:20000])
    d.to_csv(out / "panel_usado.csv", index=False)
    return {"hallazgos": H, "checks": checks, "cifras": {x: main.params[x] for x in xs},
            "metodo": (f"Variable dependiente: {names[y]} ({y}{', log' if y in logs else ''}). Explicativas: "
                       + "; ".join(f"{names[x]} ({x}{', log' if x in logs else ''})" for x in xs)
                       + ". MCO con efectos fijos de país y de año (LSDV), errores agrupados por país. Checks: estimador within, dejar un país fuera, subperiodos, VIF."),
            "limitaciones": p.get("limitaciones", []) + ["Asociación condicional, no causalidad.", "Indicadores del Banco Mundial con revisiones periódicas."]}


# ---------------------------------------------------------------------------------------------------------------
# 3) Complejidad económica (Atlas de Harvard): ¿predice el ECI el crecimiento? ¿dónde está Ecuador?
# ---------------------------------------------------------------------------------------------------------------
def atlas_eci(prov, p, out):
    y0, y1 = p.get("y0", 2000), p.get("y1", 2023)
    df = S.atlas_country_year(prov, y0, y1)
    df = df[df.eci.notna() & df.iso3.notna()]  # inRankings viene vacío en la API: se filtra con un criterio explícito
    # filtro tipo Atlas: ≥ 1 millón de habitantes y exportaciones ≥ US$ 1.000 millones en el año final
    big = set(df[(df.year == y1) & (df.population >= 1e6) & (df.exportValue >= 1e9)].iso3)
    df = df[df.iso3.isin(big)]
    # crecimiento con el PIB per cápita constante del Banco Mundial (el del Atlas trae saltos, p. ej. Ecuador 2000 por la dolarización)
    wb = []
    for yr in (y0, y1):
        js = prov.get(f"https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.KD?format=json&date={yr}&per_page=400",
                      f"wb_NY.GDP.PCAP.KD_{yr}.json").json()
        wb += [{"iso3": r["countryiso3code"], "year": yr, "pc": r["value"]} for r in js[1] if r["countryiso3code"] and r["value"]]
    wb = pd.DataFrame(wb).pivot(index="iso3", columns="year", values="pc").dropna()
    a, b = df[df.year == y0].set_index("iso3"), df[df.year == y1].set_index("iso3")
    k = a[["eci"]].rename(columns={"eci": "eci0"}).join(b[["eci"]].rename(columns={"eci": "eci1"}), how="inner").join(wb, how="inner").dropna()
    k["gdppcConst0"], k["gdppcConst1"] = k[y0], k[y1]
    k["g"] = (np.power(k.gdppcConst1 / k.gdppcConst0, 1 / (y1 - y0)) - 1) * 100
    k["lny0"] = np.log(k.gdppcConst0)
    # Hausmann-Hidalgo: crecimiento ~ ECI inicial + ingreso inicial (convergencia condicional)
    X = sm.add_constant(k[["eci0", "lny0"]]); m = sm.OLS(k.g, X).fit(cov_type="HC3")
    bnp = ols_np(k.g.values, X.values)
    checks = [{"nombre": "reproducción numpy", "ok": bool(np.allclose(bnp, m.params.values, atol=1e-8)), "detalle": "coeficientes idénticos"},
              {"nombre": "cobertura ≥ 80 países", "ok": len(k) >= 80, "detalle": f"{len(k)} países"}]
    boot = []
    for _ in range(1999):
        s = k.sample(len(k), replace=True, random_state=int(RNG.integers(1e9)))
        boot.append(ols_np(s.g.values, sm.add_constant(s[["eci0", "lny0"]]).values)[1])
    blo, bhi = np.percentile(boot, [2.5, 97.5])
    checks.append({"nombre": "bootstrap (1999 remuestreos) del efecto ECI", "ok": True, "detalle": f"IC 95% {f2(blo, 2)} a {f2(bhi, 2)}"})
    out_trim = k[(k.g > k.g.quantile(.02)) & (k.g < k.g.quantile(.98))]
    mt = sm.OLS(out_trim.g, sm.add_constant(out_trim[["eci0", "lny0"]])).fit()
    checks.append({"nombre": "sin el 2% extremo de crecimiento: mismo signo", "critico": False, "ok": bool(np.sign(mt.params.eci0) == np.sign(m.params.eci0)),
                   "detalle": f"{f2(mt.params.eci0, 2)} vs {f2(m.params.eci0, 2)}"})
    rank = df[df.year == y1].sort_values("eci", ascending=False).reset_index(drop=True)  # ya filtrado por tamaño
    focus = p.get("countries", ["ECU", "COL", "PER", "MEX", "CHL", "BRA", "ARG", "URY", "CRI", "PAN"])
    pos = {c: int(rank.index[rank.iso3 == c][0]) + 1 for c in focus if c in set(rank.iso3)}
    ecu = k.loc["ECU"] if "ECU" in k.index else None
    H = [f"En {len(k)} países, cada punto más de complejidad económica (ECI del Atlas de Harvard) en {y0} se asocia con "
         f"{f2(m.params.eci0, 2)} puntos porcentuales más de crecimiento anual del PIB per cápita {y0}-{y1}, a igual ingreso inicial "
         f"(p={f2(m.pvalues.eci0, 3)}; bootstrap IC 95%: {f2(blo, 2)} a {f2(bhi, 2)}).",
         f"Ranking de complejidad {y1} entre {len(rank)} países con más de 1 millón de habitantes y exportaciones de más de US$ 1.000 millones: " + ", ".join(f"{S.NOMBRES.get(c, c)} #{pos[c]}" for c in sorted(pos, key=pos.get)) + "."]
    if ecu is not None:
        pred = m.params.const + m.params.eci0 * ecu.eci0 + m.params.lny0 * ecu.lny0
        H.append(f"Ecuador: ECI {f2(ecu.eci0, 2)} en {y0} y {f2(ecu.eci1, 2)} en {y1}; creció {f2(ecu.g, 2)}% anual per cápita vs "
                 f"{f2(pred, 2)}% que predice el modelo con su complejidad e ingreso inicial.")
    fig, ax = chart_base("Complejidad económica y crecimiento", f"ECI {y0} (Atlas de Harvard) vs crecimiento anual del PIB per cápita {y0}-{y1}",
                         "Fuente: Growth Lab, Harvard (Atlas of Economic Complexity); Banco Mundial (WDI). Cálculos propios, MCO con errores HC3.")
    ax.set_position([0.11, 0.13, 0.82, 0.68]); ax.grid(color=GRID)
    ax.scatter(k.eci0, k.g, s=34, color=NEU, alpha=.8)
    la = k.loc[[c for c in focus if c in k.index]]
    ax.scatter(la.eci0, la.g, s=90, color=POS)
    for j, (c, rw) in enumerate(la.sort_values("g").iterrows()):
        ax.annotate(S.NOMBRES.get(c, c), (rw.eci0, rw.g), xytext=(8, -14 if j % 2 else 6), textcoords="offset points", color=NEG if c == "ECU" else INK,
                    fontsize=15 if c == "ECU" else 12, fontweight="bold" if c == "ECU" else None)
    xx = np.linspace(k.eci0.min(), k.eci0.max(), 50)
    ax.plot(xx, m.params.const + m.params.eci0 * xx + m.params.lny0 * k.lny0.mean(), color=NEG, lw=2.5)
    ax.set_xlabel(f"Complejidad económica (ECI) {y0}", color=MUTED, fontsize=15); ax.set_ylabel("% anual", color=MUTED, fontsize=15)
    fig.savefig(out / "grafico.png", facecolor=BG); plt.close(fig)
    k.to_csv(out / "cruce_paises.csv")
    return {"hallazgos": H, "checks": checks, "cifras": {"beta_eci": m.params.eci0, "p": m.pvalues.eci0},
            "metodo": ("ECI país-año del Atlas of Economic Complexity (Growth Lab, Harvard, API GraphQL pública), países con ≥ 1 millón de habitantes y "
                       f"exportaciones ≥ US$ 1.000 millones en {y1}. Crecimiento anual compuesto del PIB per cápita a precios constantes (Banco Mundial, NY.GDP.PCAP.KD) {y0}-{y1}. MCO crecimiento ~ ECI inicial + log PIB pc inicial "
                       "(convergencia condicional), errores HC3. Checks: reproducción numpy, bootstrap, recorte de extremos."),
            "limitaciones": ["El ECI se recalcula con cada versión del Atlas.", "Correlación entre países: no prueba que subir el ECI cause crecimiento.",
                             "Un solo periodo largo; no capta crisis intermedias."]}


# ---------------------------------------------------------------------------------------------------------------
# 4) Comparativo de indicadores (nivel, cambio y ranking regional): pymes, digitalización, crédito, etc.
# ---------------------------------------------------------------------------------------------------------------
def compare(prov, p, out):
    inds, countries = p["indicators"], p.get("countries", S.LATAM + ["USA", "ESP"])
    y0, y1 = p.get("y0", 2010), p.get("y1", 2024)
    labels, focus = p.get("labels", {}), p.get("focus", "ECU")
    df, names = S.worldbank(prov, inds, countries, y0, y1)
    H, checks, tab = [], [], []
    for ind in inds:
        s = df.dropna(subset=[ind])
        last = s.sort_values("year").groupby("iso3").tail(1).set_index("iso3")
        first = s.sort_values("year").groupby("iso3").head(1).set_index("iso3")
        if len(last) < 6:
            checks.append({"nombre": f"cobertura {ind}", "ok": False, "detalle": f"solo {len(last)} países con dato"}); continue
        checks.append({"nombre": f"cobertura {ind}", "ok": True, "detalle": f"{len(last)} países"})
        lab = labels.get(ind, names[ind])
        rk = last[ind].rank(ascending=False).astype(int)
        if focus in last.index:
            f, f0 = last.loc[focus], first.loc[focus]
            la_med = last[last.index.isin(S.LATAM)][ind].median()
            H.append(f"{lab}: {S.NOMBRES.get(focus, focus)} {f2(f[ind])} en {int(f.year)} (puesto {rk[focus]} de {len(last)} países de LATAM, EE. UU. y España; mediana latinoamericana "
                     f"{f2(la_med)}); en {int(f0.year)} era {f2(f0[ind])}.")
        tab.append((ind, lab, last))
    if not tab: raise ValueError("sin indicadores con cobertura")
    ind, lab, last = tab[0]
    fig, ax = chart_base(p.get("titulo_grafico", lab), f"{lab}, último año disponible por país", "Fuente: Banco Mundial (WDI). Cálculos propios.")
    s = last[ind].sort_values(); yy = np.arange(len(s))
    ax.barh(yy, s.values, color=[NEG if c == focus else POS if c in ("USA", "ESP") else NEU for c in s.index], height=.62)
    ax.set_yticks(yy, [f"{S.NOMBRES.get(c, c)} ({int(last.loc[c].year)})" for c in s.index])
    fig.savefig(out / "grafico.png", facecolor=BG); plt.close(fig)
    return {"hallazgos": H, "checks": checks, "cifras": {}, "metodo": "Último dato disponible por país y primer dato del periodo; ranking descendente.",
            "limitaciones": p.get("limitaciones", []) + ["Años de último dato distintos entre países (se indican)."]}


# ---------------------------------------------------------------------------------------------------------------
# 5) Paper reciente (arXiv): ficha con resumen literal; el post solo puede usar lo que dice el resumen
# ---------------------------------------------------------------------------------------------------------------
def paper(prov, p, out, used=()):
    items = [x for x in S.arxiv(p["query"], 15) if x["url"] not in used]
    if not items: raise ValueError("sin papers nuevos")
    it = items[0]
    (out / "paper.json").write_text(json.dumps(it, ensure_ascii=False, indent=1))
    prov.items.append({"archivo": "paper.json", "url": it["url"], "metodo": "arXiv API", "descargado": it["fecha"]})
    H = [f"Paper: «{it['titulo']}» ({it['autores']}, arXiv, {it['fecha']}). Resumen literal de los autores: {it['resumen']}"]
    return {"hallazgos": H, "checks": [{"nombre": "paper existe en arXiv", "ok": True, "detalle": it["url"]}], "cifras": {},
            "metodo": "Ficha del resumen publicado por los autores; no se replican sus cálculos.", "url": it["url"],
            "limitaciones": ["Preprint: puede no estar revisado por pares."], "sin_grafico": True}


RECIPES = {"enso": enso, "fe_panel": fe_panel, "atlas_eci": atlas_eci, "compare": compare, "paper": paper}
