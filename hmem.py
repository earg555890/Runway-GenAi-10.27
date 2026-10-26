"""H-MEM, the Meterless hierarchical memory engine, in Python: a faithful port of the reference implementation
(engines/hmem/reference/src in github.com/Meterless/Meterless, Apache-2.0) and its spec (engines/hmem/AGENTS.md).

    hmem = HMEM(clock=lambda: ms, persist_dir=path)    # state.json + ledger.jsonl when persist_dir is set
    rec = hmem.add(content=..., source=..., type=..., layer=..., tags=[...], provenance={...})
    hmem.query("text")      -> QueryResult(memories=[RetrievedMemory], context, trace)
    hmem.feedback(id, "helpful" | "not_helpful" | "wrong")
    hmem.store / hmem.ledger / hmem.sleep / hmem.dreaming / hmem.conflicts / hmem.mining

What the spec fixes exactly (and tests/test_hmem_conformance.py checks with the official conformance vectors):
- a record with no source is rejected by construction; provenance is mandatory on new writes
- retrieval: raw = 0.35 semantic + 0.20 keyword + 0.10 tag + 0.10 domain + 0.15 entity + 0.05 layer
  + 0.05 recency - 0.20 superseded; score = clamp01(raw) x confidence; threshold 0.35 on the final score; top 5
- feedback deltas: helpful +0.05 (and accessCount + 1), not_helpful -0.03, wrong -0.20 (and the review tag)
- an append-only trust ledger of the 17 canonical actions, with previous and new state
- sleep is preview-first, backs up before executing, and never archives superseding, derived or hub records
- conflicts auto-resolve only at decision confidence >= 0.70; the loser is marked supersededBy, never deleted
- dream proposals never become memory before a human approves them; approved ones carry derivedFrom lineage

The embedder is the reference's deterministic FNV-1a hash embedder (64 dims), so scores match the reference.
"""
import copy
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DAY_MS = 24 * 60 * 60 * 1000
FEEDBACK_DELTAS = {"helpful": 0.05, "not_helpful": -0.03, "wrong": -0.2}
DEFAULTS = dict(retrieval_top_n=5, retrieval_threshold=0.35, consolidation_days=7, archive_min_days=30,
                archive_max_access=2, synthesis_cosine=0.82, dream_cluster_min_size=2, dream_relatedness=0.35,
                max_dream_proposals_per_type=8, conflict_auto_resolve_gate=0.7, entity_cap=10, related_cap=5,
                recency_days=14)
LEDGER_ACTIONS = ("create", "read", "update", "delete", "feedback", "promote", "demote", "merge", "conflict_detected",
                  "conflict_resolved", "sleep_consolidate", "sleep_archive", "sleep_synthesize", "dream_proposed",
                  "dream_approved", "dream_rejected", "restore")
ORIGINS = ("chat_message", "user_correction", "file_save", "file_open", "file_edit", "model_response",
           "plan_completion", "document", "manual", "dream", "sleep_synthesis")
TYPES = ("personal", "factual", "preference", "general")
LAYERS = ("short_term", "working", "long_term")


def clamp01(x):
    return min(1.0, max(0.0, x))


# --- embeddings (reference embeddings.ts) ---------------------------------------------------------------------
DIM = 64


def tokenize(text):
    return [t for t in re.split(r"\s+", re.sub(r"[^a-z0-9\s]", " ", text.lower())) if len(t) > 1]


def _fnv1a(s):
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def embed(text):
    vec = [0.0] * DIM
    for token in tokenize(text):
        h = _fnv1a(token)
        sign = 1 if (h >> 8) % 2 == 0 else -1
        vec[h % DIM] += sign * (1 + ((h >> 16) % 8) / 8)
    norm = math.sqrt(sum(v * v for v in vec))
    return vec if norm == 0 else [v / norm for v in vec]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))          # both unit length


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / (len(sa) + len(sb) - inter)


