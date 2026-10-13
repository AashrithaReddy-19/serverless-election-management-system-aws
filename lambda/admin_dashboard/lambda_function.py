"""
GetAdminDashboardFunction  -  GET /admin/dashboard   (ADMIN only)

Registered voters, registered candidates, election status, total votes cast,
turnout. Candidate-wise vote counts are only included once the election is ENDED.
"""
from common import (
    users_table, candidates_table, votes_table, respond, get_claims, get_role,
    get_election, scan_all, compute_results,
)


def lambda_handler(event, context):
    if get_role(get_claims(event)) != "ADMIN":
        return respond(403, {"message": "Admin access only"})

    election = get_election()
    users = scan_all(users_table)
    voters = sorted(
        [{"name": u.get("name"), "email": u.get("email"), "voterId": u.get("voterId"),
          "hasVoted": bool(u.get("hasVoted", False))}
         for u in users if u.get("role") == "VOTER"],
        key=lambda v: v["name"] or "",
    )
    candidates = sorted(
        [{"candidateId": c["candidateId"], "candidateName": c.get("candidateName"),
          "partyName": c.get("partyName"), "symbol": c.get("symbol", ""), "email": c.get("email")}
         for c in scan_all(candidates_table)],
        key=lambda c: c["candidateName"] or "",
    )
    total_votes = len(scan_all(votes_table, ProjectionExpression="voteId"))
    turnout = round(total_votes * 100.0 / len(voters), 2) if voters else 0.0

    body = {
        "election": {"electionName": election.get("electionName"), "status": election.get("status"),
                     "resultDeclared": bool(election.get("resultDeclared", False))},
        "stats": {"totalVoters": len(voters), "totalCandidates": len(candidates),
                  "totalVotes": total_votes, "turnoutPercent": turnout},
        "voters": voters,
        "candidates": candidates,
    }
    if election.get("status") == "ENDED":
        body["results"] = compute_results()
    return respond(200, body)
