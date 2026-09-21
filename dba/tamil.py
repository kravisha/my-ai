"""The DBA's explanations in Tamil (§16, §43).

§16 gives the Tamil for audit trail — **தணிக்கைத் தடம்** — and Krish asked for
Tamil generally rather than only there.

## What this delivers, and what it does not

`dba/explain.py` generates a small, closed set of sentences from the structured
response. That closure is what makes translation honest here: every sentence
this agent can say is one of a known handful, so each can be written properly
in Tamil once, rather than machine-translated per request into something a
Tamil speaker would wince at.

**It falls back to English rather than guessing.** A response shape with no
Tamil rendering returns the English sentence unchanged, and `translated` says
so. Half-translated output - an English clause inside a Tamil sentence, or
worse, a transliteration - would be a worse answer than English, and the whole
point of §43 is that the sentence is the part a person actually reads.

**It covers the DBA only.** Jarvis answering in Tamil across every surface is a
larger piece of work than this milestone, and doing it badly everywhere would
be worse than doing it properly here first.

## The structured response stays authoritative

Same rule as §43 in English: this is an extra field beside the structured
response, never instead of it. Nothing branches on the Tamil.
"""

from __future__ import annotations

from dba import contract

# §16's own term, and the vocabulary the sentences below are built from.
AUDIT_TRAIL = "தணிக்கைத் தடம்"

TERMS = {
    "audit_trail": AUDIT_TRAIL,
    "record": "பதிவு",
    "records": "பதிவுகள்",
    "capability": "திறன்",
    "permission": "அனுமதி",
    "database": "தரவுத்தளம்",
    "field": "புலம்",
    "fields": "புலங்கள்",
    "question": "கேள்வி",
    "change": "மாற்றம்",
}

# Error leads, matched to `explain._error`'s English.
_ERROR_LEAD = {
    contract.PERMISSION_DENIED: "அதைச் செய்ய எனக்கு அனுமதி இல்லை.",
    contract.NOT_FOUND: "அதை என்னால் கண்டுபிடிக்க முடியவில்லை.",
    contract.DUPLICATE_DETECTED: "அது ஏற்கெனவே உள்ள ஒரு பதிவை நகலெடுக்கும்.",
    contract.CONFLICT_DETECTED: "ஏற்கெனவே பதிவு செய்யப்பட்டதுடன் அது முரண்படுகிறது.",
    contract.VALIDATION_ERROR: "அந்தக் கோரிக்கை செல்லுபடியாகாதது.",
    contract.DATABASE_UNAVAILABLE:
        "தரவுத்தளத்தை என்னால் அணுக முடியவில்லை, எனவே எதுவும் நடக்கவில்லை.",
    contract.TRANSACTION_FAILED:
        "மாற்றம் திரும்பப் பெறப்பட்டது; எதுவும் செயல்படுத்தப்படவில்லை.",
    contract.SCHEMA_MISMATCH: "அந்த வகையான பதிவு இங்கு அறிவிக்கப்படவில்லை.",
    contract.INTERNAL_ERROR: "எதிர்பாராத தோல்வி; எதுவும் எழுதப்படவில்லை.",
}


def explain(response: contract.Response) -> str:
    """The Tamil sentence, or the English one when there is no rendering."""
    return say(response)["text"]


def say(response: contract.Response) -> dict:
    """The sentence and whether it is actually Tamil.

    Returns both because a caller showing this to a person needs to know which
    language it got - a UI that labels an English fallback as Tamil is lying in
    a way the reader will notice immediately."""
    rendered = _render(response)
    if rendered is None:
        from dba import explain as english

        return {"text": english.explain(response), "translated": False,
                "why": "no Tamil rendering exists for this response shape; the "
                       "English sentence is returned unchanged rather than "
                       "half-translated"}
    return {"text": rendered, "translated": True}


def _render(response: contract.Response) -> str | None:
    if response.needs_answer:
        return _clarification(response)
    if response.status == contract.STATUS_ERROR:
        return _error(response)
    return _success(response)


