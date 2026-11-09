#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
group="$(terraform -chdir="$root/infra" output -raw resource_group_name)"
app="$(terraform -chdir="$root/infra" output -raw function_app_name)"
package="$(python3 "$root/scripts/package_function.py")"

az functionapp deployment source config-zip \
  --resource-group "$group" --name "$app" --src "$package" --build-remote true \
  --only-show-errors --output none

for attempt in {1..24}; do
  if binding_count="$(az functionapp function show \
    --resource-group "$group" --name "$app" --function-name GuardStorage \
    --query "length(config.bindings[?type=='eventGridTrigger'])" --output tsv 2>/dev/null)" \
    && [[ "$binding_count" == 1 ]]; then
    printf 'GuardStorage indexada com eventGridTrigger em %s.\n' "$app"
    exit 0
  fi
  printf 'Aguardando indexação de GuardStorage (%s/24)...\n' "$attempt"
  sleep 5
done

printf 'GuardStorage não foi indexada a tempo. Consulte docs/runbook.md.\n' >&2
exit 1
