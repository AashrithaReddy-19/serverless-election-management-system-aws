"""
UpdateElectionStatusFunction  -  POST /admin/election   (ADMIN only)

Body: {"status": "ACTIVE"}  -> Start election  (only from NOT_STARTED)
      {"status": "ENDED"}   -> End election    (only from ACTIVE)
      {"status": "RESET"}   -> New election: clears votes, hasVoted and counts
                               (keeps registered voters and candidates)
"""
from common import (
    ELECTION_ID, ELECTION_NAME, users_table, candidates_table, votes_table, election_table,
    respond, parse_body, get_claims, get_role, get_election, scan_all,
)

ALLOWED = {"NOT_STARTED": "ACTIVE", "ACTIVE": "ENDED"}


def reset_election():
    with votes_table.batch_writer() as batch:
        for v in scan_all(votes_table, ProjectionExpression="voteId"):
            batch.delete_item(Key={"voteId": v["voteId"]})
    for c in scan_all(candidates_table, ProjectionExpression="candidateId"):
        candidates_table.update_item(Key={"candidateId": c["candidateId"]},
                                     UpdateExpression="SET votes = :z",
                                     ExpressionAttributeValues={":z": 0})
    for u in scan_all(users_table):
        if u.get("role") == "VOTER":
            users_table.update_item(Key={"userId": u["userId"]},
                                    UpdateExpression="SET hasVoted = :f",
                                    ExpressionAttributeValues={":f": False})
    election_table.put_item(Item={"electionId": ELECTION_ID, "electionName": ELECTION_NAME,
                                  "status": "NOT_STARTED", "resultDeclared": False})


def lambda_handler(event, context):
    claims = get_claims(event)
    if get_role(claims) != "ADMIN":
        return respond(403, {"message": "Admin access only"})

    new_status = str(parse_body(event).get("status", "")).upper()
    current = get_election().get("status", "NOT_STARTED")

    if new_status == "RESET":
        reset_election()
        print(f"Election reset by {claims.get('email')}")
        return respond(200, {"message": "Election reset. Status is NOT_STARTED.", "status": "NOT_STARTED"})

    if ALLOWED.get(current) != new_status:
        return respond(400, {"message": f"Cannot change status from {current} to {new_status or '?'}"})

    election_table.update_item(
        Key={"electionId": ELECTION_ID},
        UpdateExpression="SET #s = :new",
        ConditionExpression="#s = :cur",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":new": new_status, ":cur": current},
    )
    print(f"Election status {current} -> {new_status} by {claims.get('email')}")
    label = "started" if new_status == "ACTIVE" else "ended"
    return respond(200, {"message": f"Election {label}.", "status": new_status})
