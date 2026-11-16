-- Descompone la estrategia D en evidencia, masa observada e incertidumbre.
-- Ejecutar una vez en Supabase antes de volver a correr src/06_trust.py.

begin;

alter table public.product_aspect_trust
    add column if not exists evidence_weight double precision;
alter table public.product_aspect_trust
    add column if not exists total_evidence_weight double precision;
alter table public.product_aspect_trust
    add column if not exists belief_mass double precision;
alter table public.product_aspect_trust
    add column if not exists uncertainty double precision;

alter table public.product_aspect_trust_staging
    add column if not exists evidence_weight double precision;
alter table public.product_aspect_trust_staging
    add column if not exists total_evidence_weight double precision;
alter table public.product_aspect_trust_staging
    add column if not exists belief_mass double precision;
alter table public.product_aspect_trust_staging
    add column if not exists uncertainty double precision;

-- Las filas D ya publicadas quedan con NULL hasta la siguiente reconstruccion.
-- NOT VALID evita inventar evidencia historica y controla toda fila nueva.
alter table public.product_aspect_trust
    drop constraint if exists product_aspect_trust_decomposition_check;
alter table public.product_aspect_trust
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

-- La publicacion sigue siendo una unica transaccion. La unica diferencia es
-- que ahora copia tambien las cuatro magnitudes auditables de D.
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

comment on column public.product_aspect_trust.evidence_weight is
'W de la polaridad de la fila D: suma de trust_score por extraction_confidence.';
comment on column public.product_aspect_trust.total_evidence_weight is
'W positivo + W negativo; permite recalcular D con otro lambda.';
comment on column public.product_aspect_trust.belief_mass is
'Masa de evidencia de la polaridad: W_s / (lambda + W_total).';
comment on column public.product_aspect_trust.uncertainty is
'Masa no resuelta por evidencia: lambda / (lambda + W_total).';

notify pgrst, 'reload schema';

commit;
