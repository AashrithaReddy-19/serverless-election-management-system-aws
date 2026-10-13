"""
CastVoteFunction  -  POST /vote   (VOTER only)

 1. Authenticate voter (Cognito JWT verified by API Gateway)
 2. Election status must be ACTIVE
 3. Voter must exist in UsersTable
 4. Role must be VOTER
 5. hasVoted must be false
 6. Candidate must exist
 7-9. ONE DynamoDB transaction (all-or-nothing):
        - save vote in VotesTable (voteId = election#voter, can only exist once)
        - candidate votes = votes + 1   (atomic counter)
        - voter hasVoted = true          (only if it was false)
10. Return "Vote submitted successfully" - never any vote counts.
"""
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from common import (
    REGION, USERS_TABLE, CANDIDATES_TABLE, VOTES_TABLE, ELECTION_TABLE, ELECTION_ID,
    users_table, candidates_table, respond, parse_body, get_claims, get_role, get_election,
)

client = boto3.client("dynamodb", region_name=REGION)
ALREADY = "You have already voted in this election"


def lambda_handler(event, context):
    claims = get_claims(event)
    user_id = claims.get("sub")

    # 1 + 4. authenticated and in the VOTER group
    if not user_id or get_role(claims) != "VOTER":
        return respond(403, {"message": "Only registered voters can vote"})

    # 2. election must be ACTIVE
    status = get_election().get("status")
    if status == "NOT_STARTED":
        return respond(400, {"message": "Election has not started yet."})
    if status == "ENDED":
        return respond(400, {"message": "Election has ended."})

    # 3 + 4. voter exists and profile role is VOTER
    voter = users_table.get_item(Key={"userId": user_id}).get("Item")
    if not voter or voter.get("role") != "VOTER":
        return respond(403, {"message": "Voter profile not found"})

    # 5. already voted?
    if voter.get("hasVoted"):
        return respond(409, {"message": ALREADY})

    # 6. candidate exists?
    candidate_id = str(parse_body(event).get("candidateId", "")).strip().upper()
    if not candidate_id or not candidates_table.get_item(Key={"candidateId": candidate_id}).get("Item"):
        return respond(400, {"message": "Invalid candidate"})

    # 7, 8, 9. atomic transaction - safe even if two requests arrive together
    vote_id = f"{ELECTION_ID}#{user_id}"
    try:
        client.transact_write_items(TransactItems=[
            {"ConditionCheck": {
                "TableName": ELECTION_TABLE,
                "Key": {"electionId": {"S": ELECTION_ID}},
                "ConditionExpression": "#s = :active",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": {":active": {"S": "ACTIVE"}},
            }},
            {"Put": {
                "TableName": VOTES_TABLE,
                "Item": {
                    "voteId": {"S": vote_id},
                    "voterId": {"S": voter.get("voterId", "")},
                    "userId": {"S": user_id},
                    "candidateId": {"S": candidate_id},
                    "electionId": {"S": ELECTION_ID},
                    "timestamp": {"S": datetime.now(timezone.utc).isoformat()},
                },
                "ConditionExpression": "attribute_not_exists(voteId)",
            }},
            {"Update": {
                "TableName": CANDIDATES_TABLE,
                "Key": {"candidateId": {"S": candidate_id}},
                "UpdateExpression": "ADD votes :one",
                "ConditionExpression": "attribute_exists(candidateId)",
                "ExpressionAttributeValues": {":one": {"N": "1"}},
            }},
            {"Update": {
                "TableName": USERS_TABLE,
                "Key": {"userId": {"S": user_id}},
                "UpdateExpression": "SET hasVoted = :t",
                "ConditionExpression": "attribute_not_exists(hasVoted) OR hasVoted = :f",
                "ExpressionAttributeValues": {":t": {"BOOL": True}, ":f": {"BOOL": False}},
            }},
        ])
    except ClientError as e:
        if e.response["Error"]["Code"] == "TransactionCanceledException":
            reasons = [r.get("Code") for r in e.response.get("CancellationReasons", [])]
            print("Vote rejected:", reasons)
            if reasons and reasons[0] == "ConditionalCheckFailed":
                return respond(400, {"message": "Election is not active."})
            if len(reasons) > 2 and reasons[2] == "ConditionalCheckFailed":
                return respond(400, {"message": "Invalid candidate"})
            return respond(409, {"message": ALREADY})
        raise

    print(f"Vote recorded: voter={voter.get('voterId')} candidate={candidate_id}")
    return respond(200, {"message": "Vote submitted successfully"})
