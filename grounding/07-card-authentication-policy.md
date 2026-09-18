# Card Authentication Voice Bot — Fictional POC Operating Procedure

> **Source:** provided as the working policy document for phase 1.
> **Status in this repo:** grounding document, and the first ingestion target. Deliberately thin —
> which makes it a good first corpus: the whole graph it should produce is small enough to be
> verified by hand, so it doubles as the ingestion pipeline's golden fixture.

---

## 1. Purpose and journey objective

This document describes a deliberately simple voice-bot journey for customer authentication. The bot
welcomes the customer, authenticates the customer, allows a maximum of three authentication attempts,
communicates the authentication outcome, and then transfers the call to CCP for further servicing.
The bot does not perform any additional servicing itself.

## 2. POC scope

- Welcome the customer and state the purpose of the interaction.
- Authenticate the customer.
- Allow a maximum of 3 authentication retries/attempts.
- On successful authentication, inform the customer that authentication was successful and transfer
  to CCP.
- After authentication remains unsuccessful at the maximum retry limit, inform the customer that
  authentication could not be completed and transfer to CCP.
- CCP handles all further servicing after transfer.

## 3. Operating procedure

**A. Opening and authentication.** Play the required opening statement. Explain that authentication
is needed before account-specific servicing can be discussed. Call `authenticate_customer`. Continue
only according to the authentication result.

**B. Authentication attempts.** Request the information required for authentication and call
`authenticate_customer`. Maintain an authentication attempt counter. The bot must not perform any
other servicing activity.

**C. Successful authentication.** If `authenticate_customer` returns `AUTHENTICATED`, inform the
customer that they have been successfully authenticated. Then transfer the call to CCP for further
servicing.

**D. Failed authentication and retry.** If authentication fails, inform the customer that the
authentication was unsuccessful and ask them to try again. The bot may make up to 3 total
authentication attempts. It must not make a fourth attempt.

**E. Maximum retry reached.** If authentication remains unsuccessful after the third attempt, inform
the customer that authentication could not be completed and that the call will be transferred to CCP
for further assistance. Then transfer the call to CCP.

**F. Transfer and end of automated journey.** After successful authentication or after the maximum
retry limit is reached, call `transfer_to_ccp`. The automated journey ends once the transfer is
initiated.

## 4. Voice and agentic behavior rules

- **Conversation state:** Remember the authentication attempt count and authentication result for the
  duration of the interaction.
- **Retry control:** Enforce a hard maximum of 3 authentication attempts. The retry counter must not
  reset during the same call.
- **Do not guess:** If required authentication information is unclear or cannot be understood, treat
  the attempt as unsuccessful and apply the retry logic.
- **Grounded outcome:** Only tell the customer that authentication succeeded when
  `authenticate_customer` returns `AUTHENTICATED`.
- **Failure messaging:** After the third unsuccessful attempt, clearly inform the customer that
  authentication could not be completed before transferring the call.
- **No servicing:** Do not answer or execute additional account-specific servicing requests in this
  POC. CCP owns further servicing.
- **Transfer:** Transfer to CCP after authentication success or after the third unsuccessful attempt.

## 5. Illustrative tools / APIs

| Tool / API | When used | Example output | Required bot behavior |
|---|---|---|---|
| `authenticate_customer` | For each authentication attempt | `AUTHENTICATED` / `FAILED` | `AUTHENTICATED` → success message → transfer to CCP. `FAILED` → failure message and retry until the third attempt. |
| `transfer_to_ccp` | After authentication success or max retry | `TRANSFERRED` / `FAILED` | End automated servicing after transfer is initiated. Handle a transfer failure using the platform's defined fallback. |

## 6. Required vs. generated language

- **Opening:** "Welcome. For your security, I need to authenticate you before we proceed."
- **Successful authentication:** "Thank you. You have been successfully authenticated. I will now
  connect you to CCP for further servicing."
- **Retry:** "I'm sorry, I couldn't verify your details. Please try again."
- **Maximum retry / failure:** "I'm sorry, I'm unable to authenticate you at this time. I will now
  connect you to a representative for further assistance."
- **Generated/conversational language:** The bot may vary wording naturally for prompts and
  transitions, provided the meaning remains consistent with the operating procedure.

## 7. Evaluation-critical behaviors

- Welcomes the customer before attempting authentication.
- Calls the authentication process and tracks attempts correctly.
- Never exceeds 3 authentication attempts in one interaction.
- Communicates successful authentication before transferring the call.
- Communicates authentication failure/max retry before transferring the call.
- Transfers to CCP after either authentication success or the maximum retry limit.
- Does not perform additional servicing within the POC.

## 8. Illustrative journey flow

*(The source document carries a flowchart here — "Simplified POC – Authentication Voice Bot". The
image is not reproduced in this transcription. It is a required ingestion input: the workflow
backbone should be recoverable from the diagram as well as from §3, and the two readings agreeing is
itself a useful check.)*

## 9. POC design boundary

This is intentionally a minimal authentication-and-transfer POC. There is no card replacement
workflow, knowledge retrieval, order placement, delivery selection, transaction review, or other
servicing logic inside the bot. The only automated outcomes are successful authentication followed by
transfer to CCP, or unsuccessful authentication after 3 attempts followed by transfer to CCP.

---

## Why this document is a good phase-1 target

It is thin, but it exercises most of the hard cases the pipeline has to get right:

| What it contains | Which ingestion problem it exercises |
|---|---|
| Prose workflow (§3) **and** a flowchart (§8) | two independent readings of the same backbone that must agree |
| "maximum of 3", "up to 3 total", "must not make a fourth" | the same numeric constraint stated three ways → duplicate detection on a canonical form |
| "must not perform any other servicing" (§3B) and "No servicing" (§4) | one prohibition stated in two scopes → merge without losing either evidence span |
| "Do not guess … treat the attempt as unsuccessful" | an implicit outcome mapping (`UNCLEAR` → `FAILED`) that is never named as an outcome |
| "Only tell the customer … when … returns AUTHENTICATED" | a grounding rule whose subject is a message and whose condition is a tool result |
| A tool table (§5) with outcomes in one cell | table parsing where the header carries the subject |
| `transfer_to_ccp` returns `FAILED`, but §9 declares only two automated outcomes | a genuine gap: a declared tool outcome with no declared destination → an open question, not an invented state |
| Required vs generated language (§6) | verbatim obligations vs paraphrase-permitted, which changes how the evaluator grades a response |

The last row is the one worth noting: a correct ingestion should **not** silently invent a
transfer-failure branch. It should record the outcome, find no destination, and raise it.