# --- the canonical record (AGENTS.md section 2) ----------------------------------------------------------------
CAMEL = {"last_accessed": "lastAccessed", "access_count": "accessCount", "chat_id": "chatId",
         "mission_id": "missionId", "goal_run_id": "goalRunId", "related_to": "relatedTo",
         "superseded_by": "supersededBy", "derived_from": "derivedFrom"}
SNAKE = {v: k for k, v in CAMEL.items()}


@dataclass
class MemoryRecord:
    id: str
    content: str
    type: str
    layer: str
    timestamp: int
    last_accessed: int
    access_count: int
    tags: list
    embedding: list
    confidence: float
    source: str
    provenance: dict                # {"origin", "learnedAt", "label", "refs"?}
    domain: str
    namespace: str
    entities: list
    related_to: list
    chat_id: str | None = None
    mission_id: str | None = None
    goal_run_id: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    derived_from: list | None = None
    score: float | None = None

    def to_dict(self, with_embedding=True):
        d = {CAMEL.get(k, k): v for k, v in asdict(self).items() if v is not None or k in ("confidence",)}
        if not with_embedding:
            d.pop("embedding", None)
        return d

    @staticmethod
    def from_dict(d):
        return MemoryRecord(**{SNAKE.get(k, k): v for k, v in d.items()})


def snapshot(r):
    """The record without its embedding, for ledger previous/new states."""
    return copy.deepcopy(r.to_dict(with_embedding=False))


# --- trust ledger (trustLedger.ts) -----------------------------------------------------------------------------
class TrustLedgerService:
    """Append-only: entries are never mutated or deleted. history() reconstructs a record's change record."""

    def __init__(self, clock, persist_dir=None):
        self.clock, self.entries = clock, []
        self.file = Path(persist_dir) / "ledger.jsonl" if persist_dir else None
        if self.file and self.file.exists():
            self.entries = [json.loads(line) for line in self.file.read_text(encoding="utf-8").splitlines() if line]

    def log(self, memory_id, action, actor, previous_state=None, new_state=None, details=None):
        if action not in LEDGER_ACTIONS:
            raise ValueError(f"H-MEM: unknown ledger action {action}")
        entry = {"memoryId": memory_id, "action": action, "actor": actor, "timestamp": self.clock()}
        if previous_state is not None:
            entry["previousState"] = previous_state
        if new_state is not None:
            entry["newState"] = new_state
        if details is not None:
            entry["details"] = details
        self.entries.append(entry)
        if self.file:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def history(self, memory_id):
        return [e for e in self.entries if e["memoryId"] == memory_id]

    def all(self):
        return list(self.entries)

    def stats(self):
        out = {}
        for e in self.entries:
            out[e["action"]] = out.get(e["action"], 0) + 1
        return out


# --- store with enrichment (memoryStore.ts) --------------------------------------------------------------------
TECH_TERMS = ["react", "python", "typescript", "javascript", "rust", "sqlite", "postgres", "indexeddb", "node",
              "docker", "graphql", "redis", "webrtc", "tauri", "electron", "llm", "embedding"]
DOMAIN_KEYWORDS = {
    "tech": ["code", "bug", "api", "database", "deploy", "framework", "library", "server", *TECH_TERMS],
    "work": ["meeting", "deadline", "client", "project", "sprint", "review", "report"],
    "personal": ["family", "hobby", "prefer", "like", "dislike", "morning", "evening"],
}
CORRECTION = re.compile(r"\b(actually|instead|no longer|not anymore|changed to|correction)\b", re.I)


