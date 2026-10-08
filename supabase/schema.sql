
create table if not exists departments (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    description text,
    created_at timestamptz not null default now()
);

create table if not exists categories (
    id uuid primary key default gen_random_uuid(),
    department_id uuid not null references departments(id) on delete cascade,
    name text not null,
    description text,
    created_at timestamptz not null default now(),
    unique(department_id, name)
);

alter table departments enable row level security;
alter table categories enable row level security;

drop policy if exists departments_server_only on departments;
create policy departments_server_only on departments for all to anon, authenticated using (false) with check (false);

drop policy if exists categories_server_only on categories;
create policy categories_server_only on categories for all to anon, authenticated using (false) with check (false);

create extension if not exists pgcrypto;

do $$
begin
    create type campuscare_role as enum ('student', 'faculty', 'staff', 'administrator');
exception
    when duplicate_object then null;
end $$;

do $$
begin
    create type ticket_status as enum ('submitted', 'assigned', 'in_progress', 'resolved', 'reopened', 'escalated');
exception
    when duplicate_object then null;
end $$;

create table if not exists users (
    clerk_id text primary key,
    email text not null default '',
    full_name text not null default '',
    phone text,
    role campuscare_role not null default 'student',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists tickets (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    description text not null,
    category_id uuid not null references categories(id),
    department_id uuid not null references departments(id),
    status ticket_status not null default 'submitted',
    owner_id text not null references users(clerk_id),
    assigned_to text references users(clerk_id),
    resolution_remarks text,
    resolved_by text references users(clerk_id),
    resolved_at timestamptz,
    resolution_attachments jsonb not null default '[]'::jsonb,
    assignment_history jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table tickets add column if not exists acknowledged_by text references users(clerk_id);
alter table tickets add column if not exists acknowledged_name text;
alter table tickets add column if not exists acknowledged_at timestamptz;
alter table tickets add column if not exists confidential boolean not null default false;

create table if not exists ticket_appointments (
    id uuid primary key default gen_random_uuid(),
    ticket_id uuid not null references tickets(id) on delete cascade,
    proposed_by text not null references users(clerk_id),
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    decision text not null default 'pending' check (decision in ('pending', 'accepted', 'rejected')),
    created_at timestamptz not null default now()
);

create table if not exists ticket_history (
    id uuid primary key default gen_random_uuid(),
    ticket_id uuid not null references tickets(id) on delete cascade,
    status ticket_status not null,
    remarks text,
    changed_by text not null references users(clerk_id),
    created_at timestamptz not null default now()
);

create table if not exists feedback (
    ticket_id uuid primary key references tickets(id) on delete cascade,
    user_id text not null references users(clerk_id),
    rating integer not null check (rating between 1 and 5),
    comment text,
    created_at timestamptz not null default now()
);

create table if not exists ticket_followers (
    ticket_id uuid not null references tickets(id) on delete cascade,
    user_id text not null references users(clerk_id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (ticket_id, user_id)
);

create table if not exists ticket_supporters (
    ticket_id uuid not null references tickets(id) on delete cascade,
    user_id text not null references users(clerk_id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (ticket_id, user_id)
);

create table if not exists ticket_media (
    id uuid primary key default gen_random_uuid(),
    ticket_id uuid references tickets(id) on delete cascade,
    uploaded_by text not null references users(clerk_id),
    public_id text not null,
    secure_url text not null,
    resource_type text,
    format text,
    bytes integer,
    original_filename text not null,
    created_at timestamptz not null default now()
);

create table if not exists messages (
    id uuid primary key default gen_random_uuid(),
    thread_id uuid default gen_random_uuid(),
    parent_id uuid references messages(id),
    sender_id text not null references users(clerk_id),
    recipient_id text references users(clerk_id),
    text text not null,
    read_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists notices (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    body text not null,
    active boolean not null default true,
    created_by text not null references users(clerk_id),
    created_at timestamptz not null default now()
);

create table if not exists audit_logs (
    id uuid primary key default gen_random_uuid(),
    actor_id text not null references users(clerk_id),
    action text not null,
    resource_type text not null,
    resource_id text,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists tickets_owner_id_idx on tickets(owner_id);
create index if not exists tickets_assigned_to_idx on tickets(assigned_to);
create index if not exists tickets_status_idx on tickets(status);
create index if not exists tickets_department_id_idx on tickets(department_id);
create index if not exists tickets_confidential_idx on tickets(confidential);
create index if not exists ticket_history_ticket_id_idx on ticket_history(ticket_id);
create index if not exists ticket_followers_user_id_idx on ticket_followers(user_id);
create index if not exists ticket_supporters_user_id_idx on ticket_supporters(user_id);
create index if not exists ticket_media_ticket_id_idx on ticket_media(ticket_id);
create index if not exists ticket_appointments_ticket_id_idx on ticket_appointments(ticket_id);
create index if not exists messages_sender_id_idx on messages(sender_id);
create index if not exists messages_recipient_id_idx on messages(recipient_id);

alter table users enable row level security;
alter table tickets enable row level security;
alter table ticket_history enable row level security;
alter table feedback enable row level security;
alter table ticket_followers enable row level security;
alter table ticket_supporters enable row level security;
alter table ticket_media enable row level security;
alter table ticket_appointments enable row level security;
alter table messages enable row level security;
alter table notices enable row level security;
alter table audit_logs enable row level security;

drop policy if exists users_server_only on users;
create policy users_server_only on users for all to anon, authenticated using (false) with check (false);
drop policy if exists tickets_server_only on tickets;
create policy tickets_server_only on tickets for all to anon, authenticated using (false) with check (false);
drop policy if exists ticket_history_server_only on ticket_history;
create policy ticket_history_server_only on ticket_history for all to anon, authenticated using (false) with check (false);
drop policy if exists feedback_server_only on feedback;
create policy feedback_server_only on feedback for all to anon, authenticated using (false) with check (false);
drop policy if exists ticket_followers_server_only on ticket_followers;
create policy ticket_followers_server_only on ticket_followers for all to anon, authenticated using (false) with check (false);
drop policy if exists ticket_supporters_server_only on ticket_supporters;
create policy ticket_supporters_server_only on ticket_supporters for all to anon, authenticated using (false) with check (false);
drop policy if exists ticket_media_server_only on ticket_media;
create policy ticket_media_server_only on ticket_media for all to anon, authenticated using (false) with check (false);
drop policy if exists ticket_appointments_server_only on ticket_appointments;
create policy ticket_appointments_server_only on ticket_appointments for all to anon, authenticated using (false) with check (false);
drop policy if exists messages_server_only on messages;
create policy messages_server_only on messages for all to anon, authenticated using (false) with check (false);
drop policy if exists notices_server_only on notices;
create policy notices_server_only on notices for all to anon, authenticated using (false) with check (false);
drop policy if exists audit_logs_server_only on audit_logs;
create policy audit_logs_server_only on audit_logs for all to anon, authenticated using (false) with check (false);

drop function if exists create_ticket_with_history(text, text, uuid, uuid, text);
create or replace function create_ticket_with_history(
    p_title text,
    p_description text,
    p_category_id uuid,
    p_department_id uuid,
    p_owner_id text,
    p_confidential boolean default false
) returns tickets
language plpgsql
security definer
set search_path = public
as $$
declare
    created_ticket tickets;
begin
    insert into tickets (title, description, category_id, department_id, owner_id, confidential)
    values (p_title, p_description, p_category_id, p_department_id, p_owner_id, p_confidential)
    returning * into created_ticket;

    insert into ticket_history (ticket_id, status, changed_by)
    values (created_ticket.id, 'submitted', p_owner_id);

    return created_ticket;
end;
$$;

create or replace function assign_ticket_with_history(
    p_ticket_id uuid,
    p_assigned_to text,
    p_actor_id text
) returns tickets
language plpgsql
security definer
set search_path = public
as $$
declare
    updated_ticket tickets;
begin
    if not exists (select 1 from users where clerk_id = p_assigned_to and role = 'staff') then
        raise exception 'assignee must be an existing staff user';
    end if;

    update tickets
    set 
        assigned_to = p_assigned_to, 
        status = 'assigned', 
        updated_at = now(),
        assignment_history = assignment_history || jsonb_build_object(
            'assigned_to', p_assigned_to,
            'assigned_by', p_actor_id,
            'assigned_at', now()
        )
    where id = p_ticket_id
    returning * into updated_ticket;

    if updated_ticket.id is null then
        raise exception 'ticket not found';
    end if;

    insert into ticket_history (ticket_id, status, remarks, changed_by)
    values (p_ticket_id, 'assigned', 'Assigned to staff', p_actor_id);

    return updated_ticket;
end;
$$;

create or replace function update_ticket_with_history(
    p_ticket_id uuid,
    p_status ticket_status,
    p_remarks text,
    p_actor_id text,
    p_attachments jsonb default '[]'::jsonb
) returns tickets
language plpgsql
security definer
set search_path = public
as $$
declare
    updated_ticket tickets;
begin
    update tickets
    set 
        status = p_status, 
        resolution_remarks = p_remarks, 
        updated_at = now(),
        resolved_by = case when p_status = 'resolved' then p_actor_id else resolved_by end,
        resolved_at = case when p_status = 'resolved' then now() else resolved_at end,
        resolution_attachments = case when p_status = 'resolved' then coalesce(p_attachments, '[]'::jsonb) else resolution_attachments end
    where id = p_ticket_id
    returning * into updated_ticket;

    if updated_ticket.id is null then
        raise exception 'ticket not found';
    end if;

    insert into ticket_history (ticket_id, status, remarks, changed_by)
    values (p_ticket_id, p_status, p_remarks, p_actor_id);

    return updated_ticket;
end;
$$;

create or replace function submit_ticket_feedback(
    p_ticket_id uuid,
    p_user_id text,
    p_rating integer,
    p_comment text
) returns feedback
language plpgsql
security definer
set search_path = public
as $$
declare
    created_feedback feedback;
begin
    if not exists (select 1 from tickets where id = p_ticket_id and owner_id = p_user_id and status = 'resolved') then
        raise exception 'only the owner can provide feedback after resolution';
    end if;

    insert into feedback (ticket_id, user_id, rating, comment)
    values (p_ticket_id, p_user_id, p_rating, p_comment)
    returning * into created_feedback;

    return created_feedback;
end;
$$;
alter table messages add column if not exists thread_id uuid default gen_random_uuid();
alter table messages add column if not exists parent_id uuid references messages(id);
alter table messages add column if not exists read_at timestamptz;
create index if not exists messages_thread_id_idx on messages(thread_id);

create table if not exists settings (
    id int primary key default 1 check (id = 1),
    config jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);
alter table settings enable row level security;
drop policy if exists settings_server_only on settings;
create policy settings_server_only on settings for all to anon, authenticated using (false) with check (false);
