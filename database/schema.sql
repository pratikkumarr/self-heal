create schema if not exists selfheal;
revoke all on schema selfheal from public, anon, authenticated;

create table if not exists selfheal.deployments (
    service_id text not null,
    deploy_id text not null,
    commit_sha text not null,
    render_status text not null,
    observed_at text not null,
    is_incident integer not null check (is_incident in (0, 1)),
    evidence text not null,
    issue_state text not null default 'not_applicable'
        check (issue_state in ('not_applicable', 'draft', 'posting', 'created', 'needs_review')),
    issue_url text,
    primary key (service_id, deploy_id)
);

alter table selfheal.deployments enable row level security;
revoke all on table selfheal.deployments from public, anon, authenticated;