def _success(response: contract.Response) -> str | None:
    what = response.entity_type or TERMS["record"]
    where = f" {response.entity_id}" if response.entity_id else ""
    result = response.result if isinstance(response.result, dict) else {}

    if response.changed:
        if response.action == contract.CREATE:
            return f"{what}{where} ஐ நான் உருவாக்கினேன்."
        if response.action == contract.UPDATE:
            fields = sorted((result.get("changed_fields") or {}))
            if fields:
                listed = ", ".join(fields)
                return (f"{what}{where} இன் {listed} ஐ நான் புதுப்பித்தேன். "
                        f"வேறு எந்தப் புலமும் மாற்றப்படவில்லை.")
            return f"{what}{where} ஐ நான் புதுப்பித்தேன்."
        if response.action == contract.ARCHIVE:
            return (f"{result.get('affected', 1)} {TERMS['records']} ஐ நான் "
                    f"காப்பகப்படுத்தினேன்.")
        if response.action == contract.DELETE_AUTHORIZED:
            return (f"{result.get('affected', 1)} {TERMS['records']} ஐ நான் "
                    f"நீக்கினேன்.")
        if response.action == contract.LINK:
            return "அந்த இரண்டு பதிவுகளையும் நான் இணைத்தேன்."
        if response.action == contract.UNLINK:
            return "அந்த இணைப்பை நான் நீக்கினேன்."
        return None

    if result.get("committed") is False:
        count = result.get("matched_records")
        if count is not None:
            return (f"எதுவும் மாற்றப்படவில்லை. அது {count} {TERMS['records']} ஐப் "
                    f"பாதிக்கும்.")
        return "எதுவும் மாற்றப்படவில்லை. இது ஒரு முன்னோட்டம் மட்டுமே."
    if "matches" in result and "count" in result:
        return f"{result['count']} {TERMS['records']} கிடைத்தன."
    if "events" in result:
        return (f"{what}{where} இல் {result.get('count', 0)} மாற்றங்கள் "
                f"{AUDIT_TRAIL} இல் பதிவாகியுள்ளன.")
    if "count" in result:
        return f"{result['count']} {TERMS['records']} உள்ளன."
    if response.warnings:
        return f"{what}{where} இல் எந்த மாற்றமும் இல்லை."
    if response.action in (contract.GET, contract.FIND, contract.SEARCH,
                           contract.LIST):
        return f"{what}{where} ஐ நான் படித்தேன்."
    return None


def _clarification(response: contract.Response) -> str:
    asked = response.clarification or {}
    options = asked.get("options") or []
    sentence = "நான் எதையும் மாற்றவில்லை."

    reason = asked.get("reason")
    if reason == contract.MULTIPLE_MATCHING_RECORDS:
        sentence += f" {len(options)} பதிவுகள் பொருந்துகின்றன. எது என்று சொல்ல முடியுமா?"
    elif reason == contract.MISSING_REQUIRED_INFORMATION:
        missing = ", ".join(str(option.get("field")) for option in options
                            if option.get("field"))
        sentence += f" {missing} தேவை. அது என்னவாக இருக்க வேண்டும்?"
    elif reason == contract.CONTRADICTORY_REQUEST:
        sentence += " கோரிக்கையில் ஒரு முரண்பாடு உள்ளது. எந்த நிலை சரி?"
    elif reason == contract.DESTRUCTIVE_SCOPE_UNCLEAR:
        sentence += (f" இது {len(options)} பதிவுகளைப் பாதிக்கும். அந்த வரம்பை "
                     f"உறுதிப்படுத்துகிறீர்களா?")
    elif reason == contract.UNCERTAIN_RELATIONSHIP:
        sentence += " எந்தப் பதிவுடன் இணைக்க வேண்டும் என்று தெளிவாக இல்லை."
    else:
        sentence += " ஒரு கேள்வி உள்ளது."

    pending = asked.get("pending_action")
    if pending:
        sentence += f" காத்திருப்பது: {pending}."
    return sentence


def _error(response: contract.Response) -> str | None:
    code = (response.error or {}).get("error_code")
    lead = _ERROR_LEAD.get(code)
    if lead is None:
        return None
    return lead


def describe() -> dict:
    """What is available in Tamil, for a caller deciding what to show."""
    return {
        "terms": dict(TERMS),
        "covers": "the DBA's generated explanations (§43) and §16's audit-trail "
                  "term",
        "does_not_cover": "Jarvis's other surfaces; that is a larger piece of "
                          "work and is not pretended to be done here",
        "falls_back_to_english": True,
    }
