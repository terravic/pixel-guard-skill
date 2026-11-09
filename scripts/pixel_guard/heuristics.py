"""Deterministic prompt-injection, exfiltration, payload decoding, and entropy threat analyzer."""

from __future__ import annotations

import base64
import binascii
import math
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass

from .config import ScanConfig
from .models import ThreatAssessment


@dataclass(frozen=True)
class HeuristicRule:
    """Single compiled regular expression rule mapping to a security flag and severity."""

    rule_id: str
    security_flag: str
    severity: str  # MEDIUM, HIGH, CRITICAL
    pattern: re.Pattern[str]


HEURISTIC_RULES: tuple[HeuristicRule, ...] = (
    HeuristicRule(
        rule_id="HR-01A",
        security_flag="INSTRUCTION_OVERRIDE_MATCH",
        severity="CRITICAL",
        pattern=re.compile(
            r"(?i)\b(?:ignore|disregard|bypass|forget|override|discard)\s+"
            r"(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|preceding|earlier|initial|system)\s+"
            r"(?:instructions?|prompts?|directives?|rules?|guidelines?|constraints?)\b"
        ),
    ),
    HeuristicRule(
        rule_id="HR-01B",
        security_flag="INSTRUCTION_OVERRIDE_MATCH",
        severity="CRITICAL",
        pattern=re.compile(
            r"(?i)\b(?:new\s+system\s+instructions?|stop\s+following\s+previous|bypass\s+all\s+safety\s+checks?)\b"
        ),
    ),
    HeuristicRule(
        rule_id="HR-02",
        security_flag="SYSTEM_ROLE_SPOOFING",
        severity="CRITICAL",
        pattern=re.compile(
            r"(?i)(?:\[\s*(?:system|assistant|developer|system\s+instruction|admin\s+override)\s*[:\]]|"
            r"\b(?:system\s+override|system\s+instruction\s*:|administrative\s+override|administrator\s+override|"
            r"developer\s+mode\s+enabled|dan\s+mode|root\s+access\s+granted)\b)"
        ),
    ),
    HeuristicRule(
        rule_id="HR-03",
        security_flag="PERSONA_JAILBREAK_MATCH",
        severity="HIGH",
        pattern=re.compile(
            r"(?i)\b(?:you\s+are\s+now|act\s+as|pretend\s+(?:you\s+are|to\s+be)|you\s+must\s+now\s+act\s+as)\s+"
            r"(?:an?\s+)?(?:unrestricted|unfiltered|jailbroken|rogue|dan|autonomous\s+root)\b"
        ),
    ),
    HeuristicRule(
        rule_id="HR-04",
        security_flag="PROMPT_EXFILTRATION_REQUEST",
        severity="CRITICAL",
        pattern=re.compile(
            r"(?i)\b(?:output|reveal|display|print|dump|exfiltrate|forward|send|leak)\s+"
            r"(?:all\s+|the\s+|your\s+|user\s+)?(?:system\s+prompt|initial\s+instructions?|api\s+keys?|"
            r"user\s+secrets?|credentials?|chat\s+history|system\s+memory|environment\s+variables?)\b"
        ),
    ),
    HeuristicRule(
        rule_id="HR-05A",
        security_flag="EXTERNAL_URL_EXFILTRATION",
        severity="CRITICAL",
        pattern=re.compile(r"(?i)!\[[^\]]*\]\(\s*https?://[^\s\)]+\)"),
    ),
    HeuristicRule(
        rule_id="HR-05B",
        security_flag="EXTERNAL_URL_EXFILTRATION",
        severity="CRITICAL",
        pattern=re.compile(
            r"(?i)https?://[^\s\"'<>]+(?:/(?:leak|exfil|sink|collect|webhook)|"
            r"\?(?:[^\s\"'<>]*&)?(?:token|secret|key|password|dump|history|data)=)"
        ),
    ),
    HeuristicRule(
        rule_id="HR-06",
        security_flag="COMMAND_EXECUTION_SIGNATURE",
        severity="CRITICAL",
        pattern=re.compile(
            r"(?i)(?:<\s*script\b|\b(?:curl|wget)\s+https?://|\b(?:bash|sh)\s+-c\b|"
            r"\bbase64\s+-d\b|\b(?:eval|exec)\s*\(|\bos\.system\s*\(|\bsubprocess\.(?:Popen|run|call)\s*\()"
        ),
    ),
)

_SEVERITY_RANK: dict[str, int] = {
    "CLEAN": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}

_BASE64_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9+/=])(?:[A-Za-z0-9+/]{4}){5,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{4})(?![A-Za-z0-9+/=])"
)
_HEX_CANDIDATE_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}){12,}\b")


