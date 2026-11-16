-- Migracion de 06_trust.py: identidad correcta, indices y publicacion atomica.
-- Ejecutar una vez en Supabase SQL Editor para una base ya instalada.

alter table public.review_trust
    drop constraint if exists review_trust_dataset_key_review_id_key;
alter table public.product_aspect_trust
    add column if not exists n_mentions int default 0;

create unique index if not exists idx_review_trust_identity
    on public.review_trust(dataset_key, product_id, review_id);
create unique index if not exists idx_pat_unique
    on public.product_aspect_trust(
        dataset_key, product_id, aspect, polarity, strategy
    );
create index if not exists idx_trust_dataset_id
    on public.review_trust(dataset_key, id);
-- Las identidades unicas ya cubren estos prefijos; se quitan copias creadas
-- por versiones intermedias para no encarecer cada publicacion.
drop index if exists public.idx_trust_dataset_product;
drop index if exists public.idx_pat_dataset_product;
drop index if exists public.idx_pat_dataset_strategy_id;
create index if not exists idx_review_aspects_dataset_id
    on public.review_aspects(dataset_key, id);
create index if not exists idx_pat_dataset_strategy_product
    on public.product_aspect_trust(dataset_key, strategy, product_id);

alter table public.review_trust
    drop constraint if exists review_trust_values_check;
alter table public.review_trust
    add constraint review_trust_values_check check (
        trust_score between 0 and 1
        and (base_score is null or base_score between 0 and 1)
        and (rate_bonus is null or rate_bonus between -1 and 1)
        and (relevance_bonus is null or relevance_bonus between 0 and 1)
        and (media_bonus is null or media_bonus between 0 and 1)
        and (likes_bonus is null or likes_bonus between 0 and 1)
        and (flag_penalty is null or flag_penalty between -1 and 0)
        and (short_penalty is null or short_penalty between -1 and 0)
    ) not valid;

alter table public.product_aspect_trust
    drop constraint if exists product_aspect_trust_values_check;
alter table public.product_aspect_trust
    add constraint product_aspect_trust_values_check check (
        polarity in ('pos', 'neg')
        and strategy in ('A', 'B', 'C', 'D', 'E')
        and agg_confidence is not null
        and agg_confidence between 0 and 1
        and n_reviews is not null and n_reviews >= 0
        and n_mentions is not null and n_mentions >= 0
        and (coverage_ratio is null or coverage_ratio between 0 and 1)
        and from_catalog is not null
        and (not from_catalog or (
            strategy = 'C' and polarity = 'pos'
            and n_reviews = 0 and n_mentions = 0
        ))
    ) not valid;

create or replace view public.review_full as
select
    rc.dataset_key,
    rc.review_id,
    rc.product_id,
    rc.rate,
    rc.content,
    rt.trust_score,
    ra.aspect,
    ra.polarity,
    ra.extraction_confidence
from public.reviews_clean as rc
left join public.review_trust as rt
    on rt.review_id = rc.review_id
   and rt.product_id = rc.product_id
   and rt.dataset_key = rc.dataset_key
inner join public.review_aspects as ra
    on ra.review_id = rc.review_id
   and ra.product_id = rc.product_id
   and ra.dataset_key = rc.dataset_key;

-- Cualquier escritura en una entrada de 06 incrementa esta revision. Es
-- global para evitar triggers por fila; un cambio en otro dataset puede
-- cancelar conservadoramente una corrida, pero nunca publicar una mezcla.
create table if not exists public.trust_source_state (
    singleton           boolean primary key default true check (singleton),
    revision            bigint not null default 0,
    updated_at          timestamptz not null default now()
);

insert into public.trust_source_state(singleton)
values (true)
on conflict (singleton) do nothing;

create or replace function public.bump_trust_source_revision()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    update public.trust_source_state
    set revision = revision + 1,
        updated_at = now()
    where singleton = true;
    return null;
end;
$$;

drop trigger if exists trg_reviews_clean_trust_revision on public.reviews_clean;
create trigger trg_reviews_clean_trust_revision
after insert or update or delete on public.reviews_clean
for each statement execute function public.bump_trust_source_revision();

