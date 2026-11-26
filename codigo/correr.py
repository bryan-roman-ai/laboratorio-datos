"""Repite un estudio del laboratorio: python codigo/correr.py <id>  (descarga los datos de nuevo y recalcula)."""
import sys, yaml
from pathlib import Path
H = Path(__file__).resolve().parent; sys.path.insert(0, str(H))
import recipes as R, sources as S
st = next(x for x in yaml.safe_load((H / "agenda.yaml").read_text()) if x["id"] == sys.argv[1])
out = H.parent / (st["id"] + "_repeticion"); out.mkdir(exist_ok=True); prov = S.Prov(out)
res = R.RECIPES[st["receta"]](prov, st.get("params", {}), out); prov.save()
for c in res["checks"]: print(("OK " if c["ok"] else "FALLA ") + c["nombre"] + ": " + c["detalle"])
for h in res["hallazgos"]: print("-", h)
