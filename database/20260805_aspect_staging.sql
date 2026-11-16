-- Reconstruccion atomica de review_aspects para 05_aspects.py.
-- Ejecutar una vez en Supabase SQL Editor si la base ya estaba instalada.

create table if not exists public.review_aspect_runs (
    run_id          uuid primary key,
    dataset_key     text not null,
    started_at      timestamptz not null default now()
);

create index if not exists idx_review_aspect_runs_dataset
    on public.review_aspect_runs(dataset_key, started_at);

create table if not exists public.review_aspects_staging (
    run_id                  uuid not null references public.review_aspect_runs(run_id) on delete cascade,
    dataset_key             text not null,
    review_id               bigint not null,
    product_id              text not null,
    aspect                  text not null,
    polarity                text not null,
    extraction_confidence   real not null,
    sentence_excerpt        text,
    has_negation            boolean default false
);

create unique index if not exists idx_aspects_staging_unique_extraction
    on public.review_aspects_staging(
        run_id, dataset_key, review_id, product_id, aspect, polarity, sentence_excerpt
    );

create index if not exists idx_aspects_staging_run
    on public.review_aspects_staging(run_id);

create or replace function public.replace_review_aspects(
    p_dataset_key text,
    p_run_id uuid
)
returns bigint
language plpgsql
set search_path = public
as $$
declare
    v_inserted bigint;
begin
    perform pg_advisory_xact_lock(hashtext(p_dataset_key));

    if not exists (
        select 1
        from public.review_aspect_runs as runs
        where runs.run_id = p_run_id
          and runs.dataset_key = p_dataset_key
    ) then
        raise exception 'No existe la ejecucion % para dataset %',
            p_run_id, p_dataset_key
            using errcode = 'P0002';
    end if;

    delete from public.review_aspects
    where dataset_key = p_dataset_key;

    insert into public.review_aspects (
        dataset_key,
        review_id,
        product_id,
        aspect,
        polarity,
        extraction_confidence,
        sentence_excerpt,
        has_negation
    )
    select
        staging.dataset_key,
        staging.review_id,
        staging.product_id,
        staging.aspect,
        staging.polarity,
        staging.extraction_confidence,
        staging.sentence_excerpt,
        staging.has_negation
    from public.review_aspects_staging as staging
    where staging.run_id = p_run_id
      and staging.dataset_key = p_dataset_key;

    get diagnostics v_inserted = row_count;

    delete from public.review_aspect_runs
    where run_id = p_run_id;

    return v_inserted;
end;
$$;
