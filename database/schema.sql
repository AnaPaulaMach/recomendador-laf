-- Schema de la capa CLEAN del pipeline LAF.
-- Ejecutar en Supabase â†’ SQL Editor â†’ New query â†’ Run.
--
-- Incluye una capa RAW minima esperada por los scripts y las tablas CLEAN que
-- son la salida de los scripts 01, 02 y 03.
-- Se mantienen separadas de la capa RAW para preservar trazabilidad.

-- ============================================================================
-- CAPA RAW MINIMA
-- Estas tablas reciben el dump original. Si ya existen con mas columnas, no hace
-- falta recrearlas; los scripts solo dependen de los campos definidos aca.
-- ============================================================================

create table if not exists datasets (
    id              bigserial primary key,
    dataset_key     text not null unique,
    category_id     text,
    category_label  text,
    site_id         text,
    status          text default 'active',
    created_at      timestamptz default now()
);

create index if not exists idx_datasets_dataset_key on datasets(dataset_key);
create index if not exists idx_datasets_category_label on datasets(category_label);


create table if not exists products_seed (
    id              bigserial primary key,
    dataset_key     text not null,
    product_id      text not null,
    position        int not null,
    analysis_status text not null default 'pending',
    analysis_reason text,
    analysis_reviewed_at timestamptz,
    created_at      timestamptz default now(),

    unique (dataset_key, product_id)
);

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

create index if not exists idx_products_seed_dataset on products_seed(dataset_key);
create index if not exists idx_products_seed_position on products_seed(position);
create index if not exists idx_products_seed_analysis_status
    on products_seed(dataset_key, analysis_status);


-- Historial inmutable de decisiones humanas sobre el corpus analitico.
-- products_seed conserva el estado vigente; esta tabla permite auditar cambios.
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
-- El timestamp esperado evita sobrescribir silenciosamente otra revision.
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


create table if not exists products_raw (
    id              bigserial primary key,
    dataset_key     text not null,
    product_id      text not null,
    domain_id       text,
    name            text,
    family_name     text,
    attributes      jsonb,
    raw_json        jsonb,
    created_at      timestamptz default now(),

    unique (dataset_key, product_id)
);

create index if not exists idx_products_raw_dataset on products_raw(dataset_key);
create index if not exists idx_products_raw_product on products_raw(product_id);


create table if not exists items_raw (
    id                  bigserial primary key,
    dataset_key         text not null,
    product_id          text not null,
    item_id             text not null,
    seller_id           bigint,
    price               numeric(14,2),
    original_price      numeric(14,2),
    condition           text,
    listing_type_id     text,
    seller_address      jsonb,
    official_store_id   bigint,
    tags                jsonb,
    sale_terms          jsonb,
    shipping_free_shipping boolean,
    shipping_logistic_type text,
    shipping_mode       text,
    raw_payload         jsonb,
    created_at          timestamptz default now(),

    unique (dataset_key, product_id, item_id)
);

create index if not exists idx_items_raw_dataset on items_raw(dataset_key);
create index if not exists idx_items_raw_dataset_id on items_raw(dataset_key, id);
create index if not exists idx_items_raw_product on items_raw(product_id);
create index if not exists idx_items_raw_item on items_raw(item_id);


create table if not exists reviews_raw (
    id                  bigserial primary key,
    dataset_key         text not null,
    review_id           bigint not null,
    product_id          text not null,
    item_id             text,
    rate                smallint,
    title               text,
    content             text,
    likes               int default 0,
    dislikes            int default 0,
    relevance           real default 0,
    forbidden_words     int default 0,
    media               jsonb,
    buying_date         timestamptz,
    date_created        timestamptz,
    raw_payload         jsonb,
    created_at          timestamptz default now(),

    unique (dataset_key, product_id, review_id)
);

create index if not exists idx_reviews_raw_dataset on reviews_raw(dataset_key);
create index if not exists idx_reviews_raw_dataset_id on reviews_raw(dataset_key, id);
create index if not exists idx_reviews_raw_product on reviews_raw(product_id);