class MemoryStoreService:
    """Tiered store (short_term, working, long_term). Enrichment on every add: domain, namespace, entities (cap 10),
    relatedTo (cap 5, bidirectional), supersedes detection."""

    def __init__(self, clock, ledger, actor, persist_dir=None, domain_keywords=None):
        self.clock, self.ledger, self.actor = clock, ledger, actor
        self.records, self.seq = {}, 0
        self.domain_keywords = domain_keywords or DOMAIN_KEYWORDS
        self.state_file = None
        if persist_dir:
            Path(persist_dir).mkdir(parents=True, exist_ok=True)
            self.state_file = Path(persist_dir) / "state.json"
            if self.state_file.exists():
                saved = json.loads(self.state_file.read_text(encoding="utf-8"))
                self.seq = saved["seq"]
                for r in saved["records"]:
                    self.records[r["id"]] = MemoryRecord.from_dict(r)

    def persist(self):
        if not self.state_file:
            return
        records = [r.to_dict() for r in sorted(self.records.values(), key=lambda r: r.id)]
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seq": self.seq, "records": records}, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.state_file)

    def add(self, content, source, type="general", layer="working", tags=None, confidence=None, provenance=None,
            chat_id=None, mission_id=None, goal_run_id=None, supersedes=None, derived_from=None):
        if not source or not str(source).strip():
            raise ValueError("H-MEM: a memory record with no source must be rejected by construction "
                             "(AGENTS.md section 2)")
        if type not in TYPES or layer not in LAYERS:
            raise ValueError(f"H-MEM: bad type/layer {type}/{layer}")
        now = self.clock()
        self.seq += 1
        tags = list(tags or [])
        domain = self.classify_domain(content, tags, type)
        record = MemoryRecord(
            id=f"mem-{self.seq}", content=content, type=type, layer=layer, timestamp=now, last_accessed=now,
            access_count=0, tags=tags, embedding=embed(content),
            confidence=clamp01(0.7 if confidence is None else confidence), source=source,
            provenance=provenance or {"origin": "manual", "learnedAt": now, "label": source},
            domain=domain, namespace=self._namespace(domain, type), entities=self.extract_entities(content),
            related_to=[], chat_id=chat_id, mission_id=mission_id, goal_run_id=goal_run_id, supersedes=supersedes,
            derived_from=derived_from)
        self._discover_relationships(record)
        self.records[record.id] = record
        self.ledger.log(record.id, "create", self.actor, new_state=snapshot(record))
        self.persist()
        return record

    def get(self, id):
        return self.records.get(id)

    def all(self):
        return list(self.records.values())

    def update(self, id, **patch):
        rec = self._must_get(id)
        prev = snapshot(rec)
        for k, v in patch.items():
            setattr(rec, SNAKE.get(k, k), v)
        self.ledger.log(id, "update", self.actor, previous_state=prev, new_state=snapshot(rec))
        self.persist()
        return rec

    def delete(self, id, reason):
        rec = self._must_get(id)
        del self.records[id]
        self.ledger.log(id, "delete", self.actor, previous_state=snapshot(rec), details={"reason": reason})
        self.persist()

    def touch(self, id):
        rec = self._must_get(id)
        rec.last_accessed = self.clock()
        rec.access_count += 1

    def promote(self, id, layer):
        rec = self._must_get(id)
        prev = snapshot(rec)
        rec.layer = layer
        self.ledger.log(id, "promote", self.actor, previous_state=prev, new_state=snapshot(rec))
        self.persist()

    def restore_all(self, records, seq):
        self.records = {r.id: copy.deepcopy(r) for r in records}
        self.seq = seq
        self.persist()

    def snapshot_all(self):
        return {"records": copy.deepcopy(list(self.records.values())), "seq": self.seq}

    def _must_get(self, id):
        rec = self.records.get(id)
        if rec is None:
            raise KeyError(f"H-MEM: unknown memory id {id}")
        return rec

    def classify_domain(self, content, tags, type):
        """Multi-pass domain classification (AGENTS.md section 5)."""
        for t in tags:
            if t.startswith("project:"):
                return t[len("project:"):]
            if t.startswith("tech:"):
                return "tech"
        tokens = set(tokenize(content))
        best, best_score = "general", 0
        for domain, kws in self.domain_keywords.items():
            score = sum(1 for kw in kws if kw in tokens)
            if domain == "personal" and type in ("personal", "preference"):
                score += 1
            if score > best_score:
                best, best_score = domain, score
        return best if best_score > 0 else "general"

    @staticmethod
    def _namespace(domain, type):
        bucket = "profile" if type in ("preference", "personal") else "facts" if type == "factual" else "notes"
        return f"{domain}/{bucket}"

    @staticmethod
    def extract_entities(content):
        entities = []
        for t in tokenize(content):
            if t in TECH_TERMS and t not in entities:
                entities.append(t)
        for m in re.finditer(r"\b([A-Z][a-zA-Z]{2,})\b", content):
            norm = m.group(1).lower()
            if norm not in ("the", "this", "that", "with") and norm not in entities:
                entities.append(norm)
        return entities[:DEFAULTS["entity_cap"]]

    def _discover_relationships(self, record):
        for other in self.records.values():
            if len(record.related_to) >= DEFAULTS["related_cap"]:
                break
            shared = [e for e in other.entities if e in record.entities]
            sim = cosine(record.embedding, other.embedding)
            if not record.supersedes and sim > 0.85 and CORRECTION.search(record.content):
                record.supersedes = other.id
                continue
            if shared and other.domain == record.domain:
                record.related_to.append(other.id)
                if len(other.related_to) < DEFAULTS["related_cap"] and record.id not in other.related_to:
                    other.related_to.append(record.id)       # bidirectional link


