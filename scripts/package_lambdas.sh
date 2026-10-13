#!/usr/bin/env bash
# Builds one deployment zip per Lambda function in ./build/
# Each zip contains the function's lambda_function.py plus the shared common.py.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
declare -A FUNCTIONS=(
  [register_user]=RegisterUserFunction
  [get_candidates]=GetCandidatesFunction
  [cast_vote]=CastVoteFunction
  [admin_dashboard]=GetAdminDashboardFunction
  [election_status]=UpdateElectionStatusFunction
  [get_results]=GetResultsFunction
)
for dir in "${!FUNCTIONS[@]}"; do
  out="build/${FUNCTIONS[$dir]}.zip"
  rm -f "$out"
  zip -j -q "$out" "lambda/$dir/lambda_function.py" "lambda/shared/common.py"
  echo "Built $out"
done