-- ============================================================================
-- TABLA 1a: items_clean
-- Las publicaciones (items) de cada producto con sus precios.
-- Output de script 01_clean.py (procesamiento de items_raw).
-- ============================================================================
create table if not exists items_clean (
    id              bigserial primary key,
    dataset_key     text not null,
    product_id      text not null,
    item_id         text not null,
    seller_id       bigint,
    price           numeric(14,2) not null,
    original_price  numeric(14,2),
    condition       text,               -- 'new' o 'used'
    listing_type    text,               -- 'gold_special', 'gold_pro', etc.
    official_store_id bigint,
    seller_address  text,
    processed_at    timestamptz default now(),

    unique (dataset_key, product_id, item_id)
);

alter table items_clean add column if not exists official_store_id bigint;

create index if not exists idx_items_clean_product on items_clean(product_id);
create index if not exists idx_items_clean_price on items_clean(price);
create index if not exists idx_items_clean_dataset on items_clean(dataset_key);
create index if not exists idx_items_clean_dataset_id on items_clean(dataset_key, id);
create index if not exists idx_items_clean_dataset_product
    on items_clean(dataset_key, product_id);

-- Migracion para instalaciones previas: REAL pierde centavos en importes
-- grandes. NUMERIC conserva exactamente dos decimales para LAF 2.
alter table public.items_clean
    alter column price type numeric(14,2) using round(price::numeric, 2),
    alter column original_price type numeric(14,2) using round(original_price::numeric, 2);


-- ============================================================================
-- TABLA 1b: reviews_clean
-- Output del script 01_clean.py (procesamiento de reviews_raw).
-- Nota: las reseÃ±as estÃ¡n a nivel de PRODUCTO, no de item individual.
-- Todas las reseÃ±as de "Moto G15" se aplican a todos los items del G15.
-- ============================================================================
create table if not exists reviews_clean (
    id              bigserial primary key,
    dataset_key     text not null,
    review_id       bigint not null,
    product_id      text not null,
    item_id         text,               -- para referencia, pero anÃ¡lisis es a nivel producto
    rate            smallint,           -- 1 a 5
    title           text,
    content         text,               -- ya normalizado: lowercase, sin URLs, etc.
    content_length  int,
    likes           int default 0,
    dislikes        int default 0,
    relevance       real default 0,
    forbidden_words int default 0,
    has_media       boolean default false,
    buying_date     timestamptz,
    date_created    timestamptz,
    processed_at    timestamptz default now(),

    unique (dataset_key, product_id, review_id)
);

create index if not exists idx_reviews_clean_product on reviews_clean(product_id);
create index if not exists idx_reviews_clean_dataset on reviews_clean(dataset_key);
create index if not exists idx_reviews_clean_dataset_id on reviews_clean(dataset_key, id);
create index if not exists idx_reviews_clean_dataset_product
    on reviews_clean(dataset_key, product_id);


-- Agrega los conteos en PostgreSQL para no transferir miles de product_id.
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


-- ============================================================================
-- TABLA 2: review_aspects
-- Output del script 05_aspects.py
-- Una fila por cada (reseÃ±a, aspecto) detectado.
-- ============================================================================
create table if not exists review_aspects (
    id                      bigserial primary key,
    dataset_key             text not null,
    review_id               bigint not null,
    product_id              text not null,
    aspect                  text not null,        -- bateria, camara, pantalla, etc.
    polarity                text not null,        -- 'pos', 'neg', 'neu'
    extraction_confidence   real not null,        -- 0 a 1: quÃ© tan claro fue
    sentence_excerpt        text,                 -- oraciÃ³n donde se detectÃ³ (para auditorÃ­a)
    has_negation            boolean default false,
    processed_at            timestamptz default now()
);

create index if not exists idx_aspects_product on review_aspects(product_id);
create index if not exists idx_aspects_aspect on review_aspects(aspect);
create index if not exists idx_aspects_review on review_aspects(review_id);
create index if not exists idx_review_aspects_dataset_id
    on review_aspects(dataset_key, id);

