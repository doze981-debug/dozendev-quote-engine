# State machine

```text
DRAFT -> SENT -> VIEWED -> MODIFIED -> APPROVED
                                  |       |
                                  +-------+
                                          v
                                  QUOTE_APPROVED
                                          v
                                   CONTRACT_SENT
                                          v
                                  CONTRACT_SIGNED
                                          v
                                  DEPOSIT_PENDING
                                          v
                                     ONBOARDING
                                          v
                                    PROJECT_READY
```

Rules:

1. Prices are resolved from the versioned price list only.
2. Customer configuration can alter only `customer_configurable` services.
3. Every customer change creates a new immutable quote version.
4. Approval freezes the current quote version.
5. Contract generation reads only the frozen approved version.
6. Signature must happen before deposit creation.
7. Deposit payment starts onboarding.
8. `PROJECT_READY` requires every required checklist item to be complete.
