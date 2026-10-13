"""
common.py - shared helpers used by every Lambda in the
Serverless Election Management and Voting System.

- Table names / settings (env vars with sensible defaults)
- JSON response helper (with CORS headers)
- Reading the logged-in user's identity and role from the
  Cognito JWT claims that API Gateway already verified.
"""
import json
import os
from decimal import Decimal

import boto3

REGION = os.environ.get("AWS_REGION", "ap-south-1")
USERS_TABLE = os.environ.get("USERS_TABLE", "UsersTable")
CANDIDATES_TABLE = os.environ.get("CANDIDATES_TABLE", "CandidatesTable")
ELECTION_TABLE = os.environ.get("ELECTION_TABLE", "ElectionTable")
VOTES_TABLE = os.environ.get("VOTES_TABLE", "VotesTable")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "YOUR_COGNITO_USER_POOL_ID")
ELECTION_ID = os.environ.get("ELECTION_ID", "MAIN")
ELECTION_NAME = os.environ.get("ELECTION_NAME", "General Election 2026")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
users_table = dynamodb.Table(USERS_TABLE)
candidates_table = dynamodb.Table(CANDIDATES_TABLE)
election_table = dynamodb.Table(ELECTION_TABLE)
votes_table = dynamodb.Table(VOTES_TABLE)


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError


def respond(status_code, body):
    """Standard API Gateway proxy response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=_default),
    }


def parse_body(event):
    try:
        return json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return {}


def get_claims(event):
    """Claims from the Cognito ID token, verified by the API Gateway JWT authorizer.
    We NEVER trust a role sent by the browser - only these verified claims."""
    rc = event.get("requestContext") or {}
    auth = rc.get("authorizer") or {}
    return (auth.get("jwt") or {}).get("claims") or auth.get("claims") or {}


def get_groups(claims):
    """cognito:groups arrives as '[ADMIN]' or 'ADMIN VOTER' or a list."""
    raw = claims.get("cognito:groups", "")
    if isinstance(raw, list):
        return [g.upper() for g in raw]
    raw = str(raw).strip("[]")
    return [g.strip().upper() for g in raw.replace(",", " ").split() if g.strip()]


def get_role(claims):
    groups = get_groups(claims)
    for role in ("ADMIN", "CANDIDATE", "VOTER"):
        if role in groups:
            return role
    return None


def get_election():
    """Returns the single election record, creating it as NOT_STARTED if missing."""
    item = election_table.get_item(Key={"electionId": ELECTION_ID}).get("Item")
    if not item:
        item = {"electionId": ELECTION_ID, "electionName": ELECTION_NAME, "status": "NOT_STARTED"}
        election_table.put_item(Item=item)
    return item


def scan_all(table, **kwargs):
    items, resp = [], table.scan(**kwargs)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items.extend(resp.get("Items", []))
    return items


def compute_results():
    """Reads all candidates' vote counts and works out the winner (or a tie)."""
    candidates = scan_all(candidates_table)
    results = sorted(
        [
            {
                "candidateId": c["candidateId"],
                "candidateName": c.get("candidateName", ""),
                "partyName": c.get("partyName", ""),
                "symbol": c.get("symbol", ""),
                "votes": int(c.get("votes", 0)),
            }
            for c in candidates
        ],
        key=lambda r: (-r["votes"], r["candidateName"]),
    )
    total_votes = sum(r["votes"] for r in results)

    winner, tied = None, []
    if results and total_votes > 0:
        top = results[0]["votes"]
        leaders = [r for r in results if r["votes"] == top]
        if len(leaders) == 1:
            winner = leaders[0]
        else:
            tied = leaders  # never pick randomly
    return {
        "totalVotes": total_votes,
        "results": results,
        "winner": winner,
        "isTie": len(tied) > 1,
        "tiedCandidates": tied,
    }