-- Evita duplicar la misma extraccion si el script 05_aspects.py se ejecuta
-- mas de una vez sobre el mismo dataset.
create unique index if not exists idx_aspects_unique_extraction
    on review_aspects(dataset_key, review_id, product_id, aspect, polarity, sentence_excerpt);


-- Cada ejecucion de 05 escribe primero en staging. La tabla final solo cambia
-- cuando todas las paginas fueron procesadas correctamente.
create table if not exists review_aspect_runs (
    run_id          uuid primary key,
    dataset_key     text not null,
    started_at      timestamptz not null default now()
);

create index if not exists idx_review_aspect_runs_dataset
    on review_aspect_runs(dataset_key, started_at);

create table if not exists review_aspects_staging (
    run_id                  uuid not null references review_aspect_runs(run_id) on delete cascade,
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
    on review_aspects_staging(
        run_id, dataset_key, review_id, product_id, aspect, polarity, sentence_excerpt
    );

create index if not exists idx_aspects_staging_run
    on review_aspects_staging(run_id);


-- PostgreSQL ejecuta toda la funcion en una transaccion: los consumidores ven
-- la version anterior completa o la nueva completa, nunca una reconstruccion
-- intermedia de review_aspects.
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

    -- La cascada elimina tambien las filas de staging ya activadas.
    delete from public.review_aspect_runs
    where run_id = p_run_id;

    return v_inserted;
end;
$$;


-- ============================================================================
-- TABLA 3: review_trust
-- Output del script 06_trust.py
-- ============================================================================
create table if not exists review_trust (
    id              bigserial primary key,
    dataset_key     text not null,
    review_id       bigint not null,
    product_id      text not null,
    trust_score     real not null,    -- 0 a 1
    -- Guardamos los componentes individuales para auditoria y para mostrar
    -- en explicaciones al usuario:
    base_score      real,
    rate_bonus      real,
    relevance_bonus real,
    media_bonus     real,
    likes_bonus     real,
    flag_penalty    real,
    short_penalty   real,
    computed_at     timestamptz default now()
);

-- La misma review_id puede aparecer bajo productos distintos del dataset.
alter table review_trust
    drop constraint if exists review_trust_dataset_key_review_id_key;
create unique index if not exists idx_review_trust_identity
    on review_trust(dataset_key, product_id, review_id);
create index if not exists idx_trust_dataset_id
    on review_trust(dataset_key, id);
-- Las identidades unicas ya cubren estos prefijos; se quitan copias creadas
-- por versiones intermedias para no encarecer cada publicacion.
drop index if exists public.idx_trust_dataset_product;
drop index if exists public.idx_pat_dataset_product;
drop index if exists public.idx_pat_dataset_strategy_id;

alter table review_trust
    drop constraint if exists review_trust_values_check;
alter table review_trust
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


-- ============================================================================
-- VISTA AUXILIAR: review_full
-- Junta todo en una sola vista para que el generador LAF lo lea fÃ¡cil
-- ============================================================================
create or replace view review_full as
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
from reviews_clean rc
left join review_trust rt
    on rt.review_id = rc.review_id
   and rt.product_id = rc.product_id
   and rt.dataset_key = rc.dataset_key
inner join review_aspects ra
    on ra.review_id = rc.review_id
   and ra.product_id = rc.product_id
   and ra.dataset_key = rc.dataset_key;


-- ============================================================================
-- TABLA 4: product_aspect_trust
-- Output del script 06_trust.py (confianza AGREGADA por producto-aspecto).
-- Una fila por (producto, aspecto, polaridad, estrategia).
-- A-E se reconstruyen y publican juntas para que pertenezcan a la misma corrida.
-- ============================================================================
create table if not exists product_aspect_trust (
    id              bigserial primary key,
    dataset_key     text not null,
    product_id      text not null,
    aspect          text not null,
    polarity        text not null,        -- 'pos' o 'neg'
    strategy        text not null,        -- 'A', 'B', 'C', 'D', 'E'
    agg_confidence  real,                 -- confianza agregada 0-1; B omite filas insuficientes
    evidence_weight double precision,     -- W de la postura; solo D
    total_evidence_weight double precision,-- W positivo + W negativo; solo D
    belief_mass     double precision,     -- W postura / (lambda + W total); solo D
    uncertainty     double precision,     -- lambda / (lambda + W total); solo D
    n_reviews       int default 0,        -- reseñas distintas que apoyan esta postura
    n_mentions      int default 0,        -- extracciones antes de colapsar repeticiones internas
    coverage_ratio  real,                 -- n_reviews / max_n_reviews del corpus
    from_catalog    boolean default false,-- true si el hecho viene solo del catÃ¡logo (estrategia C)
    computed_at     timestamptz default now()
);

alter table product_aspect_trust
    add column if not exists n_mentions int default 0;
alter table product_aspect_trust
    add column if not exists evidence_weight double precision;
alter table product_aspect_trust
    add column if not exists total_evidence_weight double precision;
alter table product_aspect_trust
    add column if not exists belief_mass double precision;
alter table product_aspect_trust
    add column if not exists uncertainty double precision;

create index if not exists idx_pat_dataset_strategy_product
    on product_aspect_trust(dataset_key, strategy, product_id);
create unique index if not exists idx_pat_unique
    on product_aspect_trust(dataset_key, product_id, aspect, polarity, strategy);

alter table product_aspect_trust
    drop constraint if exists product_aspect_trust_values_check;
alter table product_aspect_trust
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

-- Las filas historicas pueden seguir con NULL hasta reconstruir 06. NOT VALID
-- evita inventar un backfill, pero exige el contrato en toda fila nueva.
alter table product_aspect_trust
    drop constraint if exists product_aspect_trust_decomposition_check;
alter table product_aspect_trust
    add constraint product_aspect_trust_decomposition_check check (
        (
            strategy = 'D'
            and evidence_weight is not null
            and total_evidence_weight is not null
            and belief_mass is not null
            and uncertainty is not null
            and evidence_weight > 0
            and evidence_weight < 'Infinity'::double precision
            and total_evidence_weight >= evidence_weight
            and total_evidence_weight < 'Infinity'::double precision
            and belief_mass between 0 and 1
            and uncertainty > 0 and uncertainty <= 1
            and belief_mass + uncertainty <= 1.00000001
        )
        or
        (
            strategy <> 'D'
            and evidence_weight is null
            and total_evidence_weight is null
            and belief_mass is null
            and uncertainty is null
        )
    ) not valid;


-- ============================================================================
-- STAGING E HISTORIAL TRANSACCIONAL PARA 06_trust.py
-- ============================================================================

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

create table if not exists trust_dataset_state (
    dataset_key         text primary key,
    generation          bigint not null default 0,
    active_run_id       uuid,
    updated_at          timestamptz not null default now()
);

create table if not exists trust_runs (
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
    on trust_runs(dataset_key, started_at);
create unique index if not exists idx_trust_runs_run_dataset
    on public.trust_runs(run_id, dataset_key);

create table if not exists review_trust_staging (
    run_id              uuid not null references trust_runs(run_id) on delete cascade,
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
    on review_trust_staging(run_id, dataset_key, product_id, review_id);

create table if not exists product_aspect_trust_staging (
    run_id              uuid not null references trust_runs(run_id) on delete cascade,
    dataset_key         text not null,
    product_id          text not null,
    aspect              text not null,
    polarity            text not null,
    strategy            text not null,
    agg_confidence      real not null,
    evidence_weight     double precision,
    total_evidence_weight double precision,
    belief_mass         double precision,
    uncertainty         double precision,
    n_reviews           int not null default 0,
    n_mentions          int not null default 0,
    coverage_ratio      real,
    from_catalog        boolean not null default false
);

-- CREATE TABLE IF NOT EXISTS no modifica una instalacion previa.
alter table public.product_aspect_trust_staging
    add column if not exists evidence_weight double precision;
alter table public.product_aspect_trust_staging
    add column if not exists total_evidence_weight double precision;
alter table public.product_aspect_trust_staging
    add column if not exists belief_mass double precision;
alter table public.product_aspect_trust_staging
    add column if not exists uncertainty double precision;

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

alter table public.product_aspect_trust_staging
    drop constraint if exists product_aspect_trust_staging_decomposition_check;
alter table public.product_aspect_trust_staging
    add constraint product_aspect_trust_staging_decomposition_check check (
        (
            strategy = 'D'
            and evidence_weight is not null
            and total_evidence_weight is not null
            and belief_mass is not null
            and uncertainty is not null
            and evidence_weight > 0
            and evidence_weight < 'Infinity'::double precision
            and total_evidence_weight >= evidence_weight
            and total_evidence_weight < 'Infinity'::double precision
            and belief_mass between 0 and 1
            and uncertainty > 0 and uncertainty <= 1
            and belief_mass + uncertainty <= 1.00000001
        )
        or
        (
            strategy <> 'D'
            and evidence_weight is null
            and total_evidence_weight is null
            and belief_mass is null
            and uncertainty is null
        )
    ) not valid;

create unique index if not exists idx_product_aspect_trust_staging_unique
    on product_aspect_trust_staging(
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


-- Registra un run de manera idempotente y captura la generacion publicada.
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


-- Un timeout despues del commit puede provocar un reintento. Si el run ya fue
-- activado, la funcion devuelve los conteos guardados sin publicar de nuevo.
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

    select *
    into v_run
    from public.trust_runs
    where run_id = p_run_id
      and dataset_key = p_dataset_key
    for update;

    if not found then
        raise exception 'No existe la ejecucion % para dataset %',
            p_run_id, p_dataset_key
            using errcode = 'P0002';
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

    delete from public.review_trust
    where dataset_key = p_dataset_key;
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

    -- Siempre se publican A-E juntas para que compartan la misma generacion.
    delete from public.product_aspect_trust
    where dataset_key = p_dataset_key;
    insert into public.product_aspect_trust (
        dataset_key, product_id, aspect, polarity, strategy,
        agg_confidence, evidence_weight, total_evidence_weight,
        belief_mass, uncertainty,
        n_reviews, n_mentions, coverage_ratio, from_catalog
    )
    select
        dataset_key, product_id, aspect, polarity, strategy,
        agg_confidence, evidence_weight, total_evidence_weight,
        belief_mass, uncertainty,
        n_reviews, n_mentions, coverage_ratio, from_catalog
    from public.product_aspect_trust_staging
    where run_id = p_run_id and dataset_key = p_dataset_key;

    update public.trust_dataset_state
    set
        generation = generation + 1,
        active_run_id = p_run_id,
        updated_at = now()
    where dataset_key = p_dataset_key;

    update public.trust_runs
    set
        status = 'activated',
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
    where run_id = p_run_id
      and status = 'staging';
    v_changed := found;
    if v_changed then
        delete from public.review_trust_staging where run_id = p_run_id;
        delete from public.product_aspect_trust_staging where run_id = p_run_id;
    end if;
    return v_changed;
end;
$$;

comment on table product_aspect_trust is
'Confianza agregada por producto-aspecto-polaridad.
 Hay una fila por (producto, aspecto, polaridad, estrategia).
 Estrategias disponibles:
   A = sensibilidad logaritmica al volumen
   B = umbral minimo por postura
   C = experimento separado de catalogo, con procedencia explicita
   D = estrategia principal: contraccion hacia una media a priori de 0.5;
       conserva evidencia, masa observada e incertidumbre por separado
   E = proporcion ponderada sin contraccion';

comment on column product_aspect_trust.evidence_weight is
'W de la polaridad de la fila D: suma de trust_score por extraction_confidence.';
comment on column product_aspect_trust.total_evidence_weight is
'W positivo + W negativo; permite recalcular D con otro lambda.';
comment on column product_aspect_trust.belief_mass is
'Masa de evidencia de la polaridad: W_s / (lambda + W_total).';
comment on column product_aspect_trust.uncertainty is
'Masa no resuelta por evidencia: lambda / (lambda + W_total).';

