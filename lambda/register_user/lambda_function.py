"""
RegisterUserFunction  -  POST /register   (public)

Registers a VOTER or CANDIDATE:
  1. Validate input (ADMIN can never self-register).
  2. Create the user in Amazon Cognito with a permanent password.
  3. Put the user in the Cognito group VOTER or CANDIDATE (this is the trusted role).
  4. Save the profile in UsersTable (and CandidatesTable for candidates).
"""
import re

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from common import (
    USER_POOL_ID, REGION, users_table, candidates_table,
    respond, parse_body, scan_all,
)

cognito = boto3.client("cognito-idp", region_name=REGION)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ensure_group(name):
    """Creates the VOTER / CANDIDATE group the first time it is needed."""
    try:
        cognito.create_group(GroupName=name, UserPoolId=USER_POOL_ID,
                             Description=f"{name} role for the election system")
    except ClientError as e:
        if e.response["Error"]["Code"] != "GroupExistsException":
            raise


def lambda_handler(event, context):
    data = parse_body(event)
    role = str(data.get("role", "")).upper()
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if role not in ("VOTER", "CANDIDATE"):
        return respond(400, {"message": "Role must be VOTER or CANDIDATE"})
    if not name or not EMAIL_RE.match(email):
        return respond(400, {"message": "A valid name and email are required"})
    if len(password) < 8:
        return respond(400, {"message": "Password must be at least 8 characters"})

    if role == "VOTER":
        voter_id = str(data.get("voterId", "")).strip().upper()
        if not voter_id:
            return respond(400, {"message": "Voter ID is required"})
        if scan_all(users_table, FilterExpression=Attr("voterId").eq(voter_id)):
            return respond(409, {"message": "This Voter ID is already registered"})
    else:
        candidate_id = str(data.get("candidateId", "")).strip().upper()
        party = str(data.get("partyName", "")).strip()
        symbol = str(data.get("symbol", "")).strip()
        if not candidate_id or not party:
            return respond(400, {"message": "Candidate ID and Party Name are required"})
        if candidates_table.get_item(Key={"candidateId": candidate_id}).get("Item"):
            return respond(409, {"message": "This Candidate ID is already registered"})

    # ---- 1. Create the Cognito user ----
    try:
        created = cognito.admin_create_user(
            UserPoolId=USER_POOL_ID,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": name},
            ],
            MessageAction="SUPPRESS",
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "UsernameExistsException":
            return respond(409, {"message": "An account with this email already exists"})
        print("Cognito error:", e)
        return respond(400, {"message": e.response["Error"]["Message"]})

    attrs = {a["Name"]: a["Value"] for a in created["User"]["Attributes"]}
    user_id = attrs["sub"]

    try:
        cognito.admin_set_user_password(UserPoolId=USER_POOL_ID, Username=email,
                                        Password=password, Permanent=True)
        ensure_group(role)
        cognito.admin_add_user_to_group(UserPoolId=USER_POOL_ID, Username=email, GroupName=role)

        # ---- 2. Save profile in DynamoDB ----
        user = {"userId": user_id, "name": name, "email": email, "role": role}
        if role == "VOTER":
            user.update({"voterId": voter_id, "hasVoted": False})
            users_table.put_item(Item=user)
        else:
            user.update({"candidateId": candidate_id, "partyName": party, "symbol": symbol})
            candidates_table.put_item(
                Item={"candidateId": candidate_id, "candidateName": name, "partyName": party,
                      "symbol": symbol, "email": email, "userId": user_id, "votes": 0},
                ConditionExpression="attribute_not_exists(candidateId)",
            )
            users_table.put_item(Item=user)
    except ClientError as e:
        # roll back the Cognito user so the person can try again
        print("Registration failed, rolling back:", e)
        try:
            cognito.admin_delete_user(UserPoolId=USER_POOL_ID, Username=email)
        except ClientError:
            pass
        msg = e.response["Error"]["Message"]
        if e.response["Error"]["Code"] == "InvalidPasswordException":
            msg = "Password must have upper & lower case letters, a number and a symbol"
        return respond(400, {"message": msg})

    print(f"Registered {role} {email} ({user_id})")
    return respond(201, {"message": f"{role.title()} registered successfully. Please login."})
