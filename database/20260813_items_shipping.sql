-- Campos estructurados usados por LAF 2 para envio gratuito.
-- La migracion es idempotente para instalaciones que ya los incorporaron.
alter table public.items_raw
    add column if not exists shipping_free_shipping boolean,
    add column if not exists shipping_logistic_type text,
    add column if not exists shipping_mode text;

comment on column public.items_raw.shipping_free_shipping is
    'Indicador estructurado de envio gratuito informado por el marketplace.';
comment on column public.items_raw.shipping_logistic_type is
    'Modalidad logistica informativa; no se interpreta como rapidez.';
comment on column public.items_raw.shipping_mode is
    'Modo de envio informado por el marketplace.';
