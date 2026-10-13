"""
GetCandidatesFunction  -  GET /candidates   (any logged-in user)

Returns:
  - election  : name + status (NOT_STARTED / ACTIVE / ENDED)
  - me        : the logged-in user's own profile (hasVoted for voters)
  - candidates: registered candidates from CandidatesTable
                (vote counts are NEVER returned here)
"""
from common import (
    users_table, candidates_table, respond, get_claims, get_role,
    get_election, scan_all,
)


def lambda_handler(event, context):
    claims = get_claims(event)
    role = get_role(claims)
    if not role:
        return respond(403, {"message": "Not authorized"})

    election = get_election()
    profile = users_table.get_item(Key={"userId": claims.get("sub", "")}).get("Item") or {}
    me = {
        "name": profile.get("name") or claims.get("name") or claims.get("email", ""),
        "email": profile.get("email") or claims.get("email", ""),
        "role": role,
    }
    if role == "VOTER":
        me.update({"voterId": profile.get("voterId", ""), "hasVoted": bool(profile.get("hasVoted", False))})
    if role == "CANDIDATE":
        me.update({"candidateId": profile.get("candidateId", ""), "partyName": profile.get("partyName", ""),
                   "symbol": profile.get("symbol", "")})

    candidates = sorted(
        [
            {"candidateId": c["candidateId"], "candidateName": c.get("candidateName", ""),
             "partyName": c.get("partyName", ""), "symbol": c.get("symbol", "")}
            for c in scan_all(candidates_table)
        ],
        key=lambda c: c["candidateName"],
    )
    return respond(200, {
        "election": {"electionName": election.get("electionName"), "status": election.get("status")},
        "me": me,
        "candidates": candidates,
    })