def calculate_shannon_entropy(token: str) -> float:
    """Compute Shannon entropy in bits per character for a non-empty string."""
    length = len(token)
    if length == 0:
        return 0.0
    counts = Counter(token)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _is_mostly_printable_ascii(decoded_bytes: bytes) -> str | None:
    """Return UTF-8 text if >= 90% of decoded bytes are printable ASCII characters."""
    if len(decoded_bytes) < 10:
        return None
    try:
        text = decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    printable_count = sum(1 for ch in text if 32 <= ord(ch) <= 126 or ch in "\r\n\t")
    if printable_count / max(1, len(text)) < 0.90:
        return None
    # Require at least one space or recognizable command/path delimiter to avoid natural word false positives
    if not any(sep in text for sep in (" ", ":", "/", "(", "=", ";", "-")):
        return None
    return text.strip()


def decode_obfuscated_candidates(text: str) -> list[str]:
    """Deterministically decode Base64, Hex, or URL-encoded ASCII substrings."""
    decoded_list: list[str] = []

    # 1. Base64 candidates
    for match in _BASE64_CANDIDATE_RE.finditer(text):
        token = match.group(0)
        # Skip pure alphabetical English words that happen to be multiples of 4 chars
        if token.isalpha() and token.islower():
            continue
        try:
            raw = base64.b64decode(token, validate=True)
            printable = _is_mostly_printable_ascii(raw)
            if printable and printable not in decoded_list:
                decoded_list.append(printable)
        except (binascii.Error, ValueError):
            continue

    # 2. Hexadecimal candidates (including space-delimited byte dumps or OCR-split hex runs)
    hex_joined = re.sub(r"(?<=[0-9a-fA-F])\s+(?=[0-9a-fA-F])", "", text)
    for source_str in (text, hex_joined) if hex_joined != text else (text,):
        for match in _HEX_CANDIDATE_RE.finditer(source_str):
            token = match.group(0)
            try:
                raw = bytes.fromhex(token)
                printable = _is_mostly_printable_ascii(raw)
                if printable and printable not in decoded_list:
                    decoded_list.append(printable)
            except ValueError:
                continue

    # 3. Percent-encoded sequences (at least 3 %XX escapes)
    if text.count("%") >= 3 and re.search(r"(?:%[0-9A-Fa-f]{2}){3,}", text):
        unquoted = urllib.parse.unquote(text)
        if unquoted != text and unquoted not in decoded_list:
            decoded_list.append(unquoted)

    return decoded_list


def evaluate_text_threats(text: str, config: ScanConfig, _depth: int = 0) -> ThreatAssessment:
    """Evaluate text against regex threat signatures, obfuscated encodings, and Shannon entropy."""
    if not text or not text.strip():
        return ThreatAssessment(
            severity="CLEAN",
            security_flags=(),
            decoded_payloads=(),
            max_token_entropy=0.0,
        )

    flags: list[str] = []
    max_sev = "CLEAN"

    def _escalate(sev: str) -> None:
        nonlocal max_sev
        if _SEVERITY_RANK[sev] > _SEVERITY_RANK[max_sev]:
            max_sev = sev

    for rule in HEURISTIC_RULES:
        if rule.pattern.search(text):
            if rule.security_flag not in flags:
                flags.append(rule.security_flag)
            _escalate(rule.severity)

    decoded_payloads: list[str] = []
    if _depth < 2:
        for decoded in decode_obfuscated_candidates(text):
            decoded_payloads.append(decoded)
            if "OBFUSCATED_PAYLOAD_DETECTED" not in flags:
                flags.append("OBFUSCATED_PAYLOAD_DETECTED")
            _escalate("HIGH")
            nested = evaluate_text_threats(decoded, config, _depth=_depth + 1)
            for fl in nested.security_flags:
                if fl not in flags:
                    flags.append(fl)
            _escalate(nested.severity)

    # Compute maximum unspaced token Shannon entropy (ignoring benign URLs unless URL matched exfil)
    max_entropy = 0.0
    for raw_tok in text.split():
        cleaned_tok = raw_tok.strip(".,;:()[]{}<>\"'")
        if len(cleaned_tok) < config.entropy_min_length:
            continue
        if cleaned_tok.lower().startswith(("http://", "https://")):
            continue
        ent = calculate_shannon_entropy(cleaned_tok)
        if ent > max_entropy:
            max_entropy = ent
        if ent >= config.entropy_threshold:
            if "OBFUSCATED_PAYLOAD_DETECTED" not in flags:
                flags.append("OBFUSCATED_PAYLOAD_DETECTED")
            _escalate("MEDIUM")

    return ThreatAssessment(
        severity=max_sev,
        security_flags=tuple(flags),
        decoded_payloads=tuple(decoded_payloads),
        max_token_entropy=max_entropy,
    )
