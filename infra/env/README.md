# `infra/env/` — per-environment Terraform inputs

Four files, two environments. `infra/*.tf` is environment-agnostic; everything that
differs between projects lives here.

| File                   | What it is                                                     |
| ---------------------- | -------------------------------------------------------------- |
| `client.gcs.tfbackend` | State location for **nestor-pulse-prod** (the client env)       |
| `client.tfvars`        | Every per-project variable for the client env                   |
| `dev.gcs.tfbackend`    | State location for the dev project — **not usable yet**, read it |
| `dev.tfvars`           | A measured description of what is live in dev — **never applied** |

## Running it

```sh
terraform -chdir=infra init -reconfigure -backend-config=env/client.gcs.tfbackend
terraform -chdir=infra plan  -var-file=env/client.tfvars -out=/tmp/client.tfplan
terraform -chdir=infra apply /tmp/client.tfplan
```

`providers.tf` carries a partial `backend "gcs" {}`, so `init` **must** be given a
`-backend-config`. A bare `terraform init` prompts instead of silently writing a local
state file — that is deliberate. Switching environments needs `-reconfigure`.

## Two rules

1. **A `<capture-after-first-deploy>` sentinel is never applied as a literal.** Those
   values are only knowable once the resource they describe exists (a run.app URL, a
   promoted image tag). If a plan errors on one, that variable is not needed by this
   pass — set it to `""` for the pass and record which.
2. **No secret VALUE ever enters these files (D-23.4-05).** Terraform declares the
   secret *containers*; the operator adds the versions with
   `gcloud secrets versions add <NAME> --data-file=-`. Everything committed here is a
   project id, a service name, a public Firebase identifier, a public URL or a secret
   *name*.

Dev cannot be applied from these files until someone does a `terraform import` pass —
its resources were all created by hand and it has no state. See the header of
`dev.gcs.tfbackend`.