# --- retrieval and reinjection (memoryRetrieval.ts) ------------------------------------------------------------
LAYER_WEIGHT = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}


@dataclass
class RetrievedMemory:
    memory: MemoryRecord
    relevance: float


@dataclass
class QueryResult:
    memories: list
    context: str
    trace: dict = field(default_factory=dict)      # {"retrievalReason", "strategy", "scores"}


class MemoryRetrievalService:
    def __init__(self, store, ledger, clock, actor):
        self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor

    def _query_parts(self, query):
        return (embed(query), tokenize(query)[:8], self.store.extract_entities(query),
                self.store.classify_domain(query, [], "general"))

    def score_one(self, memory, query):
        return self._score(memory, *self._query_parts(query))

    def _score(self, m, q_embedding, q_tokens, q_entities, q_domain):
        semantic = clamp01(cosine(q_embedding, m.embedding))
        keyword = jaccard(q_tokens, tokenize(m.content))
        tag = jaccard(q_tokens, [t.lower() for t in m.tags])
        domain = 1 if m.domain == q_domain else 0
        entity = jaccard(q_entities, m.entities)
        layer = LAYER_WEIGHT[m.layer]
        recency = math.exp(-((self.clock() - m.last_accessed) / DAY_MS) / DEFAULTS["recency_days"])
        superseded = 1 if m.superseded_by else 0
        raw = (0.35 * semantic + 0.2 * keyword + 0.1 * tag + 0.1 * domain + 0.15 * entity + 0.05 * layer
               + 0.05 * recency - 0.2 * superseded)
        return clamp01(raw) * m.confidence

    def query(self, query, top_n=None, threshold=None, chat_id=None, touch=True):
        parts = self._query_parts(query)
        threshold = DEFAULTS["retrieval_threshold"] if threshold is None else threshold
        top_n = DEFAULTS["retrieval_top_n"] if top_n is None else top_n
        scored = []
        for m in self.store.all():
            if chat_id and m.chat_id and m.chat_id != chat_id:
                continue
            s = self._score(m, *parts)
            if s >= threshold:
                scored.append(RetrievedMemory(m, s))
        scored.sort(key=lambda r: (-r.relevance, r.memory.id))
        top = scored[:top_n]
        if touch:
            for r in top:
                self.store.touch(r.memory.id)
                self.ledger.log(r.memory.id, "read", self.actor, details={"query": query})
        strategy = ("minimal" if len(top) <= 1 else
                    "personal" if any(r.memory.type in ("personal", "preference") for r in top) else "comprehensive")
        return QueryResult(top, self.format_reinjection(top), {
            "retrievalReason": f'hybrid ranking for "{query}" (domain: {parts[3]})', "strategy": strategy,
            "scores": {r.memory.id: round(r.relevance, 4) for r in top}})

    @staticmethod
    def format_reinjection(items):
        """Domain-grouped blocks with layer markers and entities (section 6.2)."""
        if not items:
            return ""
        by_domain = {}
        for it in items:
            by_domain.setdefault(it.memory.domain, []).append(it)
        lines = ["[MEMORY CONTEXT]"]
        for domain in sorted(by_domain):
            lines.append(f"## {domain}")
            for it in by_domain[domain]:
                m = it.memory
                marker = {"long_term": "LT", "working": "WK"}.get(m.layer, "ST")
                ents = f" (entities: {', '.join(m.entities)})" if m.entities else ""
                lines.append(f"- [{marker}] {m.content}{ents} <{m.id}>")
        lines.append("[/MEMORY CONTEXT]")
        return "\n".join(lines)

    def feedback(self, memory_id, kind):
        """Exact feedback deltas (AGENTS.md section 9.2)."""
        m = self.store.get(memory_id)
        if m is None:
            raise KeyError(f"H-MEM: unknown memory id {memory_id}")
        prev = snapshot(m)
        if kind == "helpful":
            m.access_count += 1
        m.confidence = clamp01(m.confidence + FEEDBACK_DELTAS[kind])
        if kind == "wrong" and "review" not in m.tags:
            m.tags.append("review")
        self.ledger.log(memory_id, "feedback", self.actor, previous_state=prev, new_state=snapshot(m),
                        details={"kind": kind, "delta": FEEDBACK_DELTAS[kind]})
        self.store.persist()