drop trigger if exists trg_review_aspects_trust_revision on public.review_aspects;
create trigger trg_review_aspects_trust_revision
after insert or update or delete on public.review_aspects
for each statement execute function public.bump_trust_source_revision();

drop trigger if exists trg_products_seed_trust_revision on public.products_seed;
create trigger trg_products_seed_trust_revision
after insert or update or delete on public.products_seed
for each statement execute function public.bump_trust_source_revision();

drop trigger if exists trg_products_raw_trust_revision on public.products_raw;
create trigger trg_products_raw_trust_revision
after insert or update or delete on public.products_raw
for each statement execute function public.bump_trust_source_revision();

create table if not exists public.trust_dataset_state (
    dataset_key         text primary key,
    generation          bigint not null default 0,
    active_run_id       uuid,
    updated_at          timestamptz not null default now()
);

create table if not exists public.trust_runs (
    run_id                  uuid primary key,
    dataset_key             text not null,
    strategies              text[] not null,
    parameters              jsonb not null,
    status                  text not null default 'staging',
    base_generation         bigint not null,
    source_revision         bigint not null default 0,
    expected_review_rows    bigint,
    expected_fact_rows      bigint,
    expected_fact_rows_by_strategy jsonb,
    published_review_rows   bigint,
    published_fact_rows     bigint,
    published_fact_rows_by_strategy jsonb,
    started_at              timestamptz not null default now(),
    activated_at            timestamptz,
    check (cardinality(strategies) > 0),
    check (status in ('staging', 'activated', 'discarded'))
);

alter table public.trust_runs
    add column if not exists source_revision bigint not null default 0;
alter table public.trust_runs
    add column if not exists expected_fact_rows_by_strategy jsonb;
alter table public.trust_runs
    add column if not exists published_fact_rows_by_strategy jsonb;

create index if not exists idx_trust_runs_dataset
    on public.trust_runs(dataset_key, started_at);
create unique index if not exists idx_trust_runs_run_dataset
    on public.trust_runs(run_id, dataset_key);

create table if not exists public.review_trust_staging (
    run_id              uuid not null references public.trust_runs(run_id) on delete cascade,
    dataset_key         text not null,
    review_id           bigint not null,
    product_id          text not null,
    trust_score         real not null,
    base_score          real,
    rate_bonus          real,
    relevance_bonus     real,
    media_bonus         real,
    likes_bonus         real,
    flag_penalty        real,
    short_penalty       real
);

create unique index if not exists idx_review_trust_staging_unique
    on public.review_trust_staging(run_id, dataset_key, product_id, review_id);

create table if not exists public.product_aspect_trust_staging (
    run_id              uuid not null references public.trust_runs(run_id) on delete cascade,
    dataset_key         text not null,
    product_id          text not null,
    aspect              text not null,
    polarity            text not null,
    strategy            text not null,
    agg_confidence      real not null,
    n_reviews           int not null default 0,
    n_mentions          int not null default 0,
    coverage_ratio      real,
    from_catalog        boolean not null default false
);

-- La FK compuesta de abajo reemplaza estas FK historicas solo por run_id.
alter table public.review_trust_staging
    drop constraint if exists review_trust_staging_run_id_fkey;
alter table public.product_aspect_trust_staging
    drop constraint if exists product_aspect_trust_staging_run_id_fkey;

-- Las restricciones NOT VALID toleran staging abandonado de una instalacion
-- anterior, pero se aplican inmediatamente a toda fila nueva.
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'review_trust_staging_run_dataset_fk'
          and conrelid = 'public.review_trust_staging'::regclass
    ) then
        alter table public.review_trust_staging
            add constraint review_trust_staging_run_dataset_fk
            foreign key (run_id, dataset_key)
            references public.trust_runs(run_id, dataset_key)
            on delete cascade not valid;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'product_aspect_trust_staging_run_dataset_fk'
          and conrelid = 'public.product_aspect_trust_staging'::regclass
    ) then
        alter table public.product_aspect_trust_staging
            add constraint product_aspect_trust_staging_run_dataset_fk
            foreign key (run_id, dataset_key)
            references public.trust_runs(run_id, dataset_key)
            on delete cascade not valid;
    end if;
end;
$$;

