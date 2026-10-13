"""
End-to-end logic test for all six Lambda functions against mocked DynamoDB + Cognito (moto).
Run:  pip install "moto[dynamodb,cognitoidp]" boto3  &&  python tests/test_election_flow.py
"""
import importlib.util
import json
import os
import sys

os.environ.update(AWS_DEFAULT_REGION="ap-south-1", AWS_REGION="ap-south-1",
                  AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x")
from moto import mock_aws  # noqa
import boto3  # noqa

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambda")
SHARED = os.path.join(ROOT, "shared")
DIRS = {"RegisterUserFunction": "register_user", "GetCandidatesFunction": "get_candidates",
        "CastVoteFunction": "cast_vote", "GetAdminDashboardFunction": "admin_dashboard",
        "UpdateElectionStatusFunction": "election_status", "GetResultsFunction": "get_results"}


def load(fn):
    spec = importlib.util.spec_from_file_location(fn, os.path.join(ROOT, DIRS[fn], "lambda_function.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ev(claims=None, body=None, route="GET /x"):
    e = {"routeKey": route, "body": json.dumps(body or {})}
    if claims:
        e["requestContext"] = {"authorizer": {"jwt": {"claims": claims}}}
    return e


def call(mod, **kw):
    r = mod.lambda_handler(ev(**kw), None)
    return r["statusCode"], json.loads(r["body"])


@mock_aws
def main():
    ddb = boto3.client("dynamodb")
    for t, k in [("UsersTable", "userId"), ("CandidatesTable", "candidateId"),
                 ("ElectionTable", "electionId"), ("VotesTable", "voteId")]:
        ddb.create_table(TableName=t, KeySchema=[{"AttributeName": k, "KeyType": "HASH"}],
                         AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"}],
                         BillingMode="PAY_PER_REQUEST")
    cog = boto3.client("cognito-idp")
    pool = cog.create_user_pool(PoolName="p", UsernameAttributes=["email"])["UserPool"]["Id"]
    os.environ["USER_POOL_ID"] = pool
    sys.path.insert(0, SHARED)

    reg, cands, vote = load("RegisterUserFunction"), load("GetCandidatesFunction"), load("CastVoteFunction")
    admin, status, res = load("GetAdminDashboardFunction"), load("UpdateElectionStatusFunction"), load("GetResultsFunction")

    def sub_of(email):
        u = cog.admin_get_user(UserPoolId=pool, Username=email)
        return {a["Name"]: a["Value"] for a in u["UserAttributes"]}["sub"]

    pw = "Example#Pass1"  # dummy value used only against mocked Cognito
    for i, (n, p) in enumerate([("Alice", "ABC"), ("Bob", "XYZ"), ("Carol", "PQR")], 1):
        s, b = call(reg, body={"role": "CANDIDATE", "name": n, "email": f"c{i}@t.com", "password": pw,
                               "candidateId": f"c{i}", "partyName": p, "symbol": p[0]})
        assert s == 201, b
    for i in range(1, 6):
        s, b = call(reg, body={"role": "VOTER", "name": f"Voter{i}", "email": f"v{i}@t.com",
                               "password": pw, "voterId": f"v{i}"})
        assert s == 201, b
    assert call(reg, body={"role": "ADMIN", "name": "x", "email": "a@t.com", "password": pw})[0] == 400
    assert call(reg, body={"role": "VOTER", "name": "d", "email": "d@t.com", "password": pw, "voterId": "V1"})[0] == 409
    assert call(reg, body={"role": "VOTER", "name": "d", "email": "v1@t.com", "password": pw, "voterId": "V9"})[0] == 409
    print("registration OK; groups:", [g["GroupName"] for g in cog.list_groups(UserPoolId=pool)["Groups"]])

    A = {"sub": "admin-sub", "cognito:groups": "[ADMIN]", "email": "admin@t.com"}
    V = {i: {"sub": sub_of(f"v{i}@t.com"), "cognito:groups": "[VOTER]"} for i in range(1, 6)}
    C1 = {"sub": sub_of("c1@t.com"), "cognito:groups": "[CANDIDATE]"}

    s, b = call(cands, claims=V[1])
    assert s == 200 and b["election"]["status"] == "NOT_STARTED" and len(b["candidates"]) == 3
    assert all("votes" not in c for c in b["candidates"]) and b["me"]["hasVoted"] is False
    assert call(vote, claims=V[1], body={"candidateId": "C1"})[1]["message"] == "Election has not started yet."
    assert call(status, claims=V[1], body={"status": "ACTIVE"})[0] == 403
    assert call(admin, claims=V[1])[0] == 403
    assert call(status, claims=A, body={"status": "ENDED"})[0] == 400
    assert call(status, claims=A, body={"status": "ACTIVE"})[0] == 200
    assert call(res, claims=A)[0] == 403  # not ended yet

    for i, c in [(1, "C1"), (2, "C1"), (3, "C2"), (4, "C3")]:
        s, b = call(vote, claims=V[i], body={"candidateId": c})
        assert s == 200 and b == {"message": "Vote submitted successfully"}, b
    s, b = call(vote, claims=V[1], body={"candidateId": "C2"})
    assert s == 409 and b["message"] == "You have already voted in this election"
    assert call(vote, claims=V[5], body={"candidateId": "C99"})[1]["message"] == "Invalid candidate"
    assert call(vote, claims=C1, body={"candidateId": "C1"})[0] == 403
    assert call(vote, claims=A, body={"candidateId": "C1"})[0] == 403
    assert call(cands, claims=V[1])[1]["me"]["hasVoted"] is True
    s, b = call(admin, claims=A)
    assert b["stats"] == {"totalVoters": 5, "totalCandidates": 3, "totalVotes": 4, "turnoutPercent": 80.0}, b
    assert "results" not in b
    assert call(res, claims=C1)[0] == 403
    print("voting OK")

    assert call(status, claims=A, body={"status": "ENDED"})[0] == 200
    assert call(vote, claims=V[5], body={"candidateId": "C1"})[1]["message"] == "Election has ended."
    assert call(res, claims=V[1])[0] == 403
    s, b = call(res, claims=A)
    assert s == 200 and b["winner"]["candidateName"] == "Alice" and b["winner"]["votes"] == 2 and not b["isTie"]
    assert [r["votes"] for r in b["results"]] == [2, 1, 1] and b["totalVotes"] == 4
    s, b = call(res, claims=C1)
    assert s == 200 and b["winner"]["candidateId"] == "C1"
    assert call(res, claims=C1, route="POST /results/declare")[0] == 403
    s, b = call(res, claims=A, route="POST /results/declare")
    assert s == 200 and b["resultDeclared"]
    print("results OK:", json.dumps(b["winner"]))

    # ---- tie scenario ----
    assert call(status, claims=A, body={"status": "RESET"})[0] == 200
    assert call(admin, claims=A)[1]["stats"]["totalVotes"] == 0
    call(status, claims=A, body={"status": "ACTIVE"})
    for i, c in [(1, "C1"), (2, "C2"), (3, "C1"), (4, "C2"), (5, "C3")]:
        assert call(vote, claims=V[i], body={"candidateId": c})[0] == 200
    call(status, claims=A, body={"status": "ENDED"})
    s, b = call(res, claims=A)
    assert b["isTie"] and b["winner"] is None and sorted(c["candidateName"] for c in b["tiedCandidates"]) == ["Alice", "Bob"]
    print("tie OK:", [(c["candidateName"], c["votes"]) for c in b["tiedCandidates"]])
    print("ALL TESTS PASSED")


main()