# --- conflicts (conflictDetection.ts) --------------------------------------------------------------------------
OPPOSING_PAIRS = [(re.compile(r"\balways\b", re.I), re.compile(r"\bnever\b", re.I)),
                  (re.compile(r"\benable[ds]?\b", re.I), re.compile(r"\bdisable[ds]?\b", re.I)),
                  (re.compile(r"\bprefer[s]?\b", re.I), re.compile(r"\bavoid[s]?|dislike[s]?\b", re.I)),
                  (re.compile(r"\bon\b", re.I), re.compile(r"\boff\b", re.I)),
                  (re.compile(r"\byes\b", re.I), re.compile(r"\bno\b", re.I))]
NUMBER = re.compile(r"\d+(\.\d+)?")


class ConflictDetectionService:
    def __init__(self, store, ledger, clock, actor):
        self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor
        self.conflicts, self.seq = [], 0

    def scan(self):
        found, records = [], self.store.all()
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                c = self._check(records[i], records[j])
                if c:
                    found.append(c)
                    self.conflicts.append(c)
                    self.ledger.log(c["memoryA"], "conflict_detected", self.actor,
                                    details={"with": c["memoryB"], "reason": c["reason"], "confidence": c["confidence"]})
        return found

    def _check(self, a, b):
        if b.id in (a.supersedes, a.superseded_by) or a.id in (b.supersedes, b.superseded_by):
            return None                                   # an intended replacement, not a conflict
        sim = cosine(a.embedding, b.embedding)
        reason, confidence = "", 0.0
        for p, q in OPPOSING_PAIRS:
            if (p.search(a.content) and q.search(b.content)) or (q.search(a.content) and p.search(b.content)):
                if sim > 0.5:
                    reason, confidence = "opposing phrase pair on similar content", 0.5 + 0.3 * sim
        if not reason and sim > 0.8:
            na = [m.group(0) for m in NUMBER.finditer(a.content)]
            nb = [m.group(0) for m in NUMBER.finditer(b.content)]
            if na and nb and ",".join(na) != ",".join(nb):
                reason, confidence = "high-similarity conflicting numeric values", 0.55 + 0.25 * sim
        if not reason:
            return None
        if any(e in b.entities for e in a.entities):
            confidence += 0.1
        if a.domain == b.domain:
            confidence += 0.05
        if b.id in a.related_to:
            confidence -= 0.1
        self.seq += 1
        return {"id": f"conflict-{self.seq}", "memoryA": a.id, "memoryB": b.id, "reason": reason,
                "confidence": clamp01(confidence), "resolved": False}

    def auto_resolve(self, conflict):
        a, b = self.store.get(conflict["memoryA"]), self.store.get(conflict["memoryB"])

        def score_of(m):
            return (0.3 * (m.last_accessed / max(1, self.clock())) + 0.2 * min(1, m.access_count / 10)
                    + 0.25 * m.confidence + 0.1 * min(1, len(m.content) / 200)
                    + 0.15 * (1 if m.provenance.get("origin") == "user_correction" else 0.5))
        sa, sb = score_of(a), score_of(b)
        margin = abs(sa - sb) / max(sa, sb)
        decision = clamp01(conflict["confidence"] * 0.6 + margin * 0.8)
        if decision < DEFAULTS["conflict_auto_resolve_gate"]:
            return "queued"
        winner, loser = (a, b) if sa >= sb else (b, a)
        prev = snapshot(loser)
        loser.superseded_by = winner.id                   # kept and penalized, never deleted
        conflict["resolved"] = True
        conflict["resolution"] = "keep_a" if winner.id == conflict["memoryA"] else "keep_b"
        self.ledger.log(loser.id, "conflict_resolved", self.actor, previous_state=prev, new_state=snapshot(loser),
                        details={"conflictId": conflict["id"], "winner": winner.id,
                                 "decisionConfidence": round(decision, 3)})
        self.store.persist()
        return "resolved"

    autoResolve = auto_resolve

    def queue(self):
        return [c for c in self.conflicts if not c["resolved"]]


