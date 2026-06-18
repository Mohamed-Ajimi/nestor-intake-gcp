CREATE OR REPLACE FUNCTION nestor.persist_questions_on_research_start()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'nestor', 'public'
AS $function$
declare
  v_questions jsonb;
  v_extras jsonb;
  v_decomp_id uuid;
  v_question jsonb;
  v_idx integer;
  v_priority integer;
  v_text text;
begin
  if new.status != 'in_research' or old.status = 'in_research' then
    return new;
  end if;
  
  if exists (select 1 from nestor.research_questions where intake_id = new.id) then
    return new;
  end if;
  
  select value into v_questions from nestor.intake_answers 
    where intake_id = new.id and field_key = 'questions';
  select value into v_extras from nestor.intake_answers 
    where intake_id = new.id and field_key = 'extra_questions_proposed';
  
  -- Pas decomposition aanmaken als er ECHT vragen zijn om te persisten
  if (jsonb_typeof(v_questions) = 'array' and jsonb_array_length(v_questions) > 0)
     or (jsonb_typeof(v_extras) = 'array' and jsonb_array_length(v_extras) > 0)
  then
    insert into nestor.decompositions (intake_id, version, tree, method_version)
    values (new.id, 1, jsonb_build_object('source', 'auto-on-status-in_research'), 'auto-v1')
    returning id into v_decomp_id;
  else
    return new;
  end if;
  
  -- Main questions â alleen niet-lege text
  if jsonb_typeof(v_questions) = 'array' then
    v_idx := 0;
    for v_question in select * from jsonb_array_elements(v_questions)
    loop
      v_text := trim(coalesce(v_question->>'text', ''));
      if v_text = '' then
        continue;  -- skip lege
      end if;
      
      v_priority := 5 - v_idx;
      if v_priority < 1 then v_priority := 1; end if;
      
      insert into nestor.research_questions (
        intake_id, decomposition_id, question_text, question_type, priority, status
      ) values (
        new.id, v_decomp_id, v_text,
        'descriptive'::nestor.question_type,
        v_priority, 'open'
      );
      v_idx := v_idx + 1;
    end loop;
  end if;
  
  -- Extras â alleen approved EN niet-lege
  if jsonb_typeof(v_extras) = 'array' then
    for v_question in 
      select * from jsonb_array_elements(v_extras) where (value->>'approved')::boolean = true
    loop
      v_text := trim(coalesce(v_question->>'text', ''));
      if v_text = '' then
        continue;
      end if;
      
      insert into nestor.research_questions (
        intake_id, decomposition_id, question_text, rationale, priority, status
      ) values (
        new.id, v_decomp_id, v_text,
        v_question->>'rationale',
        2, 'open'
      );
    end loop;
  end if;
  
  return new;
end;
$function$


-- ============================================

CREATE OR REPLACE FUNCTION nestor.prefill_intake_answers()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'nestor', 'public'
AS $function$
declare
  v_client_name text;
begin
  -- Klantnaam ophalen
  select name into v_client_name
  from public.clients
  where id = new.client_id;
  
  -- Pre-fill client_name als de klant er Ã©Ã©n heeft
  if v_client_name is not null and v_client_name != '' then
    insert into nestor.intake_answers (intake_id, field_key, value, edited_by_client)
    values (new.id, 'client_name', to_jsonb(v_client_name), false)
    on conflict (intake_id, field_key) do nothing;
  end if;
  
  return new;
end;
$function$


-- ============================================

CREATE OR REPLACE FUNCTION nestor.submit_intake(p_token text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'nestor', 'public'
AS $function$
declare
  v_intake_id uuid;
  v_current_status nestor.intake_status;
  v_new_status nestor.intake_status;
begin
  -- Allow draft (initial submit) OR reviewed (validation submit)
  select id, status into v_intake_id, v_current_status
  from nestor.intakes
  where (client_intake_token = p_token or client_validation_token = p_token)
    and status in ('draft', 'reviewed')
  limit 1;

  if v_intake_id is null then
    raise exception 'Invalid token or intake not in submittable state';
  end if;

  -- Status transitie afhankelijk van huidige status
  if v_current_status = 'draft' then
    v_new_status := 'submitted';
  elsif v_current_status = 'reviewed' then
    v_new_status := 'validated_by_client';
  else
    raise exception 'Unexpected status: %', v_current_status;
  end if;

  update nestor.intakes
  set status     = v_new_status,
      client_validated_at = case when v_new_status = 'validated_by_client' then now() else client_validated_at end,
      updated_at = now()
  where id = v_intake_id;

  return jsonb_build_object('success', true, 'intake_id', v_intake_id, 'new_status', v_new_status);
end;
$function$


-- ============================================

CREATE OR REPLACE FUNCTION nestor.tg_bump_to_delivered()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'nestor'
AS $function$
BEGIN
  IF OLD.client_results_token IS NULL
     AND NEW.client_results_token IS NOT NULL
     AND NEW.status = 'in_research' THEN
    NEW.status := 'delivered';
    NEW.updated_at := now();
  END IF;
  RETURN NEW;
END;
$function$


-- ============================================

CREATE OR REPLACE FUNCTION nestor.tg_bump_to_in_research()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'nestor'
AS $function$
BEGIN
  UPDATE nestor.intakes
     SET status = 'in_research', updated_at = now()
   WHERE id = NEW.intake_id
     AND status = 'decomposed';
  RETURN NEW;
END;
$function$


-- ============================================

