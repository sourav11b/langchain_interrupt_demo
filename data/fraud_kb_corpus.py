"""Curated fraud-knowledge-base corpus.

Each doc gets vectorised + indexed in `fraud_kb`. Categories mirror common FSI
fraud typologies and the agent uses them as policy / playbook references.
"""
from __future__ import annotations

KB_DOCS: list[dict] = [
    {
        "title": "Card-present skimming at fuel pumps",
        "category": "card_present",
        "severity": "high",
        "text": (
            "Skimming devices at fuel pumps capture mag-stripe data and PIN entries. "
            "Indicators: low-amount card-present authorisation at a gas station "
            "immediately followed by high-value card-not-present transactions in a "
            "different MCC within 24h. Mitigation: temporary CNP block, contact "
            "cardholder, replace card, file SAR if loss > USD 1,000."
        ),
    },
    {
        "title": "Account takeover via SIM swap",
        "category": "ato",
        "severity": "critical",
        "text": (
            "Sudden device change followed by password reset, then high-value "
            "transfer to a newly added beneficiary. Indicators: new device "
            "fingerprint, OTP sent to a recently re-issued SIM, beneficiary added "
            "and used within 60 minutes. Action: freeze outbound transfers, force "
            "re-KYC with knowledge-based authentication and government ID."
        ),
    },
    {
        "title": "Card testing burst (BIN attack)",
        "category": "card_testing",
        "severity": "medium",
        "text": (
            "A burst of small-value (<$5) e-commerce auths against a single BIN "
            "indicates stolen card-number testing. Block subsequent CNP auths on "
            "any card in the BIN that authorises within the burst window. Notify "
            "scheme of compromise."
        ),
    },
    {
        "title": "Geo-velocity impossibility",
        "category": "geo_velocity",
        "severity": "high",
        "text": (
            "Two card-present transactions in cities more than 500 km apart within "
            "two hours imply a cloned card. Block the second transaction, freeze "
            "the card, and contact the customer to confirm physical possession."
        ),
    },
    {
        "title": "Mule account funnel",
        "category": "aml_mule",
        "severity": "high",
        "text": (
            "Multiple inbound P2P transfers from unrelated counterparties followed "
            "by a single outbound wire to a high-risk jurisdiction. Pattern is "
            "classic money-mule layering. Hold the outbound wire, escalate to the "
            "AML team, prepare CTR/SAR."
        ),
    },
    {
        "title": "Friendly fraud / first-party dispute",
        "category": "first_party",
        "severity": "low",
        "text": (
            "Cardholder disputes a legitimate purchase to recover funds. Look for "
            "matching device-id at checkout, prior shipping address use, and "
            "history of similar disputes. Push back via representment evidence."
        ),
    },
    {
        "title": "KYC verification factors (FSI policy)",
        "category": "kyc_policy",
        "severity": "info",
        "text": (
            "Identity verification requires at least two of: government ID match, "
            "biometric selfie liveness, address proof < 90 days, and OTP delivered "
            "to the registered mobile. For high-risk transactions over $5,000 a "
            "live agent step-up is mandatory."
        ),
    },
    {
        "title": "Case lifecycle (CRM playbook)",
        "category": "crm_policy",
        "severity": "info",
        "text": (
            "Open a case for any transaction scored >= 0.65 by the Fraud Sentinel. "
            "Initial status NEW; on customer denial, move to UNDER_INVESTIGATION; "
            "on customer confirmation, move to RESOLVED_LEGITIMATE; on no response "
            "after 30 minutes, move to PENDING_CUSTOMER. Always attach evidence "
            "documents and the agent reasoning."
        ),
    },
    {
        "title": "High-risk merchant categories",
        "category": "merchant_risk",
        "severity": "medium",
        "text": (
            "MCCs 7995 (gambling), 6051 (crypto), 4829 (wire transfer) and 5967 "
            "(adult) are higher risk for first-time customer activity. Require "
            "step-up authentication for purchases > $500."
        ),
    },
    {
        "title": "Trusted device & low-risk profile",
        "category": "low_risk",
        "severity": "info",
        "text": (
            "Transactions from a device used by the customer for >90 days, in a "
            "merchant they have used before, in their home country, and below "
            "their 95th-percentile basket size, may be auto-approved without OTP."
        ),
    },
]