# --- sleep (sleepCycle.ts) -------------------------------------------------------------------------------------
HUB_THRESHOLD = 3


class SleepCycleService:
    def __init__(self, store, ledger, clock, actor):
        self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor
        self.backups, self.backup_seq = {}, 0

    def preview(self):
        now, records = self.clock(), self.store.all()
        referenced = set()
        for m in records:
            referenced.update(m.related_to)
            if m.supersedes:
                referenced.add(m.supersedes)
            referenced.update(m.derived_from or [])
        to_consolidate = [m.id for m in records if m.layer == "short_term"
                          and now - m.last_accessed >= DEFAULTS["consolidation_days"] * DAY_MS]

        def archivable(m):
            if not (now - m.timestamp >= DEFAULTS["archive_min_days"] * DAY_MS
                    and m.access_count <= DEFAULTS["archive_max_access"] and m.id not in referenced):
                return False
            return not (m.supersedes or m.derived_from or len(m.related_to) >= HUB_THRESHOLD)   # guardrails
        to_archive = [m.id for m in records if archivable(m)]
        to_synthesize, used = [], set()
        for i, a in enumerate(records):
            if a.id in used:
                continue
            group = [a] + [b for b in records[i + 1:] if b.id not in used
                           and cosine(a.embedding, b.embedding) >= DEFAULTS["synthesis_cosine"]]
            if len(group) >= 2:
                used.update(g.id for g in group)
                to_synthesize.append([g.id for g in group])
        return {"toConsolidate": to_consolidate, "toArchive": to_archive, "toSynthesize": to_synthesize}

    def execute(self, preview=None):
        plan = preview or self.preview()
        self.backup_seq += 1
        backup_id = f"backup-{self.backup_seq}"
        self.backups[backup_id] = self.store.snapshot_all()
        log = [f"backup {backup_id} created"]
        for id in plan["toConsolidate"]:
            if self.store.get(id):
                self.store.promote(id, "long_term")
                self.ledger.log(id, "sleep_consolidate", self.actor, details={"from": "short_term", "to": "long_term"})
                log.append(f"consolidated {id}")
        for id in plan["toArchive"]:
            m = self.store.get(id)
            if m:
                self.ledger.log(id, "sleep_archive", self.actor,
                                details={"age": self.clock() - m.timestamp, "accessCount": m.access_count})
                self.store.delete(id, "sleep archive")
                log.append(f"archived {id}")
        synthesized = 0
        for group in plan["toSynthesize"]:
            members = [m for m in (self.store.get(i) for i in group) if m]
            if len(members) < 2:
                continue
            merged = self.store.add(
                content="Synthesis: " + " | ".join(m.content for m in members), source="sleep:synthesis",
                type="factual", layer="long_term", tags=list(dict.fromkeys(t for m in members for t in m.tags)),
                confidence=max(m.confidence for m in members),
                provenance={"origin": "sleep_synthesis", "learnedAt": self.clock(),
                            "label": f"synthesized from {len(members)} memories"},
                derived_from=[m.id for m in members])
            self.ledger.log(merged.id, "sleep_synthesize", self.actor, details={"sources": group})
            for m in members:
                self.store.delete(m.id, "merged by sleep synthesis")
            synthesized += 1
            log.append(f"synthesized {merged.id} from {', '.join(group)}")
        self.store.persist()
        return {"backupId": backup_id, "consolidated": len(plan["toConsolidate"]),
                "archived": len(plan["toArchive"]), "synthesized": synthesized, "actionLog": log}

    def restore(self, backup_id):
        backup = self.backups.get(backup_id)
        if backup is None:
            raise KeyError(f"H-MEM: unknown backup {backup_id}")
        self.store.restore_all(backup["records"], backup["seq"])
        self.ledger.log("*", "restore", self.actor, details={"backupId": backup_id})