alter table public.review_trust_staging
    drop constraint if exists review_trust_staging_values_check;
alter table public.review_trust_staging
    add constraint review_trust_staging_values_check check (
        trust_score between 0 and 1
        and (base_score is null or base_score between 0 and 1)
        and (rate_bonus is null or rate_bonus between -1 and 1)
        and (relevance_bonus is null or relevance_bonus between 0 and 1)
        and (media_bonus is null or media_bonus between 0 and 1)
        and (likes_bonus is null or likes_bonus between 0 and 1)
        and (flag_penalty is null or flag_penalty between -1 and 0)
        and (short_penalty is null or short_penalty between -1 and 0)
    ) not valid;

alter table public.product_aspect_trust_staging
    drop constraint if exists product_aspect_trust_staging_values_check;
alter table public.product_aspect_trust_staging
    add constraint product_aspect_trust_staging_values_check check (
        polarity in ('pos', 'neg')
        and strategy in ('A', 'B', 'C', 'D', 'E')
        and agg_confidence between 0 and 1
        and n_reviews >= 0
        and n_mentions >= 0
        and (coverage_ratio is null or coverage_ratio between 0 and 1)
        and (not from_catalog or (
            strategy = 'C' and polarity = 'pos'
            and n_reviews = 0 and n_mentions = 0
        ))
    ) not valid;

create unique index if not exists idx_product_aspect_trust_staging_unique
    on public.product_aspect_trust_staging(
        run_id, dataset_key, product_id, aspect, polarity, strategy
    );

-- Una peticion atrasada no puede volver a llenar staging despues de que el run
-- fue activado o descartado. El bloqueo tambien serializa con la finalizacion.
create or replace function public.guard_trust_staging_write()
returns trigger
language plpgsql
set search_path = public
as $$
declare
    v_status text;
    v_dataset_key text;
begin
    select status, dataset_key into v_status, v_dataset_key
    from public.trust_runs
    where run_id = new.run_id
    for share;
    if not found then
        raise exception 'No existe el run de trust %', new.run_id
            using errcode = '23503';
    end if;
    if v_status <> 'staging' then
        raise exception 'El run de trust % ya esta %', new.run_id, v_status
            using errcode = '55000';
    end if;
    if v_dataset_key <> new.dataset_key then
        raise exception 'dataset_key no coincide con el run de trust %', new.run_id
            using errcode = '23514';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_guard_review_trust_staging
    on public.review_trust_staging;
create trigger trg_guard_review_trust_staging
before insert or update on public.review_trust_staging
for each row execute function public.guard_trust_staging_write();

drop trigger if exists trg_guard_product_aspect_trust_staging
    on public.product_aspect_trust_staging;
create trigger trg_guard_product_aspect_trust_staging
before insert or update on public.product_aspect_trust_staging
for each row execute function public.guard_trust_staging_write();

create or replace function public.begin_trust_rebuild(
    p_dataset_key text,
    p_run_id uuid,
    p_strategies text[],
    p_parameters jsonb
)
returns bigint
language plpgsql
set search_path = public
as $$
declare
    v_generation bigint;
    v_source_revision bigint;
begin
    if nullif(btrim(p_dataset_key), '') is null or p_parameters is null then
        raise exception 'dataset_key y parameters son obligatorios'
            using errcode = '22023';
    end if;
    perform pg_advisory_xact_lock(
        hashtextextended('06_trust:' || p_dataset_key, 0)
    );
    if p_strategies is distinct from array['A', 'B', 'C', 'D', 'E']::text[] then
        raise exception '06_trust debe publicar A-E en una misma generacion'
            using errcode = '22023';
    end if;
    insert into public.trust_dataset_state(dataset_key)
    values (p_dataset_key)
    on conflict (dataset_key) do nothing;
    select generation into v_generation
    from public.trust_dataset_state
    where dataset_key = p_dataset_key
    for update;
    select revision into v_source_revision
    from public.trust_source_state
    where singleton = true
    for share;
    insert into public.trust_runs (
        run_id, dataset_key, strategies, parameters,
        base_generation, source_revision
    ) values (
        p_run_id, p_dataset_key, p_strategies, p_parameters,
        v_generation, v_source_revision
    )
    on conflict (run_id) do nothing;
    if not exists (
        select 1 from public.trust_runs
        where run_id = p_run_id
          and dataset_key = p_dataset_key
          and strategies = p_strategies
          and parameters = p_parameters
    ) then
        raise exception 'El run_id ya existe con otro contexto'
            using errcode = '22023';
    end if;
    select base_generation into v_generation
    from public.trust_runs
    where run_id = p_run_id;
    return v_generation;
