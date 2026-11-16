-- Resumen general por dataset
with seed as (
    select dataset_key, count(distinct product_id) as productos
    from public.products_seed
    group by dataset_key
),
raw as (
    select dataset_key, count(*) as reviews_raw
    from public.reviews_raw
    group by dataset_key
),
clean as (
    select dataset_key, count(*) as reviews_clean
    from public.reviews_clean
    group by dataset_key
)
select
    d.dataset_key,
    d.category_label,
    coalesce(s.productos, 0) as productos,
    coalesce(r.reviews_raw, 0) as reviews_raw,
    coalesce(c.reviews_clean, 0) as reviews_clean,
    round(
        100.0 * coalesce(c.reviews_clean, 0)
        / nullif(r.reviews_raw, 0),
        2
    ) as porcentaje_conservado
from public.datasets d
left join seed s using (dataset_key)
left join raw r using (dataset_key)
left join clean c using (dataset_key)
order by d.category_label, d.created_at;

-- Cantidad de resenias por rating
select
    dataset_key,
    rate,
    count(*) as cantidad,
    round(
        100.0 * count(*)
        / sum(count(*)) over (partition by dataset_key),
        2
    ) as porcentaje
from public.reviews_clean
where rate between 1 and 5
group by dataset_key, rate
order by dataset_key, rate;

-- Resumen positivo, neutral y negativo
select
    dataset_key,
    count(*) as total,
    round(avg(rate)::numeric, 2) as rating_promedio,
    count(*) filter (where rate in (1, 2)) as negativas,
    count(*) filter (where rate = 3) as neutrales,
    count(*) filter (where rate in (4, 5)) as positivas,
    round(
        100.0 * count(*) filter (where rate in (1, 2))
        / nullif(count(*), 0),
        2
    ) as porcentaje_negativas,
    round(
        100.0 * count(*) filter (where rate in (4, 5))
        / nullif(count(*), 0),
        2
    ) as porcentaje_positivas
from public.reviews_clean
where rate between 1 and 5
group by dataset_key
order by dataset_key;


-- Productos con pocas resenias
with reviews_por_producto as (
    select
        dataset_key,
        product_id,
        count(*) as cantidad_reviews
    from public.reviews_clean
    group by dataset_key, product_id
)
select
    ps.dataset_key,
    ps.product_id,
    ps.position,
    coalesce(r.cantidad_reviews, 0) as cantidad_reviews
from public.products_seed ps
left join reviews_por_producto r
    on r.dataset_key = ps.dataset_key
   and r.product_id = ps.product_id
where coalesce(r.cantidad_reviews, 0) <= 5
order by
    ps.dataset_key,
    cantidad_reviews,
    ps.position;


-- Calidad y longitud del texto
select
    dataset_key,
    count(*) as reviews_clean,
    round(avg(content_length)::numeric, 2) as longitud_promedio,
    percentile_cont(0.25)
        within group (order by content_length) as percentil_25,
    percentile_cont(0.50)
        within group (order by content_length) as mediana,
    percentile_cont(0.75)
        within group (order by content_length) as percentil_75,
    min(content_length) as longitud_minima,
    max(content_length) as longitud_maxima,
    count(*) filter (
        where content is null or btrim(content) = ''
    ) as textos_vacios
from public.reviews_clean
group by dataset_key
order by dataset_key;


-- Cobertura de trust y aspectos
with base as (
    select
        dataset_key,
        count(distinct (product_id, review_id)) as reviews_clean
    from public.reviews_clean
    group by dataset_key
),
trust as (
    select
        dataset_key,
        count(distinct (product_id, review_id)) as reviews_con_trust
    from public.review_trust
    group by dataset_key
),
aspects as (
    select
        dataset_key,
        count(distinct (product_id, review_id)) as reviews_con_aspectos,
        count(*) as aspectos_extraidos
    from public.review_aspects
    group by dataset_key
)
select
    b.dataset_key,
    b.reviews_clean,
    coalesce(t.reviews_con_trust, 0) as reviews_con_trust,
    coalesce(a.reviews_con_aspectos, 0) as reviews_con_aspectos,
    coalesce(a.aspectos_extraidos, 0) as aspectos_extraidos,
    round(
        100.0 * coalesce(t.reviews_con_trust, 0)
        / nullif(b.reviews_clean, 0),
        2
    ) as cobertura_trust,
    round(
        100.0 * coalesce(a.reviews_con_aspectos, 0)
        / nullif(b.reviews_clean, 0),
        2
    ) as cobertura_aspectos
from base b
left join trust t using (dataset_key)
left join aspects a using (dataset_key)
order by b.dataset_key;


-- Detectar duplicados inesperados
select
    dataset_key,
    product_id,
    review_id,
    count(*) as repeticiones
from public.reviews_raw
group by dataset_key, product_id, review_id
having count(*) > 1
order by repeticiones desc;


-- Valores invalidos en la capa raw
select
    dataset_key,
    count(*) as total_raw,
    count(*) filter (where rate is null) as rate_nulo,
    count(*) filter (
        where rate < 1 or rate > 5
    ) as rate_invalido,
    count(*) filter (
        where content is null or btrim(content) = ''
    ) as contenido_vacio,
    count(*) filter (where product_id is null) as producto_nulo,
    count(*) filter (where review_id is null) as review_id_nulo
from public.reviews_raw
group by dataset_key
order by dataset_key;


-- Cobertura de productos 
with productos as (
    select
        ps.dataset_key,
        ps.product_id,
        count(rc.id) as cantidad_reviews
    from public.products_seed ps
    left join public.reviews_clean rc
        on rc.dataset_key = ps.dataset_key
       and rc.product_id = ps.product_id
    group by ps.dataset_key, ps.product_id
)
select
    dataset_key,
    count(*) as productos_totales,
    count(*) filter (where cantidad_reviews = 0) as productos_sin_reviews,
    count(*) filter (
        where cantidad_reviews between 1 and 5
    ) as productos_con_pocas_reviews,
    round(avg(cantidad_reviews)::numeric, 2) as promedio_por_producto,
    percentile_cont(0.5)
        within group (order by cantidad_reviews) as mediana_por_producto,
    min(cantidad_reviews) as minimo,
    max(cantidad_reviews) as maximo
from productos
group by dataset_key
order by dataset_key;


-- Comparar ratings antes y después de limpiar
with raw_rating as (
    select dataset_key, rate, count(*) as cantidad_raw
    from public.reviews_raw
    where rate between 1 and 5
    group by dataset_key, rate
),
clean_rating as (
    select dataset_key, rate, count(*) as cantidad_clean
    from public.reviews_clean
    where rate between 1 and 5
    group by dataset_key, rate
)
select
    coalesce(r.dataset_key, c.dataset_key) as dataset_key,
    coalesce(r.rate, c.rate) as rate,
    coalesce(r.cantidad_raw, 0) as cantidad_raw,
    coalesce(c.cantidad_clean, 0) as cantidad_clean,
    round(
        100.0 * coalesce(c.cantidad_clean, 0)
        / nullif(r.cantidad_raw, 0),
        2
    ) as porcentaje_conservado
from raw_rating r
full join clean_rating c
    on c.dataset_key = r.dataset_key
   and c.rate = r.rate
order by dataset_key, rate;