# --- dreaming (dreaming.ts) ------------------------------------------------------------------------------------
class DreamingService:
    """Constructive synthesis behind a human approval boundary: proposals never become memory until approve()."""

    def __init__(self, store, ledger, clock, actor):
        self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor
        self.proposals, self.seq = {}, 0

    @staticmethod
    def _relatedness(a, b):
        return (0.5 * max(0.0, cosine(a.embedding, b.embedding)) + 0.2 * jaccard(a.tags, b.tags)
                + 0.1 * (1 if a.domain == b.domain else 0) + 0.2 * jaccard(a.entities, b.entities))

    def _cluster(self):
        records, used, clusters = self.store.all(), set(), []
        for seed in records:
            if seed.id in used:
                continue
            group = [seed] + [o for o in records if o.id != seed.id and o.id not in used
                              and self._relatedness(seed, o) >= DEFAULTS["dream_relatedness"]]
            if len(group) >= DEFAULTS["dream_cluster_min_size"]:
                used.update(g.id for g in group)
                clusters.append(group)
        return clusters

    def dream(self):
        created, cap = [], DEFAULTS["max_dream_proposals_per_type"]

        def propose(**p):
            self.seq += 1
            proposal = {**p, "id": f"dream-{self.seq}", "status": "proposed"}
            self.proposals[proposal["id"]] = proposal
            created.append(proposal)
            self.ledger.log(proposal["id"], "dream_proposed", self.actor,
                            details={"type": p["type"], "derivedFrom": p["derivedFrom"]})
        for cluster in self._cluster()[:cap]:
            domains = "/".join(dict.fromkeys(m.domain for m in cluster))
            propose(type="insight", derivedFrom=[m.id for m in cluster],
                    content=f"Across {len(cluster)} related memories ({domains}): "
                            + " + ".join(m.content for m in cluster))
        n = 0
        for m in self.store.all():
            if n >= cap:
                break
            if m.domain != "general":
                continue
            suggested = self.store.classify_domain(m.content, m.tags, m.type)
            if suggested != "general":
                propose(type="domain", content=f'Reclassify "{m.content[:60]}" as {suggested}', derivedFrom=[m.id],
                        suggestedDomain=suggested)
                n += 1
        by_domain = {}
        for m in self.store.all():
            if m.type in ("preference", "personal") or "event:user_correction" in m.tags:
                by_domain.setdefault(m.domain, []).append(m)
        n = 0
        for domain, items in by_domain.items():
            if n >= cap:
                break
            if len(items) < 2:
                continue
            propose(type="invariant", derivedFrom=[m.id for m in items],
                    content=f"Stable pattern in {domain}: " + "; ".join(m.content for m in items))
            n += 1
        return created

    def pending(self):
        return [p for p in self.proposals.values() if p["status"] == "proposed"]

    def approve(self, proposal_id):
        p = self.proposals.get(proposal_id)
        if not p or p["status"] != "proposed":
            raise KeyError(f"H-MEM: no pending proposal {proposal_id}")
        p["status"] = "approved"
        self.ledger.log(proposal_id, "dream_approved", self.actor, details={"type": p["type"]})
        if p["type"] == "domain":
            for id in p["derivedFrom"]:
                if self.store.get(id) and p.get("suggestedDomain"):
                    self.store.update(id, domain=p["suggestedDomain"])
            return None
        return self.store.add(
            content=p["content"], source="dreaming", type="factual" if p["type"] == "insight" else "preference",
            layer="long_term", tags=[f"dream:{p['type']}"], confidence=0.75,
            provenance={"origin": "dream", "learnedAt": self.clock(), "label": f"approved {p['type']} proposal"},
            derived_from=p["derivedFrom"])

    def reject(self, proposal_id):
        p = self.proposals.get(proposal_id)
        if not p or p["status"] != "proposed":
            raise KeyError(f"H-MEM: no pending proposal {proposal_id}")
        p["status"] = "rejected"                           # logged, not materialized
        self.ledger.log(proposal_id, "dream_rejected", self.actor, details={"type": p["type"]})