end;
$$;

-- La firma anterior se elimina para no dejar una sobrecarga accesible que no
-- valide los conteos individuales de A-E.
drop function if exists public.replace_trust_outputs(
    text, uuid, text[], bigint, bigint
);

create or replace function public.replace_trust_outputs(
    p_dataset_key text,
    p_run_id uuid,
    p_strategies text[],
    p_expected_review_rows bigint,
    p_expected_fact_rows bigint,
    p_expected_fact_rows_by_strategy jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
    v_run public.trust_runs%rowtype;
    v_generation bigint;
    v_active_run_id uuid;
    v_source_revision bigint;
    v_staged_reviews bigint;
    v_staged_facts bigint;
    v_expected_fact_sum bigint;
    v_strategy text;
    v_expected_strategy_facts bigint;
    v_staged_strategy_facts bigint;
begin
    if p_expected_review_rows is null or p_expected_review_rows < 0
       or p_expected_fact_rows is null or p_expected_fact_rows < 0
       or p_expected_fact_rows_by_strategy is null
       or jsonb_typeof(p_expected_fact_rows_by_strategy) <> 'object' then
        raise exception 'Los conteos esperados deben ser no negativos y completos'
            using errcode = '22023';
    end if;
    if (
        select array_agg(key order by key)
        from jsonb_object_keys(p_expected_fact_rows_by_strategy) as keys(key)
    ) is distinct from p_strategies then
        raise exception 'El mapa de conteos debe contener exactamente A-E'
            using errcode = '22023';
    end if;
    select coalesce(sum(value::bigint), 0) into v_expected_fact_sum
    from jsonb_each_text(p_expected_fact_rows_by_strategy);
    if v_expected_fact_sum <> p_expected_fact_rows or exists (
        select 1
        from jsonb_each_text(p_expected_fact_rows_by_strategy)
        where value::bigint < 0
    ) then
        raise exception 'Los conteos A-E no coinciden con el total esperado'
            using errcode = '22023';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('06_trust:' || p_dataset_key, 0)
    );
    select * into v_run
    from public.trust_runs
    where run_id = p_run_id and dataset_key = p_dataset_key
    for update;
    if not found then
        raise exception 'No existe la ejecucion % para dataset %',
            p_run_id, p_dataset_key using errcode = 'P0002';
    end if;
    if v_run.strategies is distinct from p_strategies then
        raise exception 'Las estrategias no coinciden con el run registrado'
            using errcode = '22023';
    end if;

    select generation, active_run_id into v_generation, v_active_run_id
    from public.trust_dataset_state
    where dataset_key = p_dataset_key
    for update;
    select revision into v_source_revision
    from public.trust_source_state
    where singleton = true
    for share;

    if v_run.status = 'activated' then
        if v_run.expected_review_rows is distinct from p_expected_review_rows
           or v_run.expected_fact_rows is distinct from p_expected_fact_rows
           or v_run.expected_fact_rows_by_strategy
                is distinct from p_expected_fact_rows_by_strategy then
            raise exception 'El reintento no coincide con la activacion original'
                using errcode = '22023';
        end if;
        return jsonb_build_object(
            'review_trust_rows', v_run.published_review_rows,
            'product_aspect_trust_rows', v_run.published_fact_rows,
            'fact_rows_by_strategy', v_run.published_fact_rows_by_strategy,
            'already_activated', true,
            'superseded', v_active_run_id is distinct from p_run_id,
            'source_changed', v_source_revision <> v_run.source_revision
        );
    end if;
    if v_run.status <> 'staging' then
        raise exception 'La ejecucion % tiene estado %', p_run_id, v_run.status
            using errcode = '55000';
    end if;
    if v_generation <> v_run.base_generation then
        raise exception 'El run % quedo obsoleto por otra publicacion', p_run_id
            using errcode = '55000';
    end if;
    if v_source_revision <> v_run.source_revision then
        raise exception 'Las fuentes cambiaron durante el calculo del run %', p_run_id
            using errcode = '55000';
    end if;
    select count(*) into v_staged_reviews
    from public.review_trust_staging
    where run_id = p_run_id and dataset_key = p_dataset_key;
    select count(*) into v_staged_facts
    from public.product_aspect_trust_staging
    where run_id = p_run_id and dataset_key = p_dataset_key;
    if v_staged_reviews <> p_expected_review_rows
       or v_staged_facts <> p_expected_fact_rows then
        raise exception 'Staging incompleto: reviews %/%; facts %/%',
            v_staged_reviews, p_expected_review_rows,
            v_staged_facts, p_expected_fact_rows
            using errcode = '22000';
    end if;
    foreach v_strategy in array p_strategies loop
        v_expected_strategy_facts :=
            (p_expected_fact_rows_by_strategy ->> v_strategy)::bigint;
        select count(*) into v_staged_strategy_facts
        from public.product_aspect_trust_staging
        where run_id = p_run_id
          and dataset_key = p_dataset_key
          and strategy = v_strategy;
        if v_staged_strategy_facts <> v_expected_strategy_facts then
            raise exception 'Staging incompleto para estrategia %: %/%',
                v_strategy, v_staged_strategy_facts, v_expected_strategy_facts
                using errcode = '22000';
        end if;
    end loop;
    delete from public.review_trust where dataset_key = p_dataset_key;
    insert into public.review_trust (
        dataset_key, review_id, product_id, trust_score, base_score,
        rate_bonus, relevance_bonus, media_bonus, likes_bonus,
        flag_penalty, short_penalty
    )
    select
        dataset_key, review_id, product_id, trust_score, base_score,
        rate_bonus, relevance_bonus, media_bonus, likes_bonus,
        flag_penalty, short_penalty
    from public.review_trust_staging
    where run_id = p_run_id and dataset_key = p_dataset_key;
    delete from public.product_aspect_trust where dataset_key = p_dataset_key;
    insert into public.product_aspect_trust (
        dataset_key, product_id, aspect, polarity, strategy,
        agg_confidence, n_reviews, n_mentions, coverage_ratio, from_catalog
    )
    select
        dataset_key, product_id, aspect, polarity, strategy,
        agg_confidence, n_reviews, n_mentions, coverage_ratio, from_catalog
    from public.product_aspect_trust_staging
    where run_id = p_run_id and dataset_key = p_dataset_key;
    update public.trust_dataset_state
    set generation = generation + 1,
        active_run_id = p_run_id,
        updated_at = now()
    where dataset_key = p_dataset_key;
    update public.trust_runs
    set status = 'activated',
        expected_review_rows = p_expected_review_rows,
        expected_fact_rows = p_expected_fact_rows,
        expected_fact_rows_by_strategy = p_expected_fact_rows_by_strategy,
        published_review_rows = v_staged_reviews,
        published_fact_rows = v_staged_facts,
        published_fact_rows_by_strategy = p_expected_fact_rows_by_strategy,
        activated_at = now()
    where run_id = p_run_id;
    delete from public.review_trust_staging where run_id = p_run_id;
    delete from public.product_aspect_trust_staging where run_id = p_run_id;
    return jsonb_build_object(
        'review_trust_rows', v_staged_reviews,
        'product_aspect_trust_rows', v_staged_facts,
        'fact_rows_by_strategy', p_expected_fact_rows_by_strategy,
        'already_activated', false,
        'superseded', false,
        'source_changed', false
    );
end;
$$;

create or replace function public.discard_trust_rebuild(p_run_id uuid)
returns boolean
language plpgsql
set search_path = public
as $$
declare
    v_changed boolean := false;
begin
    update public.trust_runs
    set status = 'discarded'
    where run_id = p_run_id and status = 'staging';
    v_changed := found;
    if v_changed then
        delete from public.review_trust_staging where run_id = p_run_id;
        delete from public.product_aspect_trust_staging where run_id = p_run_id;
    end if;
    return v_changed;
end;
$$;
