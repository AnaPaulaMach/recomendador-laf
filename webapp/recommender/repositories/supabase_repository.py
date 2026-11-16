"""Adaptador de datos reales. No se instancia en el modo demostración."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse


class SupabaseRepository:
    ASPECT_PAGE_SIZE = 1000

    def __init__(self, url: str, key: str):
        self.url = url.strip()
        self._key = key.strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self._key)

    def client(self):
        if not self.is_configured:
            raise RuntimeError("Supabase no está configurado; use los fixtures de demostración.")
        from supabase import create_client

        return create_client(self.url, self._key)

    def datasets(
        self,
        domain_key: str,
        *,
        category_labels: Iterable[str] = (),
        site_id: str = "",
        ready_only: bool = True,
    ) -> tuple[dict[str, str], ...]:
        """Lista snapshots del dominio, país y estado analítico solicitados."""
        if not self.is_configured:
            return ()
        client = self.client()
        response = (
            client
            .table("datasets")
            .select("dataset_key,category_id,category_label,site_id,status,created_at")
            .eq("status", "active")
            .order("created_at", desc=True)
            .execute()
        )
        rows = response.data or []
        allowed_labels = {
            self._slug(value)
            for value in (category_labels or (domain_key,))
            if str(value).strip()
        }
        requested_site = str(site_id or "").strip().upper()
        matched = [
            row
            for row in rows
            if row.get("dataset_key")
            and self._slug(str(row.get("category_label") or "")) in allowed_labels
            and (
                not requested_site
                or str(row.get("site_id") or "").strip().upper() == requested_site
            )
        ]

        if matched:
            seed_rows = (
                client.table("products_seed")
                .select("dataset_key")
                .in_("dataset_key", [row["dataset_key"] for row in matched])
                .execute()
                .data
                or []
            )
            datasets_with_products = {
                str(row.get("dataset_key") or "") for row in seed_rows
            }
            matched = [
                row for row in matched if row["dataset_key"] in datasets_with_products
            ]

        if ready_only:
            matched = [
                row
                for row in matched
                if (
                    client.table("product_aspect_trust")
                    .select("id")
                    .eq("dataset_key", row["dataset_key"])
                    .eq("strategy", "D")
                    .limit(1)
                    .execute()
                    .data
                )
            ]

        return tuple(self._dataset_option(row, domain_key) for row in matched)

    def available_quality_aspect_keys(
        self,
        dataset_key: str,
        strategy: str = "D",
        *,
        minimum_products: int = 2,
        minimum_reviews: int = 3,
    ) -> tuple[str, ...]:
        """Devuelve aspectos con evidencia suficiente para este catálogo.

        La mera existencia de una fila no alcanza: un slider que afecta a un
        único producto o se apoya en muy pocas reseñas puede inducir al usuario
        a creer que el catálogo permite una comparación que en realidad no
        existe. Se exige cobertura en varios productos y un mínimo de reseñas
        agregadas entre ambas polaridades.
        """
        if not self.is_configured:
            return ()
        if not str(dataset_key or "").strip():
            return ()
        if minimum_products <= 0 or minimum_reviews <= 0:
            raise ValueError("Los mínimos de disponibilidad deben ser positivos.")

        client = self.client()
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = (
                client.table("product_aspect_trust")
                .select("id,aspect,product_id,n_reviews")
                .eq("dataset_key", dataset_key)
                .eq("strategy", strategy)
                .order("id")
                .range(offset, offset + self.ASPECT_PAGE_SIZE - 1)
                .execute()
                .data
                or []
            )
            rows.extend(page)
            if len(page) < self.ASPECT_PAGE_SIZE:
                break
            offset += self.ASPECT_PAGE_SIZE

        products_by_aspect: dict[str, set[str]] = {}
        reviews_by_aspect: dict[str, int] = {}
        first_seen: list[str] = []
        for row in rows:
            aspect = str(row.get("aspect") or "").strip()
            product_id = str(row.get("product_id") or "").strip()
            if not aspect or not product_id:
                continue
            if aspect not in products_by_aspect:
                products_by_aspect[aspect] = set()
                reviews_by_aspect[aspect] = 0
                first_seen.append(aspect)
            products_by_aspect[aspect].add(product_id)
            try:
                reviews_by_aspect[aspect] += max(0, int(row.get("n_reviews") or 0))
            except (TypeError, ValueError):
                continue

        return tuple(
            aspect
            for aspect in first_seen
            if len(products_by_aspect[aspect]) >= minimum_products
            and reviews_by_aspect[aspect] >= minimum_reviews
        )

    def laf1_generation_data(
        self,
        dataset_key: str,
        strategy: str = "D",
        *,
        top_n: int = 20,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Carga la entrada de 08 para un único snapshot revisado.

        El alcance se decide exclusivamente con ``products_seed``. Los
        productos excluidos nunca se consultan como candidatos y la generación
        se bloquea si todavía queda alguna revisión humana pendiente.
        """
        if not self.is_configured:
            raise RuntimeError("Supabase no está configurado para generar LAF 1.")
        if not str(dataset_key or "").strip():
            raise ValueError("dataset_key es obligatorio para generar LAF 1.")
        if top_n <= 0:
            raise ValueError("top_n debe ser positivo.")

        client = self.client()
        seed_rows = (
            client.table("products_seed")
            .select("product_id,position,analysis_status")
            .eq("dataset_key", dataset_key)
            .order("position")
            .execute()
            .data
            or []
        )
        if not seed_rows:
            raise RuntimeError(
                f"El catálogo {dataset_key!r} no contiene productos revisados."
            )

        pending = [
            str(row.get("product_id") or "")
            for row in seed_rows
            if str(row.get("analysis_status") or "pending").strip().lower()
            == "pending"
        ]
        if pending:
            raise RuntimeError(
                f"El catálogo tiene {len(pending)} productos pendientes de revisión."
            )

        included_rows = [
            row
            for row in seed_rows
            if str(row.get("analysis_status") or "").strip().lower() == "included"
            and str(row.get("product_id") or "").strip()
        ]
        if not included_rows:
            raise RuntimeError("El catálogo no tiene productos incluidos para LAF 1.")

        included_ids = [str(row["product_id"]) for row in included_rows]
        candidate_rows = [
            row
            for row in included_rows
            if self._positive_int(row.get("position"), default=top_n + 1) <= top_n
        ]
        if not candidate_rows:
            raise RuntimeError(f"El catálogo no tiene candidatos dentro del top {top_n}.")

        raw_rows = (
            client.table("products_raw")
            .select("product_id,name,family_name")
            .eq("dataset_key", dataset_key)
            .in_("product_id", included_ids)
            .execute()
            .data
            or []
        )
        names = {
            str(row.get("product_id") or ""): str(
                row.get("name") or row.get("family_name") or row.get("product_id")
            )
            for row in raw_rows
            if row.get("product_id")
        }

        item_rows = (
            client.table("items_clean")
            .select("product_id,price")
            .eq("dataset_key", dataset_key)
            .in_("product_id", included_ids)
            .execute()
            .data
            or []
        )
        prices: dict[str, list[float]] = defaultdict(list)
        for row in item_rows:
            product_id = str(row.get("product_id") or "")
            price = self._nonnegative_float(row.get("price"))
            if product_id and price is not None:
                prices[product_id].append(price)

        products: dict[str, dict[str, Any]] = {}
        for row in candidate_rows:
            product_id = str(row["product_id"])
            product_prices = prices.get(product_id, [])
            products[product_id] = {
                "name": names.get(product_id, product_id),
                "position": self._positive_int(row.get("position")),
                "price_min": min(product_prices) if product_prices else None,
                "price_max": max(product_prices) if product_prices else None,
                "n_items": len(product_prices),
            }

        evidence_rows = (
            client.table("product_aspect_trust")
            .select(
                "product_id,aspect,polarity,agg_confidence,n_reviews,"
                "coverage_ratio,from_catalog"
            )
            .eq("dataset_key", dataset_key)
            .eq("strategy", strategy)
            .in_("product_id", included_ids)
            .execute()
            .data
            or []
        )
        evidence = [
            dict(row)
            for row in evidence_rows
            if row.get("agg_confidence") is not None
        ]
        return products, evidence

    def aspect_mention_examples(
        self,
        dataset_key: str,
        product_id: str,
        aspect: str,
        per_polarity: int = 2,
    ) -> list[dict[str, Any]]:
        """Menciones concretas del aspecto, para mostrar como ejemplo.

        Devuelve las de mayor peso de testimonio (``trust_score``) de cada
        polaridad, con la oración exacta donde el extractor detectó el aspecto
        (``review_aspects.sentence_excerpt``). No participa del ranking: es
        material de auditoría para la persona que lee la explicación.
        """
        if not self.is_configured:
            return []
        dataset_key = str(dataset_key or "").strip()
        product_id = str(product_id or "").strip()
        aspect = str(aspect or "").strip()
        if not (dataset_key and product_id and aspect):
            return []
        client = self.client()
        rows = (
            client.table("review_full")
            .select("review_id,rate,trust_score,polarity,extraction_confidence")
            .eq("dataset_key", dataset_key)
            .eq("product_id", product_id)
            .eq("aspect", aspect)
            .neq("polarity", "neu")
            .order("trust_score", desc=True)
            .limit(120)
            .execute()
            .data
            or []
        )
        chosen: dict[str, list[dict[str, Any]]] = {"pos": [], "neg": []}
        for row in rows:
            bucket = chosen.get(str(row.get("polarity") or ""))
            if bucket is None or len(bucket) >= max(int(per_polarity), 0):
                continue
            bucket.append(row)
        selected = chosen["pos"] + chosen["neg"]
        if not selected:
            return []
        review_ids = [row.get("review_id") for row in selected if row.get("review_id") is not None]
        excerpts: dict[tuple[Any, str], str] = {}
        if review_ids:
            for item in (
                client.table("review_aspects")
                .select("review_id,polarity,sentence_excerpt")
                .eq("dataset_key", dataset_key)
                .eq("product_id", product_id)
                .eq("aspect", aspect)
                .in_("review_id", review_ids)
                .execute()
                .data
                or []
            ):
                key = (item.get("review_id"), str(item.get("polarity") or ""))
                if item.get("sentence_excerpt") and key not in excerpts:
                    excerpts[key] = str(item["sentence_excerpt"]).strip()
        examples = []
        for row in selected:
            polarity = str(row.get("polarity") or "")
            excerpt = excerpts.get((row.get("review_id"), polarity), "")
            if not excerpt:
                continue
            examples.append(
                {
                    "polarity": polarity,
                    "excerpt": excerpt,
                    "trust": round(float(row.get("trust_score") or 0.0), 2),
                    "extraction_confidence": round(
                        float(row.get("extraction_confidence") or 0.0), 2
                    ),
                    "rate": row.get("rate"),
                }
            )
        return examples

    def blind_review_evidence(
        self,
        dataset_key: str,
        product_ids: Iterable[str],
        aspects: Iterable[str],
    ) -> list[dict[str, Any]]:
        """Carga reseñas trazables sin incorporar ningún resultado del ranking.

        ``review_full`` reúne el texto limpio, la extracción de aspecto y la
        confianza individual. La paginación y el orden estable evitan que una
        revisión humana dependa del límite por defecto de PostgREST.
        """
        if not self.is_configured:
            raise RuntimeError("Supabase no está configurado para preparar la revisión.")
        dataset_key = str(dataset_key or "").strip()
        product_ids = tuple(dict.fromkeys(str(item).strip() for item in product_ids if str(item).strip()))
        aspects = tuple(dict.fromkeys(str(item).strip() for item in aspects if str(item).strip()))
        if not dataset_key:
            raise ValueError("dataset_key es obligatorio para preparar la revisión.")
        if not product_ids:
            raise ValueError("Se necesita al menos un producto candidato.")
        if not aspects:
            raise ValueError("Se necesita al menos un aspecto.")

        client = self.client()
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = (
                client.table("review_full")
                .select(
                    "dataset_key,product_id,review_id,rate,content,aspect,polarity,"
                    "trust_score,extraction_confidence"
                )
                .eq("dataset_key", dataset_key)
                .in_("product_id", list(product_ids))
                .in_("aspect", list(aspects))
                .neq("polarity", "neu")
                .order("product_id")
                .order("review_id")
                .order("aspect")
                .range(offset, offset + self.ASPECT_PAGE_SIZE - 1)
                .execute()
                .data
                or []
            )
            rows.extend(dict(row) for row in page)
            if len(page) < self.ASPECT_PAGE_SIZE:
                break
            offset += self.ASPECT_PAGE_SIZE
        return rows

    def laf2_audit_products(
        self,
        dataset_key: str,
        *,
        top_n: int = 20,
    ) -> tuple[dict[str, Any], ...]:
        """Lista productos revisados para la prueba local aislada de LAF 2."""
        if not self.is_configured:
            raise RuntimeError("Supabase no esta configurado para auditar LAF 2.")
        client = self.client()
        candidates = self._laf_candidate_rows(client, dataset_key, top_n=top_n)
        product_ids = [str(row["product_id"]) for row in candidates]

        raw_rows = (
            client.table("products_raw")
            .select("product_id,name,family_name")
            .eq("dataset_key", dataset_key)
            .in_("product_id", product_ids)
            .execute()
            .data
            or []
        )
        names = {
            str(row.get("product_id") or ""): str(
                row.get("name") or row.get("family_name") or row.get("product_id")
            )
            for row in raw_rows
            if row.get("product_id")
        }
        item_rows = (
            client.table("items_clean")
            .select("product_id,price")
            .eq("dataset_key", dataset_key)
            .in_("product_id", product_ids)
            .execute()
            .data
            or []
        )
        prices: dict[str, list[Decimal]] = defaultdict(list)
        for row in item_rows:
            product_id = str(row.get("product_id") or "")
            price = self._money_decimal(row.get("price"))
            if product_id and price is not None:
                prices[product_id].append(price)

        result = []
        for row in candidates:
            product_id = str(row["product_id"])
            observed = prices.get(product_id, [])
            if not observed:
                continue
            result.append(
                {
                    "product_id": product_id,
                    "name": names.get(product_id, product_id),
                    "position": self._positive_int(row.get("position")),
                    "price_min": float(min(observed)),
                    "price_max": float(max(observed)),
                    "items_count": len(observed),
                }
            )
        return tuple(result)

    def laf2_generation_items(
        self,
        dataset_key: str,
        product_id: str,
        *,
        budget_min: float | None = None,
        budget_max: float | None = None,
        top_n: int = 20,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Carga publicaciones limpias y sus condiciones para un solo producto."""
        if not self.is_configured:
            raise RuntimeError("Supabase no esta configurado para generar LAF 2.")
        requested_product = str(product_id or "").strip()
        if not requested_product:
            raise ValueError("product_id es obligatorio para generar LAF 2.")
        lower = self._money_decimal(budget_min) if budget_min is not None else None
        upper = self._money_decimal(budget_max) if budget_max is not None else None
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("El presupuesto minimo no puede superar al maximo.")

        client = self.client()
        candidates = self._laf_candidate_rows(client, dataset_key, top_n=top_n)
        candidate = next(
            (
                row
                for row in candidates
                if str(row.get("product_id") or "") == requested_product
            ),
            None,
        )
        if candidate is None:
            raise RuntimeError(
                "El producto de auditoria no esta incluido entre los candidatos revisados."
            )

        product_rows = (
            client.table("products_raw")
            .select("product_id,name,family_name")
            .eq("dataset_key", dataset_key)
            .eq("product_id", requested_product)
            .limit(1)
            .execute()
            .data
            or []
        )
        product_row = product_rows[0] if product_rows else {}
        product = {
            "product_id": requested_product,
            "name": str(
                product_row.get("name")
                or product_row.get("family_name")
                or requested_product
            ),
            "position": self._positive_int(candidate.get("position")),
        }

        clean_rows = (
            client.table("items_clean")
            .select(
                "item_id,price,original_price,listing_type,seller_id,official_store_id"
            )
            .eq("dataset_key", dataset_key)
            .eq("product_id", requested_product)
            .execute()
            .data
            or []
        )
        selected_clean = []
        for row in clean_rows:
            price = self._money_decimal(row.get("price"))
            if price is None:
                continue
            if lower is not None and price < lower:
                continue
            if upper is not None and price > upper:
                continue
            selected_clean.append((price, dict(row)))
        selected_clean.sort(key=lambda item: (item[0], str(item[1].get("item_id") or "")))
        if not selected_clean:
            raise RuntimeError("Ninguna publicacion entra en el presupuesto indicado.")

        item_ids = [str(row.get("item_id") or "") for _, row in selected_clean]
        raw_rows = (
            client.table("items_raw")
            .select(
                "item_id,price,original_price,official_store_id,listing_type_id,"
                "tags,sale_terms,seller_id,shipping_free_shipping,"
                "shipping_logistic_type,shipping_mode"
            )
            .eq("dataset_key", dataset_key)
            .eq("product_id", requested_product)
            .in_("item_id", item_ids)
            .execute()
            .data
            or []
        )
        raw_by_id = {
            str(row.get("item_id") or ""): dict(row)
            for row in raw_rows
            if row.get("item_id")
        }
        items = []
        for _, clean in selected_clean:
            item_id = str(clean.get("item_id") or "")
            raw = raw_by_id.get(item_id)
            if raw is None:
                continue
            raw["price"] = clean.get("price")
            raw["original_price"] = clean.get("original_price")
            raw["seller_id"] = clean.get("seller_id") or raw.get("seller_id")
            raw["official_store_id"] = (
                clean.get("official_store_id") or raw.get("official_store_id")
            )
            raw["listing_type_id"] = (
                raw.get("listing_type_id") or clean.get("listing_type")
            )
            items.append(raw)
        if not items:
            raise RuntimeError(
                "Las publicaciones limpias no tienen una fila correspondiente en items_raw."
            )
        return product, items

    def laf2_dataset_items(
        self,
        dataset_key: str,
        *,
        top_n: int = 20,
    ) -> list[dict[str, Any]]:
        """Publicaciones crudas de todos los candidatos del catálogo.

        Sirve para saber qué condiciones de compra existen en el snapshot antes
        de mostrar los controles; no filtra por presupuesto.
        """
        if not self.is_configured:
            return []
        client = self.client()
        candidates = self._laf_candidate_rows(client, dataset_key, top_n=top_n)
        product_ids = [str(row.get("product_id") or "") for row in candidates]
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = (
                client.table("items_raw")
                .select(
                    "item_id,product_id,price,original_price,official_store_id,"
                    "listing_type_id,tags,sale_terms,seller_id,"
                    "shipping_free_shipping,shipping_logistic_type,shipping_mode"
                )
                .eq("dataset_key", dataset_key)
                .in_("product_id", product_ids)
                .order("id")
                .range(offset, offset + self.ASPECT_PAGE_SIZE - 1)
                .execute()
                .data
                or []
            )
            rows.extend(dict(row) for row in page)
            if len(page) < self.ASPECT_PAGE_SIZE:
                break
            offset += self.ASPECT_PAGE_SIZE
        return rows

    def _laf_candidate_rows(self, client, dataset_key: str, *, top_n: int):
        if not str(dataset_key or "").strip():
            raise ValueError("dataset_key es obligatorio.")
        if top_n <= 0:
            raise ValueError("top_n debe ser positivo.")
        rows = (
            client.table("products_seed")
            .select("product_id,position,analysis_status")
            .eq("dataset_key", dataset_key)
            .order("position")
            .execute()
            .data
            or []
        )
        if not rows:
            raise RuntimeError(f"El catalogo {dataset_key!r} no contiene productos revisados.")
        pending = [
            row
            for row in rows
            if str(row.get("analysis_status") or "pending").strip().lower()
            == "pending"
        ]
        if pending:
            raise RuntimeError(
                f"El catalogo tiene {len(pending)} productos pendientes de revision."
            )
        candidates = [
            row
            for row in rows
            if str(row.get("analysis_status") or "").strip().lower() == "included"
            and str(row.get("product_id") or "").strip()
            and self._positive_int(row.get("position"), default=top_n + 1) <= top_n
        ]
        if not candidates:
            raise RuntimeError(f"El catalogo no tiene candidatos dentro del top {top_n}.")
        return candidates

    @staticmethod
    def _money_decimal(value: Any) -> Decimal | None:
        try:
            numeric = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return numeric if numeric.is_finite() and numeric >= 0 else None

    @staticmethod
    def _positive_int(value: Any, default: int = 0) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return default
        return numeric if numeric > 0 else default

    @staticmethod
    def _nonnegative_float(value: Any) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if numeric >= 0 else None

    @classmethod
    def _dataset_option(cls, row: dict[str, Any], domain_key: str) -> dict[str, str]:
        category = str(row.get("category_label") or domain_key).strip()
        site_id = str(row.get("site_id") or "").strip().upper()
        country = {
            "MLM": "México",
            "MCO": "Colombia",
            "MLA": "Argentina",
        }.get(site_id, site_id or "País no informado")
        captured = cls._display_date(row.get("created_at"))
        return {
            "key": str(row.get("dataset_key") or ""),
            "label": f"{category} · {country} · {captured}",
            "description": "Snapshot procesado y disponible para análisis",
            "category_label": category,
            "site_id": site_id,
            "captured_at": captured,
        }

    @staticmethod
    def _display_date(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return "fecha no informada"
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        return parsed.strftime("%d/%m/%Y")

    def product_images(
        self,
        dataset_key: str,
        product_ids: Iterable[str],
    ) -> dict[str, str]:
        """Devuelve la primera imagen segura de cada producto de catálogo.

        La imagen ya existe en ``products_raw.raw_json.pictures``. La consulta
        prioriza el snapshot elegido y, si se está usando el fixture de
        demostración, busca el mismo producto en cualquier snapshot disponible.
        Las credenciales y el JSON completo nunca llegan al navegador.
        """
        if not self.is_configured:
            return {}

        ids = tuple(
            dict.fromkeys(
                str(product_id or "").strip().upper()
                for product_id in product_ids
                if str(product_id or "").strip()
            )
        )
        if not ids:
            return {}

        rows = self._product_rows(ids, dataset_key=dataset_key)
        if not rows and dataset_key:
            rows = self._product_rows(ids)

        images: dict[str, str] = {}
        for row in rows:
            product_id = str(row.get("product_id") or "").strip().upper()
            image_url = self._catalog_image_url(row.get("raw_json"))
            if product_id and image_url and product_id not in images:
                images[product_id] = image_url
        return images

    def listing_price_range(
        self,
        dataset_key: str,
        product_id: str,
    ) -> tuple[float, float, int] | None:
        """Resume los precios de las publicaciones del producto elegido."""
        if not self.is_configured or not dataset_key or not product_id:
            return None
        response = (
            self.client()
            .table("items_raw")
            .select("price")
            .eq("dataset_key", dataset_key)
            .eq("product_id", product_id.strip().upper())
            .execute()
        )
        return self._price_range(response.data or [])

    @staticmethod
    def _price_range(rows: Iterable[dict[str, Any]]) -> tuple[float, float, int] | None:
        prices = []
        for row in rows:
            try:
                value = float(row.get("price"))
            except (TypeError, ValueError):
                continue
            if value >= 0:
                prices.append(value)
        if not prices:
            return None
        return min(prices), max(prices), len(prices)

    def _product_rows(
        self,
        product_ids: tuple[str, ...],
        *,
        dataset_key: str = "",
    ) -> list[dict[str, Any]]:
        query = (
            self.client()
            .table("products_raw")
            .select("product_id,raw_json")
            .in_("product_id", list(product_ids))
        )
        if dataset_key:
            query = query.eq("dataset_key", dataset_key)
        response = query.execute()
        return list(response.data or [])

    @staticmethod
    def _catalog_image_url(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        pictures = payload.get("pictures")
        if not isinstance(pictures, list):
            return ""
        for picture in pictures:
            if not isinstance(picture, dict):
                continue
            for key in ("secure_url", "url"):
                candidate = str(picture.get(key) or "").strip()
                if SupabaseRepository._is_mercadolibre_image(candidate):
                    return candidate
        return ""

    @staticmethod
    def _is_mercadolibre_image(url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").casefold()
        return parsed.scheme == "https" and (
            hostname == "mlstatic.com" or hostname.endswith(".mlstatic.com")
        )

    @staticmethod
    def _slug(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", "_", ascii_value.casefold()).strip("_")