# --- mining (memoryMining.ts): the model-free path is the default ----------------------------------------------
EVENT_TYPE_MAP = {"chat_message": "general", "user_correction": "preference", "file_save": "factual",
                  "file_open": "general", "file_edit": "factual", "model_response": "factual",
                  "plan_completion": "factual"}
SIGNAL = re.compile(r"\b(prefer|always|never|decided|chose|choose|use|because|instead|must|should|important|"
                    r"remember)\b", re.I)


class MemoryMiningService:
    def __init__(self, store, clock, miner_fn=None):
        self.store, self.clock, self.miner_fn = store, clock, miner_fn

    def mine_interaction(self, event, text, chat_id=None, layer=None):
        candidates = parse_strict_json_array(self.miner_fn(
            f"Extract durable memories from this {event} as a strict JSON array of strings:\n\n{text}")) \
            if self.miner_fn else self.mine_model_free(text)
        return [self.store.add(content=c, source=f"interaction:{event}", type=EVENT_TYPE_MAP[event],
                               layer=layer or ("working" if self.miner_fn else "short_term"), tags=[f"event:{event}"],
                               provenance={"origin": event, "learnedAt": self.clock(), "label": f"mined from {event}"},
                               chat_id=chat_id) for c in candidates]

    @staticmethod
    def mine_model_free(text):
        """No-model fallback (4.3): concise direct sentences as short-term memories."""
        parts = re.split(r"(?<=[.!?])\s+|\n+", text)
        return [s.strip() for s in parts if 20 <= len(s.strip()) <= 300 and SIGNAL.search(s)][:10]


def parse_strict_json_array(raw):
    """Strip markdown fences, tolerate minor noise (section 4.1 step 3)."""
    cleaned = re.sub(r"```\s*$", "", re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.I)).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        return []
    return [x for x in parsed if isinstance(x, str) and len(x.strip()) >= 5] if isinstance(parsed, list) else []


# --- facade (index.ts) -----------------------------------------------------------------------------------------
class HMEM:
    def __init__(self, clock=None, persist_dir=None, actor="system", miner_fn=None, domain_keywords=None):
        import time
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.ledger = TrustLedgerService(self.clock, persist_dir)
        self.store = MemoryStoreService(self.clock, self.ledger, actor, persist_dir, domain_keywords)
        self.mining = MemoryMiningService(self.store, self.clock, miner_fn)
        self.retrieval = MemoryRetrievalService(self.store, self.ledger, self.clock, actor)
        self.conflicts = ConflictDetectionService(self.store, self.ledger, self.clock, actor)
        self.sleep = SleepCycleService(self.store, self.ledger, self.clock, actor)
        self.dreaming = DreamingService(self.store, self.ledger, self.clock, actor)

    def add(self, **kwargs):
        return self.store.add(**kwargs)

    def query(self, query, **kwargs):
        return self.retrieval.query(query, **kwargs)

    def feedback(self, memory_id, kind):
        self.retrieval.feedback(memory_id, kind)
