# Architecture

```
                    ┌────────────────────────┐
                    │      User Browser      │
                    │ (Voter/Candidate/Admin)│
                    └───────────┬────────────┘
             1. load site       │       2. login (InitiateAuth)
        ┌───────────────────────┼──────────────────────────┐
        ▼                       │                          ▼
┌───────────────┐               │                 ┌──────────────────┐
│  Amazon S3    │               │                 │  Amazon Cognito  │
│ static website│               │                 │ User pool + groups│
└───────────────┘               │                 │ VOTER/CANDIDATE/ │
                                │ 3. API call +   │ ADMIN → ID token │
                                │    Bearer token └──────────────────┘
                                ▼
                    ┌────────────────────────┐
                    │  Amazon API Gateway    │
                    │  HTTP API "VotingAPI"  │
                    │  JWT authorizer (401)  │
                    └───────────┬────────────┘
                                ▼
                    ┌────────────────────────┐      ┌──────────────────┐
                    │      AWS Lambda        │─────▶│ Amazon CloudWatch│
                    │  6 Python functions    │ logs │      Logs        │
                    │  (role re-checked)     │      └──────────────────┘
                    └───────────┬────────────┘
                                ▼  (IAM least-privilege role)
                    ┌────────────────────────┐
                    │    Amazon DynamoDB     │
                    │ UsersTable             │
                    │ CandidatesTable        │
                    │ ElectionTable          │
                    │ VotesTable             │
                    └────────────────────────┘
```

## Request lifecycle (cast a vote)

1. The voter's browser sends `POST /vote` with `Authorization: Bearer <ID token>` and `{"candidateId": "C101"}`.
2. The API Gateway JWT authorizer validates the token's signature, issuer and audience. If the token is invalid, the response is `401`.
3. `CastVoteFunction` reads the `sub` and `cognito:groups` claims and requires `VOTER`.
4. It checks that the election is `ACTIVE`, the voter profile exists, `hasVoted` is false and the candidate exists.
5. A single DynamoDB `TransactWriteItems` call writes the vote (unique `voteId`), increments the candidate's `votes` and sets `hasVoted = true`. It also re-checks that the election is still `ACTIVE`.
6. The function returns `{"message": "Vote submitted successfully"}`. No counts are returned.

## Code layout

| Path | Contents |
|---|---|
| `frontend/` | Static website (HTML/CSS/JS) |
| `lambda/<function>/lambda_function.py` | Handler for each Lambda |
| `lambda/shared/common.py` | Shared helpers: table names, CORS response, claim parsing, results/winner calculation |
| `api/api-definition.json` | OpenAPI 3 definition of the HTTP API, with placeholders for account-specific IDs |
| `scripts/package_lambdas.sh` | Builds one zip per function (handler + common.py) |
| `tests/` | Mocked end-to-end test suite |

## Design decisions

- **Single shared election (`electionId = MAIN`)** keeps the data model simple for a college project. The code is ready to be extended to multiple elections.
- **Deterministic vote ID (`MAIN#<userId>`)** makes duplicate votes impossible at the database level, even under concurrency.
- **The atomic counter on `CandidatesTable.votes`** makes results an O(number of candidates) read instead of counting every vote.
- **Admin cannot self-register.** Admin accounts are created by the system owner in Cognito.
