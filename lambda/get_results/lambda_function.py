"""
GetResultsFunction
  GET  /results          (ADMIN or CANDIDATE, only when election is ENDED)
  POST /results/declare  (ADMIN only) - declares the winner and stores it

Winner logic: highest vote count wins. If two or more candidates share the
highest count, the result is a TIE - a winner is never picked randomly.
"""
from common import (
    ELECTION_ID, users_table, election_table, respond, get_claims, get_role,
    get_election, scan_all, compute_results,
)


def lambda_handler(event, context):
    claims = get_claims(event)
    role = get_role(claims)
    route = event.get("routeKey", "GET /results")

    if role not in ("ADMIN", "CANDIDATE"):
        return respond(403, {"message": "Results are only available to the admin and candidates"})
    if route.startswith("POST") and role != "ADMIN":
        return respond(403, {"message": "Only the admin can declare the winner"})

    election = get_election()
    if election.get("status") != "ENDED":
        return respond(403, {"message": "Results will be available after the election has ended.",
                             "status": election.get("status")})

    data = compute_results()
    total_voters = len([u for u in scan_all(users_table) if u.get("role") == "VOTER"])
    data["totalVoters"] = total_voters
    data["turnoutPercent"] = round(data["totalVotes"] * 100.0 / total_voters, 2) if total_voters else 0.0
    data["electionName"] = election.get("electionName")

    if route.startswith("POST"):
        summary = (f"TIE: {', '.join(c['candidateName'] for c in data['tiedCandidates'])}"
                   if data["isTie"] else
                   (data["winner"]["candidateName"] if data["winner"] else "No votes cast"))
        election_table.update_item(
            Key={"electionId": ELECTION_ID},
            UpdateExpression="SET resultDeclared = :t, declaredResult = :w",
            ExpressionAttributeValues={":t": True, ":w": summary},
        )
        print(f"Result declared by {claims.get('email')}: {summary}")
        election["resultDeclared"] = True

    data["resultDeclared"] = bool(election.get("resultDeclared", False))
    return respond(200, data)
