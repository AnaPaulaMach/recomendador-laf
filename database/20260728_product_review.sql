-- Migracion: revision humana y auditable de los productos del corpus.
-- Ejecutar una vez en Supabase SQL Editor antes de abrir 01b_product_review.py.

alter table products_seed
    add column if not exists analysis_status text not null default 'pending';
alter table products_seed
    add column if not exists analysis_reason text;
alter table products_seed
    add column if not exists analysis_reviewed_at timestamptz;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'products_seed_analysis_status_check'
          and conrelid = 'products_seed'::regclass
    ) then
        alter table products_seed
            add constraint products_seed_analysis_status_check
            check (analysis_status in ('pending', 'included', 'excluded'));
    end if;
end
$$;

create index if not exists idx_products_seed_analysis_status
    on products_seed(dataset_key, analysis_status);

create table if not exists product_review_decisions (
    id              bigserial primary key,
    dataset_key     text not null,
    product_id      text not null,
    decision        text not null,
    reason          text,
    reviewer        text,
    decided_at      timestamptz not null default now(),

    foreign key (dataset_key, product_id)
        references products_seed(dataset_key, product_id)
        on delete cascade,
    check (decision in ('pending', 'included', 'excluded'))
);

create index if not exists idx_product_review_decisions_product
    on product_review_decisions(dataset_key, product_id, decided_at desc);

-- Guarda el estado vigente y su historial dentro de una unica transaccion.
create or replace function public.save_product_review_decision(
    p_dataset_key text,
    p_product_id text,
    p_decision text,
    p_reason text,
    p_reviewer text,
    p_expected_reviewed_at timestamptz default null
)
returns table (
    analysis_status text,
    analysis_reason text,
    analysis_reviewed_at timestamptz
)
language plpgsql
set search_path = public
as $$
declare
    v_decided_at timestamptz := now();
begin
    if p_decision not in ('pending', 'included', 'excluded') then
        raise exception 'Decision de producto invalida: %', p_decision
            using errcode = '22023';
    end if;

    update public.products_seed as ps
    set
        analysis_status = p_decision,
        analysis_reason = nullif(btrim(p_reason), ''),
        analysis_reviewed_at = v_decided_at
    where ps.dataset_key = p_dataset_key
      and ps.product_id = p_product_id
      and ps.analysis_reviewed_at is not distinct from p_expected_reviewed_at
    returning
        ps.analysis_status,
        ps.analysis_reason,
        ps.analysis_reviewed_at
    into
        analysis_status,
        analysis_reason,
        analysis_reviewed_at;

    if not found then
        if not exists (
            select 1
            from public.products_seed as ps
            where ps.dataset_key = p_dataset_key
              and ps.product_id = p_product_id
        ) then
            raise exception 'No existe product_id=% en dataset_key=%',
                p_product_id, p_dataset_key
                using errcode = 'P0002';
        end if;
        raise exception
            'La decision de product_id=% fue modificada por otra sesion; recarga antes de guardar',
            p_product_id
            using errcode = '40001';
    end if;

    insert into public.product_review_decisions (
        dataset_key,
        product_id,
        decision,
        reason,
        reviewer,
        decided_at
    ) values (
        p_dataset_key,
        p_product_id,
        p_decision,
        nullif(btrim(p_reason), ''),
        nullif(btrim(p_reviewer), ''),
        v_decided_at
    );
    return next;
end;
$$;

-- Calcula los conteos en PostgreSQL y devuelve una fila por producto.
create or replace function public.product_clean_counts(p_dataset_key text)
returns table (
    product_id text,
    review_count bigint,
    item_count bigint
)
language sql
stable
set search_path = public
as $$
    with review_counts as (
        select rc.product_id, count(*)::bigint as review_count
        from public.reviews_clean as rc
        where rc.dataset_key = p_dataset_key
        group by rc.product_id
    ),
    item_counts as (
        select ic.product_id, count(*)::bigint as item_count
        from public.items_clean as ic
        where ic.dataset_key = p_dataset_key
        group by ic.product_id
    )
    select
        ps.product_id,
        coalesce(rc.review_count, 0)::bigint,
        coalesce(ic.item_count, 0)::bigint
    from public.products_seed as ps
    left join review_counts as rc using (product_id)
    left join item_counts as ic using (product_id)
    where ps.dataset_key = p_dataset_key
    order by ps.position;
$$;

create index if not exists idx_items_clean_dataset_product
    on public.items_clean(dataset_key, product_id);
create index if not exists idx_reviews_clean_dataset_product
    on public.reviews_clean(dataset_key, product_id);
