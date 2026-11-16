"""Recorre el flujo web real (Django test Client + settings/.env reales + Docker) hasta el ranking
de publicaciones de un producto, e imprime lo que ve el usuario. Uso: python flujo_web_real.py [product_id]"""
import os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webapp")); os.chdir(ROOT / "webapp")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "laf_web.settings")
import django; django.setup()
from django.conf import settings
from django.test import Client
from django.urls import reverse
settings.ALLOWED_HOSTS = ["*"]
pid = sys.argv[1] if len(sys.argv) > 1 else "MLM16250244"
c = Client()
r = c.post(reverse("recommender:start"), {"domain": "cafe", "dataset_key": os.environ["DATASET_KEY"], "strategy": "D"})
flow_url = r["Location"]; flow_id = flow_url.rstrip("/").split("/")[-2] if flow_url.endswith("/") else flow_url.split("/")[-2]
print("flow:", flow_url)
quality = {k: "0.67" for k in ["sabor","aroma","intensidad","dulzor","tueste","acidez","presentacion","rendimiento","variedad","preparacion","molienda","originalidad","tamano","caducidad"]}
r = c.post(reverse("recommender:quality", args=[flow_id]), quality); print("quality ->", r.status_code)
r = c.post(reverse("recommender:select-product", args=[flow_id, pid])); print("select ->", r.status_code)
r = c.get(reverse("recommender:purchase", args=[flow_id])); html = r.content.decode()
print("purchase GET ->", r.status_code)
print("  nota condiciones:", re.findall(r'<p class="budget-range-note">(Ninguna[^<]*)</p>', html))
print("  sliders:", re.findall(r'class="preference-legend">([^<]+)<', html))
solo_envio = len(sys.argv) > 2 and sys.argv[2] == "solo_envio"
prefs = {"budget_min": "", "budget_max": "", "precio": "0" if solo_envio else "0.33", "descuento": "0" if solo_envio else "0.67", "garantia": "0" if solo_envio else "0.67", "tienda_oficial": "0" if solo_envio else "0.67", "envio": "1", "cuotas": "1", "factura": "1"}
r = c.post(reverse("recommender:purchase", args=[flow_id]), prefs); print("purchase POST ->", r.status_code, r.get("Location"))
r = c.get(reverse("recommender:listing-ranking", args=[flow_id])); html = r.content.decode()
print("listing ->", r.status_code)
print("  aviso:", re.findall(r'(Ninguna publicaci[^<]*)</p>', html))
rows = re.findall(r'<h2>([^<]*)</h2>.*?<dt>Precio</dt><dd>([^<]*)</dd>.*?<dt>Envío</dt><dd>([^<]*)</dd>.*?listing-match-label">([^<]*)<', html, re.S)
for i, (seller, price, ship, label) in enumerate(rows, 1):
    print(f"  {i:>2} {seller:22s} {price:>10s} envio={ship:12s} -> {label}")
from recommender.models import RecommendationSession
f = RecommendationSession.objects.get(id=flow_id)
print("  status:", f.laf2_result["evaluation_status"], "| decision:", f.laf2_result["ranking"][0]["metadata"].get("decision_model"), "| sin evidencia:", f.laf2_result["ranking"][0]["metadata"].get("conditions_without_evidence"))
print("  scores:", [(e["entity_id"], round(e["final_score"], 3), e["status"]) for e in f.laf2_result["ranking"]])
print("URL ranking: http://localhost:8001" + reverse("recommender:listing-ranking", args=[flow_id]))
print("URL compra:  http://localhost:8001" + reverse("recommender:purchase", args=[flow_id]))
